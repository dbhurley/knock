-- 012_add_school_ein_and_people_sources.sql
-- Adds EIN column to schools table for 990 filing lookups
-- and any additional indexes needed for people-sources service

-- Add EIN to schools table (needed for Form 990 board member extraction)
ALTER TABLE schools ADD COLUMN IF NOT EXISTS ein VARCHAR(20);
CREATE INDEX IF NOT EXISTS idx_schools_ein ON schools(ein);

-- Add career_trajectory_score to people (for flagging high-visibility leaders)
ALTER TABLE people ADD COLUMN IF NOT EXISTS career_trajectory_score INTEGER
    CHECK (career_trajectory_score BETWEEN 0 AND 100);

-- Ensure person_publications allows 'podcast' type (no constraint to change,
-- just note: publication_type varchar(50) already accommodates this)

-- Index for faster dedup lookups on person_publications
CREATE INDEX IF NOT EXISTS idx_person_pubs_title ON person_publications(title);
CREATE INDEX IF NOT EXISTS idx_person_pubs_publisher ON person_publications(publisher);
