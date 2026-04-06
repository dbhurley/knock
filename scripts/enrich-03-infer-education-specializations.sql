-- enrich-03-infer-education-specializations.sql
-- Infer education level, specializations, and leadership style from existing text fields
-- Run with: docker exec -i knock-postgres-1 psql -U knock_admin -d knock < scripts/enrich-03-infer-education-specializations.sql

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- PART 1: INFER EDUCATION LEVEL
-- ═══════════════════════════════════════════════════════════════════════════

-- Source: suffix, prefix, current_title, linkedin_headline, linkedin_summary

-- 1a. From suffix field (most reliable: "Ed.D.", "Ph.D.", "M.Ed.")
UPDATE people
SET inferred_education_level = 'doctorate'
WHERE inferred_education_level IS NULL
  AND (
    suffix ~* '(ed\.?d|ph\.?d|edd|phd|d\.min|d\.ed|jd|j\.d)'
    OR prefix ~* '(dr\.?)'
  );

DO $$
DECLARE cnt INTEGER;
BEGIN
  SELECT COUNT(*) INTO cnt FROM people WHERE inferred_education_level = 'doctorate';
  RAISE NOTICE 'Education inference - doctorate from suffix/prefix: %', cnt;
END $$;

UPDATE people
SET inferred_education_level = 'masters'
WHERE inferred_education_level IS NULL
  AND suffix ~* '(m\.?ed|m\.?a|m\.?s|mba|m\.div|m\.?ed\.?|msed)';

DO $$
DECLARE cnt INTEGER;
BEGIN
  SELECT COUNT(*) INTO cnt FROM people WHERE inferred_education_level = 'masters';
  RAISE NOTICE 'Education inference - masters from suffix: %', cnt;
END $$;

-- 1b. From title and headline text
UPDATE people
SET inferred_education_level = 'doctorate'
WHERE inferred_education_level IS NULL
  AND (
    current_title ~* '(ed\.?d|ph\.?d|doctor)'
    OR linkedin_headline ~* '(ed\.?d|ph\.?d|edd|phd|doctoral)'
  );

UPDATE people
SET inferred_education_level = 'masters'
WHERE inferred_education_level IS NULL
  AND (
    linkedin_headline ~* '(m\.?ed|mba|master|m\.a\.|m\.s\.)'
    OR linkedin_summary ~* '(master.s degree|master of|m\.ed\.|mba|earned (his|her|their) m)'
  );

-- 1c. From linkedin_summary for broader education mentions
UPDATE people
SET inferred_education_level = 'doctorate'
WHERE inferred_education_level IS NULL
  AND linkedin_summary ~* '(completed (his|her|their) (ed\.?d|ph\.?d|doctorate)|doctoral program|dissertation|earned (his|her|their) (ed\.?d|ph\.?d))';

UPDATE people
SET inferred_education_level = 'bachelors'
WHERE inferred_education_level IS NULL
  AND linkedin_summary ~* '(b\.?a\.|b\.?s\.|bachelor|undergraduate degree)';

DO $$
DECLARE
  doc_count INTEGER;
  masters_count INTEGER;
  bachelors_count INTEGER;
  unknown_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO doc_count FROM people WHERE inferred_education_level = 'doctorate';
  SELECT COUNT(*) INTO masters_count FROM people WHERE inferred_education_level = 'masters';
  SELECT COUNT(*) INTO bachelors_count FROM people WHERE inferred_education_level = 'bachelors';
  SELECT COUNT(*) INTO unknown_count FROM people WHERE inferred_education_level IS NULL;

  RAISE NOTICE '=== Education Inference Results ===';
  RAISE NOTICE 'Doctorate:  %', doc_count;
  RAISE NOTICE 'Masters:    %', masters_count;
  RAISE NOTICE 'Bachelors:  %', bachelors_count;
  RAISE NOTICE 'Unknown:    %', unknown_count;
END $$;

-- 1d. Insert inferred education into person_education table (if not already there)
INSERT INTO person_education (person_id, institution, degree, field_of_study, is_education_leadership)
SELECT
  p.id,
  'Inferred from profile',
  CASE p.inferred_education_level
    WHEN 'doctorate' THEN
      CASE
        WHEN p.suffix ~* 'ph\.?d' THEN 'Ph.D.'
        WHEN p.suffix ~* 'ed\.?d' THEN 'Ed.D.'
        WHEN p.suffix ~* 'jd|j\.d' THEN 'J.D.'
        ELSE 'Ed.D.'  -- Default doctorate for education leaders
      END
    WHEN 'masters' THEN
      CASE
        WHEN p.suffix ~* 'mba' THEN 'M.B.A.'
        WHEN p.suffix ~* 'm\.?ed' THEN 'M.Ed.'
        ELSE 'M.Ed.'  -- Default masters for education leaders
      END
    WHEN 'bachelors' THEN 'B.A.'
    ELSE NULL
  END,
  CASE
    WHEN p.primary_role IN ('head_of_school', 'division_head', 'academic_dean', 'principal') THEN 'Education Leadership'
    WHEN p.primary_role = 'cfo' THEN 'Business Administration'
    ELSE 'Education'
  END,
  CASE WHEN p.inferred_education_level IN ('doctorate', 'masters') AND p.primary_role IN ('head_of_school', 'division_head', 'academic_dean', 'principal') THEN TRUE ELSE FALSE END
