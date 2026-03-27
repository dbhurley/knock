import { query } from './db.js';
import type { MatchScoreResult, MatchFactors } from '../types/index.js';

/**
 * Weighted multi-factor scoring algorithm.
 *
 * Weights (must sum to 1.0):
 *   position_experience  0.25
 *   school_type           0.15
 *   geography             0.10
 *   education             0.10
 *   enrollment            0.10
 *   specializations       0.10
 *   cultural_fit          0.10
 *   career_stage          0.05
 *   availability          0.05
 */
const WEIGHTS: Record<keyof MatchFactors, number> = {
  position_experience: 0.25,
  school_type: 0.15,
  geography: 0.10,
  education: 0.10,
  enrollment: 0.10,
  specializations: 0.10,
  cultural_fit: 0.10,
  career_stage: 0.05,
  availability: 0.05,
};

interface SearchContext {
  search_id: string;
  position_category: string | null;
  preferred_school_types: string[];
  required_education: string[];
  required_experience_years: number | null;
  school_state: string | null;
  school_enrollment: number | null;
  ideal_candidate_profile: string | null;
  target_start_date: string | null;
  search_urgency: string | null;
}

interface CandidateRow {
  id: string;
  full_name: string;
  current_title: string | null;
  current_organization: string | null;
  candidate_status: string | null;
  primary_role: string | null;
  career_stage: string | null;
  state: string | null;
  willing_to_relocate: boolean | null;
  preferred_states: string[] | null;
  school_type_experience: string[] | null;
  specializations: string[] | null;
  cultural_fit_tags: string[] | null;
  knock_rating: number | null;
  availability_date: string | null;
  is_in_active_search: boolean;
  has_current_position_match: boolean;
  has_any_position_match: boolean;
  education_levels: string[] | null;
  enrollment_experience_low: number | null;
  enrollment_experience_high: number | null;
}

/** Load the search context needed for scoring. */
async function loadSearchContext(searchId: string): Promise<SearchContext | null> {
  const row = await query<Record<string, unknown>>(
    `SELECT
       s.id AS search_id,
       s.position_category,
       s.preferred_school_types,
       s.required_education,
       s.required_experience_years,
       s.target_start_date,
       s.search_urgency,
       sch.state AS school_state,
       sch.enrollment_total AS school_enrollment
     FROM searches s
     JOIN schools sch ON sch.id = s.school_id
     WHERE s.id = $1`,
    [searchId],
  );
  if (!row[0]) return null;
  const r = row[0];
  return {
    search_id: r.search_id as string,
    position_category: r.position_category as string | null,
    preferred_school_types: (r.preferred_school_types as string[]) ?? [],
    required_education: (r.required_education as string[]) ?? [],
    required_experience_years: r.required_experience_years as number | null,
    school_state: r.school_state as string | null,
    school_enrollment: r.school_enrollment as number | null,
    ideal_candidate_profile: null,
    target_start_date: r.target_start_date as string | null,
    search_urgency: r.search_urgency as string | null,
  };
}

// ─── Individual Factor Scorers (each returns 0-100) ───────────────────────

function scorePositionExperience(c: CandidateRow, ctx: SearchContext): number {
  if (c.has_current_position_match) return 100;
  if (c.has_any_position_match) return 80;
  if (c.primary_role === ctx.position_category) return 60;
  return 20;
}

function scoreSchoolType(c: CandidateRow, ctx: SearchContext): number {
  if (!ctx.preferred_school_types.length) return 50;
  const exp = c.school_type_experience ?? [];
  const overlap = exp.some((t) => ctx.preferred_school_types.includes(t));
  return overlap ? 100 : 30;
}

function scoreGeography(c: CandidateRow, ctx: SearchContext): number {
  if (!ctx.school_state) return 50;
  if (c.state === ctx.school_state) return 100;
  const prefStates = c.preferred_states ?? [];
  if (prefStates.includes(ctx.school_state)) return 80;
  if (c.willing_to_relocate) return 70;
  return 30;
}

