-- 011_create_enrichment_tables.sql
-- Tables for the enrichment service: compensation data, social profiles, publications

-- Person compensation from Form 990 filings
CREATE TABLE person_compensation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    ein VARCHAR(20),                          -- IRS Employer Identification Number
    fiscal_year INTEGER NOT NULL,
    base_compensation BIGINT,
    bonus BIGINT,
    other_compensation BIGINT,
    deferred_compensation BIGINT,
    nontaxable_benefits BIGINT,
    total_compensation BIGINT,
    hours_per_week DECIMAL(5,2),
    position_title VARCHAR(300),
    source VARCHAR(50) DEFAULT 'form_990',    -- 'form_990', 'self_reported', 'market_data'
    source_url VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(person_id, school_id, fiscal_year)
);

CREATE INDEX idx_person_comp_person ON person_compensation(person_id);
CREATE INDEX idx_person_comp_school ON person_compensation(school_id);
CREATE INDEX idx_person_comp_year ON person_compensation(fiscal_year);
CREATE INDEX idx_person_comp_total ON person_compensation(total_compensation);
CREATE INDEX idx_person_comp_ein ON person_compensation(ein);

-- Person social profiles (LinkedIn, Twitter, etc.)
CREATE TABLE person_social_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,            -- 'linkedin', 'twitter', 'facebook', 'instagram', 'personal_website'
    profile_url VARCHAR(500),
    username VARCHAR(200),
    follower_count INTEGER,
    bio TEXT,
    verified BOOLEAN DEFAULT FALSE,
    last_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(person_id, platform)
);

CREATE INDEX idx_person_social_person ON person_social_profiles(person_id);
CREATE INDEX idx_person_social_platform ON person_social_profiles(platform);

-- Person publications (articles, books, dissertations)
CREATE TABLE person_publications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    publication_type VARCHAR(50) NOT NULL,     -- 'book', 'article', 'dissertation', 'blog_post', 'op_ed', 'white_paper'
    title VARCHAR(500) NOT NULL,
    publisher VARCHAR(300),
    publication_date DATE,
    url VARCHAR(500),
    isbn VARCHAR(20),
    doi VARCHAR(100),
    abstract TEXT,
    co_authors TEXT[],
    tags TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_pubs_person ON person_publications(person_id);
CREATE INDEX idx_person_pubs_type ON person_publications(publication_type);

-- Track enrichment source provenance per field
CREATE TABLE enrichment_provenance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50) NOT NULL,         -- 'person', 'school'
    entity_id UUID NOT NULL,
    field_name VARCHAR(100) NOT NULL,
    field_value TEXT,
    source VARCHAR(50) NOT NULL,              -- 'form_990', 'school_website', 'nais_directory', 'news_monitor', etc.
    source_url VARCHAR(500),
    confidence DECIMAL(3,2),                  -- 0.00 to 1.00
    enriched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(entity_type, entity_id, field_name, source)
);

CREATE INDEX idx_enrichment_prov_entity ON enrichment_provenance(entity_type, entity_id);
CREATE INDEX idx_enrichment_prov_source ON enrichment_provenance(source);
