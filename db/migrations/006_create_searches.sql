-- 006_create_searches.sql
-- Searches, search candidates, and search activities

-- A search is an active engagement to fill a position
CREATE TABLE searches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_number VARCHAR(20) UNIQUE,     -- 'KNK-2026-001' sequential
    school_id UUID REFERENCES schools(id) ON DELETE RESTRICT,

    -- Position Details
    position_title VARCHAR(300) NOT NULL,
    position_category VARCHAR(50),        -- 'head_of_school', 'division_head', etc.
    position_description TEXT,
    position_requirements TEXT,
    reports_to VARCHAR(200),              -- Who this role reports to

    -- Compensation
    salary_range_low INTEGER,
    salary_range_high INTEGER,
    salary_band VARCHAR(20),              -- Maps to pricing bands
    additional_compensation TEXT,          -- Housing, car, etc.
    benefits_notes TEXT,

    -- Timeline
    target_start_date DATE,               -- When the school wants the person to start
    search_urgency VARCHAR(20),           -- 'immediate', 'standard', 'flexible'
    contract_length VARCHAR(50),          -- '3 years', '5 years', 'indefinite'

    -- Search Criteria
    required_education TEXT[],            -- ['ed_d', 'ph_d', 'masters']
    required_experience_years INTEGER,
    preferred_school_types TEXT[],        -- ['boarding', 'day', 'k12']
    preferred_backgrounds TEXT[],         -- What kind of backgrounds preferred
    ideal_candidate_profile TEXT,         -- Free-form description
    dealbreakers TEXT,                    -- Must-not-have criteria

    -- Knock Pricing
    pricing_band VARCHAR(20),            -- 'band_a', 'band_b', ..., 'band_f'
    fee_amount INTEGER,                  -- Fixed fee in dollars
    fee_status VARCHAR(30),              -- 'quoted', 'accepted', 'invoiced', 'paid', 'overdue'
    deposit_amount INTEGER,
    deposit_paid BOOLEAN DEFAULT FALSE,
    deposit_paid_date DATE,
    final_payment_date DATE,

    -- Status
    status VARCHAR(30) NOT NULL DEFAULT 'intake',
    -- Statuses: 'intake', 'profiling', 'sourcing', 'screening', 'presenting',
    --           'interviewing', 'finalist', 'offer', 'placed', 'closed_no_fill',
    --           'on_hold', 'cancelled'
    status_changed_at TIMESTAMPTZ DEFAULT NOW(),

    -- Client Contact
    client_contact_name VARCHAR(300),
    client_contact_title VARCHAR(200),
    client_contact_email VARCHAR(300),
    client_contact_phone VARCHAR(20),
    search_committee_members TEXT,        -- JSON array or free text

    -- Assignment
    lead_consultant VARCHAR(200),         -- Primary Knock consultant
    support_consultants TEXT[],

    -- Results
    candidates_identified INTEGER DEFAULT 0,
    candidates_presented INTEGER DEFAULT 0,
    candidates_interviewed INTEGER DEFAULT 0,
    finalists INTEGER DEFAULT 0,
    placed_person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    placement_date DATE,
    placement_salary INTEGER,

    -- Metadata
    notes TEXT,
    internal_notes TEXT,                  -- Not shared with client
    tags TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

CREATE INDEX idx_searches_school ON searches(school_id);
CREATE INDEX idx_searches_status ON searches(status);
CREATE INDEX idx_searches_category ON searches(position_category);
CREATE INDEX idx_searches_band ON searches(pricing_band);
CREATE INDEX idx_searches_created ON searches(created_at);

-- Candidates being considered for a search
CREATE TABLE search_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_id UUID REFERENCES searches(id) ON DELETE CASCADE,
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    status VARCHAR(30) NOT NULL DEFAULT 'identified',
    -- Statuses: 'identified', 'contacted', 'interested', 'screening',
    --           'presented', 'interviewing', 'finalist', 'offered',
    --           'accepted', 'declined', 'withdrawn', 'rejected'
    match_score DECIMAL(5,2),             -- Janet's computed match score (0-100)
    match_reasoning TEXT,                 -- Why Janet thinks this is a match
    source VARCHAR(50),                   -- 'database', 'referral', 'linkedin', 'conference', 'inbound'
    referred_by VARCHAR(300),
    presented_at TIMESTAMPTZ,
    interview_dates TIMESTAMPTZ[],
    interview_feedback TEXT,
    client_feedback TEXT,
    candidate_feedback TEXT,
    rejection_reason TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(search_id, person_id)
);

CREATE INDEX idx_search_candidates_search ON search_candidates(search_id);
CREATE INDEX idx_search_candidates_person ON search_candidates(person_id);
CREATE INDEX idx_search_candidates_status ON search_candidates(status);
CREATE INDEX idx_search_candidates_score ON search_candidates(match_score);

-- Activity log for search progress
CREATE TABLE search_activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_id UUID REFERENCES searches(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,
    -- Types: 'status_change', 'candidate_added', 'candidate_contacted',
    --        'interview_scheduled', 'presentation_sent', 'client_meeting',
    --        'note_added', 'fee_invoiced', 'fee_paid'
    description TEXT,
    performed_by VARCHAR(200),            -- 'janet', 'consultant_name', 'system'
    related_person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    metadata JSONB,                       -- Flexible additional data
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_search_activities_search ON search_activities(search_id);
CREATE INDEX idx_search_activities_type ON search_activities(activity_type);
CREATE INDEX idx_search_activities_date ON search_activities(created_at);
