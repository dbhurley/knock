/**
 * LinkedIn connections CSV importer.
 *
 * Reads a LinkedIn export CSV with columns:
 *   First Name, Last Name, Email Address, Company, Position, Connected On, URL
 *
 * Maps to the people table, cross-references Company with schools table,
 * and sets data_source='linkedin_import'.
 */

import { createReadStream } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'csv-parse';
import {
  query,
  getClient,
  createSyncLog,
  completeSyncLog,
  closePool,
} from '../lib/db.js';
import { normalizeName, normalizeEmail, normalizePhone } from '../utils/normalize.js';
import { findDuplicatePerson } from '../utils/deduplicate.js';
import { fuzzyMatchSchool } from './linkedin-school-match.js';

// ---------------------------------------------------------------------------
// CSV row mapping
// ---------------------------------------------------------------------------

interface LinkedInRow {
  'First Name'?: string;
  'Last Name'?: string;
  'Email Address'?: string;
  'Company'?: string;
  'Position'?: string;
  'Connected On'?: string;
  'URL'?: string;
  // Some LinkedIn exports use slightly different column names
  'first_name'?: string;
  'last_name'?: string;
  'email'?: string;
  'company'?: string;
  'position'?: string;
  'connected_on'?: string;
  'url'?: string;
  [key: string]: string | undefined;
}

function getField(row: LinkedInRow, ...keys: string[]): string {
  for (const k of keys) {
    if (row[k]?.trim()) return row[k]!.trim();
  }
  return '';
}

function mapLinkedInRow(row: LinkedInRow, batchId: string) {
  const firstName = getField(row, 'First Name', 'first_name');
  const lastName = getField(row, 'Last Name', 'last_name');
  const fullName = [firstName, lastName].filter(Boolean).join(' ');

  if (!fullName) return null;

  const email = normalizeEmail(getField(row, 'Email Address', 'email'));
  const company = getField(row, 'Company', 'company');
  const position = getField(row, 'Position', 'position');
  const connectedOn = getField(row, 'Connected On', 'connected_on');
  const linkedinUrl = getField(row, 'URL', 'url');

  // Extract LinkedIn ID from URL (e.g. https://www.linkedin.com/in/some-slug)
  let linkedinId: string | null = null;
  if (linkedinUrl) {
    const match = linkedinUrl.match(/linkedin\.com\/in\/([^/?]+)/);
    if (match) {
      linkedinId = match[1];
    }
  }

  return {
    first_name: firstName || null,
    last_name: lastName || null,
    full_name: fullName,
    name_normalized: normalizeName(fullName),
    email_primary: email || null,
    current_title: position || null,
    current_organization: company || null,
    linkedin_id: linkedinId,
    linkedin_url: linkedinUrl || null,
    linkedin_headline: position ? `${position}${company ? ` at ${company}` : ''}` : null,
    data_source: 'linkedin_import' as const,
    import_batch_id: batchId,
    candidate_status: 'active' as const,
    connected_on: connectedOn ? parseLinkedInDate(connectedOn) : null,
  };
}

/**
 * Parse LinkedIn date format: "DD Mon YYYY" or "YYYY-MM-DD" or "Mon DD, YYYY"
 */
function parseLinkedInDate(dateStr: string): Date | null {
  const d = new Date(dateStr);
  if (!isNaN(d.getTime())) return d;
  return null;
}

/**
 * Detect primary_role from the position title.
 * Returns a role classification or null.
 */
function detectRole(position: string | null): string | null {
  if (!position) return null;
  const lower = position.toLowerCase();

  if (/\bhead of school\b|\bheadmaster\b|\bheadmistress\b|\bhead master\b/.test(lower)) {
    return 'head_of_school';
  }
  if (/\bdivision head\b|\bupper school head\b|\blower school head\b|\bmiddle school head\b/.test(lower)) {
    return 'division_head';
  }
  if (/\bacademic dean\b|\bdean of (faculty|academics)\b/.test(lower)) {
    return 'academic_dean';
  }
  if (/\bcfo\b|\bchief financial\b|\bbusiness manager\b|\bfinance director\b/.test(lower)) {
    return 'cfo';
  }
  if (/\badmission/i.test(lower) && /\bdirector\b|\bvp\b|\bhead\b/.test(lower)) {
    return 'admissions_director';
  }
  if (/\bdevelopment\b|\badvancement\b/.test(lower) && /\bdirector\b|\bvp\b|\bhead\b/.test(lower)) {
    return 'development_director';
  }
  if (/\bathletic director\b|\bdirector of athletics\b/.test(lower)) {
    return 'athletic_director';
  }
  if (/\bprincipal\b/.test(lower)) {
    return 'principal';
  }
  if (/\bteacher\b|\bfaculty\b|\binstructor\b/.test(lower)) {
    return 'teacher';
  }
  return null;
}

