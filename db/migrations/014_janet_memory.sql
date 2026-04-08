-- 014_janet_memory.sql
-- Janet's memory moves from markdown files into the database.
-- Two tables: janet_memory (what she knows) and janet_outputs (what she told whom).
-- This replaces the bloated SOUL.md / memory/YYYY-MM-DD.md approach.

-- ═══════════════════════════════════════════════════════════════════════
-- janet_memory: structured facts, decisions, standing instructions
-- ═══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS janet_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Categorization
    kind VARCHAR(40) NOT NULL,
    -- kinds:
    --   'standing_instruction' — Dan told her "always do X"
    --   'fact'                 — something she should know (Becca Thomas = Rebecca, Ed.D.)
    --   'decision'             — a decision made in conversation ("use CCA Colleyville not Cornerstone GA")
    --   'followup'             — something to do later
    --   'preference'           — Dan's style preferences
    --   'correction'           — past mistake + what's correct now
    --   'context'              — general context about a person/school/search

    -- Subject (what this memory is about)
    subject VARCHAR(500),  -- short label: "CCA Colleyville", "Angela Rimington", "Dan's pricing style"

    -- Content
    content TEXT NOT NULL,  -- the actual memory, in Janet's own words

    -- Entity references (structured links to DB records)
    related_search_id UUID REFERENCES searches(id) ON DELETE SET NULL,
    related_school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    related_person_id UUID REFERENCES people(id) ON DELETE SET NULL,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,  -- superseded memories get is_active=false, not deleted
    superseded_by UUID REFERENCES janet_memory(id),
    priority SMALLINT DEFAULT 5,  -- 1-10, higher = more important

    -- Source tracking
    source VARCHAR(50),  -- 'telegram', 'email', 'self_inference', 'import', 'manual'
    source_message_id VARCHAR(200),
    learned_from VARCHAR(100),  -- who said it ('dan', 'becca_thomas', 'self')

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ,
    access_count INTEGER DEFAULT 0,

    -- Search
    search_vector tsvector
);

CREATE INDEX IF NOT EXISTS idx_janet_memory_kind ON janet_memory(kind) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_janet_memory_subject ON janet_memory(subject) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_janet_memory_search ON janet_memory(related_search_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_janet_memory_school ON janet_memory(related_school_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_janet_memory_person ON janet_memory(related_person_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_janet_memory_priority ON janet_memory(priority DESC, updated_at DESC) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_janet_memory_fts ON janet_memory USING gin(search_vector);

-- Full-text trigger
CREATE OR REPLACE FUNCTION janet_memory_fts_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.subject, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.kind, '')), 'C');
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_janet_memory_fts ON janet_memory;
CREATE TRIGGER trg_janet_memory_fts
    BEFORE INSERT OR UPDATE ON janet_memory
    FOR EACH ROW EXECUTE FUNCTION janet_memory_fts_update();

