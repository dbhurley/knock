/**
 * db-query.ts
 *
 * OpenClaw tool that wraps the Knock REST API for database queries.
 * Provides typed interfaces for querying schools, people, and searches.
 *
 * This tool is invoked by Janet (the OpenClaw agent) when she needs to
 * query the Knock database. It translates structured parameters into
 * REST API calls against api.askknock.com.
 */

const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:4000/api/v1";
const API_KEY = process.env.API_KEY || "";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ApiResponse<T> {
  data: T;
  meta?: {
    total: number;
    page: number;
    per_page: number;
    total_pages: number;
  };
}

interface SchoolQuery {
  name?: string;
  state?: string;
  school_type?: string;
  min_enrollment?: number;
  max_enrollment?: number;
  boarding?: boolean;
  nais_member?: boolean;
  tier?: string;
  religious_affiliation?: string;
  coed_status?: string;
  free_text?: string;
  page?: number;
  per_page?: number;
}

interface PersonQuery {
  name?: string;
  role?: string;
  state?: string;
  career_stage?: string;
  specializations?: string[];
  status?: string;
  min_rating?: number;
  education_level?: string;
  school_type_experience?: string;
  free_text?: string;
  page?: number;
  per_page?: number;
}

interface SearchQuery {
  status?: string;
  school_id?: string;
  position_category?: string;
  page?: number;
  per_page?: number;
}

interface CreateSearchParams {
  school_id: string;
  position_title: string;
  position_category: string;
  salary_range_low?: number;
  salary_range_high?: number;
  fee_amount?: number;
  deposit_amount?: number;
  start_date?: string;
  target_fill_date?: string;
  required_qualifications?: Record<string, unknown>;
  preferred_qualifications?: Record<string, unknown>;
  preferred_school_types?: string[];
  required_education_level?: string;
  primary_contact_person_id?: string;
  search_committee_notes?: string;
  notes?: string;
}

interface UpdateSearchParams {
  search_id: string;
  status?: string;
  notes?: string;
  [key: string]: unknown;
}

interface InteractionParams {
  person_id: string;
  interaction_type: string;
  search_id?: string;
  notes?: string;
  sentiment?: string;
  follow_up_date?: string;
  follow_up_action?: string;
}

interface SignalQuery {
  days_back?: number;
  signal_type?: string;
  unactioned_only?: boolean;
  state?: string;
  school_id?: string;
}

// ---------------------------------------------------------------------------
// HTTP client
// ---------------------------------------------------------------------------

async function apiRequest<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  params?: Record<string, unknown>,
): Promise<ApiResponse<T>> {
  const url = new URL(`${API_BASE_URL}${path}`);

  const options: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
  };

  if (method === "GET" && params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        if (Array.isArray(value)) {
          url.searchParams.set(key, value.join(","));
        } else {
          url.searchParams.set(key, String(value));
        }
      }
    }
  } else if (params) {
    options.body = JSON.stringify(params);
  }

  const response = await fetch(url.toString(), options);

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(
      `API request failed: ${response.status} ${response.statusText} - ${errorBody}`,
    );
  }

  return response.json() as Promise<ApiResponse<T>>;
}

// ---------------------------------------------------------------------------
// School queries
// ---------------------------------------------------------------------------

export async function querySchools(params: SchoolQuery) {
  return apiRequest("GET", "/schools", params as Record<string, unknown>);
}

export async function getSchoolDetail(schoolId: string) {
  return apiRequest("GET", `/schools/${schoolId}`);
}

export async function getSchoolLeadership(schoolId: string) {
  return apiRequest("GET", `/schools/${schoolId}/leadership`);
}

export async function getSchoolFinancials(schoolId: string) {
  return apiRequest("GET", `/schools/${schoolId}/financials`);
}

// ---------------------------------------------------------------------------
// People queries
// ---------------------------------------------------------------------------

export async function queryPeople(params: PersonQuery) {
  const queryParams: Record<string, unknown> = { ...params };
  if (params.specializations) {
    queryParams.specializations = params.specializations.join(",");
  }
  return apiRequest("GET", "/people", queryParams);
}

export async function getPersonDetail(personId: string) {
  return apiRequest("GET", `/people/${personId}`);
}

export async function getPersonExperience(personId: string) {
  return apiRequest("GET", `/people/${personId}/experience`);
}

export async function getPersonInteractions(personId: string) {
  return apiRequest("GET", `/people/${personId}/interactions`);
}

// ---------------------------------------------------------------------------
// Search queries
// ---------------------------------------------------------------------------