/**
 * Detect career stage from position title.
 */
function detectCareerStage(position: string | null): string | null {
  if (!position) return null;
  const lower = position.toLowerCase();
  if (/\bretired\b|\bemeritus\b|\bformer\b/.test(lower)) return 'retired';
  if (/\bhead of school\b|\bheadmaster\b|\bceo\b|\bpresident\b/.test(lower)) return 'senior';
  if (/\bdirector\b|\bvp\b|\bdean\b|\bdivision head\b/.test(lower)) return 'mid_career';
  if (/\bassistant\b|\bassociate\b|\bcoordinator\b/.test(lower)) return 'emerging';
  return null;
}

// ---------------------------------------------------------------------------
// Upsert logic
// ---------------------------------------------------------------------------

const UPSERT_PERSON_SQL = `
  INSERT INTO people (
    linkedin_id, first_name, last_name, full_name, name_normalized,
    email_primary, current_title, current_organization,
    linkedin_url, linkedin_headline,
    primary_role, career_stage,
    data_source, import_batch_id, candidate_status
  ) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
  )
  ON CONFLICT (linkedin_id) DO UPDATE SET
    first_name           = COALESCE(EXCLUDED.first_name, people.first_name),
    last_name            = COALESCE(EXCLUDED.last_name, people.last_name),
    full_name            = EXCLUDED.full_name,
    name_normalized      = EXCLUDED.name_normalized,
    email_primary        = COALESCE(EXCLUDED.email_primary, people.email_primary),
    current_title        = COALESCE(EXCLUDED.current_title, people.current_title),
    current_organization = COALESCE(EXCLUDED.current_organization, people.current_organization),
    linkedin_url         = COALESCE(EXCLUDED.linkedin_url, people.linkedin_url),
    linkedin_headline    = COALESCE(EXCLUDED.linkedin_headline, people.linkedin_headline),
    primary_role         = COALESCE(EXCLUDED.primary_role, people.primary_role),
    career_stage         = COALESCE(EXCLUDED.career_stage, people.career_stage),
    updated_at           = NOW()
  RETURNING id, (xmax = 0) AS inserted
`;

const INSERT_PERSON_NO_LINKEDIN_SQL = `
  INSERT INTO people (
    first_name, last_name, full_name, name_normalized,
    email_primary, current_title, current_organization,
    linkedin_url, linkedin_headline,
    primary_role, career_stage,
    data_source, import_batch_id, candidate_status
  ) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
  )
  RETURNING id
`;

// ---------------------------------------------------------------------------
// Main import function
// ---------------------------------------------------------------------------

export interface LinkedInImportOptions {
  csvPath?: string;
  batchId?: string;
}

export async function importLinkedIn(options: LinkedInImportOptions = {}): Promise<void> {
  const csvPath = options.csvPath || resolve(process.cwd(), 'data', 'linkedin', 'Connections.csv');
  const batchId = options.batchId || `li_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`;

  console.log(`[linkedin] Starting LinkedIn import from ${csvPath} (batch: ${batchId})`);

  const syncLogId = await createSyncLog('linkedin', 'full');
  const stats = { records_processed: 0, records_created: 0, records_updated: 0, records_errored: 0 };

  try {
    await processLinkedInCsv(csvPath, batchId, stats);

    const status = stats.records_errored > 0 ? 'partial' : 'completed';
    await completeSyncLog(syncLogId, stats, status);

    console.log('[linkedin] Import complete:', stats);
  } catch (err) {
    await completeSyncLog(syncLogId, stats, 'failed', String(err));
    console.error('[linkedin] Import failed:', err);
    throw err;
  }
}

