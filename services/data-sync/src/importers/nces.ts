/**
 * NCES Private School Survey (PSS) data importer.
 *
 * Reads CSV files from ./data/nces/ directory, maps NCES fields to the
 * schools table, and upserts by nces_id.
 *
 * NCES Field Mapping (from PRD section 6.1):
 *   PPIN       -> nces_id
 *   PINST      -> name
 *   PADDRS     -> street_address
 *   PCITY      -> city
 *   PSTABB     -> state
 *   PZIP       -> zip
 *   NUMSTUDS   -> enrollment_total
 *   LEVEL      -> school_type  (needs normalization)
 *   ORIENT     -> religious_affiliation (needs normalization)
 *   CESSION    -> coed_status
 *   PKTCH      -> total_teachers
 *   STUTEFTR   -> student_teacher_ratio
 *   LATITUDE   -> latitude
 *   LONGITUDE  -> longitude
 */

import { createReadStream, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { parse } from 'csv-parse';
import {
  query,
  getClient,
  createSyncLog,
  completeSyncLog,
  closePool,
} from '../lib/db.js';
import { normalizeName, normalizePhone, normalizeState, normalizeZip } from '../utils/normalize.js';

// ---------------------------------------------------------------------------
// NCES code normalizers
// ---------------------------------------------------------------------------

/**
 * Normalize NCES LEVEL code to our school_type enum.
 *
 * NCES LEVEL values (typical PSS coding):
 *   1 = Elementary
 *   2 = Secondary
 *   3 = Combined (elementary + secondary)
 */
function normalizeSchoolType(level: string | undefined): string | null {
  if (!level) return null;
  const code = level.trim();
  switch (code) {
    case '1':
      return 'elementary';
    case '2':
      return 'high';
    case '3':
      return 'k12';
    default:
      return 'other';
  }
}

/**
 * Normalize NCES ORIENT code to religious_affiliation string.
 *
 * NCES ORIENT values (typical PSS coding):
 *   1 = Roman Catholic
 *   2 = Other religious (conservative Christian, other affiliated)
 *   3 = Nonsectarian
 *
 * More detailed ORIENT codes in some PSS years:
 *   11 = Roman Catholic - diocesan
 *   12 = Roman Catholic - private
 *   13 = Roman Catholic - parish
 *   21 = Conservative Christian
 *   22 = Other affiliated
 *   23 = Unaffiliated
 *   31 = Regular
 *   32 = Special emphasis
 *   33 = Special education
 */
function normalizeReligiousAffiliation(orient: string | undefined): string | null {
  if (!orient) return null;
  const code = orient.trim();
  // Handle 2-digit codes first
  if (code.startsWith('1')) return 'Catholic';
  if (code === '21') return 'Conservative Christian';
  if (code === '22') return 'Other Religious';
  if (code === '23') return 'Unaffiliated Religious';
  if (code.startsWith('3')) return 'Nonsectarian';
  // Single-digit fallback
  switch (code) {
    case '1':
      return 'Catholic';
    case '2':
      return 'Other Religious';
    case '3':
      return 'Nonsectarian';
    default:
      return code; // Keep raw value for unknown codes
  }
}

/**
 * Normalize NCES CESSION (coeducation) code.
 *   1 = Coed
 *   2 = Male only
 *   3 = Female only
 */
function normalizeCoed(cession: string | undefined): string | null {
  if (!cession) return null;
  switch (cession.trim()) {
    case '1':
      return 'coed';
    case '2':
      return 'boys';
    case '3':
      return 'girls';
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// CSV row -> school record mapping
// ---------------------------------------------------------------------------

interface NcesRow {
  [key: string]: string | undefined;
}

function mapNcesRow(row: NcesRow, surveyYear: number) {
  const ncesId = (row.PPIN || row.ppin || '').trim();
  if (!ncesId) return null;

  const name = (row.PINST || row.pinst || '').trim();
  if (!name) return null;

  return {
    nces_id: ncesId,
    name,
    name_normalized: normalizeName(name),
    street_address: (row.PADDRS || row.paddrs || '').trim() || null,
    city: (row.PCITY || row.pcity || '').trim() || null,
    state: normalizeState(row.PSTABB || row.pstabb) || null,
    zip: normalizeZip(row.PZIP || row.pzip) || null,
    enrollment_total: parseIntSafe(row.NUMSTUDS || row.numstuds),
    school_type: normalizeSchoolType(row.LEVEL || row.level),
    religious_affiliation: normalizeReligiousAffiliation(row.ORIENT || row.orient),
    coed_status: normalizeCoed(row.CESSION || row.cession),
    total_teachers: parseIntSafe(row.PKTCH || row.pktch),
    student_teacher_ratio: parseFloatSafe(row.STUTEFTR || row.stuteftr),
    latitude: parseFloatSafe(row.LATITUDE || row.latitude),
    longitude: parseFloatSafe(row.LONGITUDE || row.longitude),
    phone: normalizePhone(row.PTELENUM || row.ptelenum) || null,
    nces_survey_year: surveyYear,
    data_source: 'nces',
    is_active: true,
  };
}

function parseIntSafe(val: string | undefined): number | null {
  if (!val) return null;
  const n = parseInt(val.trim(), 10);
  return Number.isNaN(n) ? null : n;
}

function parseFloatSafe(val: string | undefined): number | null {
  if (!val) return null;
  const n = parseFloat(val.trim());
  return Number.isNaN(n) ? null : n;
}

// ---------------------------------------------------------------------------
// Upsert logic
// ---------------------------------------------------------------------------

const UPSERT_SQL = `
  INSERT INTO schools (
    nces_id, name, name_normalized, street_address, city, state, zip,
    enrollment_total, school_type, religious_affiliation, coed_status,
    total_teachers, student_teacher_ratio, latitude, longitude, phone,
    nces_survey_year, data_source, is_active
  ) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
    $16, $17, $18, $19
  )
  ON CONFLICT (nces_id) DO UPDATE SET
    name              = EXCLUDED.name,
    name_normalized   = EXCLUDED.name_normalized,
    street_address    = COALESCE(EXCLUDED.street_address, schools.street_address),
    city              = COALESCE(EXCLUDED.city, schools.city),
    state             = COALESCE(EXCLUDED.state, schools.state),
    zip               = COALESCE(EXCLUDED.zip, schools.zip),
    enrollment_total  = COALESCE(EXCLUDED.enrollment_total, schools.enrollment_total),
    school_type       = COALESCE(EXCLUDED.school_type, schools.school_type),
    religious_affiliation = COALESCE(EXCLUDED.religious_affiliation, schools.religious_affiliation),
    coed_status       = COALESCE(EXCLUDED.coed_status, schools.coed_status),
    total_teachers    = COALESCE(EXCLUDED.total_teachers, schools.total_teachers),
    student_teacher_ratio = COALESCE(EXCLUDED.student_teacher_ratio, schools.student_teacher_ratio),
    latitude          = COALESCE(EXCLUDED.latitude, schools.latitude),
    longitude         = COALESCE(EXCLUDED.longitude, schools.longitude),
    phone             = COALESCE(EXCLUDED.phone, schools.phone),
    nces_survey_year  = EXCLUDED.nces_survey_year,
    is_active         = EXCLUDED.is_active,
    updated_at        = NOW()
  RETURNING (xmax = 0) AS inserted
`;

// ---------------------------------------------------------------------------
// Main import function
// ---------------------------------------------------------------------------

export interface NcesImportOptions {
  dataDir?: string;
  surveyYear?: number;
  batchSize?: number;
}

export async function importNces(options: NcesImportOptions = {}): Promise<void> {
  const dataDir = options.dataDir || resolve(process.cwd(), 'data', 'nces');
  const surveyYear = options.surveyYear || detectSurveyYear();
  const batchSize = options.batchSize || 100;

  console.log(`[nces] Starting NCES PSS import from ${dataDir} (survey year ${surveyYear})`);

  // Find CSV files in the data directory
  let csvFiles: string[];
  try {
    csvFiles = readdirSync(dataDir)
      .filter((f) => f.toLowerCase().endsWith('.csv'))
      .map((f) => join(dataDir, f));
  } catch (err) {
    console.error(`[nces] Cannot read data directory ${dataDir}:`, err);
    throw err;
  }

  if (csvFiles.length === 0) {
    console.warn(`[nces] No CSV files found in ${dataDir}. Place NCES PSS CSV files there first.`);
    return;
  }

  console.log(`[nces] Found ${csvFiles.length} CSV file(s): ${csvFiles.map((f) => f.split('/').pop()).join(', ')}`);

  const syncLogId = await createSyncLog('nces', 'full');
  const stats = { records_processed: 0, records_created: 0, records_updated: 0, records_errored: 0 };

  try {
    for (const csvFile of csvFiles) {
      console.log(`[nces] Processing ${csvFile.split('/').pop()}...`);
      await processNcesCsv(csvFile, surveyYear, batchSize, stats);
    }

    const status = stats.records_errored > 0 ? 'partial' : 'completed';
    await completeSyncLog(syncLogId, stats, status);

    console.log('[nces] Import complete:', stats);
  } catch (err) {
    await completeSyncLog(syncLogId, stats, 'failed', String(err));
    console.error('[nces] Import failed:', err);
    throw err;
  }
}

async function processNcesCsv(
  filePath: string,
  surveyYear: number,
  batchSize: number,
  stats: { records_processed: number; records_created: number; records_updated: number; records_errored: number },
): Promise<void> {
  let currentBatch: NonNullable<ReturnType<typeof mapNcesRow>>[] = [];

  return new Promise((resolveP, rejectP) => {
    const parser = createReadStream(filePath).pipe(
      parse({
        columns: true,
        skip_empty_lines: true,
        trim: true,
        relax_column_count: true,
      }),
    );

    parser.on('data', (row: NcesRow) => {
      const mapped = mapNcesRow(row, surveyYear);
      if (mapped) {
        currentBatch.push(mapped);
        if (currentBatch.length >= batchSize) {
          // Flush batch
          const batch = currentBatch;
          currentBatch = [];
          parser.pause();
          flushBatch(batch, stats)
            .then(() => parser.resume())
            .catch(rejectP);
        }
      }
    });

    parser.on('end', async () => {
      try {
        if (currentBatch.length > 0) {
          await flushBatch(currentBatch, stats);
        }
        resolveP();
      } catch (err) {
        rejectP(err);
      }
    });

    parser.on('error', rejectP);
  });
}

async function flushBatch(
  batch: NonNullable<ReturnType<typeof mapNcesRow>>[],
  stats: { records_processed: number; records_created: number; records_updated: number; records_errored: number },
): Promise<void> {
  const client = await getClient();
  try {
    await client.query('BEGIN');
    for (const record of batch) {
      if (!record) continue;
      stats.records_processed++;
      try {
        const res = await client.query(UPSERT_SQL, [
          record.nces_id,
          record.name,
          record.name_normalized,
          record.street_address,
          record.city,
          record.state,
          record.zip,
          record.enrollment_total,
          record.school_type,
          record.religious_affiliation,
          record.coed_status,
          record.total_teachers,
          record.student_teacher_ratio,
          record.latitude,
          record.longitude,
          record.phone,
          record.nces_survey_year,
          record.data_source,
          record.is_active,
        ]);
        if (res.rows[0]?.inserted) {
          stats.records_created++;
        } else {
          stats.records_updated++;
        }
      } catch (err) {
        stats.records_errored++;
        console.error(`[nces] Error upserting NCES ID ${record.nces_id}:`, err);
      }
    }
    await client.query('COMMIT');
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }

  if (stats.records_processed % 1000 === 0) {
    console.log(`[nces] Progress: ${stats.records_processed} processed, ${stats.records_created} created, ${stats.records_updated} updated`);
  }
}

/**
 * Detect the likely survey year from the current date.
 * PSS is biennial; recent years: 2019-20, 2021-22, 2023-24.
 */
function detectSurveyYear(): number {
  const now = new Date();
  const year = now.getFullYear();
  // PSS data releases lag by ~1 year. Use the most recent even year.
  const base = year % 2 === 0 ? year - 2 : year - 1;
  return base;
}

// ---------------------------------------------------------------------------
// CLI entry point
// ---------------------------------------------------------------------------

const isMainModule =
  process.argv[1] &&
  (process.argv[1].endsWith('/nces.ts') || process.argv[1].endsWith('/nces.js'));

if (isMainModule) {
  const dataDir = process.argv[2] || undefined;
  const surveyYear = process.argv[3] ? parseInt(process.argv[3], 10) : undefined;

  importNces({ dataDir, surveyYear })
    .then(() => {
      console.log('[nces] Done.');
      return closePool();
    })
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('[nces] Fatal error:', err);
      process.exit(1);
    });
}
