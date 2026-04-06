-- enrich-02-dedup-quality.sql
-- Detect duplicate people records and compute data completeness scores
-- Run with: docker exec -i knock-postgres-1 psql -U knock_admin -d knock < scripts/enrich-02-dedup-quality.sql

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ═══════════════════════════════════════════════════════════════════════════
-- PART 1: DUPLICATE DETECTION
-- ═══════════════════════════════════════════════════════════════════════════

-- Reset previous duplicate groupings
UPDATE people SET duplicate_group_id = NULL, duplicate_confidence = NULL, is_primary_record = TRUE;

-- ─── Strategy A: Exact email match ────────────────────────────────────────
-- Same email_primary = definite duplicate (confidence 0.95)

WITH email_dupes AS (
  SELECT
    LOWER(TRIM(email_primary)) AS norm_email,
    MIN(id::TEXT)::UUID AS primary_id,
    gen_random_uuid() AS group_id
  FROM people
  WHERE email_primary IS NOT NULL
    AND email_primary != ''
  GROUP BY LOWER(TRIM(email_primary))
  HAVING COUNT(*) > 1
)
UPDATE people p
SET duplicate_group_id = ed.group_id,
    duplicate_confidence = 0.95,
    is_primary_record = (p.id = ed.primary_id),
    updated_at = NOW()
FROM email_dupes ed
WHERE LOWER(TRIM(p.email_primary)) = ed.norm_email;

DO $$
DECLARE cnt INTEGER;
BEGIN
  SELECT COUNT(DISTINCT duplicate_group_id) INTO cnt FROM people WHERE duplicate_group_id IS NOT NULL;
  RAISE NOTICE 'Strategy A (email match): found % duplicate groups', cnt;
END $$;

-- ─── Strategy B: Same name + same organization ───────────────────────────
-- Very likely duplicate (confidence 0.85)

WITH name_org_dupes AS (
  SELECT
    LOWER(TRIM(full_name)) AS norm_name,
    LOWER(TRIM(current_organization)) AS norm_org,
    MIN(id::TEXT)::UUID AS primary_id,
    gen_random_uuid() AS group_id
  FROM people
  WHERE duplicate_group_id IS NULL  -- Skip already-flagged
    AND full_name IS NOT NULL
    AND current_organization IS NOT NULL
    AND current_organization != ''
  GROUP BY LOWER(TRIM(full_name)), LOWER(TRIM(current_organization))
  HAVING COUNT(*) > 1
)
UPDATE people p
SET duplicate_group_id = nod.group_id,
    duplicate_confidence = 0.85,
    is_primary_record = (p.id = nod.primary_id),
    updated_at = NOW()
FROM name_org_dupes nod
WHERE p.duplicate_group_id IS NULL
  AND LOWER(TRIM(p.full_name)) = nod.norm_name
  AND LOWER(TRIM(p.current_organization)) = nod.norm_org;

DO $$
DECLARE cnt INTEGER;
BEGIN
  SELECT COUNT(DISTINCT duplicate_group_id) INTO cnt FROM people
  WHERE duplicate_group_id IS NOT NULL AND duplicate_confidence = 0.85;
  RAISE NOTICE 'Strategy B (name+org match): found % duplicate groups', cnt;
END $$;

-- ─── Strategy C: Fuzzy name match + same state ──────────────────────────
-- Probable duplicate (confidence 0.70)
-- Only match if names are very similar (>0.8 trigram) and same state

WITH fuzzy_name_dupes AS (
  SELECT
    a.id AS id_a,
    b.id AS id_b,
    similarity(a.name_normalized, b.name_normalized) AS sim,
    gen_random_uuid() AS group_id
  FROM people a
  JOIN people b
    ON a.id < b.id
    AND a.state IS NOT NULL
    AND a.state = b.state
    AND similarity(a.name_normalized, b.name_normalized) > 0.8
  WHERE a.duplicate_group_id IS NULL
    AND b.duplicate_group_id IS NULL
    AND a.name_normalized IS NOT NULL
    AND b.name_normalized IS NOT NULL
    AND LENGTH(a.name_normalized) > 5
)
UPDATE people p
SET duplicate_group_id = fnd.group_id,
    duplicate_confidence = 0.70,
    is_primary_record = (p.id = fnd.id_a),
    updated_at = NOW()
