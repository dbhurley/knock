-- 002_create_schools.sql
-- Primary school record

CREATE TABLE schools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nces_id VARCHAR(12) UNIQUE,           -- NCES School ID (PSS)
    name VARCHAR(500) NOT NULL,
    name_normalized VARCHAR(500),          -- Lowercase, stripped for search
    school_type VARCHAR(50),               -- 'elementary', 'middle', 'high', 'k8', 'k12', 'other'
    religious_affiliation VARCHAR(100),    -- From NCES: Catholic, Jewish, Nonsectarian, etc.
    coed_status VARCHAR(20),              -- 'coed', 'boys', 'girls'
    boarding_status VARCHAR(20),          -- 'day', 'boarding', 'day_boarding'
    grade_low VARCHAR(5),                 -- Lowest grade: 'PK', 'K', '1', etc.
    grade_high VARCHAR(5),               -- Highest grade: '8', '12', 'PG'
    enrollment_total INTEGER,
    enrollment_pk INTEGER,
    enrollment_k INTEGER,
    enrollment_1_5 INTEGER,
    enrollment_6_8 INTEGER,
    enrollment_9_12 INTEGER,
    enrollment_pg INTEGER,

    -- Location
    street_address VARCHAR(500),
    city VARCHAR(200),
    state VARCHAR(2),
    zip VARCHAR(10),
    county VARCHAR(200),
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    metro_status VARCHAR(20),             -- 'urban', 'suburban', 'rural'

    -- Contact
    phone VARCHAR(20),
    fax VARCHAR(20),
    website VARCHAR(500),
    email VARCHAR(300),

    -- Financial
    tuition_low INTEGER,                  -- Lowest tuition offered
    tuition_high INTEGER,                 -- Highest tuition offered
    endowment_size BIGINT,               -- Estimated endowment in dollars
    annual_fund_size INTEGER,
    operating_budget BIGINT,
    financial_aid_pct DECIMAL(5,2),       -- % of students receiving aid
    avg_aid_amount INTEGER,

    -- Staff
    total_teachers INTEGER,
    fte_teachers DECIMAL(8,2),
    student_teacher_ratio DECIMAL(5,2),
    pct_teachers_advanced_degree DECIMAL(5,2),
    total_staff INTEGER,

    -- Accreditation & Membership
    nais_member BOOLEAN DEFAULT FALSE,    -- National Association of Independent Schools
    state_accredited BOOLEAN DEFAULT FALSE,
    regional_accreditation VARCHAR(100),  -- e.g., 'NEASC', 'WASC', 'SACS', etc.

    -- Classification
    is_private BOOLEAN DEFAULT TRUE,
    is_independent BOOLEAN,               -- True independent vs. parochial/religious-affiliated
    is_charter BOOLEAN DEFAULT FALSE,
    is_magnet BOOLEAN DEFAULT FALSE,
    nces_category VARCHAR(50),            -- NCES school category code
    level_code VARCHAR(10),               -- NCES level code

    -- Knock Internal
    tier VARCHAR(20),                     -- 'platinum', 'gold', 'silver', 'bronze', 'unranked'
    is_active BOOLEAN DEFAULT TRUE,
    last_head_change DATE,                -- When the current HOS started
    next_head_change_expected DATE,       -- Predicted transition
    notes TEXT,
    tags TEXT[],                           -- Flexible tagging: ['boarding', 'progressive', 'STEM-focus']

    -- Metadata
    data_source VARCHAR(50) DEFAULT 'nces', -- 'nces', 'manual', 'linkedin', 'web_scrape'
    nces_survey_year INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ,

    -- Search optimization
    search_vector tsvector
);

-- Indexes
CREATE INDEX idx_schools_state ON schools(state);
CREATE INDEX idx_schools_type ON schools(school_type);
CREATE INDEX idx_schools_enrollment ON schools(enrollment_total);
CREATE INDEX idx_schools_tier ON schools(tier);
CREATE INDEX idx_schools_nces_id ON schools(nces_id);
CREATE INDEX idx_schools_city_state ON schools(city, state);
CREATE INDEX idx_schools_boarding ON schools(boarding_status);
CREATE INDEX idx_schools_coed ON schools(coed_status);
CREATE INDEX idx_schools_search ON schools USING gin(search_vector);
CREATE INDEX idx_schools_tags ON schools USING gin(tags);
CREATE INDEX idx_schools_name_trgm ON schools USING gin(name_normalized gin_trgm_ops);

-- Trigger to update search vector
CREATE OR REPLACE FUNCTION schools_search_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.city, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.state, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.religious_affiliation, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.tags, ' '), '')), 'C');
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_schools_search
    BEFORE INSERT OR UPDATE ON schools
    FOR EACH ROW EXECUTE FUNCTION schools_search_update();
