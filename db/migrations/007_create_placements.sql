-- 007_create_placements.sql
-- Successful placements (historical record)

CREATE TABLE placements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_id UUID REFERENCES searches(id) ON DELETE SET NULL,
    school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    position_title VARCHAR(300),
    placement_date DATE NOT NULL,
    start_date DATE,
    salary INTEGER,
    contract_term VARCHAR(50),
    fee_charged INTEGER,
    fee_collected INTEGER,

    -- Outcome tracking
    still_in_role BOOLEAN DEFAULT TRUE,
    departure_date DATE,
    departure_reason VARCHAR(100),
    tenure_months INTEGER,                -- Computed from dates

    -- Satisfaction
    school_satisfaction INTEGER CHECK (school_satisfaction BETWEEN 1 AND 5),
    candidate_satisfaction INTEGER CHECK (candidate_satisfaction BETWEEN 1 AND 5),
    follow_up_6mo_date DATE,
    follow_up_6mo_notes TEXT,
    follow_up_12mo_date DATE,
    follow_up_12mo_notes TEXT,

    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_placements_school ON placements(school_id);
CREATE INDEX idx_placements_person ON placements(person_id);
CREATE INDEX idx_placements_date ON placements(placement_date);