FROM fuzzy_name_dupes fnd
WHERE p.id IN (fnd.id_a, fnd.id_b)
  AND p.duplicate_group_id IS NULL;

DO $$
DECLARE
  total_groups INTEGER;
  total_dupes INTEGER;
BEGIN
  SELECT COUNT(DISTINCT duplicate_group_id), COUNT(*) INTO total_groups, total_dupes
  FROM people WHERE duplicate_group_id IS NOT NULL;
  RAISE NOTICE '=== Duplicate Detection Summary ===';
  RAISE NOTICE 'Total duplicate groups: %', total_groups;
  RAISE NOTICE 'Total people in duplicate groups: %', total_dupes;
  RAISE NOTICE 'Primary records: %', (SELECT COUNT(*) FROM people WHERE is_primary_record = TRUE AND duplicate_group_id IS NOT NULL);
  RAISE NOTICE 'Secondary records: %', (SELECT COUNT(*) FROM people WHERE is_primary_record = FALSE);
END $$;

-- ═══════════════════════════════════════════════════════════════════════════
-- PART 2: DATA COMPLETENESS SCORING
-- ═══════════════════════════════════════════════════════════════════════════

-- Score each person 0-100 based on how many key fields are populated.
-- Weighted by importance to matching and outreach.

UPDATE people SET data_completeness_score = (
  -- Identity (15 pts max)
  (CASE WHEN full_name IS NOT NULL AND full_name != '' THEN 5 ELSE 0 END) +
  (CASE WHEN first_name IS NOT NULL AND last_name IS NOT NULL THEN 5 ELSE 0 END) +
  (CASE WHEN prefix IS NOT NULL OR suffix IS NOT NULL THEN 5 ELSE 0 END) +

  -- Contact (20 pts max)
  (CASE WHEN email_primary IS NOT NULL AND email_primary != '' THEN 12 ELSE 0 END) +
  (CASE WHEN phone_primary IS NOT NULL AND phone_primary != '' THEN 5 ELSE 0 END) +
  (CASE WHEN linkedin_url IS NOT NULL THEN 3 ELSE 0 END) +

  -- Location (10 pts max)
  (CASE WHEN state IS NOT NULL THEN 5 ELSE 0 END) +
  (CASE WHEN city IS NOT NULL THEN 3 ELSE 0 END) +
  (CASE WHEN willing_to_relocate IS NOT NULL THEN 2 ELSE 0 END) +

  -- Current Position (15 pts max)
  (CASE WHEN current_title IS NOT NULL AND current_title != '' THEN 5 ELSE 0 END) +
  (CASE WHEN current_organization IS NOT NULL AND current_organization != '' THEN 3 ELSE 0 END) +
  (CASE WHEN current_school_id IS NOT NULL THEN 5 ELSE 0 END) +
  (CASE WHEN primary_role IS NOT NULL THEN 2 ELSE 0 END) +

  -- Professional Depth (20 pts max)
  (CASE WHEN career_stage IS NOT NULL THEN 3 ELSE 0 END) +
  (CASE WHEN specializations IS NOT NULL AND array_length(specializations, 1) > 0 THEN 5 ELSE 0 END) +
  (CASE WHEN school_type_experience IS NOT NULL AND array_length(school_type_experience, 1) > 0 THEN 4 ELSE 0 END) +
  (CASE WHEN enrollment_experience_range IS NOT NULL THEN 4 ELSE 0 END) +
  (CASE WHEN EXISTS (SELECT 1 FROM person_education pe WHERE pe.person_id = people.id) THEN 4 ELSE 0 END) +

  -- Assessment (10 pts max)
  (CASE WHEN knock_rating IS NOT NULL THEN 4 ELSE 0 END) +
  (CASE WHEN cultural_fit_tags IS NOT NULL AND array_length(cultural_fit_tags, 1) > 0 THEN 3 ELSE 0 END) +
  (CASE WHEN leadership_style IS NOT NULL AND array_length(leadership_style, 1) > 0 THEN 3 ELSE 0 END) +

  -- Status (5 pts max)
  (CASE WHEN candidate_status IS NOT NULL THEN 3 ELSE 0 END) +
  (CASE WHEN availability_date IS NOT NULL THEN 2 ELSE 0 END) +

  -- Compensation (5 pts max)
  (CASE WHEN current_compensation IS NOT NULL THEN 3 ELSE 0 END) +
  (CASE WHEN compensation_expectation IS NOT NULL THEN 2 ELSE 0 END)
),
last_enriched_at = NOW(),
enrichment_version = COALESCE(enrichment_version, 0) + 1;

