-- 003_create_school_extended.sql
-- School extended data tables
-- Note: school_board_members and school_leadership_history reference people(id),
-- but people table is created in 004. We use deferred FK constraints or
-- create these FK references after people table exists.
-- Solution: create tables without the people FK here, add FK in 004 after people is created.

-- School accreditations and memberships
CREATE TABLE school_accreditations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    organization VARCHAR(200) NOT NULL,    -- 'NAIS', 'NEASC', 'WASC', etc.
    accreditation_type VARCHAR(100),       -- 'full', 'provisional', 'candidate'
    granted_date DATE,
    expiry_date DATE,
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- School academic programs and specialties
CREATE TABLE school_programs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    program_type VARCHAR(50),             -- 'ap', 'ib', 'stem', 'arts', 'athletics', 'special_ed'
    program_name VARCHAR(300),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- School board of trustees/directors
-- person_id FK to people added in 004_create_people.sql after people table exists
CREATE TABLE school_board_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    person_id UUID,                       -- FK added after people table is created
    name VARCHAR(300),                    -- If person not yet in people table
    role VARCHAR(100),                    -- 'chair', 'vice_chair', 'treasurer', 'secretary', 'member'
    term_start DATE,
    term_end DATE,
    is_current BOOLEAN DEFAULT TRUE,
    linkedin_url VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- School financial snapshots (annual)
CREATE TABLE school_financials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    fiscal_year INTEGER NOT NULL,
    revenue BIGINT,
    expenses BIGINT,
    endowment BIGINT,
    annual_fund BIGINT,
    capital_campaign BIGINT,
    tuition_revenue BIGINT,
    enrollment INTEGER,
    tuition_low INTEGER,
    tuition_high INTEGER,
    source VARCHAR(50),                   -- 'form_990', 'school_report', 'estimate'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(school_id, fiscal_year)
);

-- School leadership history
-- person_id FK to people added in 004_create_people.sql after people table exists
CREATE TABLE school_leadership_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    person_id UUID,                       -- FK added after people table is created
    position_title VARCHAR(200),
    start_date DATE,
    end_date DATE,
    departure_reason VARCHAR(100),        -- 'retirement', 'new_position', 'terminated', 'contract_end', 'unknown'
    is_current BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
