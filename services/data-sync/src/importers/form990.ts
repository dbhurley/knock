/**
 * ProPublica Nonprofit 990 API integration.
 *
 * Queries https://projects.propublica.org/nonprofits/api/v2/ to fetch
 * IRS Form 990 data for schools, extracting revenue, expenses,
 * executive compensation, and board member information.
 *
 * Updates the school_financials and school_board_members tables.
 */

import {
  query,
  createSyncLog,
  completeSyncLog,
  closePool,
} from '../lib/db.js';

// ---------------------------------------------------------------------------
// Rate limiter: be polite to the ProPublica API
// ---------------------------------------------------------------------------

const RATE_LIMIT_MS = 1000; // 1 request per second
let lastRequestTime = 0;

async function rateLimitedFetch(url: string): Promise<any> {
  const now = Date.now();
  const elapsed = now - lastRequestTime;
  if (elapsed < RATE_LIMIT_MS) {
    await sleep(RATE_LIMIT_MS - elapsed);
  }
  lastRequestTime = Date.now();

  const response = await fetch(url, {
    headers: {
      'User-Agent': 'Knock Data Sync (askknock.com)',
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    if (response.status === 429) {
      // Rate limited; back off and retry
      console.warn('[990] Rate limited, backing off 10s...');
      await sleep(10_000);
      return rateLimitedFetch(url);
    }
    throw new Error(`ProPublica API error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// ProPublica API types
// ---------------------------------------------------------------------------

interface ProPublicaSearchResult {
  total_results: number;
  organizations: ProPublicaOrg[];
}

interface ProPublicaOrg {
  ein: number;
  name: string;
  city: string;
  state: string;
  ntee_code: string;
  score: number;
}

interface ProPublicaOrgDetail {
  organization: {
    ein: number;
    name: string;
    city: string;
    state: string;
    ntee_code: string;
    subsection_code: number;
    total_revenue: number;
    total_expenses: number;
  };
  filings_with_data: ProPublicaFiling[];
}

interface ProPublicaFiling {
  tax_prd_yr: number;
  totrevenue: number;
  totfuncexpns: number;
  totassetsend: number;
  totliabend: number;
  pct_compnsatncurrofcrs: number;
  // Some filings include officer compensation details
  pdf_url?: string;
}

// ---------------------------------------------------------------------------
// School 990 sync
// ---------------------------------------------------------------------------

export interface Form990SyncOptions {
  /** Limit to specific school IDs */
  schoolIds?: string[];
  /** Maximum number of schools to process */
  maxSchools?: number;
  /** Fiscal year to target (defaults to most recent) */
  fiscalYear?: number;
}

export async function syncForm990(options: Form990SyncOptions = {}): Promise<void> {
  console.log('[990] Starting Form 990 sync via ProPublica API');

  const syncLogId = await createSyncLog('form_990', options.schoolIds ? 'incremental' : 'full');
  const stats = { records_processed: 0, records_created: 0, records_updated: 0, records_errored: 0 };

  try {
    // Get schools to process
    let schoolsQuery: string;
    let schoolsParams: any[];

    if (options.schoolIds && options.schoolIds.length > 0) {
      schoolsQuery = `
        SELECT id, name, city, state, nces_id
        FROM schools
        WHERE id = ANY($1) AND is_active = true
        ORDER BY name
      `;
      schoolsParams = [options.schoolIds];
    } else {
      // Process schools that haven't been synced recently or ever
      const limit = options.maxSchools || 100;
      schoolsQuery = `
        SELECT s.id, s.name, s.city, s.state, s.nces_id
        FROM schools s
        LEFT JOIN school_financials sf ON sf.school_id = s.id
        WHERE s.is_active = true
          AND s.is_private = true
        GROUP BY s.id
        HAVING MAX(sf.fiscal_year) IS NULL
           OR MAX(sf.fiscal_year) < $1
        ORDER BY s.enrollment_total DESC NULLS LAST
        LIMIT $2
      `;
      const targetYear = options.fiscalYear || new Date().getFullYear() - 1;
      schoolsParams = [targetYear, limit];
    }

    const schoolsResult = await query(schoolsQuery, schoolsParams);
    const schools = schoolsResult.rows;

    console.log(`[990] Processing ${schools.length} schools`);

    for (const school of schools) {
      stats.records_processed++;
      try {
        await processSchool990(school);
        stats.records_updated++;
      } catch (err) {
        stats.records_errored++;
        console.error(`[990] Error processing ${school.name}:`, err);
      }

      if (stats.records_processed % 10 === 0) {
        console.log(`[990] Progress: ${stats.records_processed}/${schools.length}`);
      }
    }

    const status = stats.records_errored > 0 ? 'partial' : 'completed';
    await completeSyncLog(syncLogId, stats, status);
    console.log('[990] Sync complete:', stats);
  } catch (err) {
    await completeSyncLog(syncLogId, stats, 'failed', String(err));
    console.error('[990] Sync failed:', err);
    throw err;
  }
}

async function processSchool990(school: {
  id: string;
  name: string;
  city: string | null;
  state: string | null;
  nces_id: string | null;
}): Promise<void> {
  // Search ProPublica for the school by name + state
  const searchTerm = encodeURIComponent(school.name);
  const stateParam = school.state ? `&state%5Bid%5D=${school.state}` : '';
  const searchUrl = `https://projects.propublica.org/nonprofits/api/v2/search.json?q=${searchTerm}${stateParam}&ntee%5Bid%5D=2`; // NTEE 2 = Education

  const searchResult: ProPublicaSearchResult = await rateLimitedFetch(searchUrl);

  if (!searchResult.organizations || searchResult.organizations.length === 0) {
    console.log(`[990] No 990 results for: ${school.name}`);
    return;
  }

  // Pick the best matching organization
  const bestOrg = searchResult.organizations[0]; // ProPublica sorts by relevance

  // Fetch detailed filing info
  const detailUrl = `https://projects.propublica.org/nonprofits/api/v2/organizations/${bestOrg.ein}.json`;
  const detail: ProPublicaOrgDetail = await rateLimitedFetch(detailUrl);

  if (!detail.filings_with_data || detail.filings_with_data.length === 0) {
    console.log(`[990] No filing data for ${school.name} (EIN: ${bestOrg.ein})`);
    return;
  }

  // Process each filing year
  for (const filing of detail.filings_with_data.slice(0, 5)) {
    // Only keep last 5 years
    await upsertSchoolFinancial(school.id, filing, bestOrg.ein);
  }

  // Update the school record with the latest financial summary
  const latestFiling = detail.filings_with_data[0];
  if (latestFiling && detail.organization) {
    await query(
      `UPDATE schools
       SET operating_budget = $1,
           updated_at = NOW()
       WHERE id = $2
         AND (operating_budget IS NULL OR operating_budget < $1)`,
      [latestFiling.totrevenue || detail.organization.total_revenue, school.id],
    );
  }
}

async function upsertSchoolFinancial(
  schoolId: string,
  filing: ProPublicaFiling,
  ein: number,
): Promise<void> {
  await query(
    `INSERT INTO school_financials (
       school_id, fiscal_year, revenue, expenses, source
     ) VALUES ($1, $2, $3, $4, 'form_990')
     ON CONFLICT (school_id, fiscal_year) DO UPDATE SET
       revenue  = COALESCE(EXCLUDED.revenue, school_financials.revenue),
       expenses = COALESCE(EXCLUDED.expenses, school_financials.expenses),
       source   = 'form_990'`,
    [
      schoolId,
      filing.tax_prd_yr,
      filing.totrevenue || null,
      filing.totfuncexpns || null,
    ],
  );
}

// ---------------------------------------------------------------------------
// CLI entry point
// ---------------------------------------------------------------------------

const isMainModule =
  process.argv[1] &&
  (process.argv[1].endsWith('/form990.ts') || process.argv[1].endsWith('/form990.js'));

if (isMainModule) {
  const maxSchools = process.argv[2] ? parseInt(process.argv[2], 10) : 50;

  syncForm990({ maxSchools })
    .then(() => {
      console.log('[990] Done.');
      return closePool();
    })
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('[990] Fatal error:', err);
      process.exit(1);
    });
}
