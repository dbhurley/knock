/**
 * Fuzzy school matching helper for the LinkedIn importer.
 * Cross-references a company name from LinkedIn with schools in the database.
 */

import { query } from '../lib/db.js';
import { normalizeName, similarity } from '../utils/normalize.js';

const MATCH_THRESHOLD = 0.7;

// Simple in-memory cache to avoid repeated DB lookups for the same company name
const matchCache = new Map<string, string | null>();

/**
 * Attempt to match a company name from LinkedIn to a school in the database.
 * Returns the school UUID or null if no confident match.
 */
export async function fuzzyMatchSchool(companyName: string): Promise<string | null> {
  if (!companyName) return null;

  const normalizedCompany = normalizeName(companyName);
  if (!normalizedCompany) return null;

  // Check cache
  if (matchCache.has(normalizedCompany)) {
    return matchCache.get(normalizedCompany) ?? null;
  }

  // Quick check for common non-school organizations
  if (isLikelyNotASchool(normalizedCompany)) {
    matchCache.set(normalizedCompany, null);
    return null;
  }

  // Try pg_trgm similarity search (if the extension is available) with a reasonably
  // scoped query. Fall back to LIKE prefix if trgm isn't set up.
  try {
    const res = await query(
      `SELECT id, name, name_normalized,
              similarity(name_normalized, $1) AS sim
       FROM schools
       WHERE name_normalized % $1
       ORDER BY sim DESC
       LIMIT 5`,
      [normalizedCompany],
    );

    if (res.rows.length > 0 && res.rows[0].sim >= MATCH_THRESHOLD) {
      matchCache.set(normalizedCompany, res.rows[0].id);
      return res.rows[0].id;
    }
  } catch {
    // pg_trgm not available; fall back to LIKE-based search
    const prefix = normalizedCompany.split(' ').slice(0, 2).join(' ');
    const res = await query(
      `SELECT id, name, name_normalized
       FROM schools
       WHERE name_normalized LIKE $1 || '%'
       LIMIT 20`,
      [prefix],
    );

    let bestScore = 0;
    let bestId: string | null = null;

    for (const row of res.rows) {
      const score = similarity(companyName, row.name);
      if (score > bestScore) {
        bestScore = score;
        bestId = row.id;
      }
    }

    if (bestScore >= MATCH_THRESHOLD && bestId) {
      matchCache.set(normalizedCompany, bestId);
      return bestId;
    }
  }

  matchCache.set(normalizedCompany, null);
  return null;
}

/**
 * Quick heuristic to skip clearly non-school organizations.
 */
function isLikelyNotASchool(normalizedName: string): boolean {
  const nonSchoolPatterns = [
    'consulting',
    'partners',
    'advisors',
    'solutions',
    'technology',
    'technologies',
    'software',
    'capital',
    'ventures',
    'financial',
    'bank',
    'insurance',
    'healthcare',
    'hospital',
    'medical',
    'law firm',
    'attorneys',
    'real estate',
    'marketing',
    'media group',
    'self-employed',
    'selfemployed',
    'freelance',
    'retired',
  ];

  return nonSchoolPatterns.some((p) => normalizedName.includes(p));
}

/**
 * Clear the match cache (useful between test runs).
 */
export function clearMatchCache(): void {
  matchCache.clear();
}
