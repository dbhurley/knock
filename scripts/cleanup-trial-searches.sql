-- Remove trial searches KNK-2026-001 and KNK-2026-002
-- Run with: docker exec -i knock-postgres-1 psql -U knock_admin -d knock < scripts/cleanup-trial-searches.sql

BEGIN;

-- Show what we're deleting
SELECT search_number, position_title, status, created_at
FROM searches
WHERE search_number IN ('KNK-2026-001', 'KNK-2026-002');

-- Remove dependent records first
DELETE FROM search_activities
WHERE search_id IN (SELECT id FROM searches WHERE search_number IN ('KNK-2026-001', 'KNK-2026-002'));

DELETE FROM search_candidates
WHERE search_id IN (SELECT id FROM searches WHERE search_number IN ('KNK-2026-001', 'KNK-2026-002'));

-- Remove the searches
DELETE FROM searches
WHERE search_number IN ('KNK-2026-001', 'KNK-2026-002');

-- Confirm clean state
SELECT COUNT(*) AS remaining_searches FROM searches;

COMMIT;
