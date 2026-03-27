-- 005_create_people_extended.sql
-- People extended data tables
-- Also adds deferred FK constraints from school_board_members and school_leadership_history to people

-- Add FK constraints that were deferred from 003 (people table now exists)
ALTER TABLE school_board_members
    ADD CONSTRAINT fk_school_board_members_person
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE SET NULL;

ALTER TABLE school_leadership_history
    ADD CONSTRAINT fk_school_leadership_history_person
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE SET NULL;

-- Education history
CREATE TABLE person_education (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    institution VARCHAR(300) NOT NULL,
    degree VARCHAR(100),                  -- 'B.A.', 'M.Ed.', 'Ed.D.', 'Ph.D.', etc.
    field_of_study VARCHAR(300),
    graduation_year INTEGER,
    honors VARCHAR(200),
    is_education_leadership BOOLEAN DEFAULT FALSE, -- Flag if Ed Leadership program
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_ed_person ON person_education(person_id);
CREATE INDEX idx_person_ed_degree ON person_education(degree);

-- Work experience history
CREATE TABLE person_experience (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    organization VARCHAR(300) NOT NULL,
    school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    title VARCHAR(300) NOT NULL,
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN DEFAULT FALSE,
    description TEXT,
    position_category VARCHAR(50),        -- Maps to our position categories
    school_type VARCHAR(50),              -- Type of school at time of position
    school_enrollment INTEGER,            -- Enrollment at time of position
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_exp_person ON person_experience(person_id);
CREATE INDEX idx_person_exp_school ON person_experience(school_id);
CREATE INDEX idx_person_exp_current ON person_experience(is_current);

-- Certifications and licenses
CREATE TABLE person_certifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    certification_name VARCHAR(300),
    issuing_organization VARCHAR(300),
    issue_date DATE,
    expiry_date DATE,
    credential_id VARCHAR(100),
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Skills and competencies
CREATE TABLE person_skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    skill_name VARCHAR(200) NOT NULL,
    category VARCHAR(50),                 -- 'leadership', 'academic', 'financial', 'technical', 'interpersonal'
    proficiency VARCHAR(20),              -- 'expert', 'advanced', 'intermediate', 'basic'
    endorsed_count INTEGER DEFAULT 0,     -- LinkedIn endorsements
    source VARCHAR(50),                   -- 'linkedin', 'self_reported', 'assessed'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_skills_person ON person_skills(person_id);
CREATE INDEX idx_person_skills_name ON person_skills(skill_name);

-- Professional references
CREATE TABLE person_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    reference_person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    reference_name VARCHAR(300),
    reference_title VARCHAR(300),
    reference_organization VARCHAR(300),
    reference_email VARCHAR(300),
    reference_phone VARCHAR(20),
    relationship VARCHAR(100),            -- 'supervisor', 'colleague', 'board_member', 'direct_report'
    reference_type VARCHAR(50),           -- 'professional', 'personal', 'board'
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Interaction log
CREATE TABLE person_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50),          -- 'email', 'phone', 'meeting', 'linkedin', 'conference', 'telegram'
    direction VARCHAR(10),                -- 'inbound', 'outbound'
    subject VARCHAR(500),
    content TEXT,
    outcome VARCHAR(100),                 -- 'positive', 'neutral', 'negative', 'no_response'
    follow_up_date DATE,
    follow_up_notes TEXT,
    conducted_by VARCHAR(200),            -- Who at Knock had the interaction
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_interactions_person ON person_interactions(person_id);
CREATE INDEX idx_person_interactions_type ON person_interactions(interaction_type);
CREATE INDEX idx_person_interactions_date ON person_interactions(created_at);