function scoreEducation(c: CandidateRow, ctx: SearchContext): number {
  if (!ctx.required_education.length) return 50;
  const levels = c.education_levels ?? [];
  // Check if candidate has any of the required degrees
  const hasRequired = ctx.required_education.some((req) =>
    levels.some((l) => l.toLowerCase().includes(req.toLowerCase())),
  );
  if (hasRequired) return 100;
  // Partial credit for advanced degrees
  const hasAdvanced = levels.some((l) =>
    ['ed.d.', 'ph.d.', 'ed.d', 'ph.d', 'doctorate'].some((d) =>
      l.toLowerCase().includes(d),
    ),
  );
  if (hasAdvanced) return 70;
  return 30;
}

function scoreEnrollment(c: CandidateRow, ctx: SearchContext): number {
  if (!ctx.school_enrollment) return 50;
  const low = c.enrollment_experience_low;
  const high = c.enrollment_experience_high;
  if (low === null || high === null) return 40;
  const target = ctx.school_enrollment;
  if (target >= low && target <= high) return 100;
  // Within 50% range
  const margin = target * 0.5;
  if (target >= low - margin && target <= high + margin) return 70;
  return 30;
}

function scoreSpecializations(c: CandidateRow, ctx: SearchContext): number {
  // Use knock_rating as a proxy for specialization depth when no specific
  // requirements are provided. Higher rating = deeper specialization.
  const rating = c.knock_rating ?? 3;
  const specs = c.specializations ?? [];
  if (specs.length === 0) return rating * 15;
  // More specializations = higher score, capped at 100
  return Math.min(100, 40 + specs.length * 15);
}

function scoreCulturalFit(c: CandidateRow, _ctx: SearchContext): number {
  const tags = c.cultural_fit_tags ?? [];
  if (tags.length === 0) return 50;
  // Rating-boosted cultural fit
  const rating = c.knock_rating ?? 3;
  return Math.min(100, 30 + tags.length * 10 + rating * 5);
}

function scoreCareerStage(c: CandidateRow, _ctx: SearchContext): number {
  switch (c.career_stage) {
    case 'senior':
      return 100;
    case 'veteran':
      return 90;
    case 'mid_career':
      return 75;
    case 'emerging':
      return 50;
    case 'retired':
      return 30;
    default:
      return 50;
  }
}

function scoreAvailability(c: CandidateRow, ctx: SearchContext): number {
  if (c.candidate_status === 'active') return 100;
  if (c.candidate_status === 'passive') return 70;
  if (c.is_in_active_search) return 40; // Already in another search
  if (c.availability_date && ctx.target_start_date) {
    const avail = new Date(c.availability_date);
    const target = new Date(ctx.target_start_date);
    if (avail <= target) return 90;
    // Available within 3 months of target
    const diffMs = avail.getTime() - target.getTime();
    const diffDays = diffMs / (1000 * 60 * 60 * 24);
    if (diffDays <= 90) return 70;
    return 40;
  }
  return 50;
}

/** Compute all factor scores for a single candidate. */
function computeFactors(c: CandidateRow, ctx: SearchContext): MatchFactors {
  return {
    position_experience: scorePositionExperience(c, ctx),
    school_type: scoreSchoolType(c, ctx),
    geography: scoreGeography(c, ctx),
    education: scoreEducation(c, ctx),
    enrollment: scoreEnrollment(c, ctx),
    specializations: scoreSpecializations(c, ctx),
    cultural_fit: scoreCulturalFit(c, ctx),
    career_stage: scoreCareerStage(c, ctx),
    availability: scoreAvailability(c, ctx),
  };
}

/** Compute the weighted composite score (0-100). */
function compositeScore(factors: MatchFactors): number {
  let total = 0;
  for (const [key, weight] of Object.entries(WEIGHTS)) {
    total += factors[key as keyof MatchFactors] * weight;
  }
  return Math.round(total * 100) / 100;
}

// ─── Public API ────────────────────────────────────────────────────────────

/**
 * Score a single candidate against a search.
 */
