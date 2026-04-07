-- enrich-04-backfill-experience.sql
-- Backfill structured experience and tag data from existing fields and linked schools.
-- Run AFTER enrich-01-school-linkage.sql so that current_school_id is populated.
--
-- This script dramatically improves matching engine accuracy by populating fields
-- that the scoring algorithm reads (person_experience, enrollment_experience_range,
-- cultural_fit_tags, religious_school_experience).
--
-- Run with:
--   docker exec -i knock-postgres psql -U knock_admin -d knock < scripts/enrich-04-backfill-experience.sql

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- PART 1: Populate person_experience for currently-employed people
-- ═══════════════════════════════════════════════════════════════════════════
-- The matching engine checks person_experience.is_current to score
-- position_experience. Without these rows, current heads of school score 60
-- instead of 100.

INSERT INTO person_experience (
  person_id, organization, school_id, title, is_current,
  position_category, school_enrollment, school_type
)
SELECT
  p.id,
  COALESCE(s.name, p.current_organization, 'Unknown'),
  p.current_school_id,
  COALESCE(p.current_title, 'Unknown'),
  TRUE,
  p.primary_role,
  s.enrollment_total,
  s.school_type
FROM people p
LEFT JOIN schools s ON p.current_school_id = s.id
WHERE p.current_title IS NOT NULL
  AND p.current_organization IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM person_experience pe
    WHERE pe.person_id = p.id AND pe.is_current = TRUE
  );

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Step 1 (person_experience): inserted % records', cnt;
END $$;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 2: Backfill enrollment_experience_range from current school
-- ═══════════════════════════════════════════════════════════════════════════
-- The matching engine checks enrollment range to see if a candidate has
-- experience with schools of the target size. We use the linked school's
-- enrollment ± a margin as a reasonable initial range.

UPDATE people p
SET enrollment_experience_range = int4range(
  GREATEST(s.enrollment_total - 200, 1),
  s.enrollment_total + 500
)
FROM schools s
WHERE p.current_school_id = s.id
  AND s.enrollment_total IS NOT NULL
  AND p.enrollment_experience_range IS NULL;

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Step 2 (enrollment_experience_range): updated % people', cnt;
END $$;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 3: Inherit cultural_fit_tags from linked school characteristics
-- ═══════════════════════════════════════════════════════════════════════════
-- A person leading a Catholic boarding school inherits faith-based + boarding
-- tags by default. These can be overridden manually via the assessment tool.

UPDATE people p
SET cultural_fit_tags = ARRAY(
  SELECT DISTINCT unnest(arr.tag)
  FROM (
    VALUES
      (CASE WHEN s.religious_affiliation IS NOT NULL AND s.religious_affiliation != 'Nonsectarian'
            THEN ARRAY['faith-based'] ELSE ARRAY[]::TEXT[] END),
      (CASE WHEN s.religious_affiliation = 'Nonsectarian'
            THEN ARRAY['secular'] ELSE ARRAY[]::TEXT[] END),
      (CASE WHEN s.boarding_status IN ('boarding', 'day_boarding')
            THEN ARRAY['boarding-experienced'] ELSE ARRAY[]::TEXT[] END),
      (CASE WHEN s.coed_status = 'coed' THEN ARRAY['coed'] ELSE ARRAY[]::TEXT[] END),
      (CASE WHEN s.coed_status IN ('boys','girls') THEN ARRAY['single-sex'] ELSE ARRAY[]::TEXT[] END),
      (CASE WHEN s.school_culture_tags IS NOT NULL THEN s.school_culture_tags ELSE ARRAY[]::TEXT[] END)
  ) AS arr(tag)
  WHERE arr.tag IS NOT NULL AND array_length(arr.tag, 1) > 0
)
FROM schools s
WHERE p.current_school_id = s.id
  AND (p.cultural_fit_tags IS NULL OR array_length(p.cultural_fit_tags, 1) IS NULL OR array_length(p.cultural_fit_tags, 1) = 0);

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Step 3 (cultural_fit_tags): updated % people', cnt;
END $$;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 4: Set boarding/religious experience flags from linked schools
-- ═══════════════════════════════════════════════════════════════════════════

UPDATE people p
SET
  religious_school_experience = (s.religious_affiliation IS NOT NULL AND s.religious_affiliation != 'Nonsectarian'),
  boarding_experience = (s.boarding_status IN ('boarding', 'day_boarding'))
FROM schools s
WHERE p.current_school_id = s.id
  AND (p.religious_school_experience IS NULL OR p.boarding_experience IS NULL);

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Step 4 (experience flags): updated % people', cnt;
END $$;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 5: Default education to masters for senior school leaders
-- ═══════════════════════════════════════════════════════════════════════════
-- Industry minimum for HOS, division heads, and academic deans is a master's
-- degree. Without specific data, this is a safe default.

UPDATE people SET inferred_education_level = 'masters'
WHERE inferred_education_level IS NULL
  AND primary_role IN ('head_of_school', 'division_head', 'academic_dean', 'principal');

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Step 5a (default masters): updated % people', cnt;
END $$;

-- Insert person_education records for the newly-set defaults
INSERT INTO person_education (person_id, institution, degree, field_of_study, is_education_leadership)
SELECT p.id, 'Inferred from role', 'M.Ed.', 'Education Leadership', TRUE
FROM people p
WHERE p.inferred_education_level = 'masters'
  AND NOT EXISTS (SELECT 1 FROM person_education pe WHERE pe.person_id = p.id);

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Step 5b (education records): inserted % records', cnt;
END $$;


-- ═══════════════════════════════════════════════════════════════════════════
-- SUMMARY
-- ═══════════════════════════════════════════════════════════════════════════

DO $$
DECLARE
  total INTEGER;
  with_exp INTEGER;
  with_enroll INTEGER;
  with_cul INTEGER;
  with_edu INTEGER;
BEGIN
  SELECT COUNT(*) INTO total FROM people;
  SELECT COUNT(DISTINCT person_id) INTO with_exp FROM person_experience;
  SELECT COUNT(*) INTO with_enroll FROM people WHERE enrollment_experience_range IS NOT NULL;
  SELECT COUNT(*) INTO with_cul FROM people WHERE cultural_fit_tags IS NOT NULL AND array_length(cultural_fit_tags, 1) > 0;
  SELECT COUNT(*) INTO with_edu FROM people WHERE EXISTS (SELECT 1 FROM person_education pe WHERE pe.person_id = people.id);

  RAISE NOTICE '=== Backfill Summary (of % total) ===', total;
  RAISE NOTICE 'With person_experience:        % (%.0f%%)', with_exp, with_exp::float / total * 100;
  RAISE NOTICE 'With enrollment_range:         % (%.0f%%)', with_enroll, with_enroll::float / total * 100;
  RAISE NOTICE 'With cultural_fit_tags:        % (%.0f%%)', with_cul, with_cul::float / total * 100;
  RAISE NOTICE 'With education record:         % (%.0f%%)', with_edu, with_edu::float / total * 100;
END $$;

COMMIT;