FROM people p
WHERE p.inferred_education_level IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM person_education pe WHERE pe.person_id = p.id
  );

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Inserted % inferred education records into person_education', cnt;
END $$;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 2: INFER SPECIALIZATIONS FROM TITLE/HEADLINE/SUMMARY
-- ═══════════════════════════════════════════════════════════════════════════

-- Only for people who currently have no specializations
-- Build specializations from keyword detection in text fields

-- Create a temp table of keyword → specialization mappings
CREATE TEMP TABLE spec_keywords (
  keyword TEXT,
  specialization TEXT
);

INSERT INTO spec_keywords VALUES
  -- Academic areas
  ('stem', 'stem'),
  ('science', 'stem'),
  ('technology', 'stem'),
  ('engineering', 'stem'),
  ('mathematics', 'stem'),
  ('arts', 'arts'),
  ('performing arts', 'arts'),
  ('visual arts', 'arts'),
  ('music', 'arts'),
  ('humanities', 'humanities'),
  ('literacy', 'literacy'),
  ('reading', 'literacy'),

  -- School operations
  ('fundrais', 'fundraising'),
  ('advancement', 'fundraising'),
  ('development office', 'fundraising'),
  ('capital campaign', 'fundraising'),
  ('annual fund', 'fundraising'),
  ('enrollment', 'enrollment_management'),
  ('admission', 'enrollment_management'),
  ('marketing', 'enrollment_management'),
  ('financial aid', 'financial_management'),
  ('budget', 'financial_management'),
  ('finance', 'financial_management'),
  ('endowment', 'financial_management'),
  ('facilities', 'operations'),
  ('operations', 'operations'),

  -- Leadership specialties
  ('diversity', 'dei'),
  ('equity', 'dei'),
  ('inclusion', 'dei'),
  ('dei', 'dei'),
  ('deib', 'dei'),
  ('multicultural', 'dei'),
  ('boarding', 'boarding'),
  ('residential', 'boarding'),
  ('international', 'international'),
  ('global', 'international'),
  ('faith', 'faith_based'),
  ('spiritual', 'faith_based'),
  ('ministry', 'faith_based'),
  ('catholic', 'faith_based'),
  ('episcopal', 'faith_based'),
  ('quaker', 'faith_based'),
  ('montessori', 'montessori'),
  ('waldorf', 'waldorf'),
  ('reggio', 'progressive_education'),
  ('progressive', 'progressive_education'),
  ('project.based', 'progressive_education'),

  -- Special populations
  ('special education', 'special_education'),
  ('learning differ', 'special_education'),
  ('learning disabilit', 'special_education'),
  ('gifted', 'gifted_education'),
  ('talented', 'gifted_education'),
  ('early childhood', 'early_childhood'),
  ('preschool', 'early_childhood'),
  ('pre-k', 'early_childhood'),

  -- Technology
  ('edtech', 'educational_technology'),
  ('1:1', 'educational_technology'),
  ('one.to.one', 'educational_technology'),
  ('digital learning', 'educational_technology'),
  ('online learning', 'educational_technology'),

  -- Governance
  ('accreditation', 'accreditation'),
  ('governance', 'governance'),
  ('board', 'governance'),
  ('strategic plan', 'strategic_planning'),
  ('long.range plan', 'strategic_planning'),
  ('visioning', 'strategic_planning'),

  -- Curriculum
  ('curriculum', 'curriculum_development'),
  ('assessment', 'curriculum_development'),
  ('instruction', 'curriculum_development'),
  ('pedagogy', 'curriculum_development');

-- Apply specialization inference
UPDATE people p
SET specializations = sub.inferred_specs,
    updated_at = NOW()
FROM (
  SELECT
    p2.id,
    ARRAY(SELECT DISTINCT sk.specialization
      FROM spec_keywords sk
      WHERE
        COALESCE(p2.current_title, '') || ' ' ||
        COALESCE(p2.linkedin_headline, '') || ' ' ||
        COALESCE(p2.linkedin_summary, '') || ' ' ||
        COALESCE(array_to_string(p2.tags, ' '), '')
        ~* sk.keyword
      ORDER BY sk.specialization
    ) AS inferred_specs
  FROM people p2
  WHERE (p2.specializations IS NULL OR array_length(p2.specializations, 1) IS NULL)
    AND (
      p2.current_title IS NOT NULL
      OR p2.linkedin_headline IS NOT NULL
      OR p2.linkedin_summary IS NOT NULL
    )
) sub
WHERE p.id = sub.id
  AND array_length(sub.inferred_specs, 1) > 0;

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Specialization inference: updated % people', cnt;
END $$;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 3: INFER LEADERSHIP STYLE FROM TEXT
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TEMP TABLE style_keywords (
  keyword TEXT,
  style TEXT
);

