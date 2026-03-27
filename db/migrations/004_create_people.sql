-- 004_create_people.sql
-- Primary person record

CREATE TABLE people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    linkedin_id VARCHAR(100) UNIQUE,       -- LinkedIn member ID or profile slug
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    full_name VARCHAR(300) NOT NULL,
    name_normalized VARCHAR(300),           -- For search
    preferred_name VARCHAR(100),            -- Nickname or preferred first name
    prefix VARCHAR(20),                     -- 'Dr.', 'Rev.', etc.
    suffix VARCHAR(20),                     -- 'Ed.D.', 'Ph.D.', 'Jr.', etc.

    -- Contact
    email_primary VARCHAR(300),
    email_secondary VARCHAR(300),
    phone_primary VARCHAR(20),
    phone_secondary VARCHAR(20),
    phone_type VARCHAR(20),                -- 'mobile', 'work', 'home'

    -- Location
    city VARCHAR(200),
    state VARCHAR(2),
    zip VARCHAR(10),
    country VARCHAR(2) DEFAULT 'US',
    willing_to_relocate BOOLEAN,
    preferred_regions TEXT[],               -- ['northeast', 'southeast', 'west']
    preferred_states TEXT[],                -- ['MA', 'CT', 'NY']

    -- Current Position
    current_title VARCHAR(300),
    current_organization VARCHAR(300),
    current_school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    current_position_start DATE,
    years_in_current_role INTEGER,

    -- Professional Profile
    career_stage VARCHAR(30),              -- 'emerging', 'mid_career', 'senior', 'veteran', 'retired'
    primary_role VARCHAR(50),              -- 'head_of_school', 'division_head', 'academic_dean', etc.
    specializations TEXT[],                -- ['fundraising', 'stem', 'boarding', 'dei']
    school_type_experience TEXT[],         -- ['k12', 'k8', '9_12', 'boarding', 'day']
    enrollment_experience_range INT4RANGE, -- Range of school sizes led
    budget_experience_range INT8RANGE,     -- Range of budgets managed

    -- Compensation
    current_compensation INTEGER,          -- Estimated current total comp
    compensation_expectation VARCHAR(50),  -- 'open', '200-250k', '300k+', etc.
    compensation_notes TEXT,

    -- LinkedIn Data
    linkedin_url VARCHAR(500),
    linkedin_headline VARCHAR(500),
    linkedin_summary TEXT,
    linkedin_connections INTEGER,
    linkedin_profile_photo_url VARCHAR(500),
    linkedin_last_synced TIMESTAMPTZ,

    -- Assessment
    knock_rating INTEGER CHECK (knock_rating BETWEEN 1 AND 5), -- 1-5 internal rating
    cultural_fit_tags TEXT[],              -- ['progressive', 'traditional', 'faith-based', 'innovative']
    leadership_style TEXT[],              -- ['collaborative', 'visionary', 'operational', 'transformational']
    strengths TEXT[],
    development_areas TEXT[],
    interview_notes TEXT,

    -- Status
    candidate_status VARCHAR(30),          -- 'active', 'passive', 'not_looking', 'placed', 'do_not_contact', 'retired'
    is_in_active_search BOOLEAN DEFAULT FALSE,
    availability_date DATE,
    last_contacted_at TIMESTAMPTZ,
    last_interaction_type VARCHAR(50),     -- 'email', 'phone', 'linkedin', 'in_person', 'conference'
    relationship_strength VARCHAR(20),     -- 'strong', 'moderate', 'weak', 'new'

    -- Data Source
    data_source VARCHAR(50),              -- 'linkedin_import', 'manual', 'referral', 'conference', 'web'
    source_connection VARCHAR(300),       -- Who referred/connected them
    import_batch_id VARCHAR(50),          -- Which LinkedIn export batch

    -- Metadata
    tags TEXT[],
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ,

    -- Search
    search_vector tsvector
);

-- Indexes
CREATE INDEX idx_people_name ON people(last_name, first_name);
CREATE INDEX idx_people_name_trgm ON people USING gin(name_normalized gin_trgm_ops);
CREATE INDEX idx_people_status ON people(candidate_status);
CREATE INDEX idx_people_role ON people(primary_role);
CREATE INDEX idx_people_stage ON people(career_stage);
CREATE INDEX idx_people_state ON people(state);
CREATE INDEX idx_people_school ON people(current_school_id);
CREATE INDEX idx_people_linkedin ON people(linkedin_id);
CREATE INDEX idx_people_search ON people USING gin(search_vector);
CREATE INDEX idx_people_tags ON people USING gin(tags);
CREATE INDEX idx_people_specializations ON people USING gin(specializations);
CREATE INDEX idx_people_cultural_fit ON people USING gin(cultural_fit_tags);
CREATE INDEX idx_people_rating ON people(knock_rating);

-- Search vector trigger
CREATE OR REPLACE FUNCTION people_search_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.full_name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.current_title, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.current_organization, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.linkedin_headline, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.specializations, ' '), '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.tags, ' '), '')), 'D');
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_people_search
    BEFORE INSERT OR UPDATE ON people
    FOR EACH ROW EXECUTE FUNCTION people_search_update();