export async function scoreCandidate(
  searchId: string,
  personId: string,
): Promise<MatchScoreResult | null> {
  const ctx = await loadSearchContext(searchId);
  if (!ctx) return null;

  const rows = await query<CandidateRow>(
    `SELECT
       p.id, p.full_name, p.current_title, p.current_organization,
       p.candidate_status, p.primary_role, p.career_stage,
       p.state, p.willing_to_relocate, p.preferred_states,
       p.school_type_experience, p.specializations, p.cultural_fit_tags,
       p.knock_rating, p.availability_date, p.is_in_active_search,
       EXISTS (
         SELECT 1 FROM person_experience pe
         WHERE pe.person_id = p.id
           AND pe.position_category = $2
           AND pe.is_current = true
       ) AS has_current_position_match,
       EXISTS (
         SELECT 1 FROM person_experience pe
         WHERE pe.person_id = p.id
           AND pe.position_category = $2
       ) AS has_any_position_match,
       ARRAY(
         SELECT degree FROM person_education ped
         WHERE ped.person_id = p.id
       ) AS education_levels,
       (SELECT MIN(pe.school_enrollment) FROM person_experience pe WHERE pe.person_id = p.id AND pe.school_enrollment IS NOT NULL) AS enrollment_experience_low,
       (SELECT MAX(pe.school_enrollment) FROM person_experience pe WHERE pe.person_id = p.id AND pe.school_enrollment IS NOT NULL) AS enrollment_experience_high
     FROM people p
     WHERE p.id = $1`,
    [personId, ctx.position_category],
  );

  const c = rows[0];
  if (!c) return null;

  const factors = computeFactors(c, ctx);
  return {
    person_id: c.id,
    full_name: c.full_name,
    current_title: c.current_title,
    current_organization: c.current_organization,
    composite_score: compositeScore(factors),
    factors,
  };
}

/**
 * Find and rank candidates for a search.
 */
export async function findCandidates(
  searchId: string,
  limit = 50,
  minScore = 0,
): Promise<MatchScoreResult[]> {
  const ctx = await loadSearchContext(searchId);
  if (!ctx) return [];

  const rows = await query<CandidateRow>(
    `SELECT
       p.id, p.full_name, p.current_title, p.current_organization,
       p.candidate_status, p.primary_role, p.career_stage,
       p.state, p.willing_to_relocate, p.preferred_states,
       p.school_type_experience, p.specializations, p.cultural_fit_tags,
       p.knock_rating, p.availability_date, p.is_in_active_search,
       EXISTS (
         SELECT 1 FROM person_experience pe
         WHERE pe.person_id = p.id
           AND pe.position_category = $1
           AND pe.is_current = true
       ) AS has_current_position_match,
       EXISTS (
         SELECT 1 FROM person_experience pe
         WHERE pe.person_id = p.id
           AND pe.position_category = $1
       ) AS has_any_position_match,
       ARRAY(
         SELECT degree FROM person_education ped
         WHERE ped.person_id = p.id
       ) AS education_levels,
       (SELECT MIN(pe.school_enrollment) FROM person_experience pe WHERE pe.person_id = p.id AND pe.school_enrollment IS NOT NULL) AS enrollment_experience_low,
       (SELECT MAX(pe.school_enrollment) FROM person_experience pe WHERE pe.person_id = p.id AND pe.school_enrollment IS NOT NULL) AS enrollment_experience_high
     FROM people p
     WHERE p.candidate_status IN ('active', 'passive')
       AND p.id NOT IN (
         SELECT person_id FROM search_candidates
         WHERE search_id = $2 AND status = 'rejected'
       )`,
    [ctx.position_category, searchId],
  );

  const results: MatchScoreResult[] = [];

  for (const c of rows) {
    const factors = computeFactors(c, ctx);
    const score = compositeScore(factors);
    if (score >= minScore) {
      results.push({
        person_id: c.id,
        full_name: c.full_name,
        current_title: c.current_title,
        current_organization: c.current_organization,
        composite_score: score,
        factors,
      });
    }
  }

  results.sort((a, b) => b.composite_score - a.composite_score);
  return results.slice(0, limit);
}
