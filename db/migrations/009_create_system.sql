-- 009_create_system.sql
-- System and configuration tables

-- Pricing bands configuration
CREATE TABLE pricing_bands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    band_code VARCHAR(20) UNIQUE NOT NULL,
    band_name VARCHAR(100),
    salary_range_low INTEGER NOT NULL,
    salary_range_high INTEGER NOT NULL,
    fee_amount INTEGER NOT NULL,           -- Fixed fee for this band
    deposit_pct DECIMAL(5,2) DEFAULT 50.00, -- Deposit percentage
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tagging taxonomy
CREATE TABLE tag_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category VARCHAR(50) NOT NULL UNIQUE,  -- 'school_type', 'leadership_style', 'specialization', etc.
    description TEXT,
    allowed_values TEXT[],                 -- If constrained
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit log
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,     -- 'school', 'person', 'search', etc.
    entity_id UUID NOT NULL,
    action VARCHAR(20) NOT NULL,          -- 'create', 'update', 'delete'
    changed_fields JSONB,
    changed_by VARCHAR(200),              -- 'janet', 'system', 'user:name'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_date ON audit_log(created_at);

-- Data sync tracking
CREATE TABLE data_sync_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(50) NOT NULL,          -- 'nces', 'linkedin', 'form_990', etc.
    sync_type VARCHAR(50),                -- 'full', 'incremental', 'manual'
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    records_processed INTEGER DEFAULT 0,
    records_created INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_errored INTEGER DEFAULT 0,
    status VARCHAR(20),                   -- 'running', 'completed', 'failed', 'partial'
    error_details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
