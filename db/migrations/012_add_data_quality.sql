-- 012_add_data_quality.sql
-- Add data quality tracking columns to people table

-- Data completeness score (0-100) computed by enrichment scripts
ALTER TABLE people ADD COLUMN IF NOT EXISTS data_completeness_score INTEGER;

-- Duplicate detection: group ID links suspected duplicates together
ALTER TABLE people ADD COLUMN IF NOT EXISTS duplicate_group_id UUID;
ALTER TABLE people ADD COLUMN IF NOT EXISTS duplicate_confidence DECIMAL(3,2);
ALTER TABLE people ADD COLUMN IF NOT EXISTS is_primary_record BOOLEAN DEFAULT TRUE;

-- Enrichment tracking
ALTER TABLE people ADD COLUMN IF NOT EXISTS last_enriched_at TIMESTAMPTZ;
ALTER TABLE people ADD COLUMN IF NOT EXISTS enrichment_version INTEGER DEFAULT 0;

-- Inferred education level (from title/suffix parsing, before person_education is populated)
ALTER TABLE people ADD COLUMN IF NOT EXISTS inferred_education_level VARCHAR(20);
-- 'doctorate', 'masters', 'bachelors', 'unknown'

CREATE INDEX IF NOT EXISTS idx_people_completeness ON people(data_completeness_score);
CREATE INDEX IF NOT EXISTS idx_people_duplicate_group ON people(duplicate_group_id);
CREATE INDEX IF NOT EXISTS idx_people_enrichment ON people(last_enriched_at);
