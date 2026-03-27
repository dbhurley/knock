// ─── School ────────────────────────────────────────────────────────────────

export interface School {
  id: string;
  nces_id: string | null;
  name: string;
  name_normalized: string | null;
  school_type: string | null;
  religious_affiliation: string | null;
  coed_status: string | null;
  boarding_status: string | null;
  grade_low: string | null;
  grade_high: string | null;
  enrollment_total: number | null;

  // Location
  street_address: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
  county: string | null;
  latitude: number | null;
  longitude: number | null;
  metro_status: string | null;

  // Contact
  phone: string | null;
  website: string | null;
  email: string | null;

  // Financial
  tuition_low: number | null;
  tuition_high: number | null;
  endowment_size: number | null;
  operating_budget: number | null;
  financial_aid_pct: number | null;

  // Staff
  total_teachers: number | null;
  student_teacher_ratio: number | null;

  // Classification
  nais_member: boolean;
  is_independent: boolean | null;
  tier: string | null;
  is_active: boolean;
  tags: string[];

  created_at: string;
  updated_at: string;
}

export interface SchoolLeadership {
  id: string;
  school_id: string;
  person_id: string | null;
  position_title: string | null;
  start_date: string | null;
  end_date: string | null;
  departure_reason: string | null;
  is_current: boolean;
}

export interface SchoolFinancial {
  id: string;
  school_id: string;
  fiscal_year: number;
  revenue: number | null;
  expenses: number | null;
  endowment: number | null;
  annual_fund: number | null;
  enrollment: number | null;
  tuition_low: number | null;
  tuition_high: number | null;
  source: string | null;
}

// ─── Person ────────────────────────────────────────────────────────────────

export interface Person {
  id: string;
  linkedin_id: string | null;
  first_name: string | null;
  last_name: string | null;
  full_name: string;
  preferred_name: string | null;
  prefix: string | null;
  suffix: string | null;

  // Contact
  email_primary: string | null;
  phone_primary: string | null;

  // Location
  city: string | null;
  state: string | null;
  willing_to_relocate: boolean | null;
  preferred_regions: string[];
  preferred_states: string[];

  // Current Position
  current_title: string | null;
  current_organization: string | null;
  current_school_id: string | null;
  years_in_current_role: number | null;

  // Professional Profile
  career_stage: string | null;
  primary_role: string | null;
  specializations: string[];
  school_type_experience: string[];

  // Assessment
  knock_rating: number | null;
  cultural_fit_tags: string[];
  leadership_style: string[];

  // Status
  candidate_status: string | null;
  is_in_active_search: boolean;
  availability_date: string | null;
  relationship_strength: string | null;

  // Metadata
  tags: string[];
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersonExperience {
  id: string;
  person_id: string;
  organization: string;
  school_id: string | null;
  title: string;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  description: string | null;
  position_category: string | null;
  school_type: string | null;
  school_enrollment: number | null;
}

export interface PersonInteraction {
  id: string;
  person_id: string;
  interaction_type: string | null;
  direction: string | null;
  subject: string | null;
  content: string | null;
  outcome: string | null;
  follow_up_date: string | null;
  conducted_by: string | null;
  created_at: string;
}

// ─── Search ────────────────────────────────────────────────────────────────

export interface Search {
  id: string;
  search_number: string | null;
  school_id: string;

  position_title: string;
  position_category: string | null;
  position_description: string | null;

  salary_range_low: number | null;
  salary_range_high: number | null;
  salary_band: string | null;

  target_start_date: string | null;
  search_urgency: string | null;

  required_education: string[];
  required_experience_years: number | null;
  preferred_school_types: string[];
  ideal_candidate_profile: string | null;

  pricing_band: string | null;
  fee_amount: number | null;
  fee_status: string | null;
  deposit_amount: number | null;
  deposit_paid: boolean;

  status: string;
  status_changed_at: string;

  client_contact_name: string | null;
  client_contact_email: string | null;
  lead_consultant: string | null;

  candidates_identified: number;
  candidates_presented: number;
  placed_person_id: string | null;
  placement_date: string | null;

  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface SearchCandidate {
  id: string;
  search_id: string;
  person_id: string;
  status: string;
  match_score: number | null;
  match_reasoning: string | null;
  source: string | null;
  referred_by: string | null;
  presented_at: string | null;
  interview_feedback: string | null;
  client_feedback: string | null;
  candidate_feedback: string | null;
  rejection_reason: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// ─── Pricing ───────────────────────────────────────────────────────────────

export interface PricingBand {
  band: string;
  label: string;
  salary_low: number;
  salary_high: number | null;
  fee: number;
  deposit: number;
}

export interface PricingQuote {
  salary: number;
  band: PricingBand;
  fee: number;
  deposit: number;
}

// ─── Signal ────────────────────────────────────────────────────────────────

export interface Signal {
  id: string;
  signal_type: string;
  school_id: string | null;
  person_id: string | null;
  headline: string | null;
  description: string | null;
  source_url: string | null;
  source_name: string | null;
  signal_date: string | null;
  confidence: string | null;
  impact: string | null;
  actioned: boolean;
  created_at: string;
}

// ─── Match ─────────────────────────────────────────────────────────────────

export interface MatchScoreResult {
  person_id: string;
  full_name: string;
  current_title: string | null;
  current_organization: string | null;
  composite_score: number;
  factors: MatchFactors;
}

export interface MatchFactors {
  position_experience: number;
  school_type: number;
  geography: number;
  education: number;
  enrollment: number;
  specializations: number;
  cultural_fit: number;
  career_stage: number;
  availability: number;
}

// ─── Pagination ────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  data: T[];
  pagination: {
    page: number;
    per_page: number;
    total: number;
    total_pages: number;
  };
}

// ─── Stats ─────────────────────────────────────────────────────────────────

export interface SystemStats {
  schools: number;
  people: number;
  active_searches: number;
  total_searches: number;
  placements: number;
  signals: number;
}
