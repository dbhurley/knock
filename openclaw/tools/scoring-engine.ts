/**
 * scoring-engine.ts
 *
 * OpenClaw tool that calls the Knock match scoring API endpoint.
 * Implements the weighted multi-factor scoring system for matching
 * candidates to search engagements.
 *
 * The primary scoring logic lives server-side in the API. This tool
 * provides the interface for Janet to invoke scoring and interpret
 * results. It also includes a local fallback scorer for cases where
 * the API is unavailable or for quick estimates.
 */

const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:4000/api/v1";
const API_KEY = process.env.API_KEY || "";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ScoringRequest {
  person_id: string;
  search_id: string;
}

interface BulkScoringRequest {
  person_ids: string[];
  search_id: string;
  min_score?: number;
  limit?: number;
}

interface FactorScore {
  factor: string;
  weight: number;
  score: number;
  note: string;
}

interface ScoringResult {
  person_id: string;
  search_id: string;
  composite_score: number;
  score_label: string;
  factors: FactorScore[];
  strengths: string[];
  concerns: string[];
  reasoning: string;
  recommendation: "advance" | "consider" | "pass";
  scored_at: string;
}

interface FindCandidatesRequest {
  search_id: string;
  limit?: number;
  min_score?: number;
  exclude_person_ids?: string[];
}

interface FindCandidatesResult {
  search_id: string;
  total_evaluated: number;
  results: ScoringResult[];
}

// ---------------------------------------------------------------------------
// Scoring factor definitions
// ---------------------------------------------------------------------------

const SCORING_FACTORS = {
  position_experience: {
    weight: 0.25,
    description: "Has held similar role",
  },
  school_type_match: {
    weight: 0.15,
    description: "Experience with similar school type",
  },
  geographic_fit: {
    weight: 0.10,
    description: "Location preference alignment",
  },
  education_level: {
    weight: 0.10,
    description: "Meets or exceeds education requirements",
  },
  enrollment_match: {
    weight: 0.10,
    description: "Experience with similar enrollment size",
  },
  specializations: {
    weight: 0.10,
    description: "Matches required specialties",
  },
  cultural_fit: {
    weight: 0.10,
    description: "Alignment with school culture",
  },
  career_stage: {
    weight: 0.05,
    description: "Appropriate career trajectory",
  },
  availability: {
    weight: 0.05,
    description: "Timeline alignment",
  },
} as const;

// ---------------------------------------------------------------------------
// Score label derivation
// ---------------------------------------------------------------------------

function getScoreLabel(score: number): string {
  if (score >= 90) return "Exceptional match";
  if (score >= 80) return "Strong match";
  if (score >= 70) return "Good match";
  if (score >= 60) return "Moderate match";
  return "Partial match";
}

