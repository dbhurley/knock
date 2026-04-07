-- 013_school_segments.sql
-- Adds clean school segmentation for newsletter targeting and matching.
-- Replaces the noisy NCES religious_affiliation field with normalized buckets.

ALTER TABLE schools ADD COLUMN IF NOT EXISTS school_segment VARCHAR(50);
ALTER TABLE schools ADD COLUMN IF NOT EXISTS pedagogy VARCHAR(50);
CREATE INDEX IF NOT EXISTS idx_schools_segment ON schools(school_segment);
CREATE INDEX IF NOT EXISTS idx_schools_pedagogy ON schools(pedagogy);

-- See scripts/segment-schools.sh for the populate logic.