-- ═══════════════════════════════════════════════════════════════════════
-- janet_outputs: ledger of what Janet said to whom, through which channel
-- ═══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS janet_outputs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- When and where
    channel VARCHAR(30) NOT NULL,  -- 'telegram', 'email', 'web', 'internal'
    recipient VARCHAR(300),  -- telegram user id, email address, etc.
    recipient_label VARCHAR(300),  -- human-readable: "Dan (@dbhurley)", "becca@covenantchristian.net"

    -- Content
    summary VARCHAR(1000),  -- one-line summary of what Janet said
    full_text TEXT,  -- full message body

    -- Trigger
    in_response_to VARCHAR(1000),  -- what question/prompt triggered this

    -- Entity references
    related_search_id UUID REFERENCES searches(id) ON DELETE SET NULL,
    related_school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    related_person_id UUID REFERENCES people(id) ON DELETE SET NULL,

    -- Memory links (which memory records informed this output)
    informed_by_memory_ids UUID[],

    -- Metadata
    contains_claims BOOLEAN DEFAULT FALSE,  -- TRUE if Janet made factual claims (flag for review)
    flagged_for_review BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_janet_outputs_channel ON janet_outputs(channel, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_janet_outputs_recipient ON janet_outputs(recipient, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_janet_outputs_search ON janet_outputs(related_search_id);
CREATE INDEX IF NOT EXISTS idx_janet_outputs_created ON janet_outputs(created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════
-- Seed with the current CCA memories (migrate from the markdown mess)
-- ═══════════════════════════════════════════════════════════════════════

INSERT INTO janet_memory (kind, subject, content, related_school_id, related_person_id, related_search_id, source, learned_from, priority) VALUES

-- Standing instructions
('standing_instruction', 'Anti-hallucination',
 'Never invent data. If a field is NULL in the database, say it is not on file. Do not fabricate addresses, phone numbers, emails, enrollment, founding year, teacher counts, or ratios. Always query the database fresh before citing specific facts.',
 NULL, NULL, NULL, 'manual', 'dan', 10),

('standing_instruction', 'Memory-first protocol',
 'Before responding to any question: (1) query janet_memory for relevant facts, (2) query the knock-api database for current records, (3) only then answer. Log every response to janet_outputs.',
 NULL, NULL, NULL, 'manual', 'dan', 10),

('standing_instruction', 'Naming: Dan',
 'Dan Hurley goes by "Dan" — his Telegram profile shows "Dan''l" but that is just his handle, not what he is called.',
 NULL, NULL, NULL, 'manual', 'dan', 8),

-- CCA Colleyville facts (authoritative)
('fact', 'Covenant Christian Academy - Colleyville TX',
 'Covenant Christian Academy in Colleyville, TX is the subject of active search KNK-2026-001. School has 537 students, website covenantchristian.net, tagged classical_christian and accs (ACCS-accredited). Pedagogy: classical. Segment: evangelical_christian. No street address, phone, or email are on file in the database.',
 '2b9769f0-2017-48f7-b797-859937613e23', NULL, NULL, 'manual', 'dan', 9),

('fact', 'Becca Thomas identity',
 'Becca Thomas is Rebecca Thomas, Ed.D. — current Head of School at Covenant Christian Academy of Colleyville. She is the client contact for search KNK-2026-001. She is BOTH the departing HOS and the primary contact (she is running the search for her own replacement).',
 '2b9769f0-2017-48f7-b797-859937613e23',
 '3ea5dc78-f89e-4f47-97e2-33a44c7ff734',
 NULL, 'manual', 'dan', 9),

('fact', 'Angela Rimington candidate profile',
 'Angela Rimington is Head of School at Veritas Christian Academy of Houston, started 2025. 30+ years in classical Christian and independent school leadership. Prior: Highlands Latin School where she doubled enrollment in 5 years. Retention record: 94% student, 97% faculty. Email: angela.rimington@gmail.com. Phone: 202-746-6958.',
 NULL,
 '33c56846-026d-41da-bb59-0d5461ec02e8',
 NULL, 'manual', 'dan', 8),

('decision', 'Angela at CCA - flag short tenure',
 'When presenting Angela Rimington to the CCA search committee, proactively flag that she has only 1 year at Veritas (started 2025). Committees will ask about the short tenure.',
 NULL,
 '33c56846-026d-41da-bb59-0d5461ec02e8',
 NULL, 'manual', 'dan', 7),

('correction', 'CCA is Covenant, not Cornerstone',
 'Earlier confusion: Angela Rimington was initially mis-tagged to "Cornerstone Christian Academy GA". The correct school is Covenant Christian Academy in Colleyville, TX. This was corrected on 2026-04-08.',
 '2b9769f0-2017-48f7-b797-859937613e23',
 '33c56846-026d-41da-bb59-0d5461ec02e8',
 NULL, 'manual', 'dan', 8),

-- Pricing reference (standing instruction)
('standing_instruction', 'Knock pricing bands',
 'Knock uses FIXED fees, not % of salary. Bands: A $70-100K->$20K | B $100-150K->$30K | C $150-200K->$40K | D $200-275K->$55K | E $275-375K->$75K | F $375-500K->$100K | G $500K+->$125K. This is Knock''s key differentiator vs Carney Sandoe and others.',
 NULL, NULL, NULL, 'manual', 'dan', 9);

-- Link the CCA memories to the search once it exists
UPDATE janet_memory
SET related_search_id = (SELECT id FROM searches WHERE search_number = 'KNK-2026-001' LIMIT 1)
WHERE subject IN ('Covenant Christian Academy - Colleyville TX', 'Becca Thomas identity', 'Angela Rimington candidate profile', 'Angela at CCA - flag short tenure', 'CCA is Covenant, not Cornerstone');

-- Verify
SELECT 'janet_memory rows' AS tbl, COUNT(*)::text AS count FROM janet_memory
UNION ALL SELECT 'janet_outputs rows', COUNT(*)::text FROM janet_outputs
UNION ALL SELECT 'kinds', string_agg(DISTINCT kind, ', ') FROM janet_memory;