-- Report data quality distribution
DO $$
DECLARE
  avg_score DECIMAL;
  median_score INTEGER;
  below_25 INTEGER;
  between_25_50 INTEGER;
  between_50_75 INTEGER;
  above_75 INTEGER;
BEGIN
  SELECT AVG(data_completeness_score), PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY data_completeness_score)
  INTO avg_score, median_score
  FROM people;

  SELECT COUNT(*) INTO below_25 FROM people WHERE data_completeness_score < 25;
  SELECT COUNT(*) INTO between_25_50 FROM people WHERE data_completeness_score BETWEEN 25 AND 49;
  SELECT COUNT(*) INTO between_50_75 FROM people WHERE data_completeness_score BETWEEN 50 AND 74;
  SELECT COUNT(*) INTO above_75 FROM people WHERE data_completeness_score >= 75;

  RAISE NOTICE '=== Data Quality Distribution ===';
  RAISE NOTICE 'Average completeness: %.1f/100', avg_score;
  RAISE NOTICE 'Median completeness: %/100', median_score;
  RAISE NOTICE 'Poor (<25):      %', below_25;
  RAISE NOTICE 'Fair (25-49):    %', between_25_50;
  RAISE NOTICE 'Good (50-74):    %', between_50_75;
  RAISE NOTICE 'Excellent (75+): %', above_75;
END $$;

-- Top fields that are most commonly missing (for enrichment prioritization)
DO $$
DECLARE
  total INTEGER;
  missing_email INTEGER;
  missing_phone INTEGER;
  missing_school_link INTEGER;
  missing_education INTEGER;
  missing_specializations INTEGER;
  missing_cultural_fit INTEGER;
  missing_rating INTEGER;
  missing_state INTEGER;
  missing_career_stage INTEGER;
BEGIN
  SELECT COUNT(*) INTO total FROM people;
  SELECT COUNT(*) INTO missing_email FROM people WHERE email_primary IS NULL OR email_primary = '';
  SELECT COUNT(*) INTO missing_phone FROM people WHERE phone_primary IS NULL OR phone_primary = '';
  SELECT COUNT(*) INTO missing_school_link FROM people WHERE current_school_id IS NULL;
  SELECT COUNT(*) INTO missing_education FROM people WHERE NOT EXISTS (SELECT 1 FROM person_education pe WHERE pe.person_id = people.id);
  SELECT COUNT(*) INTO missing_specializations FROM people WHERE specializations IS NULL OR array_length(specializations, 1) IS NULL;
  SELECT COUNT(*) INTO missing_cultural_fit FROM people WHERE cultural_fit_tags IS NULL OR array_length(cultural_fit_tags, 1) IS NULL;
  SELECT COUNT(*) INTO missing_rating FROM people WHERE knock_rating IS NULL;
  SELECT COUNT(*) INTO missing_state FROM people WHERE state IS NULL;
  SELECT COUNT(*) INTO missing_career_stage FROM people WHERE career_stage IS NULL;

  RAISE NOTICE '=== Missing Field Report (of % total) ===', total;
  RAISE NOTICE 'Missing email:           % (%.0f%%)', missing_email, missing_email::float / total * 100;
  RAISE NOTICE 'Missing phone:           % (%.0f%%)', missing_phone, missing_phone::float / total * 100;
  RAISE NOTICE 'Missing school link:     % (%.0f%%)', missing_school_link, missing_school_link::float / total * 100;
  RAISE NOTICE 'Missing education:       % (%.0f%%)', missing_education, missing_education::float / total * 100;
  RAISE NOTICE 'Missing specializations: % (%.0f%%)', missing_specializations, missing_specializations::float / total * 100;
  RAISE NOTICE 'Missing cultural fit:    % (%.0f%%)', missing_cultural_fit, missing_cultural_fit::float / total * 100;
  RAISE NOTICE 'Missing knock rating:    % (%.0f%%)', missing_rating, missing_rating::float / total * 100;
  RAISE NOTICE 'Missing state:           % (%.0f%%)', missing_state, missing_state::float / total * 100;
  RAISE NOTICE 'Missing career stage:    % (%.0f%%)', missing_career_stage, missing_career_stage::float / total * 100;
END $$;

COMMIT;