function getRecommendation(score: number): "advance" | "consider" | "pass" {
  if (score >= 75) return "advance";
  if (score >= 55) return "consider";
  return "pass";
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

async function apiRequest<T>(
  method: "GET" | "POST",
  path: string,
  body?: Record<string, unknown>,
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  const options: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
  };

  if (body) {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(
      `Scoring API request failed: ${response.status} ${response.statusText} - ${errorBody}`,
    );
  }

  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Primary scoring functions
// ---------------------------------------------------------------------------

/**
 * Score a single candidate against a search engagement.
 * Calls the server-side scoring API which has full access to
 * candidate and search data.
 */
export async function scoreCandidate(
  request: ScoringRequest,
): Promise<ScoringResult> {
  return apiRequest<ScoringResult>("POST", "/match/score", {
    person_id: request.person_id,
    search_id: request.search_id,
  });
}

/**
 * Score multiple candidates against a search engagement.
 * More efficient than individual calls for batch operations.
 */
export async function scoreCandidatesBulk(
  request: BulkScoringRequest,
): Promise<ScoringResult[]> {
  const result = await apiRequest<{ results: ScoringResult[] }>(
    "POST",
    "/match/score/bulk",
    {
      person_ids: request.person_ids,
      search_id: request.search_id,
      min_score: request.min_score ?? 0,
      limit: request.limit ?? 50,
    },
  );
  return result.results;
}

/**
 * Find and rank the best candidates for a search from the entire
 * candidate database. The API handles the initial filtering and
 * returns scored results.
 */
export async function findCandidates(
  request: FindCandidatesRequest,
): Promise<FindCandidatesResult> {
  return apiRequest<FindCandidatesResult>("POST", "/match/find", {
    search_id: request.search_id,
    limit: request.limit ?? 50,
    min_score: request.min_score ?? 40,
    exclude_person_ids: request.exclude_person_ids ?? [],
  });
}

// ---------------------------------------------------------------------------
// Local scoring utilities (for quick estimates without API call)
// ---------------------------------------------------------------------------

/**
 * Calculate a composite score from individual factor scores.
 * Used for local estimation or when the full API is not needed.
 */
export function calculateCompositeScore(
  factorScores: Record<string, number>,
): number {
  let weightedSum = 0;
  let totalWeight = 0;

  for (const [factor, config] of Object.entries(SCORING_FACTORS)) {
    const score = factorScores[factor];
    if (score !== undefined) {
      weightedSum += config.weight * score;
      totalWeight += config.weight;
    }
  }

  if (totalWeight === 0) return 0;
  return Math.round(weightedSum / totalWeight);
}

/**
 * Format a scoring result for Telegram display.
 */
export function formatScoringResult(result: ScoringResult): string {
  const lines: string[] = [];

  lines.push(`**Match Score: ${result.composite_score}/100** -- ${result.score_label}`);
  lines.push("");

  if (result.strengths.length > 0) {
    lines.push("**Strengths**");
    for (const strength of result.strengths) {
      lines.push(`- ${strength}`);
    }
    lines.push("");
  }

  if (result.concerns.length > 0) {
    lines.push("**Considerations**");
    for (const concern of result.concerns) {
      lines.push(`- ${concern}`);
    }
    lines.push("");
  }

  lines.push("**Factor Breakdown**");
  for (const factor of result.factors) {
    const pct = Math.round(factor.weight * 100);
    lines.push(`${factor.factor}: ${factor.score}/100 (${pct}%) -- ${factor.note}`);
  }
  lines.push("");

  lines.push(`**Recommendation**: ${result.recommendation}`);

  return lines.join("\n");
}

/**
 * Compare two candidates side by side for a given search.
 */
export async function compareCandidates(
  personId1: string,
  personId2: string,
  searchId: string,
): Promise<{ candidate1: ScoringResult; candidate2: ScoringResult }> {
  const [candidate1, candidate2] = await Promise.all([
    scoreCandidate({ person_id: personId1, search_id: searchId }),
    scoreCandidate({ person_id: personId2, search_id: searchId }),
  ]);

  return { candidate1, candidate2 };
}

/**
 * Format a side-by-side comparison for Telegram display.
 */
export function formatComparison(
  candidate1: ScoringResult & { name: string },
  candidate2: ScoringResult & { name: string },
): string {
  const lines: string[] = [];

  lines.push("**Candidate Comparison**");
  lines.push("");
  lines.push(
    `**${candidate1.name}**: ${candidate1.composite_score}/100 (${candidate1.score_label})`,
  );
  lines.push(
    `**${candidate2.name}**: ${candidate2.composite_score}/100 (${candidate2.score_label})`,
  );
  lines.push("");
  lines.push("**Factor-by-Factor**");

  for (const factor of Object.keys(SCORING_FACTORS)) {
    const f1 = candidate1.factors.find((f) => f.factor === factor);
    const f2 = candidate2.factors.find((f) => f.factor === factor);
    const s1 = f1?.score ?? 0;
    const s2 = f2?.score ?? 0;
    const indicator = s1 > s2 ? "<" : s1 < s2 ? ">" : "=";
    lines.push(`${factor}: ${s1} ${indicator} ${s2}`);
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// OpenClaw tool registration
// ---------------------------------------------------------------------------

export const tools = {
  score_candidate: {
    handler: scoreCandidate,
    description: "Calculate match score between a candidate and a search",
  },
  score_candidates_bulk: {
    handler: scoreCandidatesBulk,
    description: "Score multiple candidates against a search in batch",
  },
  find_candidates: {
    handler: findCandidates,
    description: "Find and rank the best candidates for a search",
  },
  compare_candidates: {
    handler: (params: {
      person_id_1: string;
      person_id_2: string;
      search_id: string;
    }) =>
      compareCandidates(params.person_id_1, params.person_id_2, params.search_id),
    description: "Compare two candidates side by side for a search",
  },
};
