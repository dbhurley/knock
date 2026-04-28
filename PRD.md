# Knock - Product Requirements Document (PRD)

**Version**: 1.0
**Date**: 2026-03-27
**Status**: Draft
**Domain**: askknock.com

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Company Overview & Market Position](#2-company-overview--market-position)
3. [System Architecture](#3-system-architecture)
4. [Infrastructure & Deployment](#4-infrastructure--deployment)
5. [Database Design](#5-database-design)
6. [Data Sources & Ingestion](#6-data-sources--ingestion)
7. [Janet - AI Office Manager (OpenClaw Agent)](#7-janet---ai-office-manager-openclaw-agent)
8. [Pricing Engine](#8-pricing-engine)
9. [Search & Matchmaking Engine](#9-search--matchmaking-engine)
10. [Workflow: End-to-End Search Process](#10-workflow-end-to-end-search-process)
11. [Telegram Bot Interface](#11-telegram-bot-interface)
12. [Web Dashboard & Gateway](#12-web-dashboard--gateway)
13. [CI/CD Pipeline](#13-cicd-pipeline)
14. [API Design](#14-api-design)
15. [Security & Access Control](#15-security--access-control)
16. [Data Sync & Maintenance](#16-data-sync--maintenance)
17. [Monitoring & Observability](#17-monitoring--observability)
18. [Development Phases & Milestones](#18-development-phases--milestones)
19. [File & Repository Structure](#19-file--repository-structure)
20. [Appendices](#20-appendices)

---

## 1. Executive Summary

**Knock** is a specialized executive recruiting agency serving the private and independent school sector in the United States. Unlike traditional recruiting firms that charge percentage-based fees (typically 25-33% of first-year salary), Knock uses a **fixed-price, salary-band model** that provides transparency and significant cost savings to client schools.

Knock maintains the **largest and most comprehensive database** of:
- Private and independent schools (elementary, middle, high school) in the US
- Current and former heads of school, headmasters, and executive administrators
- Emerging talent: recent graduates of educational leadership programs
- Career trajectories and movement patterns across the industry

The system is powered by **Janet**, an AI office manager built on OpenClaw, who handles intake, search, matchmaking, and workflow orchestration through a Telegram bot interface and web dashboard.

### Core Value Propositions
1. **Fixed pricing** - predictable costs for schools, no percentage surprises
2. **Deepest database** - more schools and candidates than any competitor
3. **AI-powered matchmaking** - Janet finds fits faster than human-only processes
4. **Industry specialization** - exclusively focused on private/independent school leadership
5. **Continuous intelligence** - automated monitoring of LinkedIn, NCES, and industry sources

---

## 2. Company Overview & Market Position

### Target Market
- **Primary clients**: Private and independent K-12 schools in the United States seeking executive leadership
- **Secondary clients**: Candidates seeking head of school or executive positions
- **Market size**: ~34,000+ private schools in the US (NCES data), with estimated 3,000-5,000 leadership transitions annually

### Positions Recruited
| Position Category | Examples | Typical Salary Range |
|---|---|---|
| Head of School / Headmaster | School-wide CEO equivalent | $150,000 - $500,000+ |
| Division Head | Lower/Middle/Upper School Head | $100,000 - $250,000 |
| Academic Dean | Dean of Faculty, Dean of Academics | $90,000 - $200,000 |
| CFO / Business Manager | Chief Financial/Operating Officer | $100,000 - $250,000 |
| Admissions Director | VP/Director of Enrollment | $80,000 - $180,000 |
| Development Director | VP/Director of Advancement | $90,000 - $200,000 |
| Athletic Director | Director of Athletics | $70,000 - $150,000 |
| Technology Director | CTO / Director of IT | $80,000 - $175,000 |
| DEI Officer | Chief Diversity Officer | $80,000 - $175,000 |
| Communications Director | Director of Marketing/Comms | $70,000 - $150,000 |

### Competitive Landscape
| Competitor | Model | Knock Advantage |
|---|---|---|
| Carney Sandoe & Associates | % of salary (typically 25-33%) | Fixed pricing, AI-powered matching |
| RG175 | % of salary | Larger database, technology platform |
| Educator's Ally | % of salary | Deeper school profiles, faster turnaround |
| Resource Group 175 | % of salary | Transparent pricing, comprehensive data |
| Storbeck Search | % of salary + retainer | No retainer, fixed price |

---

## 3. System Architecture

### High-Level Architecture

```
                    +------------------+
                    |   askknock.com   |
                    |  (Public Site)   |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
    +---------v---------+     +-------------v-----------+
    | janet.askknock.com |     |    Telegram Bot API     |
    | (OpenClaw Gateway) |     |    (@KnockJanetBot)     |
    +--------+----------+     +------------+------------+
             |                             |
             +-------------+---------------+
                           |
                  +--------v--------+
                  |    OpenClaw     |
                  |   Agent Core    |
                  |   ("Janet")     |
                  +--------+--------+
                           |
              +------------+------------+
              |            |            |
     +--------v---+  +----v-----+  +---v--------+
     |   Skills   |  | Workflows|  |  Tools     |
     | - Intake   |  | - Search |  | - DB Query |
     | - Search   |  |   Process|  | - LinkedIn |
     | - Match    |  | - Onboard|  | - NCES Sync|
     | - Report   |  | - Close  |  | - Email    |
     +-----+------+  +----+-----+  +---+--------+
           |               |            |
           +-------+-------+------------+
                   |
          +--------v--------+
          |     Redis       |
          |  (Cache Layer)  |
          +--------+--------+
                   |
          +--------v--------+
          |   PostgreSQL    |
          |  (Primary DB)   |
          +--------+--------+
                   |
     +-------------+-------------+
     |             |             |
+----v----+  +----v----+  +----v----+
| Schools |  | People  |  | Searches|
| Tables  |  | Tables  |  | Tables  |
+---------+  +---------+  +---------+
```

### Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Server** | DigitalOcean Droplet (Ubuntu 24.04) | Cost-effective, full control, single-server simplicity |
| **Database** | PostgreSQL 16 | Relational integrity, full-text search, JSONB for flexible data |
| **Cache** | Redis 7 (via KeyDB or Dragonfly) | Sub-millisecond queries for Janet, session state, search caching |
| **AI Agent** | OpenClaw (self-hosted) | Open source, custom skills, permissive access, Telegram integration |
| **Bot Interface** | Telegram Bot API | Instant messaging, rich formatting, file sharing, zero cost |
| **Web Gateway** | OpenClaw Dashboard | Admin interface at janet.askknock.com |
| **Reverse Proxy** | Caddy v2 | Automatic HTTPS, simple config, reverse proxy |
| **CI/CD** | GitHub Actions → SSH deploy | Push-to-deploy, zero-downtime updates |
| **Containerization** | Docker + Docker Compose | Reproducible environments, easy orchestration |
| **Search** | pg_trgm + Redis Search (or Meilisearch) | Full-text search with fuzzy matching |
| **Data Sync** | Custom Python/Node scripts + cron | NCES, LinkedIn, and other source ingestion |
| **Monitoring** | Prometheus + Grafana (lightweight) | System and application metrics |
| **DNS** | Cloudflare (free tier) | DDoS protection, fast DNS, edge caching for public site |

### Domain Configuration

| Subdomain | Purpose | Backend |
|---|---|---|
| `askknock.com` | Public marketing site + client portal | Static site / Next.js |
| `janet.askknock.com` | OpenClaw Gateway dashboard (token-protected) | OpenClaw Gateway |
| `api.askknock.com` | REST API for integrations | Node.js/Express or Fastify |
| `grafana.askknock.com` | Monitoring dashboard (internal) | Grafana |

---

## 4. Infrastructure & Deployment

### DigitalOcean Droplet Specification

| Spec | Recommendation | Rationale |
|---|---|---|
| **Plan** | Premium Intel, 4 vCPU / 8GB RAM / 160GB NVMe | PostgreSQL + Redis + OpenClaw + services |
| **Region** | NYC1 or SFO3 | US-based for low latency to US schools |
| **Image** | Ubuntu 24.04 LTS | Long-term support, wide ecosystem |
| **Backups** | Enabled (weekly) | Disaster recovery |
| **Monitoring** | Enabled | DO-level metrics |
| **VPC** | Default VPC | Network isolation |

### Software Installation Order

```bash
# 1. System updates and essentials
apt update && apt upgrade -y
apt install -y curl git build-essential nginx certbot python3 python3-pip

# 2. Docker & Docker Compose
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin

# 3. Caddy (reverse proxy with automatic HTTPS)
apt install -y caddy

# 4. PostgreSQL 16
# (via Docker container)

# 5. Redis 7 (or KeyDB/Dragonfly for performance)
# (via Docker container)

# 6. Node.js 22 LTS (via nvm)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.0/install.sh | bash
nvm install 22

# 7. OpenClaw
# (installed per OpenClaw docs, self-hosted mode)

# 8. Application code (from git repo)
git clone <repo-url> /opt/knock
```

### Docker Compose Services

```yaml
# docker-compose.yml (reference structure)
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d
    environment:
      POSTGRES_DB: knock
      POSTGRES_USER: knock_admin
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "127.0.0.1:5432:5432"
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 2gb --maxmemory-policy allkeys-lru
    volumes:
      - redisdata:/data
    ports:
      - "127.0.0.1:6379:6379"
    restart: unless-stopped

  meilisearch:
    image: getmeili/meilisearch:latest
    volumes:
      - msdata:/meili_data
    environment:
      MEILI_MASTER_KEY: ${MEILI_MASTER_KEY}
    ports:
      - "127.0.0.1:7700:7700"
    restart: unless-stopped

  openclaw:
    build: ./openclaw
    depends_on:
      - postgres
      - redis
    environment:
      DATABASE_URL: postgres://knock_admin:${POSTGRES_PASSWORD}@postgres:5432/knock
      REDIS_URL: redis://redis:6379
      OPENCLAW_TOKEN: ${OPENCLAW_TOKEN}
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
    ports:
      - "127.0.0.1:3000:3000"
    restart: unless-stopped

  data-sync:
    build: ./services/data-sync
    depends_on:
      - postgres
      - redis
    environment:
      DATABASE_URL: postgres://knock_admin:${POSTGRES_PASSWORD}@postgres:5432/knock
      REDIS_URL: redis://redis:6379
    restart: unless-stopped

  caddy:
    image: caddy:2-alpine
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    ports:
      - "80:80"
      - "443:443"
    restart: unless-stopped

volumes:
  pgdata:
  redisdata:
  msdata:
  caddy_data:
  caddy_config:
```

### Caddyfile

```
askknock.com {
    root * /opt/knock/public
    file_server
    # Or reverse_proxy to Next.js
}

janet.askknock.com {
    reverse_proxy localhost:3000
}

api.askknock.com {
    reverse_proxy localhost:4000
}

grafana.askknock.com {
    reverse_proxy localhost:3001
    basicauth {
        admin $GRAFANA_HASH
    }
}
```

---

## 5. Database Design

### Entity Relationship Overview

```
Schools ─────────────── SchoolContacts ──────────────── People
   │                         │                            │
   ├── SchoolProfiles        │                            ├── PersonProfiles
   ├── SchoolAccreditations  │                            ├── PersonEducation
   ├── SchoolFinancials      │                            ├── PersonExperience
   ├── SchoolPrograms        │                            ├── PersonCertifications
   │                         │                            ├── PersonSkills
   │                    Searches ◄────────────────────────┤
   │                         │                            │
   │                    SearchCandidates                  │
   │                         │                            │
   │                    SearchActivities                  │
   │                         │                            │
   │                    Placements ───────────────────────┘
   │
   └── SchoolBoardMembers
```

### Core Tables

#### 5.1 Schools

```sql
-- Primary school record
CREATE TABLE schools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nces_id VARCHAR(12) UNIQUE,           -- NCES School ID (PSS)
    name VARCHAR(500) NOT NULL,
    name_normalized VARCHAR(500),          -- Lowercase, stripped for search
    school_type VARCHAR(50),               -- 'elementary', 'middle', 'high', 'k8', 'k12', 'other'
    religious_affiliation VARCHAR(100),    -- From NCES: Catholic, Jewish, Nonsectarian, etc.
    coed_status VARCHAR(20),              -- 'coed', 'boys', 'girls'
    boarding_status VARCHAR(20),          -- 'day', 'boarding', 'day_boarding'
    grade_low VARCHAR(5),                 -- Lowest grade: 'PK', 'K', '1', etc.
    grade_high VARCHAR(5),               -- Highest grade: '8', '12', 'PG'
    enrollment_total INTEGER,
    enrollment_pk INTEGER,
    enrollment_k INTEGER,
    enrollment_1_5 INTEGER,
    enrollment_6_8 INTEGER,
    enrollment_9_12 INTEGER,
    enrollment_pg INTEGER,

    -- Location
    street_address VARCHAR(500),
    city VARCHAR(200),
    state VARCHAR(2),
    zip VARCHAR(10),
    county VARCHAR(200),
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    metro_status VARCHAR(20),             -- 'urban', 'suburban', 'rural'

    -- Contact
    phone VARCHAR(20),
    fax VARCHAR(20),
    website VARCHAR(500),
    email VARCHAR(300),

    -- Financial
    tuition_low INTEGER,                  -- Lowest tuition offered
    tuition_high INTEGER,                 -- Highest tuition offered
    endowment_size BIGINT,               -- Estimated endowment in dollars
    annual_fund_size INTEGER,
    operating_budget BIGINT,
    financial_aid_pct DECIMAL(5,2),       -- % of students receiving aid
    avg_aid_amount INTEGER,

    -- Staff
    total_teachers INTEGER,
    fte_teachers DECIMAL(8,2),
    student_teacher_ratio DECIMAL(5,2),
    pct_teachers_advanced_degree DECIMAL(5,2),
    total_staff INTEGER,

    -- Accreditation & Membership
    nais_member BOOLEAN DEFAULT FALSE,    -- National Association of Independent Schools
    state_accredited BOOLEAN DEFAULT FALSE,
    regional_accreditation VARCHAR(100),  -- e.g., 'NEASC', 'WASC', 'SACS', etc.

    -- Classification
    is_private BOOLEAN DEFAULT TRUE,
    is_independent BOOLEAN,               -- True independent vs. parochial/religious-affiliated
    is_charter BOOLEAN DEFAULT FALSE,
    is_magnet BOOLEAN DEFAULT FALSE,
    nces_category VARCHAR(50),            -- NCES school category code
    level_code VARCHAR(10),               -- NCES level code

    -- Knock Internal
    tier VARCHAR(20),                     -- 'platinum', 'gold', 'silver', 'bronze', 'unranked'
    is_active BOOLEAN DEFAULT TRUE,
    last_head_change DATE,                -- When the current HOS started
    next_head_change_expected DATE,       -- Predicted transition
    notes TEXT,
    tags TEXT[],                           -- Flexible tagging: ['boarding', 'progressive', 'STEM-focus']

    -- Metadata
    data_source VARCHAR(50) DEFAULT 'nces', -- 'nces', 'manual', 'linkedin', 'web_scrape'
    nces_survey_year INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ,

    -- Search optimization
    search_vector tsvector
);

-- Indexes
CREATE INDEX idx_schools_state ON schools(state);
CREATE INDEX idx_schools_type ON schools(school_type);
CREATE INDEX idx_schools_enrollment ON schools(enrollment_total);
CREATE INDEX idx_schools_tier ON schools(tier);
CREATE INDEX idx_schools_nces_id ON schools(nces_id);
CREATE INDEX idx_schools_city_state ON schools(city, state);
CREATE INDEX idx_schools_boarding ON schools(boarding_status);
CREATE INDEX idx_schools_coed ON schools(coed_status);
CREATE INDEX idx_schools_search ON schools USING gin(search_vector);
CREATE INDEX idx_schools_tags ON schools USING gin(tags);
CREATE INDEX idx_schools_name_trgm ON schools USING gin(name_normalized gin_trgm_ops);

-- Trigger to update search vector
CREATE OR REPLACE FUNCTION schools_search_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.city, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.state, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.religious_affiliation, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.tags, ' '), '')), 'C');
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_schools_search
    BEFORE INSERT OR UPDATE ON schools
    FOR EACH ROW EXECUTE FUNCTION schools_search_update();
```

#### 5.2 School Extended Data

```sql
-- School accreditations and memberships
CREATE TABLE school_accreditations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    organization VARCHAR(200) NOT NULL,    -- 'NAIS', 'NEASC', 'WASC', etc.
    accreditation_type VARCHAR(100),       -- 'full', 'provisional', 'candidate'
    granted_date DATE,
    expiry_date DATE,
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- School academic programs and specialties
CREATE TABLE school_programs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    program_type VARCHAR(50),             -- 'ap', 'ib', 'stem', 'arts', 'athletics', 'special_ed'
    program_name VARCHAR(300),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- School board of trustees/directors
CREATE TABLE school_board_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    name VARCHAR(300),                    -- If person not yet in people table
    role VARCHAR(100),                    -- 'chair', 'vice_chair', 'treasurer', 'secretary', 'member'
    term_start DATE,
    term_end DATE,
    is_current BOOLEAN DEFAULT TRUE,
    linkedin_url VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- School financial snapshots (annual)
CREATE TABLE school_financials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    fiscal_year INTEGER NOT NULL,
    revenue BIGINT,
    expenses BIGINT,
    endowment BIGINT,
    annual_fund BIGINT,
    capital_campaign BIGINT,
    tuition_revenue BIGINT,
    enrollment INTEGER,
    tuition_low INTEGER,
    tuition_high INTEGER,
    source VARCHAR(50),                   -- 'form_990', 'school_report', 'estimate'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(school_id, fiscal_year)
);

-- School leadership history
CREATE TABLE school_leadership_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID REFERENCES schools(id) ON DELETE CASCADE,
    person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    position_title VARCHAR(200),
    start_date DATE,
    end_date DATE,
    departure_reason VARCHAR(100),        -- 'retirement', 'new_position', 'terminated', 'contract_end', 'unknown'
    is_current BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### 5.3 People (Candidates & Contacts)

```sql
-- Primary person record
CREATE TABLE people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    linkedin_id VARCHAR(100) UNIQUE,       -- LinkedIn member ID or profile slug
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    full_name VARCHAR(300) NOT NULL,
    name_normalized VARCHAR(300),           -- For search
    preferred_name VARCHAR(100),            -- Nickname or preferred first name
    prefix VARCHAR(20),                     -- 'Dr.', 'Rev.', etc.
    suffix VARCHAR(20),                     -- 'Ed.D.', 'Ph.D.', 'Jr.', etc.

    -- Contact
    email_primary VARCHAR(300),
    email_secondary VARCHAR(300),
    phone_primary VARCHAR(20),
    phone_secondary VARCHAR(20),
    phone_type VARCHAR(20),                -- 'mobile', 'work', 'home'

    -- Location
    city VARCHAR(200),
    state VARCHAR(2),
    zip VARCHAR(10),
    country VARCHAR(2) DEFAULT 'US',
    willing_to_relocate BOOLEAN,
    preferred_regions TEXT[],               -- ['northeast', 'southeast', 'west']
    preferred_states TEXT[],                -- ['MA', 'CT', 'NY']

    -- Current Position
    current_title VARCHAR(300),
    current_organization VARCHAR(300),
    current_school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    current_position_start DATE,
    years_in_current_role INTEGER,

    -- Professional Profile
    career_stage VARCHAR(30),              -- 'emerging', 'mid_career', 'senior', 'veteran', 'retired'
    primary_role VARCHAR(50),              -- 'head_of_school', 'division_head', 'academic_dean', etc.
    specializations TEXT[],                -- ['fundraising', 'stem', 'boarding', 'dei']
    school_type_experience TEXT[],         -- ['k12', 'k8', '9_12', 'boarding', 'day']
    enrollment_experience_range INT4RANGE, -- Range of school sizes led
    budget_experience_range INT8RANGE,     -- Range of budgets managed

    -- Compensation
    current_compensation INTEGER,          -- Estimated current total comp
    compensation_expectation VARCHAR(50),  -- 'open', '200-250k', '300k+', etc.
    compensation_notes TEXT,

    -- LinkedIn Data
    linkedin_url VARCHAR(500),
    linkedin_headline VARCHAR(500),
    linkedin_summary TEXT,
    linkedin_connections INTEGER,
    linkedin_profile_photo_url VARCHAR(500),
    linkedin_last_synced TIMESTAMPTZ,

    -- Assessment
    knock_rating INTEGER CHECK (knock_rating BETWEEN 1 AND 5), -- 1-5 internal rating
    cultural_fit_tags TEXT[],              -- ['progressive', 'traditional', 'faith-based', 'innovative']
    leadership_style TEXT[],              -- ['collaborative', 'visionary', 'operational', 'transformational']
    strengths TEXT[],
    development_areas TEXT[],
    interview_notes TEXT,

    -- Status
    candidate_status VARCHAR(30),          -- 'active', 'passive', 'not_looking', 'placed', 'do_not_contact', 'retired'
    is_in_active_search BOOLEAN DEFAULT FALSE,
    availability_date DATE,
    last_contacted_at TIMESTAMPTZ,
    last_interaction_type VARCHAR(50),     -- 'email', 'phone', 'linkedin', 'in_person', 'conference'
    relationship_strength VARCHAR(20),     -- 'strong', 'moderate', 'weak', 'new'

    -- Data Source
    data_source VARCHAR(50),              -- 'linkedin_import', 'manual', 'referral', 'conference', 'web'
    source_connection VARCHAR(300),       -- Who referred/connected them
    import_batch_id VARCHAR(50),          -- Which LinkedIn export batch

    -- Metadata
    tags TEXT[],
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ,

    -- Search
    search_vector tsvector
);

-- Indexes
CREATE INDEX idx_people_name ON people(last_name, first_name);
CREATE INDEX idx_people_name_trgm ON people USING gin(name_normalized gin_trgm_ops);
CREATE INDEX idx_people_status ON people(candidate_status);
CREATE INDEX idx_people_role ON people(primary_role);
CREATE INDEX idx_people_stage ON people(career_stage);
CREATE INDEX idx_people_state ON people(state);
CREATE INDEX idx_people_school ON people(current_school_id);
CREATE INDEX idx_people_linkedin ON people(linkedin_id);
CREATE INDEX idx_people_search ON people USING gin(search_vector);
CREATE INDEX idx_people_tags ON people USING gin(tags);
CREATE INDEX idx_people_specializations ON people USING gin(specializations);
CREATE INDEX idx_people_cultural_fit ON people USING gin(cultural_fit_tags);
CREATE INDEX idx_people_rating ON people(knock_rating);

-- Search vector trigger
CREATE OR REPLACE FUNCTION people_search_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.full_name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.current_title, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.current_organization, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.linkedin_headline, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.specializations, ' '), '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.tags, ' '), '')), 'D');
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_people_search
    BEFORE INSERT OR UPDATE ON people
    FOR EACH ROW EXECUTE FUNCTION people_search_update();
```

#### 5.4 People Extended Data

```sql
-- Education history
CREATE TABLE person_education (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    institution VARCHAR(300) NOT NULL,
    degree VARCHAR(100),                  -- 'B.A.', 'M.Ed.', 'Ed.D.', 'Ph.D.', etc.
    field_of_study VARCHAR(300),
    graduation_year INTEGER,
    honors VARCHAR(200),
    is_education_leadership BOOLEAN DEFAULT FALSE, -- Flag if Ed Leadership program
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_ed_person ON person_education(person_id);
CREATE INDEX idx_person_ed_degree ON person_education(degree);

-- Work experience history
CREATE TABLE person_experience (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    organization VARCHAR(300) NOT NULL,
    school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    title VARCHAR(300) NOT NULL,
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN DEFAULT FALSE,
    description TEXT,
    position_category VARCHAR(50),        -- Maps to our position categories
    school_type VARCHAR(50),              -- Type of school at time of position
    school_enrollment INTEGER,            -- Enrollment at time of position
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_exp_person ON person_experience(person_id);
CREATE INDEX idx_person_exp_school ON person_experience(school_id);
CREATE INDEX idx_person_exp_current ON person_experience(is_current);

-- Certifications and licenses
CREATE TABLE person_certifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    certification_name VARCHAR(300),
    issuing_organization VARCHAR(300),
    issue_date DATE,
    expiry_date DATE,
    credential_id VARCHAR(100),
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Skills and competencies
CREATE TABLE person_skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    skill_name VARCHAR(200) NOT NULL,
    category VARCHAR(50),                 -- 'leadership', 'academic', 'financial', 'technical', 'interpersonal'
    proficiency VARCHAR(20),              -- 'expert', 'advanced', 'intermediate', 'basic'
    endorsed_count INTEGER DEFAULT 0,     -- LinkedIn endorsements
    source VARCHAR(50),                   -- 'linkedin', 'self_reported', 'assessed'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_skills_person ON person_skills(person_id);
CREATE INDEX idx_person_skills_name ON person_skills(skill_name);

-- Professional references
CREATE TABLE person_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    reference_person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    reference_name VARCHAR(300),
    reference_title VARCHAR(300),
    reference_organization VARCHAR(300),
    reference_email VARCHAR(300),
    reference_phone VARCHAR(20),
    relationship VARCHAR(100),            -- 'supervisor', 'colleague', 'board_member', 'direct_report'
    reference_type VARCHAR(50),           -- 'professional', 'personal', 'board'
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Interaction log
CREATE TABLE person_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50),          -- 'email', 'phone', 'meeting', 'linkedin', 'conference', 'telegram'
    direction VARCHAR(10),                -- 'inbound', 'outbound'
    subject VARCHAR(500),
    content TEXT,
    outcome VARCHAR(100),                 -- 'positive', 'neutral', 'negative', 'no_response'
    follow_up_date DATE,
    follow_up_notes TEXT,
    conducted_by VARCHAR(200),            -- Who at Knock had the interaction
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_interactions_person ON person_interactions(person_id);
CREATE INDEX idx_person_interactions_type ON person_interactions(interaction_type);
CREATE INDEX idx_person_interactions_date ON person_interactions(created_at);
```

#### 5.5 Searches (Active Engagements)

```sql
-- A search is an active engagement to fill a position
CREATE TABLE searches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_number VARCHAR(20) UNIQUE,     -- 'KNK-2026-001' sequential
    school_id UUID REFERENCES schools(id) ON DELETE RESTRICT,

    -- Position Details
    position_title VARCHAR(300) NOT NULL,
    position_category VARCHAR(50),        -- 'head_of_school', 'division_head', etc.
    position_description TEXT,
    position_requirements TEXT,
    reports_to VARCHAR(200),              -- Who this role reports to

    -- Compensation
    salary_range_low INTEGER,
    salary_range_high INTEGER,
    salary_band VARCHAR(20),              -- Maps to pricing bands
    additional_compensation TEXT,          -- Housing, car, etc.
    benefits_notes TEXT,

    -- Timeline
    target_start_date DATE,               -- When the school wants the person to start
    search_urgency VARCHAR(20),           -- 'immediate', 'standard', 'flexible'
    contract_length VARCHAR(50),          -- '3 years', '5 years', 'indefinite'

    -- Search Criteria
    required_education TEXT[],            -- ['ed_d', 'ph_d', 'masters']
    required_experience_years INTEGER,
    preferred_school_types TEXT[],        -- ['boarding', 'day', 'k12']
    preferred_backgrounds TEXT[],         -- What kind of backgrounds preferred
    ideal_candidate_profile TEXT,         -- Free-form description
    dealbreakers TEXT,                    -- Must-not-have criteria

    -- Knock Pricing
    pricing_band VARCHAR(20),            -- 'band_a', 'band_b', ..., 'band_f'
    fee_amount INTEGER,                  -- Fixed fee in dollars
    fee_status VARCHAR(30),              -- 'quoted', 'accepted', 'invoiced', 'paid', 'overdue'
    deposit_amount INTEGER,
    deposit_paid BOOLEAN DEFAULT FALSE,
    deposit_paid_date DATE,
    final_payment_date DATE,

    -- Status
    status VARCHAR(30) NOT NULL DEFAULT 'intake',
    -- Statuses: 'intake', 'profiling', 'sourcing', 'screening', 'presenting',
    --           'interviewing', 'finalist', 'offer', 'placed', 'closed_no_fill',
    --           'on_hold', 'cancelled'
    status_changed_at TIMESTAMPTZ DEFAULT NOW(),

    -- Client Contact
    client_contact_name VARCHAR(300),
    client_contact_title VARCHAR(200),
    client_contact_email VARCHAR(300),
    client_contact_phone VARCHAR(20),
    search_committee_members TEXT,        -- JSON array or free text

    -- Assignment
    lead_consultant VARCHAR(200),         -- Primary Knock consultant
    support_consultants TEXT[],

    -- Results
    candidates_identified INTEGER DEFAULT 0,
    candidates_presented INTEGER DEFAULT 0,
    candidates_interviewed INTEGER DEFAULT 0,
    finalists INTEGER DEFAULT 0,
    placed_person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    placement_date DATE,
    placement_salary INTEGER,

    -- Metadata
    notes TEXT,
    internal_notes TEXT,                  -- Not shared with client
    tags TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

CREATE INDEX idx_searches_school ON searches(school_id);
CREATE INDEX idx_searches_status ON searches(status);
CREATE INDEX idx_searches_category ON searches(position_category);
CREATE INDEX idx_searches_band ON searches(pricing_band);
CREATE INDEX idx_searches_created ON searches(created_at);

-- Candidates being considered for a search
CREATE TABLE search_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_id UUID REFERENCES searches(id) ON DELETE CASCADE,
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    status VARCHAR(30) NOT NULL DEFAULT 'identified',
    -- Statuses: 'identified', 'contacted', 'interested', 'screening',
    --           'presented', 'interviewing', 'finalist', 'offered',
    --           'accepted', 'declined', 'withdrawn', 'rejected'
    match_score DECIMAL(5,2),             -- Janet's computed match score (0-100)
    match_reasoning TEXT,                 -- Why Janet thinks this is a match
    source VARCHAR(50),                   -- 'database', 'referral', 'linkedin', 'conference', 'inbound'
    referred_by VARCHAR(300),
    presented_at TIMESTAMPTZ,
    interview_dates TIMESTAMPTZ[],
    interview_feedback TEXT,
    client_feedback TEXT,
    candidate_feedback TEXT,
    rejection_reason TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(search_id, person_id)
);

CREATE INDEX idx_search_candidates_search ON search_candidates(search_id);
CREATE INDEX idx_search_candidates_person ON search_candidates(person_id);
CREATE INDEX idx_search_candidates_status ON search_candidates(status);
CREATE INDEX idx_search_candidates_score ON search_candidates(match_score);

-- Activity log for search progress
CREATE TABLE search_activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_id UUID REFERENCES searches(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,
    -- Types: 'status_change', 'candidate_added', 'candidate_contacted',
    --        'interview_scheduled', 'presentation_sent', 'client_meeting',
    --        'note_added', 'fee_invoiced', 'fee_paid'
    description TEXT,
    performed_by VARCHAR(200),            -- 'janet', 'consultant_name', 'system'
    related_person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    metadata JSONB,                       -- Flexible additional data
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_search_activities_search ON search_activities(search_id);
CREATE INDEX idx_search_activities_type ON search_activities(activity_type);
CREATE INDEX idx_search_activities_date ON search_activities(created_at);
```

#### 5.6 Placements & Outcomes

```sql
-- Successful placements (historical record)
CREATE TABLE placements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_id UUID REFERENCES searches(id) ON DELETE SET NULL,
    school_id UUID REFERENCES schools(id) ON DELETE SET NULL,
    person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    position_title VARCHAR(300),
    placement_date DATE NOT NULL,
    start_date DATE,
    salary INTEGER,
    contract_term VARCHAR(50),
    fee_charged INTEGER,
    fee_collected INTEGER,

    -- Outcome tracking
    still_in_role BOOLEAN DEFAULT TRUE,
    departure_date DATE,
    departure_reason VARCHAR(100),
    tenure_months INTEGER,                -- Computed from dates

    -- Satisfaction
    school_satisfaction INTEGER CHECK (school_satisfaction BETWEEN 1 AND 5),
    candidate_satisfaction INTEGER CHECK (candidate_satisfaction BETWEEN 1 AND 5),
    follow_up_6mo_date DATE,
    follow_up_6mo_notes TEXT,
    follow_up_12mo_date DATE,
    follow_up_12mo_notes TEXT,

    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_placements_school ON placements(school_id);
CREATE INDEX idx_placements_person ON placements(person_id);
CREATE INDEX idx_placements_date ON placements(placement_date);
```

#### 5.7 Industry Intelligence

```sql
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
```

#### 5.8 System & Configuration Tables

```sql
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

-- Seed pricing bands
INSERT INTO pricing_bands (band_code, band_name, salary_range_low, salary_range_high, fee_amount) VALUES
    ('band_a', 'Band A: Entry Executive',     70000,   100000,  20000),
    ('band_b', 'Band B: Mid Executive',       100001,  150000,  30000),
    ('band_c', 'Band C: Senior Executive',    150001,  200000,  40000),
    ('band_d', 'Band D: Head of School I',    200001,  275000,  55000),
    ('band_e', 'Band E: Head of School II',   275001,  375000,  75000),
    ('band_f', 'Band F: Head of School III',  375001,  500000, 100000),
    ('band_g', 'Band G: Elite',               500001, 9999999, 125000);

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
```

### Redis Cache Schema

```
# Hot cache for Janet's queries
knock:school:{id}               → JSON (full school record)
knock:person:{id}               → JSON (full person record)
knock:search:{id}               → JSON (active search record)

# Search indexes (sorted sets for fast filtering)
knock:idx:schools:by_state:{ST} → Sorted Set (school_id, enrollment)
knock:idx:schools:by_type:{type}→ Sorted Set (school_id, enrollment)
knock:idx:schools:by_tier:{tier}→ Sorted Set (school_id, score)
knock:idx:people:by_role:{role} → Sorted Set (person_id, rating)
knock:idx:people:by_state:{ST}  → Sorted Set (person_id, rating)
knock:idx:people:by_stage:{stg} → Sorted Set (person_id, rating)
knock:idx:people:active         → Set (person_ids currently available)

# Session state
knock:session:{session_id}      → JSON (conversation state)
knock:search_draft:{search_id}  → JSON (in-progress intake)

# Rate limiting
knock:rate:{user_id}            → Counter with TTL

# Full-text search (if using RediSearch module)
knock:ft:schools                → FT Index
knock:ft:people                 → FT Index
```

---

## 6. Data Sources & Ingestion

### 6.1 NCES Private School Survey (PSS) — Primary School Data

**Source**: https://nces.ed.gov/surveys/pss/pssdata.asp

| Detail | Value |
|---|---|
| **Format** | SAS, SPSS, CSV, Stata files |
| **Frequency** | Biennial (every 2 years), latest ~2023-24 |
| **Records** | ~34,000+ private schools |
| **Key Fields** | School name, address, phone, enrollment, grade range, type, religious affiliation, coeducation status, student/teacher ratio |

**Ingestion Process**:
1. Download latest PSS data files from NCES
2. Parse CSV/SAS format into structured records
3. Map NCES fields to our `schools` table schema
4. Upsert by `nces_id` (unique school identifier)
5. Flag schools that have closed or changed status
6. Run biennial on new data release + quarterly verification checks

**NCES Field Mapping** (key fields):

| NCES Field | Our Field | Notes |
|---|---|---|
| PPIN | nces_id | Unique school ID |
| PINST | name | School name |
| PADDRS | street_address | Street address |
| PCITY | city | City |
| PSTABB | state | State abbreviation |
| PZIP | zip | ZIP code |
| NUMSTUDS | enrollment_total | Total enrollment |
| LEVEL | school_type | Grade level classification |
| ORIENT | religious_affiliation | Religious orientation |
| CESSION | coed_status | Coeducation status |
| PKTCH | total_teachers | Number of teachers |
| STUTEFTR | student_teacher_ratio | Student/teacher ratio |
| LATITUDE | latitude | GPS latitude |
| LONGITUDE | longitude | GPS longitude |

### 6.2 LinkedIn Data Import — Candidate Base

**Source**: LinkedIn profile export (founder's ~1,700 connections)

| Detail | Value |
|---|---|
| **Format** | CSV export from LinkedIn |
| **Records** | ~1,700 initial contacts |
| **Key Fields** | Name, headline, company, position, email, LinkedIn URL |

**Ingestion Process**:
1. Export connections from LinkedIn (Settings > Data Privacy > Get a copy of your data)
2. Parse CSV: First Name, Last Name, Email, Company, Position, Connected On, LinkedIn URL
3. Enrich with profile data where available
4. Map to `people` table
5. Set `data_source = 'linkedin_import'` and `import_batch_id`
6. Cross-reference with schools table to link `current_school_id`
7. Flag educational leadership roles for priority processing

**Ongoing LinkedIn Monitoring** (future, manual or semi-automated):
- Monitor connections' profile changes (new positions = potential transition signal)
- Track new connections in the space
- Monitor school pages for leadership announcements
- Track relevant hashtags and posts (#HeadOfSchool, #IndependentSchools)

### 6.3 Additional Data Sources

| Source | Data | Frequency | Method |
|---|---|---|---|
| **NAIS School Directory** | Member schools, demographics, leadership | Annual | Web scrape or data partnership |
| **IRS Form 990** (via ProPublica API) | School financials, executive compensation, board members | Annual | API pull (api.propublica.org/nonprofit/v2/) |
| **State Education Departments** | Approved private school lists, accreditation | Varies | Web scrape per state |
| **TABS (The Association of Boarding Schools)** | Boarding school directory | Annual | Partnership or web data |
| **School websites** | Current leadership, mission, programs | Quarterly | Targeted web scrape |
| **Educational leadership program directories** | Graduate programs, alumni | Annual | Web scrape / partnerships |
| **Job boards** (NAIS Career Center, ISM, EdSurge) | Open positions = search opportunities | Daily | RSS/scrape monitoring |
| **Conference attendee lists** | NAIS Annual Conference, People of Color Conference | Event-driven | Manual import |
| **Google Alerts / News** | Leadership transitions, school news | Real-time | API/RSS integration |

### 6.4 Data Quality & Enrichment Pipeline

```
Raw Data → Normalize → Deduplicate → Enrich → Validate → Load → Index
                                        ↓
                              ┌─────────────────────┐
                              │  Enrichment Sources  │
                              │  - Clearbit/FullCont │
                              │  - Google Maps API   │
                              │  - School websites   │
                              │  - ProPublica 990    │
                              └─────────────────────┘
```

**Deduplication Strategy**:
- Schools: Match on NCES ID first, then fuzzy match on name + city + state
- People: Match on LinkedIn ID first, then fuzzy match on name + organization
- Use pg_trgm similarity scoring with threshold of 0.7

---

## 7. Janet - AI Office Manager (OpenClaw Agent)

### 7.1 Identity & Personality

| Attribute | Value |
|---|---|
| **Name** | Janet |
| **Role** | Office Manager & Research Associate at Knock |
| **Tone** | Professional, warm, knowledgeable, efficient |
| **Interface** | Telegram bot (@KnockJanetBot) + web dashboard |
| **Model** | OpenClaw with custom skills (self-hosted) |

### 7.2 Core Capabilities

1. **Intake Interviews** — Conduct structured intake for new search engagements
2. **Database Search** — Query schools and candidates with natural language
3. **Matchmaking** — Score and rank candidates against search criteria
4. **Status Updates** — Report on active search progress
5. **Data Entry** — Add/update school and candidate records via conversation
6. **Industry Intelligence** — Surface relevant signals and trends
7. **Report Generation** — Create search summaries, candidate profiles, market analyses
8. **Calendar/Task Management** — Track follow-ups and deadlines

### 7.3 OpenClaw Configuration

```yaml
# openclaw-config.yaml (reference)
agent:
  name: Janet
  description: "Office Manager for Knock Executive Search"
  model: "anthropic/claude-sonnet-4-6"  # or local model
  system_prompt: |
    You are Janet, the office manager for Knock, a specialized recruiting agency
    for private and independent school executives in the United States. You are
    professional, warm, extremely knowledgeable about the independent school
    landscape, and efficient. You have access to Knock's comprehensive database
    of schools and candidates.

    Your core responsibilities:
    1. Conduct intake interviews for new search engagements
    2. Search and query the Knock database for schools and candidates
    3. Match candidates to open positions using your deep industry knowledge
    4. Provide status updates on active searches
    5. Maintain and update records
    6. Surface industry intelligence and signals

    Always be helpful but maintain confidentiality. Never share candidate
    information with unauthorized parties. When conducting intake, be thorough
    but conversational.

gateway:
  host: janet.askknock.com
  token_auth: true
  pairing_mode: permissive  # No pairing requirements

telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  pairing_mode: permissive  # Anyone can talk to Janet on Telegram
  allowed_updates: ["message", "callback_query"]
```

### 7.4 Custom Skills

#### Skill: Intake Interview

```yaml
skill_name: intake_interview
description: "Conduct a structured intake interview for a new executive search engagement"
trigger: "When a user mentions needing to find a new head of school, executive, or starting a new search"
```

**Intake Interview Flow**:

```
1. SCHOOL IDENTIFICATION
   - "Which school is this search for?"
   - Lookup school in database, confirm details
   - If not in DB: collect name, location, type, size

2. POSITION DETAILS
   - Position title and reporting structure
   - Is this a new position or replacement?
   - If replacement: What happened to the predecessor?
   - Expected start date
   - Contract term

3. COMPENSATION
   - Salary range (or confirm based on school tier)
   - Additional comp (housing, car, benefits)
   - Quote fixed fee based on salary band
   - Confirm pricing acceptance

4. SEARCH CRITERIA
   - Required qualifications (education, experience)
   - Preferred background (school type experience)
   - Leadership style preferences
   - Cultural fit priorities
   - Diversity considerations
   - Dealbreakers

5. SCHOOL PROFILE (if not already detailed in DB)
   - Mission and values
   - Current challenges/opportunities
   - Board dynamics
   - Community characteristics
   - Recent leadership history

6. LOGISTICS
   - Search committee composition
   - Primary contact information
   - Preferred communication cadence
   - Timeline constraints
   - Confidentiality requirements

7. CONFIRMATION
   - Summarize all collected information
   - Confirm fee and deposit
   - Outline next steps and timeline
   - Create search record in database
```

#### Skill: Candidate Search

```yaml
skill_name: candidate_search
description: "Search the Knock database for candidates matching specific criteria"
parameters:
  - position_type: string (optional)
  - location_preference: string (optional)
  - school_type: string (optional)
  - experience_years: integer (optional)
  - specializations: string[] (optional)
  - education_level: string (optional)
  - salary_range: string (optional)
  - free_text: string (optional)
```

**Search Algorithm**:
1. Parse natural language query into structured parameters
2. Query PostgreSQL with full-text search + filters
3. Score results using weighted criteria matching
4. Cache results in Redis for quick pagination
5. Return ranked list with match reasoning

#### Skill: School Lookup

```yaml
skill_name: school_lookup
description: "Look up school information by name, location, or characteristics"
```

#### Skill: Match Score

```yaml
skill_name: match_score
description: "Score a specific candidate against a specific search"
output: "0-100 score with reasoning"
```

**Scoring Factors** (weighted):

| Factor | Weight | Description |
|---|---|---|
| Position Experience | 25% | Has held similar role |
| School Type Match | 15% | Experience with similar school type |
| Geographic Fit | 10% | Location preference alignment |
| Education Level | 10% | Meets or exceeds requirements |
| Enrollment Match | 10% | Experience with similar size |
| Specializations | 10% | Matches required specialties |
| Cultural Fit | 10% | Alignment with school culture |
| Career Stage | 5% | Appropriate career trajectory |
| Availability | 5% | Timeline alignment |

#### Skill: Generate Report

```yaml
skill_name: generate_report
description: "Generate various reports: search status, candidate profile, market analysis"
report_types:
  - search_status_report
  - candidate_presentation
  - market_analysis
  - placement_history
  - pipeline_report
```

#### Skill: Update Record

```yaml
skill_name: update_record
description: "Add or update information in the Knock database"
entity_types:
  - school
  - person
  - search
  - interaction
```

#### Skill: Industry Monitor

```yaml
skill_name: industry_monitor
description: "Check and report on recent industry signals and intelligence"
```

### 7.5 Database Tools (OpenClaw MCP-style)

Janet needs direct database access tools:

```typescript
// Tool definitions for Janet
const tools = [
  {
    name: "query_schools",
    description: "Search schools database with filters",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string" },
        state: { type: "string" },
        school_type: { type: "string" },
        min_enrollment: { type: "integer" },
        max_enrollment: { type: "integer" },
        boarding: { type: "boolean" },
        nais_member: { type: "boolean" },
        free_text: { type: "string" }
      }
    }
  },
  {
    name: "query_people",
    description: "Search people/candidates database with filters",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string" },
        role: { type: "string" },
        state: { type: "string" },
        career_stage: { type: "string" },
        specializations: { type: "array", items: { type: "string" } },
        status: { type: "string" },
        min_rating: { type: "integer" },
        free_text: { type: "string" }
      }
    }
  },
  {
    name: "get_school_detail",
    description: "Get full details for a specific school",
    inputSchema: {
      type: "object",
      properties: { school_id: { type: "string" } },
      required: ["school_id"]
    }
  },
  {
    name: "get_person_detail",
    description: "Get full details for a specific person including history",
    inputSchema: {
      type: "object",
      properties: { person_id: { type: "string" } },
      required: ["person_id"]
    }
  },
  {
    name: "create_search",
    description: "Create a new search engagement record",
    inputSchema: { /* search fields */ }
  },
  {
    name: "update_search_status",
    description: "Update the status of an active search",
    inputSchema: {
      type: "object",
      properties: {
        search_id: { type: "string" },
        new_status: { type: "string" },
        notes: { type: "string" }
      },
      required: ["search_id", "new_status"]
    }
  },
  {
    name: "score_candidate",
    description: "Calculate match score between a candidate and a search",
    inputSchema: {
      type: "object",
      properties: {
        person_id: { type: "string" },
        search_id: { type: "string" }
      },
      required: ["person_id", "search_id"]
    }
  },
  {
    name: "add_interaction",
    description: "Log an interaction with a person",
    inputSchema: { /* interaction fields */ }
  },
  {
    name: "get_active_searches",
    description: "List all active search engagements",
    inputSchema: {}
  },
  {
    name: "get_industry_signals",
    description: "Retrieve recent industry signals and news",
    inputSchema: {
      type: "object",
      properties: {
        days_back: { type: "integer", default: 30 },
        signal_type: { type: "string" },
        unactioned_only: { type: "boolean" }
      }
    }
  }
];
```

---

## 8. Pricing Engine

### Fixed-Price Band Model

Knock's pricing model uses salary bands. The fee is approximately 20% of the upper end of each band, resulting in fees that are generally 15-25% of the actual salary — competitive with percentage-based competitors but predictable and transparent.

| Band | Salary Range | Fixed Fee | ~% at Midpoint | Deposit (50%) |
|---|---|---|---|---|
| **Band A** | $70,000 - $100,000 | $20,000 | ~23% | $10,000 |
| **Band B** | $100,001 - $150,000 | $30,000 | ~24% | $15,000 |
| **Band C** | $150,001 - $200,000 | $40,000 | ~23% | $20,000 |
| **Band D** | $200,001 - $275,000 | $55,000 | ~23% | $27,500 |
| **Band E** | $275,001 - $375,000 | $75,000 | ~23% | $37,500 |
| **Band F** | $375,001 - $500,000 | $100,000 | ~23% | $50,000 |
| **Band G** | $500,001+ | $125,000 | ~20%+ | $62,500 |

### Pricing Rules
1. **Band determination**: Based on the upper end of the school's stated salary range
2. **Deposit**: 50% due upon engagement signing
3. **Balance**: Due upon placement (candidate accepts offer)
4. **Guarantee**: If the placed candidate departs within 12 months, Knock will conduct a replacement search at no additional fee (client pays expenses only)
5. **Cancelled search**: Deposit is non-refundable but can be applied to a future search within 24 months
6. **Expenses**: Travel, background checks, and psychological assessments billed separately at cost

---

## 9. Search & Matchmaking Engine

### 9.1 Search Algorithm

Janet uses a multi-factor scoring system to match candidates to searches:

```
TOTAL SCORE = Σ(factor_weight × factor_score) / Σ(factor_weight)

Where each factor_score is 0-100 and factor_weight is configurable
```

**Scoring Implementation**:

```sql
-- Example scoring query (simplified)
WITH candidate_scores AS (
    SELECT
        p.id,
        p.full_name,
        p.current_title,
        p.current_organization,

        -- Position experience score (0-100)
        CASE
            WHEN EXISTS (
                SELECT 1 FROM person_experience pe
                WHERE pe.person_id = p.id
                AND pe.position_category = s.position_category
                AND pe.is_current = true
            ) THEN 100
            WHEN EXISTS (
                SELECT 1 FROM person_experience pe
                WHERE pe.person_id = p.id
                AND pe.position_category = s.position_category
            ) THEN 80
            WHEN p.primary_role = s.position_category THEN 60
            ELSE 20
        END AS position_score,

        -- School type match (0-100)
        CASE
            WHEN p.school_type_experience && s.preferred_school_types THEN 100
            ELSE 30
        END AS school_type_score,

        -- Geographic score (0-100)
        CASE
            WHEN p.state = sch.state THEN 100
            WHEN p.willing_to_relocate THEN 70
            WHEN sch.state = ANY(p.preferred_states) THEN 80
            ELSE 30
        END AS geo_score,

        -- Rating boost
        COALESCE(p.knock_rating * 20, 50) AS rating_score

    FROM people p
    CROSS JOIN searches s
    JOIN schools sch ON s.school_id = sch.id
    WHERE s.id = $search_id
    AND p.candidate_status IN ('active', 'passive')
    AND p.id NOT IN (
        SELECT person_id FROM search_candidates
        WHERE search_id = $search_id AND status = 'rejected'
    )
)
SELECT *,
    (position_score * 0.25 +
     school_type_score * 0.15 +
     geo_score * 0.10 +
     rating_score * 0.10) AS composite_score
FROM candidate_scores
ORDER BY composite_score DESC
LIMIT 50;
```

### 9.2 Redis Search Caching

For Janet's real-time queries, hot data is cached in Redis:

```python
# Pseudo-code for Redis search index
async def build_candidate_index():
    """Rebuild Redis search index from PostgreSQL"""
    candidates = await db.fetch_all("SELECT * FROM people WHERE candidate_status IN ('active', 'passive')")

    pipe = redis.pipeline()
    for c in candidates:
        key = f"knock:person:{c['id']}"
        pipe.json().set(key, "$", {
            "id": str(c["id"]),
            "name": c["full_name"],
            "title": c["current_title"],
            "org": c["current_organization"],
            "state": c["state"],
            "role": c["primary_role"],
            "stage": c["career_stage"],
            "rating": c["knock_rating"],
            "specializations": c["specializations"],
            "tags": c["tags"],
            "status": c["candidate_status"]
        })

        # Add to sorted sets for fast filtering
        if c["state"]:
            pipe.zadd(f"knock:idx:people:by_state:{c['state']}", {str(c['id']): c['knock_rating'] or 0})
        if c["primary_role"]:
            pipe.zadd(f"knock:idx:people:by_role:{c['primary_role']}", {str(c['id']): c['knock_rating'] or 0})

    await pipe.execute()
```

---

## 10. Workflow: End-to-End Search Process

### Complete Search Lifecycle

```
Phase 1: INTAKE (1-2 days)
├── Initial contact (school reaches out or Knock identifies opportunity)
├── Janet conducts intake interview (Skill: intake_interview)
├── School profile review/update
├── Position requirements documented
├── Pricing quoted and agreed (band-based)
├── Engagement letter signed
├── Deposit received
└── Search record created (status: 'intake' → 'profiling')

Phase 2: PROFILING (3-5 days)
├── Deep dive into school culture, challenges, opportunities
├── Search committee interviews (if applicable)
├── Position specification document created
├── Ideal candidate profile refined
├── Search strategy developed
└── Status: 'profiling' → 'sourcing'

Phase 3: SOURCING (2-4 weeks)
├── Janet runs database queries against criteria
├── Candidate pool identified (typically 30-100 initial matches)
├── LinkedIn outreach to passive candidates
├── Referral network activated
├── Industry signal monitoring for relevant transitions
├── Candidates scored and ranked
├── Initial screening conversations
└── Status: 'sourcing' → 'screening'

Phase 4: SCREENING (2-3 weeks)
├── Deep screening interviews with top 15-25 candidates
├── Credential verification
├── Reference preliminary checks
├── Cultural fit assessment
├── Candidate interest confirmation
├── Compensation alignment check
├── Short list developed (8-12 candidates)
└── Status: 'screening' → 'presenting'

Phase 5: PRESENTING (1-2 weeks)
├── Candidate presentation materials prepared
├── Presentation to search committee
├── Committee reviews and selects interview candidates
├── 4-6 candidates selected for school interviews
└── Status: 'presenting' → 'interviewing'

Phase 6: INTERVIEWING (3-6 weeks)
├── First-round interviews (typically virtual)
├── Interview feedback collected (both sides)
├── Second-round interviews (on-campus visits)
├── Community events / stakeholder meetings
├── Finalist identification (2-3 candidates)
└── Status: 'interviewing' → 'finalist'

Phase 7: FINALIST (1-3 weeks)
├── Deep reference checks (5-8 per finalist)
├── Background verification
├── Finalist campus visits (if not already done)
├── Board presentations
├── Final committee deliberation
├── Selection of preferred candidate
└── Status: 'finalist' → 'offer'

Phase 8: OFFER & CLOSE (1-2 weeks)
├── Compensation negotiation support
├── Offer letter preparation guidance
├── Offer extended
├── Candidate acceptance (or return to finalists)
├── Public announcement planning
├── Transition planning support
├── Final invoice sent
└── Status: 'offer' → 'placed'

Phase 9: FOLLOW-UP (ongoing)
├── 30-day check-in
├── 90-day check-in
├── 6-month formal review
├── 12-month formal review
├── Guarantee period monitoring
└── Relationship maintenance
```

### Status Transition Rules

```
intake ─────→ profiling
profiling ───→ sourcing
sourcing ────→ screening
screening ───→ presenting
presenting ──→ interviewing
interviewing → finalist
finalist ────→ offer
offer ───────→ placed
                └──→ closed_no_fill (if no acceptance)

Any status ──→ on_hold (reversible)
Any status ──→ cancelled (terminal)
closed_no_fill → re-opened as new search (with credit)
```

---

## 11. Telegram Bot Interface

### Bot Setup

| Setting | Value |
|---|---|
| **Bot Username** | @KnockJanetBot |
| **Bot Display Name** | Janet - Knock Search |
| **Description** | AI Office Manager for Knock Executive Search. Ask me about schools, candidates, and active searches. |
| **Pairing** | Permissive (no authentication required for initial access) |

### Command Structure

```
/start          - Introduction and capabilities overview
/help           - List available commands
/search         - Start a new search intake
/find           - Find candidates or schools
/status         - Check status of active searches
/school [name]  - Look up a school
/candidate [name] - Look up a candidate
/report         - Generate a report
/signal         - Check recent industry signals
/update         - Update a record
/stats          - Database statistics
```

### Conversation Modes

1. **Free Chat** — Natural language queries, Janet interprets and acts
2. **Intake Mode** — Structured interview flow (skill: intake_interview)
3. **Search Mode** — Database query and results browsing
4. **Report Mode** — Generating formatted documents

---

## 12. Web Dashboard & Gateway

### janet.askknock.com (OpenClaw Gateway)

**Access**: Token-based authentication only (no pairing)

**Features**:
- Chat interface for Janet (web-based alternative to Telegram)
- Search management dashboard
- Database browser (schools, candidates)
- Active search pipeline view
- Analytics and reporting
- System configuration

### askknock.com (Public Site)

**Pages**:
- Home: Value proposition, differentiation
- About: Knock's story, team, approach
- Services: What we offer, pricing transparency
- For Schools: Client information, engagement process
- For Candidates: How to join the network
- Contact: Get in touch, start a search
- Blog/Insights: Industry thought leadership
- **Status (`/status`)**: Client search-status lookup. Verifies the visitor by reference number (KNK-YYYY-NNN, returned at intake) plus the email captured on the intake form, then renders a redacted progress view: position, school, current phase (1–8), candidates identified, candidates presented to committee, and last-update date. Auth-exempt at the API layer (`POST /api/v1/searches/status`); on any mismatch returns 404 without disclosing existence. The intake success screen deep-links here as `?ref=KNK-YYYY-NNN` so new clients land prefilled. This is the first surface in the **stickiness strategy** — clients return to a Knock-controlled page throughout the 10–16-week engagement instead of waiting for an email.

---

## 13. CI/CD Pipeline

### Git-to-Deploy Flow

```
Developer pushes to main
        │
        v
GitHub Actions triggered
        │
        ├── Run tests
        ├── Lint code
        ├── Build Docker images
        ├── Push to GitHub Container Registry (ghcr.io)
        │
        v
SSH to DigitalOcean Droplet
        │
        ├── Pull latest images
        ├── Run database migrations
        ├── Docker Compose up (rolling restart)
        ├── Health check verification
        ├── Notify on success/failure
        │
        v
Live at askknock.com
```

### GitHub Actions Workflow

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
      - run: npm ci
      - run: npm test
      - run: npm run lint

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DROPLET_IP }}
          username: deploy
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /opt/knock
            git pull origin main
            docker compose build
            docker compose up -d
            docker compose exec -T app npm run db:migrate
            sleep 5
            curl -f http://localhost:3000/health || exit 1
            echo "Deploy successful"
```

---

## 14. API Design

### REST API (api.askknock.com)

```
# Schools
GET    /api/v1/schools                    # List schools (paginated, filterable)
GET    /api/v1/schools/:id                # Get school detail
POST   /api/v1/schools                    # Create school
PATCH  /api/v1/schools/:id                # Update school
GET    /api/v1/schools/:id/leadership     # School leadership history
GET    /api/v1/schools/:id/financials     # School financial history

# People
GET    /api/v1/people                     # List people (paginated, filterable)
GET    /api/v1/people/:id                 # Get person detail
POST   /api/v1/people                     # Create person
PATCH  /api/v1/people/:id                 # Update person
GET    /api/v1/people/:id/experience      # Person work history
GET    /api/v1/people/:id/interactions    # Interaction log

# Searches
GET    /api/v1/searches                   # List searches
GET    /api/v1/searches/:id               # Get search detail
POST   /api/v1/searches                   # Create search
PATCH  /api/v1/searches/:id               # Update search
POST   /api/v1/searches/status            # Public client status lookup (no API key) — body: { search_number, contact_email }; returns redacted phase + pipeline counts only on email match, 404 otherwise
GET    /api/v1/searches/:id/candidates    # Candidates for this search
POST   /api/v1/searches/:id/candidates    # Add candidate to search
PATCH  /api/v1/searches/:id/candidates/:cid # Update candidate status

# Matchmaking
POST   /api/v1/match/score                # Score candidate against search
POST   /api/v1/match/find                 # Find candidates for a search

# Industry
GET    /api/v1/signals                    # Recent industry signals
POST   /api/v1/signals                    # Create signal

# Pricing
GET    /api/v1/pricing/bands              # Get pricing bands
GET    /api/v1/pricing/quote              # Get quote for salary range

# System
GET    /api/v1/health                     # Health check
GET    /api/v1/stats                      # Database statistics
POST   /api/v1/sync/nces                  # Trigger NCES sync
POST   /api/v1/sync/linkedin              # Trigger LinkedIn import
```

---

## 15. Security & Access Control

### Authentication Layers

| Layer | Method | Users |
|---|---|---|
| **OpenClaw Gateway** | Token-based (single token) | Knock team |
| **Telegram Bot** | Permissive (open) | Anyone (initially) |
| **REST API** | API key + HTTPS | Internal services, future integrations |
| **Database** | Password + localhost only | Application services |
| **Server SSH** | Key-based only (no password) | DevOps |
| **Grafana** | Basic auth | Knock team |

### Security Measures
- All traffic over HTTPS (Caddy auto-TLS)
- PostgreSQL only accepts connections from localhost/Docker network
- Redis only accepts connections from localhost/Docker network
- SSH key-only authentication, no root login
- UFW firewall: only ports 80, 443, 22 open
- Regular automated backups (DO + pg_dump)
- Sensitive data encrypted at rest (candidate PII)
- Audit logging on all data modifications
- Rate limiting on API endpoints

### Data Privacy
- FERPA awareness (student data adjacent)
- Candidate consent tracking for data storage
- Right to deletion support
- No candidate data shared without explicit consent
- Interaction logs retained for 7 years (industry standard)

---

## 16. Data Sync & Maintenance

### Automated Sync Schedule

| Source | Frequency | Method | Window |
|---|---|---|---|
| NCES PSS Data | Biennial + quarterly check | Download + import script | Off-hours |
| ProPublica 990 | Annual (after filing season) | API pull | Weekly check |
| Job board monitoring | Daily | RSS/scrape | 6 AM ET |
| School website leadership | Monthly | Targeted scrape | Weekend |
| Redis cache rebuild | Daily | PostgreSQL → Redis sync | 3 AM ET |
| Search index update | Real-time on write | Trigger-based | Immediate |
| Backup (PostgreSQL) | Daily | pg_dump to DO Spaces | 2 AM ET |
| Backup (Redis) | Hourly | RDB snapshot | On the hour |

### Cron Jobs

```cron
# /etc/cron.d/knock
0 2 * * *     deploy  /opt/knock/scripts/backup-postgres.sh
0 3 * * *     deploy  /opt/knock/scripts/rebuild-redis-cache.sh
0 6 * * *     deploy  /opt/knock/scripts/check-job-boards.sh
0 0 * * 0     deploy  /opt/knock/scripts/scrape-school-leadership.sh
0 4 1 * *     deploy  /opt/knock/scripts/sync-990-data.sh
0 5 * * *     deploy  /opt/knock/scripts/generate-daily-signals.sh
```

---

## 17. Monitoring & Observability

### Metrics to Track

| Category | Metric | Alert Threshold |
|---|---|---|
| **System** | CPU usage | >80% sustained 5min |
| **System** | Memory usage | >85% |
| **System** | Disk usage | >80% |
| **Database** | Connection count | >80% of max |
| **Database** | Query latency (p99) | >500ms |
| **Database** | Table sizes | >80% of disk |
| **Redis** | Memory usage | >80% of maxmemory |
| **Redis** | Hit rate | <90% |
| **Application** | API response time (p99) | >2s |
| **Application** | Error rate | >5% of requests |
| **Bot** | Janet response time | >10s |
| **Bot** | Failed tool calls | >3 consecutive |
| **Business** | Active searches | Informational |
| **Business** | Database records | Informational |

### Monitoring Stack

```
Prometheus (metrics collection)
    ↓
Grafana (dashboards + alerting)
    ↓
Alertmanager (notifications)
    ↓
Telegram (alert channel)
```

---

## 18. Development Phases & Milestones

### Phase 1: Foundation (Week 1-2)
- [ ] DigitalOcean droplet provisioned and secured
- [ ] Docker Compose environment configured
- [ ] PostgreSQL database with all tables created
- [ ] Redis configured and running
- [ ] Caddy reverse proxy with SSL for all subdomains
- [ ] Git repo initialized with CI/CD pipeline
- [ ] Basic health check endpoints

### Phase 2: Data Layer (Week 2-3)
- [ ] NCES data downloaded and import script written
- [ ] NCES data loaded into schools table (~34,000 records)
- [ ] LinkedIn export imported into people table (~1,700 records)
- [ ] Cross-referencing people to schools completed
- [ ] Redis cache populated from PostgreSQL
- [ ] Full-text search indexes built and tested
- [ ] Meilisearch configured as secondary search engine

### Phase 3: Janet Core (Week 3-4)
- [ ] OpenClaw installed and configured
- [ ] Janet system prompt and personality defined
- [ ] Database query tools implemented and connected
- [ ] Basic conversation flow working
- [ ] Gateway dashboard accessible at janet.askknock.com
- [ ] Token authentication configured

### Phase 4: Telegram Bot (Week 4-5)
- [ ] Telegram bot created and configured
- [ ] Webhook endpoint deployed
- [ ] Permissive pairing enabled
- [ ] Basic commands working (/start, /help, /find, /school)
- [ ] Natural language queries routing to correct tools
- [ ] Rich message formatting (Markdown, inline keyboards)

### Phase 5: Skills & Workflows (Week 5-7)
- [ ] Intake interview skill implemented and tested
- [ ] Candidate search skill with scoring
- [ ] School lookup skill
- [ ] Match scoring algorithm implemented
- [ ] Report generation skill
- [ ] Record update skill
- [ ] Full search workflow documented and tested

### Phase 6: Data Enrichment (Week 7-9)
- [ ] ProPublica 990 integration (school financials)
- [ ] Job board monitoring scripts
- [ ] School website scraping for leadership data
- [ ] Industry signal detection pipeline
- [ ] Educational leadership program database
- [ ] Automated sync schedules configured

### Phase 7: Public Site & Polish (Week 9-10)
- [ ] askknock.com public site deployed
- [ ] Monitoring and alerting configured
- [ ] Backup verification tested
- [ ] Performance optimization (query tuning, cache warming)
- [ ] Documentation completed
- [ ] User acceptance testing

### Phase 8: Launch & Iterate (Week 10+)
- [ ] Soft launch with select schools
- [ ] Feedback collection and iteration
- [ ] Additional data source integrations
- [ ] Advanced analytics and reporting
- [ ] Client portal features
- [ ] Candidate self-service features

---

## 19. File & Repository Structure

```
knock/
├── .github/
│   └── workflows/
│       ├── deploy.yml                    # Main deploy pipeline
│       ├── test.yml                      # PR test runner
│       └── data-sync.yml                 # Scheduled data sync
│
├── docker-compose.yml                    # All services orchestration
├── docker-compose.dev.yml                # Development overrides
├── Caddyfile                             # Reverse proxy config
├── .env.example                          # Environment variable template
│
├── db/
│   ├── migrations/                       # Numbered SQL migrations
│   │   ├── 001_create_schools.sql
│   │   ├── 002_create_people.sql
│   │   ├── 003_create_searches.sql
│   │   ├── 004_create_extended_tables.sql
│   │   ├── 005_create_industry_tables.sql
│   │   ├── 006_create_system_tables.sql
│   │   └── 007_seed_pricing_bands.sql
│   ├── seeds/                            # Seed data
│   │   └── pricing_bands.sql
│   └── scripts/
│       ├── migrate.sh                    # Run migrations
│       └── reset.sh                      # Reset database (dev only)
│
├── services/
│   ├── api/                              # REST API service
│   │   ├── Dockerfile
│   │   ├── package.json
│   │   ├── src/
│   │   │   ├── index.ts                  # Entry point
│   │   │   ├── routes/
│   │   │   │   ├── schools.ts
│   │   │   │   ├── people.ts
│   │   │   │   ├── searches.ts
│   │   │   │   ├── match.ts
│   │   │   │   ├── pricing.ts
│   │   │   │   ├── signals.ts
│   │   │   │   └── health.ts
│   │   │   ├── models/
│   │   │   ├── middleware/
│   │   │   ├── lib/
│   │   │   │   ├── db.ts                 # PostgreSQL client
│   │   │   │   ├── redis.ts              # Redis client
│   │   │   │   ├── search.ts             # Search engine abstraction
│   │   │   │   └── scoring.ts            # Match scoring engine
│   │   │   └── types/
│   │   └── tests/
│   │
│   ├── data-sync/                        # Data ingestion service
│   │   ├── Dockerfile
│   │   ├── package.json
│   │   ├── src/
│   │   │   ├── importers/
│   │   │   │   ├── nces.ts               # NCES PSS data importer
│   │   │   │   ├── linkedin.ts           # LinkedIn CSV importer
│   │   │   │   ├── form990.ts            # ProPublica 990 API
│   │   │   │   ├── job-boards.ts         # Job board scraper
│   │   │   │   └── school-websites.ts    # Leadership scraper
│   │   │   ├── enrichers/
│   │   │   │   ├── geocode.ts
│   │   │   │   ├── school-enrich.ts
│   │   │   │   └── person-enrich.ts
│   │   │   ├── cache/
│   │   │   │   └── redis-sync.ts         # PostgreSQL → Redis sync
│   │   │   └── utils/
│   │   │       ├── deduplicate.ts
│   │   │       └── normalize.ts
│   │   └── data/
│   │       └── nces/                     # Downloaded NCES files
│   │
│   └── web/                              # Public website
│       ├── Dockerfile
│       ├── package.json
│       └── src/
│           ├── pages/                    # Or app/ for Next.js App Router
│           └── components/
│
├── openclaw/                             # OpenClaw agent configuration
│   ├── Dockerfile
│   ├── config.yaml                       # Agent configuration
│   ├── skills/
│   │   ├── intake_interview.yaml         # Intake skill definition
│   │   ├── candidate_search.yaml         # Search skill
│   │   ├── school_lookup.yaml            # School lookup skill
│   │   ├── match_score.yaml              # Scoring skill
│   │   ├── generate_report.yaml          # Report generation
│   │   ├── update_record.yaml            # Data update skill
│   │   └── industry_monitor.yaml         # Signal monitoring
│   ├── tools/
│   │   ├── db-query.ts                   # Database query tool
│   │   ├── db-write.ts                   # Database write tool
│   │   ├── redis-search.ts              # Redis search tool
│   │   ├── scoring-engine.ts            # Match scoring tool
│   │   └── report-builder.ts            # Report generation tool
│   ├── workflows/
│   │   ├── search-lifecycle.yaml         # Full search workflow
│   │   └── data-enrichment.yaml          # Data pipeline workflow
│   └── prompts/
│       ├── system.md                     # Janet's system prompt
│       ├── intake-template.md            # Intake conversation template
│       └── candidate-profile.md          # Candidate presentation template
│
├── scripts/
│   ├── setup-server.sh                   # Initial server setup
│   ├── backup-postgres.sh                # Database backup
│   ├── rebuild-redis-cache.sh            # Cache rebuild
│   ├── check-job-boards.sh              # Job board monitor
│   ├── scrape-school-leadership.sh      # Leadership scraper
│   ├── sync-990-data.sh                  # 990 data sync
│   └── generate-daily-signals.sh         # Daily signal generation
│
├── docs/
│   ├── PRD.md                            # This document
│   ├── DATABASE.md                       # Database schema docs
│   ├── API.md                            # API documentation
│   ├── DEPLOYMENT.md                     # Deployment guide
│   ├── SKILLS.md                         # Janet skills documentation
│   └── DATA-SOURCES.md                   # Data source documentation
│
├── tests/
│   ├── integration/
│   ├── unit/
│   └── fixtures/
│
├── package.json                          # Root workspace config
├── tsconfig.json                         # TypeScript config
├── README.md
└── .gitignore
```

---

## 20. Appendices

### Appendix A: NCES PSS Data Dictionary

Key variables from the Private School Survey that map to our schema:

| Variable | Description | Type |
|---|---|---|
| PPIN | Private school ID number | Char(8) |
| PINST | Institution name | Char(100) |
| PADDRS | Street address | Char(40) |
| PCITY | City | Char(20) |
| PSTABB | State abbreviation | Char(2) |
| PZIP | ZIP code | Char(5) |
| LEVEL | School level (1=Elem, 2=Sec, 3=Combined) | Num |
| NUMSTUDS | Total enrollment | Num |
| P_INDIAN through P_PACIFIC | Enrollment by race/ethnicity | Num |
| PKTCH | Total teachers | Num |
| ORIENT | Religious orientation | Num (coded) |
| CESSION | Coeducational | Num (1=Yes, 2=No) |
| LATITUDE | Latitude | Num |
| LONGITUDE | Longitude | Num |

Full data dictionary available at: https://nces.ed.gov/surveys/pss/pssdata.asp

### Appendix B: LinkedIn Export Format

Standard LinkedIn connections export CSV columns:
- First Name
- Last Name
- Email Address
- Company
- Position
- Connected On
- URL (LinkedIn profile URL)

### Appendix C: ProPublica Nonprofit API

**Base URL**: `https://projects.propublica.org/nonprofits/api/v2/`

**Key Endpoints**:
- `GET /search.json?q={school_name}` — Search for organizations
- `GET /organizations/{ein}.json` — Organization details + filings
- Filing data includes: revenue, expenses, executive compensation, board members

### Appendix D: Glossary

| Term | Definition |
|---|---|
| **NAIS** | National Association of Independent Schools |
| **NCES** | National Center for Education Statistics |
| **PSS** | Private School Survey (NCES biennial survey) |
| **HOS** | Head of School |
| **TABS** | The Association of Boarding Schools |
| **ISM** | Independent School Management |
| **NEASC** | New England Association of Schools and Colleges |
| **WASC** | Western Association of Schools and Colleges |
| **SACS** | Southern Association of Colleges and Schools |
| **EIN** | Employer Identification Number (IRS tax ID) |
| **Form 990** | IRS annual filing for tax-exempt organizations |
| **Search** | An active engagement to fill a specific position |
| **Placement** | A successfully filled position |
| **Signal** | An industry event or trend relevant to recruiting |
| **Band** | A salary range used for pricing |

### Appendix E: Environment Variables

```bash
# .env.example

# PostgreSQL
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=knock
POSTGRES_USER=knock_admin
POSTGRES_PASSWORD=

# Redis
REDIS_URL=redis://redis:6379

# OpenClaw
OPENCLAW_TOKEN=
OPENCLAW_MODEL=anthropic/claude-sonnet-4-6

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_URL=https://api.askknock.com/webhooks/telegram

# Meilisearch
MEILI_MASTER_KEY=
MEILI_HOST=http://meilisearch:7700

# ProPublica API (no key needed, rate-limited)
PROPUBLICA_BASE_URL=https://projects.propublica.org/nonprofits/api/v2

# Backups
DO_SPACES_KEY=
DO_SPACES_SECRET=
DO_SPACES_BUCKET=knock-backups
DO_SPACES_REGION=nyc3

# Monitoring
GRAFANA_ADMIN_PASSWORD=

# Application
NODE_ENV=production
API_PORT=4000
LOG_LEVEL=info
```

---

## Document History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-03-27 | Knock Team | Initial PRD |

---

*This PRD serves as the single source of truth for the Knock platform. All development agents should reference this document for context, database schema, workflows, and architectural decisions.*
