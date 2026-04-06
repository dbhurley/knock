-- enrich-01-school-linkage.sql
-- Re-match people to schools using multi-strategy fuzzy matching
-- Run with: docker exec -i knock-postgres-1 psql -U knock_admin -d knock < scripts/enrich-01-school-linkage.sql

BEGIN;

-- Ensure pg_trgm is available
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Report current state
DO $$
DECLARE
  total_people INTEGER;
  linked_people INTEGER;
  unlinked_people INTEGER;
BEGIN
  SELECT COUNT(*) INTO total_people FROM people;
  SELECT COUNT(*) INTO linked_people FROM people WHERE current_school_id IS NOT NULL;
  unlinked_people := total_people - linked_people;
  RAISE NOTICE '=== School Linkage Repair ===';
  RAISE NOTICE 'Total people: %', total_people;
  RAISE NOTICE 'Already linked: % (%.1f%%)', linked_people, (linked_people::float / GREATEST(total_people, 1) * 100);
  RAISE NOTICE 'Unlinked: %', unlinked_people;
END $$;

-- ─── Strategy 1: Exact name match (normalized) ───────────────────────────
-- Match people.current_organization against schools.name_normalized exactly

UPDATE people p
SET current_school_id = sub.school_id,
    updated_at = NOW()
FROM (
  SELECT DISTINCT ON (p2.id)
    p2.id AS person_id,
    s.id AS school_id
  FROM people p2
  JOIN schools s
    ON LOWER(TRIM(p2.current_organization)) = LOWER(TRIM(s.name))
    OR LOWER(TRIM(p2.current_organization)) = s.name_normalized
  WHERE p2.current_school_id IS NULL
    AND p2.current_organization IS NOT NULL
    AND p2.current_organization != ''
  ORDER BY p2.id, s.enrollment_total DESC NULLS LAST
) sub
WHERE p.id = sub.person_id;

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Strategy 1 (exact name): linked % people', cnt;
END $$;

-- ─── Strategy 2: Normalized with common suffixes stripped ─────────────────
-- Remove "School", "Academy", "Institute" etc. from both sides and match

CREATE OR REPLACE FUNCTION _strip_school_suffixes(input TEXT) RETURNS TEXT AS $$
BEGIN
  RETURN TRIM(REGEXP_REPLACE(
    LOWER(TRIM(input)),
    '\s*(school|academy|institute|college prep|preparatory|prep|day school|country day|the)\s*',
    ' ',
    'gi'
  ));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

UPDATE people p
SET current_school_id = sub.school_id,
    updated_at = NOW()
FROM (
  SELECT DISTINCT ON (p2.id)
    p2.id AS person_id,
    s.id AS school_id
  FROM people p2
  JOIN schools s
    ON _strip_school_suffixes(p2.current_organization) = _strip_school_suffixes(s.name)
  WHERE p2.current_school_id IS NULL
    AND p2.current_organization IS NOT NULL
    AND LENGTH(TRIM(p2.current_organization)) > 3
  ORDER BY p2.id, s.enrollment_total DESC NULLS LAST
) sub
WHERE p.id = sub.person_id;

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Strategy 2 (stripped suffixes): linked % people', cnt;
END $$;

-- ─── Strategy 3: Trigram similarity with city+state boost ─────────────────
-- Use pg_trgm similarity for fuzzy matching, boosted when city/state also match

UPDATE people p
SET current_school_id = sub.school_id,
    updated_at = NOW()
FROM (
  SELECT DISTINCT ON (p2.id)
    p2.id AS person_id,
    s.id AS school_id,
    similarity(LOWER(p2.current_organization), LOWER(s.name)) AS sim_score
  FROM people p2
  JOIN schools s
    ON similarity(LOWER(p2.current_organization), LOWER(s.name)) > 0.45
  WHERE p2.current_school_id IS NULL
    AND p2.current_organization IS NOT NULL
    AND LENGTH(TRIM(p2.current_organization)) > 5
    -- Boost: require state match or very high similarity
    AND (
      (p2.state IS NOT NULL AND p2.state = s.state AND similarity(LOWER(p2.current_organization), LOWER(s.name)) > 0.45)
      OR similarity(LOWER(p2.current_organization), LOWER(s.name)) > 0.7
    )
    -- Filter out non-school organizations
    AND p2.current_organization !~* '(consulting|university|college\s|foundation|association|board\s|district|public\sschool|charter)'
  ORDER BY p2.id, sim_score DESC, s.enrollment_total DESC NULLS LAST
) sub
WHERE p.id = sub.person_id;

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Strategy 3 (trigram + geo): linked % people', cnt;
END $$;

-- ─── Strategy 4: Backfill state from linked school ────────────────────────
-- If a person is now linked to a school but has no state, copy it over

UPDATE people p
SET state = s.state,
    city = COALESCE(p.city, s.city),
    updated_at = NOW()
FROM schools s
WHERE p.current_school_id = s.id
  AND p.state IS NULL
  AND s.state IS NOT NULL;

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Strategy 4 (geo backfill from school): updated % people', cnt;
END $$;

-- ─── Strategy 5: Populate school_type_experience from linked school ───────
-- If a person has a linked school, ensure the school's type is in their experience

UPDATE people p
SET school_type_experience = ARRAY(
  SELECT DISTINCT unnest
  FROM unnest(COALESCE(p.school_type_experience, ARRAY[]::TEXT[]) || ARRAY[s.school_type]) AS unnest
  WHERE unnest IS NOT NULL
),
    updated_at = NOW()
FROM schools s
WHERE p.current_school_id = s.id
  AND s.school_type IS NOT NULL
  AND (p.school_type_experience IS NULL OR NOT (p.school_type_experience @> ARRAY[s.school_type]::TEXT[]));

DO $$
DECLARE cnt INTEGER;
BEGIN
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'Strategy 5 (school_type_experience backfill): updated % people', cnt;
END $$;

-- Report final state
DO $$
DECLARE
  total_people INTEGER;
  linked_people INTEGER;
BEGIN
  SELECT COUNT(*) INTO total_people FROM people;
  SELECT COUNT(*) INTO linked_people FROM people WHERE current_school_id IS NOT NULL;
  RAISE NOTICE '=== Final State ===';
  RAISE NOTICE 'Total people: %', total_people;
  RAISE NOTICE 'Linked to school: % (%.1f%%)', linked_people, (linked_people::float / GREATEST(total_people, 1) * 100);
END $$;

-- Clean up helper function
DROP FUNCTION IF EXISTS _strip_school_suffixes(TEXT);

COMMIT;