export async function querySearches(params: SearchQuery) {
  return apiRequest("GET", "/searches", params as Record<string, unknown>);
}

export async function getSearchDetail(searchId: string) {
  return apiRequest("GET", `/searches/${searchId}`);
}

export async function getSearchCandidates(searchId: string) {
  return apiRequest("GET", `/searches/${searchId}/candidates`);
}

export async function createSearch(params: CreateSearchParams) {
  return apiRequest("POST", "/searches", params as Record<string, unknown>);
}

export async function updateSearch(params: UpdateSearchParams) {
  const { search_id, ...body } = params;
  return apiRequest(
    "PATCH",
    `/searches/${search_id}`,
    body as Record<string, unknown>,
  );
}

export async function addCandidateToSearch(
  searchId: string,
  personId: string,
  notes?: string,
) {
  return apiRequest("POST", `/searches/${searchId}/candidates`, {
    person_id: personId,
    notes,
  });
}

export async function updateCandidateStatus(
  searchId: string,
  candidateId: string,
  status: string,
  notes?: string,
) {
  return apiRequest(
    "PATCH",
    `/searches/${searchId}/candidates/${candidateId}`,
    { status, notes },
  );
}

// ---------------------------------------------------------------------------
// Interactions
// ---------------------------------------------------------------------------

export async function addInteraction(params: InteractionParams) {
  const { person_id, ...body } = params;
  return apiRequest(
    "POST",
    `/people/${person_id}/interactions`,
    body as Record<string, unknown>,
  );
}

// ---------------------------------------------------------------------------
// Industry signals
// ---------------------------------------------------------------------------

export async function getSignals(params: SignalQuery) {
  return apiRequest("GET", "/signals", params as Record<string, unknown>);
}

export async function createSignal(signal: Record<string, unknown>) {
  return apiRequest("POST", "/signals", signal);
}

// ---------------------------------------------------------------------------
// Pricing
// ---------------------------------------------------------------------------

export async function getPricingQuote(salaryLow: number, salaryHigh: number) {
  return apiRequest("GET", "/pricing/quote", {
    salary_low: salaryLow,
    salary_high: salaryHigh,
  });
}

export async function getPricingBands() {
  return apiRequest("GET", "/pricing/bands");
}

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------

export async function getHealthCheck() {
  return apiRequest("GET", "/health");
}

export async function getDatabaseStats() {
  return apiRequest("GET", "/stats");
}

export async function triggerNcesSync() {
  return apiRequest("POST", "/sync/nces");
}

export async function triggerLinkedInImport() {
  return apiRequest("POST", "/sync/linkedin");
}

// ---------------------------------------------------------------------------
// OpenClaw tool registration
// ---------------------------------------------------------------------------

/**
 * Export all tools in the format expected by OpenClaw for tool registration.
 * Each tool maps to one or more API endpoints.
 */
export const tools = {
  query_schools: {
    handler: querySchools,
    description: "Search schools database with filters",
  },
  get_school_detail: {
    handler: getSchoolDetail,
    description: "Get full details for a specific school",
  },
  query_people: {
    handler: queryPeople,
    description: "Search people/candidates database with filters",
  },
  get_person_detail: {
    handler: getPersonDetail,
    description: "Get full details for a specific person including history",
  },
  create_search: {
    handler: createSearch,
    description: "Create a new search engagement record",
  },
  update_search_status: {
    handler: updateSearch,
    description: "Update the status of an active search",
  },
  get_active_searches: {
    handler: () => querySearches({ status: "active" }),
    description: "List all active search engagements",
  },
  score_candidate: {
    handler: async (params: { person_id: string; search_id: string }) =>
      apiRequest("POST", "/match/score", params),
    description: "Calculate match score between a candidate and a search",
  },
  find_candidates: {
    handler: async (params: {
      search_id: string;
      limit?: number;
      min_score?: number;
    }) => apiRequest("POST", "/match/find", params),
    description: "Find and rank candidates for a search",
  },
  add_interaction: {
    handler: addInteraction,
    description: "Log an interaction with a person",
  },
  get_industry_signals: {
    handler: getSignals,
    description: "Retrieve recent industry signals and news",
  },
  get_pricing_quote: {
    handler: (params: { salary_low: number; salary_high: number }) =>
      getPricingQuote(params.salary_low, params.salary_high),
    description: "Get a pricing quote for a salary range",
  },
  get_database_stats: {
    handler: getDatabaseStats,
    description: "Get database statistics and record counts",
  },
};
