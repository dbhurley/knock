-- 013_add_assessment_fields.sql
-- Add assessment fields used by the candidate rating tool

ALTER TABLE people ADD COLUMN IF NOT EXISTS ideal_next_role VARCHAR(50);
-- 'larger_hos', 'similar_hos', 'division_head', 'consultant', 'retired', 'other'

ALTER TABLE people ADD COLUMN IF NOT EXISTS transition_readiness VARCHAR(30);
-- 'ready_now', 'ready_1yr', 'ready_2yr', 'not_ready'

CREATE INDEX IF NOT EXISTS idx_people_transition ON people(transition_readiness);
CREATE INDEX IF NOT EXISTS idx_people_ideal_role ON people(ideal_next_role);
