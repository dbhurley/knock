-- 008_create_industry.sql
-- Industry intelligence tables

-- Conference and event tracking
CREATE TABLE industry_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_name VARCHAR(500) NOT NULL,
    organization VARCHAR(300),            -- 'NAIS', 'TABS', state association, etc.
    event_type VARCHAR(50),               -- 'conference', 'workshop', 'webinar', 'job_fair'
    start_date DATE,
    end_date DATE,
    location VARCHAR(300),
    url VARCHAR(500),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- People attending events
CREATE TABLE event_attendees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES industry_events(id) ON DELETE CASCADE,
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    role VARCHAR(50),                     -- 'speaker', 'attendee', 'panelist', 'organizer'
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Industry news and signals
CREATE TABLE industry_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type VARCHAR(50) NOT NULL,
    -- Types: 'head_departure', 'head_appointment', 'school_merger',
    --        'school_closing', 'accreditation_change', 'enrollment_shift',
    --        'leadership_search_announced', 'board_change', 'scandal',
    --        'expansion', 'program_launch', 'financial_issue'
    school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    headline VARCHAR(500),
    description TEXT,
    source_url VARCHAR(500),
    source_name VARCHAR(200),
    signal_date DATE,
    confidence VARCHAR(20),               -- 'confirmed', 'likely', 'rumor'
    impact VARCHAR(20),                   -- 'high', 'medium', 'low'
    actioned BOOLEAN DEFAULT FALSE,       -- Has Knock acted on this?
    action_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_signals_type ON industry_signals(signal_type);
CREATE INDEX idx_signals_school ON industry_signals(school_id);
CREATE INDEX idx_signals_date ON industry_signals(signal_date);
CREATE INDEX idx_signals_actioned ON industry_signals(actioned);

-- Educational leadership programs (pipeline tracking)
CREATE TABLE leadership_programs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution VARCHAR(300) NOT NULL,
    program_name VARCHAR(300),
    degree_type VARCHAR(50),              -- 'ed_d', 'ph_d', 'masters', 'certificate'
    specialization VARCHAR(200),
    program_url VARCHAR(500),
    avg_cohort_size INTEGER,
    typical_duration VARCHAR(50),         -- '2 years', '3 years', etc.
    program_format VARCHAR(50),           -- 'full_time', 'part_time', 'executive', 'online', 'hybrid'
    ranking_tier VARCHAR(20),             -- 'top_10', 'top_25', 'top_50', 'other'
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Graduates from leadership programs (future candidate pipeline)
CREATE TABLE program_graduates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id UUID REFERENCES leadership_programs(id) ON DELETE SET NULL,
    person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    graduation_year INTEGER,
    dissertation_topic VARCHAR(500),
    cohort_name VARCHAR(100),
    current_status VARCHAR(50),           -- 'placed', 'seeking', 'advancing', 'unknown'
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