INSERT INTO style_keywords VALUES
  ('collaborat', 'collaborative'),
  ('partner', 'collaborative'),
  ('team', 'collaborative'),
  ('consensus', 'collaborative'),
  ('vision', 'visionary'),
  ('innovat', 'visionary'),
  ('transform', 'transformational'),
  ('change agent', 'transformational'),
  ('turnaround', 'transformational'),
  ('reimagin', 'transformational'),
  ('operational', 'operational'),
  ('efficien', 'operational'),
  ('systems', 'operational'),
  ('process', 'operational'),
  ('servant leader', 'servant'),
  ('servant', 'servant'),
  ('community', 'community_builder'),
  ('relationship', 'community_builder'),
  ('inclusive', 'community_builder'),
  ('data.driven', 'data_driven'),
  ('evidence.based', 'data_driven'),
  ('measur', 'data_driven'),
  ('entrepreneuri', 'entrepreneurial'),
  ('startup', 'entrepreneurial'),
  ('founded', 'entrepreneurial');

UPDATE people p
SET leadership_style = sub.inferred_styles,
    updated_at = NOW()
FROM (
  SELECT
    p2.id,
    ARRAY(SELECT DISTINCT stk.style
      FROM style_keywords stk
      WHERE
        COALESCE(p2.current_title, '') || ' ' ||
        COALESCE(p2.linkedin_headline, '') || ' ' ||
        COALESCE(p2.linkedin_summary, '')
        ~* stk.keyword
      ORDER BY stk.style
    ) AS inferred_styles
  FROM people p2
  WHERE (p2.leadership_style IS NULL OR array_length(p2.leadership_style, 1) IS NULL)
    AND (
      p2.linkedin_headline IS NOT NULL
      OR p2.linkedin_summary IS NOT NULL
    )
) sub
WHERE p.id = sub.id
  AND array_length(sub.inferred_styles, 1) > 0;

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Leadership style inference: updated % people', cnt;
END $$;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 4: INFER CAREER STAGE (for people where it's missing)
-- ═══════════════════════════════════════════════════════════════════════════

-- Use title keywords and years in role to infer career stage
UPDATE people
SET career_stage = CASE
  -- Retired indicators
  WHEN current_title ~* '(retired|emerit|former head)' THEN 'retired'
  -- Veteran: "Head of School" with long tenure or "founding" in title
  WHEN primary_role = 'head_of_school' AND years_in_current_role >= 10 THEN 'veteran'
  WHEN current_title ~* '(founding|emerit)' THEN 'veteran'
  -- Senior: current head or experienced division head
  WHEN primary_role = 'head_of_school' THEN 'senior'
  WHEN primary_role = 'division_head' AND years_in_current_role >= 5 THEN 'senior'
  -- Mid-career: division heads, deans, experienced directors
  WHEN primary_role IN ('division_head', 'academic_dean', 'cfo') THEN 'mid_career'
  WHEN current_title ~* '(director|dean|assistant head|associate head)' THEN 'mid_career'
  -- Emerging: teachers, coordinators, early-career
  WHEN current_title ~* '(teacher|coordinator|counselor|coach)' THEN 'emerging'
  ELSE NULL
END,
updated_at = NOW()
WHERE career_stage IS NULL
  AND current_title IS NOT NULL;

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Career stage inference: updated % people', cnt;
END $$;


-- ═══════════════════════════════════════════════════════════════════════════
-- SUMMARY
-- ═══════════════════════════════════════════════════════════════════════════

DO $$
DECLARE
  total INTEGER;
  with_education INTEGER;
  with_specs INTEGER;
  with_style INTEGER;
  with_stage INTEGER;
BEGIN
  SELECT COUNT(*) INTO total FROM people;
  SELECT COUNT(*) INTO with_education FROM people WHERE inferred_education_level IS NOT NULL;
  SELECT COUNT(*) INTO with_specs FROM people WHERE specializations IS NOT NULL AND array_length(specializations, 1) > 0;
  SELECT COUNT(*) INTO with_style FROM people WHERE leadership_style IS NOT NULL AND array_length(leadership_style, 1) > 0;
  SELECT COUNT(*) INTO with_stage FROM people WHERE career_stage IS NOT NULL;

  RAISE NOTICE '=== Enrichment Summary (of % total) ===', total;
  RAISE NOTICE 'With education level: % (%.0f%%)', with_education, with_education::float / total * 100;
  RAISE NOTICE 'With specializations: % (%.0f%%)', with_specs, with_specs::float / total * 100;
  RAISE NOTICE 'With leadership style: % (%.0f%%)', with_style, with_style::float / total * 100;
  RAISE NOTICE 'With career stage: % (%.0f%%)', with_stage, with_stage::float / total * 100;
END $$;

DROP TABLE IF EXISTS spec_keywords;
DROP TABLE IF EXISTS style_keywords;

COMMIT;
