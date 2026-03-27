/**
 * Deduplication utilities for schools and people.
 *
 * Strategy from PRD section 6.4:
 * - Schools: match on NCES ID first, then fuzzy match on name + city + state (0.7 threshold)
 * - People:  match on LinkedIn ID first, then fuzzy match on name + organization (0.7 threshold)
 */

import { query } from '../lib/db.js';
import { normalizeName, similarity } from './normalize.js';

const FUZZY_THRESHOLD = 0.7;

// ---------------------------------------------------------------------------
// School deduplication
// ---------------------------------------------------------------------------

export interface SchoolMatchCandidate {
  id: string;
  nces_id: string | null;
  name: string;
  name_normalized: string | null;
  city: string | null;
  state: string | null;
}

export interface MatchResult {
  matched: boolean;
  matchedId: string | null;
  matchType: 'nces_id' | 'fuzzy' | null;
  score: number;
}

/**
 * Find a matching school record in the database.
 *
 * 1. Exact match on nces_id (authoritative)
 * 2. Fuzzy match on name + city + state with combined score >= 0.7
 */
export async function findDuplicateSchool(
  ncesId: string | null,
  name: string,
  city: string | null,
  state: string | null,
): Promise<MatchResult> {
  // 1. Try exact NCES ID match
  if (ncesId) {
    const res = await query(
      'SELECT id FROM schools WHERE nces_id = $1 LIMIT 1',
      [ncesId],
    );
    if (res.rows.length > 0) {
      return { matched: true, matchedId: res.rows[0].id, matchType: 'nces_id', score: 1 };
    }
  }

  // 2. Fuzzy match: pull candidates from same state (if known) to limit search space
  const normalizedName = normalizeName(name);
  if (!normalizedName) {
    return { matched: false, matchedId: null, matchType: null, score: 0 };
  }

  let candidateQuery: string;
  let candidateParams: any[];

  if (state) {
    // Use pg_trgm similarity if available, otherwise fall back to pulling all from state
    candidateQuery = `
      SELECT id, nces_id, name, name_normalized, city, state
      FROM schools
      WHERE state = $1
        AND is_active = true
      LIMIT 500
    `;
    candidateParams = [state.toUpperCase()];
  } else {
    // No state filter: try to narrow by first few chars of normalized name
    candidateQuery = `
      SELECT id, nces_id, name, name_normalized, city, state
      FROM schools
      WHERE name_normalized LIKE $1 || '%'
        AND is_active = true
      LIMIT 200
    `;
    candidateParams = [normalizedName.slice(0, 4)];
  }

  const res = await query<SchoolMatchCandidate>(candidateQuery, candidateParams);

  let bestScore = 0;
  let bestId: string | null = null;

  for (const row of res.rows) {
    const nameScore = similarity(name, row.name);
    const cityScore = city && row.city ? similarity(city, row.city) : 0;

    // Weighted score: name is most important, city provides confirmation
    const combinedScore = city && row.city
      ? nameScore * 0.7 + cityScore * 0.3
      : nameScore;

    if (combinedScore > bestScore) {
      bestScore = combinedScore;
      bestId = row.id;
    }
  }

  if (bestScore >= FUZZY_THRESHOLD && bestId) {
    return { matched: true, matchedId: bestId, matchType: 'fuzzy', score: bestScore };
  }

  return { matched: false, matchedId: null, matchType: null, score: bestScore };
}

// ---------------------------------------------------------------------------
// Person deduplication
// ---------------------------------------------------------------------------

export interface PersonMatchCandidate {
  id: string;
  linkedin_id: string | null;
  full_name: string;
  name_normalized: string | null;
  current_organization: string | null;
}

/**
 * Find a matching person record in the database.
 *
 * 1. Exact match on linkedin_id (authoritative)
 * 2. Fuzzy match on name + organization with combined score >= 0.7
 */
export async function findDuplicatePerson(
  linkedinId: string | null,
  fullName: string,
  organization: string | null,
): Promise<MatchResult> {
  // 1. Try exact LinkedIn ID match
  if (linkedinId) {
    const res = await query(
      'SELECT id FROM people WHERE linkedin_id = $1 LIMIT 1',
      [linkedinId],
    );
    if (res.rows.length > 0) {
      return { matched: true, matchedId: res.rows[0].id, matchType: 'nces_id', score: 1 };
    }
  }

  // 2. Fuzzy match on name + organization
  const normalizedName = normalizeName(fullName);
  if (!normalizedName) {
    return { matched: false, matchedId: null, matchType: null, score: 0 };
  }

  // Pull candidates with similar-ish names using prefix
  const prefix = normalizedName.split(' ')[0]; // first name part
  const res = await query<PersonMatchCandidate>(
    `SELECT id, linkedin_id, full_name, name_normalized, current_organization
     FROM people
     WHERE name_normalized LIKE $1 || '%'
     LIMIT 300`,
    [prefix],
  );

  let bestScore = 0;
  let bestId: string | null = null;

  for (const row of res.rows) {
    const nameScore = similarity(fullName, row.full_name);
    const orgScore =
      organization && row.current_organization
        ? similarity(organization, row.current_organization)
        : 0;

    // Weighted: name is primary, org confirms
    const combinedScore =
      organization && row.current_organization
        ? nameScore * 0.6 + orgScore * 0.4
        : nameScore;

    if (combinedScore > bestScore) {
      bestScore = combinedScore;
      bestId = row.id;
    }
  }

  if (bestScore >= FUZZY_THRESHOLD && bestId) {
    return { matched: true, matchedId: bestId, matchType: 'fuzzy', score: bestScore };
  }

  return { matched: false, matchedId: null, matchType: null, score: bestScore };
}