async function processLinkedInCsv(
  csvPath: string,
  batchId: string,
  stats: { records_processed: number; records_created: number; records_updated: number; records_errored: number },
): Promise<void> {
  return new Promise((resolveP, rejectP) => {
    const parser = createReadStream(csvPath).pipe(
      parse({
        columns: true,
        skip_empty_lines: true,
        trim: true,
        relax_column_count: true,
        bom: true,
      }),
    );

    const rows: ReturnType<typeof mapLinkedInRow>[] = [];

    parser.on('data', (row: LinkedInRow) => {
      const mapped = mapLinkedInRow(row, batchId);
      if (mapped) rows.push(mapped);
    });

    parser.on('end', async () => {
      try {
        console.log(`[linkedin] Parsed ${rows.length} records from CSV`);

        for (const record of rows) {
          if (!record) continue;
          stats.records_processed++;

          try {
            await upsertPerson(record, stats);
          } catch (err) {
            stats.records_errored++;
            console.error(`[linkedin] Error importing ${record.full_name}:`, err);
          }

          if (stats.records_processed % 100 === 0) {
            console.log(`[linkedin] Progress: ${stats.records_processed}/${rows.length}`);
          }
        }

        resolveP();
      } catch (err) {
        rejectP(err);
      }
    });

    parser.on('error', rejectP);
  });
}

async function upsertPerson(
  record: NonNullable<ReturnType<typeof mapLinkedInRow>>,
  stats: { records_created: number; records_updated: number },
): Promise<void> {
  const role = detectRole(record.current_title);
  const stage = detectCareerStage(record.current_title);

  // Attempt to cross-reference company with schools table
  let schoolId: string | null = null;
  if (record.current_organization) {
    schoolId = await fuzzyMatchSchool(record.current_organization);
  }

  if (record.linkedin_id) {
    // Upsert by linkedin_id
    const res = await query(UPSERT_PERSON_SQL, [
      record.linkedin_id,
      record.first_name,
      record.last_name,
      record.full_name,
      record.name_normalized,
      record.email_primary,
      record.current_title,
      record.current_organization,
      record.linkedin_url,
      record.linkedin_headline,
      role,
      stage,
      record.data_source,
      record.import_batch_id,
      record.candidate_status,
    ]);

    const personId = res.rows[0].id;
    const isNew = res.rows[0].inserted;

    if (isNew) {
      stats.records_created++;
    } else {
      stats.records_updated++;
    }

    // Link to school if found
    if (schoolId) {
      await query(
        'UPDATE people SET current_school_id = $1 WHERE id = $2 AND current_school_id IS NULL',
        [schoolId, personId],
      );
    }
  } else {
    // No LinkedIn ID: check for duplicates first
    const dup = await findDuplicatePerson(null, record.full_name, record.current_organization);
    if (dup.matched && dup.matchedId) {
      // Update existing record
      await query(
        `UPDATE people SET
           email_primary = COALESCE($1, email_primary),
           current_title = COALESCE($2, current_title),
           current_organization = COALESCE($3, current_organization),
           linkedin_url = COALESCE($4, linkedin_url),
           primary_role = COALESCE($5, primary_role),
           career_stage = COALESCE($6, career_stage),
           current_school_id = COALESCE($7, current_school_id),
           updated_at = NOW()
         WHERE id = $8`,
        [
          record.email_primary,
          record.current_title,
          record.current_organization,
          record.linkedin_url,
          role,
          stage,
          schoolId,
          dup.matchedId,
        ],
      );
      stats.records_updated++;
    } else {
      // Insert new
      const res = await query(INSERT_PERSON_NO_LINKEDIN_SQL, [
        record.first_name,
        record.last_name,
        record.full_name,
        record.name_normalized,
        record.email_primary,
        record.current_title,
        record.current_organization,
        record.linkedin_url,
        record.linkedin_headline,
        role,
        stage,
        record.data_source,
        record.import_batch_id,
        record.candidate_status,
      ]);

      const personId = res.rows[0].id;
      if (schoolId) {
        await query('UPDATE people SET current_school_id = $1 WHERE id = $2', [schoolId, personId]);
      }

      stats.records_created++;
    }
  }
}

// ---------------------------------------------------------------------------
// CLI entry point
// ---------------------------------------------------------------------------

const isMainModule =
  process.argv[1] &&
  (process.argv[1].endsWith('/linkedin.ts') || process.argv[1].endsWith('/linkedin.js'));

if (isMainModule) {
  const csvPath = process.argv[2] || undefined;

  importLinkedIn({ csvPath })
    .then(() => {
      console.log('[linkedin] Done.');
      return closePool();
    })
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('[linkedin] Fatal error:', err);
      process.exit(1);
    });
}
