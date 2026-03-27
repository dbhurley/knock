-- 011_matching_engine.sql
-- Schema additions for the matching and prediction engine

-- Add transition prediction columns to schools
ALTER TABLE schools
    ADD COLUMN IF NOT EXISTS transition_prediction_score DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS predicted_transition_date DATE;

CREATE INDEX IF NOT EXISTS idx_schools_transition_score
    ON schools(transition_prediction_score DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_schools_predicted_transition
    ON schools(predicted_transition_date)
    WHERE predicted_transition_date IS NOT NULL;

-- Transition signals log: track which signals fired for each school prediction run
CREATE TABLE IF NOT EXISTS transition_signals_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    signal_name VARCHAR(100) NOT NULL,
    signal_points INTEGER NOT NULL,
    fired BOOLEAN NOT NULL DEFAULT FALSE,
    detail TEXT,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transition_signals_school
    ON transition_signals_log(school_id);
CREATE INDEX IF NOT EXISTS idx_transition_signals_date
    ON transition_signals_log(computed_at);

-- Match scores history: audit trail of match scores computed
CREATE TABLE IF NOT EXISTS match_scores_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID REFERENCES people(id) ON DELETE CASCADE,
    search_id UUID REFERENCES searches(id) ON DELETE CASCADE,
    composite_score DECIMAL(5,2) NOT NULL,
    hard_pass BOOLEAN NOT NULL,
    base_score DECIMAL(5,2),
    bonus_total DECIMAL(5,2),
    tier VARCHAR(20),
    factors JSONB,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_match_scores_candidate
    ON match_scores_log(candidate_id);
CREATE INDEX IF NOT EXISTS idx_match_scores_search
    ON match_scores_log(search_id);
CREATE INDEX IF NOT EXISTS idx_match_scores_composite
    ON match_scores_log(composite_score DESC);
