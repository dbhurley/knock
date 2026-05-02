# CLAUDE.md — Knock Executive Search Platform

> Complete system documentation for AI agents working on this codebase.
> Last updated: 2026-05-02

---

## 1. What Is Knock?

**Knock** is a specialized executive recruiting agency for the private and independent K-12 school sector in the United States. Unlike traditional search firms that charge 25-33% of first-year salary, Knock uses **fixed-price salary bands** ($20K-$125K) providing cost transparency.

**Founder:** Dan Hurley (@dbhurley)
**Domain:** askknock.com
**AI Office Manager:** Janet (@JanetKnockBot on Telegram)

### Core Business Model
Schools hire Knock when they need a new Head of School (or other executive). Janet handles intake, sourcing, matching, and pipeline management. Dan handles relationship selling, onsite visits, interviews, and committee guidance.

### Pricing Bands (fixed fees, not percentage)
| Band | Salary Range | Fee |
|------|-------------|-----|
| A | $70-100K | $20,000 |
| B | $100-150K | $30,000 |
| C | $150-200K | $40,000 |
| D | $200-275K | $55,000 |
| E | $275-375K | $75,000 |
| F | $375-500K | $100,000 |
| G | $500K+ | $125,000 |

---

## 2. Architecture Overview

```
                    ┌──────────────────┐
                    │  askknock.com     │ Caddy (auto-HTTPS)
                    │  janet.askknock   │ port 80/443
                    │  api.askknock     │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼──────┐ ┌────▼─────┐ ┌──────▼───────┐
     │  OpenClaw     │ │ Knock API│ │ Matching     │
     │  (Janet)      │ │ Fastify  │ │ Engine       │
     │  port 3000    │ │ port 4000│ │ FastAPI 4001 │
     │  systemd      │ │ Docker   │ │ systemd      │
     └────────┬──────┘ └────┬─────┘ └──────┬───────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
                    ┌────────▼─────────┐
                    │   PostgreSQL 16  │
                    │   Docker :5432   │
                    │   37+ tables     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Redis 7        │
                    │   Docker :6379   │
                    │   Cache layer    │
                    └──────────────────┘
```

### Technology Stack
| Layer | Technology | Notes |
|-------|-----------|-------|
| Server | DigitalOcean Droplet (4 vCPU, 8GB RAM, 160GB NVMe) | NYC1, Ubuntu 24.04 |
| Database | PostgreSQL 16 (Docker) | 37+ tables, full-text search via pg_trgm |
| Cache | Redis 7 (Docker) | Candidate/school index caching |
| Search | Meilisearch (Docker) | Secondary search engine |
| API | Node.js 22 / Fastify / TypeScript | port 4000, Docker |
| Matching | Python 3.12 / FastAPI | port 4001, systemd |
| AI Agent | OpenClaw 2026.3.24 | Janet, port 3000, systemd |
| Proxy | Caddy 2.11.2 | Auto-HTTPS, reverse proxy, Docker |
| Email | Postfix + Dovecot + OpenDKIM | janet@askknock.com, systemd |
| CI/CD | GitHub Actions → SSH deploy | Push-to-deploy on main |
| Monitoring | Prometheus + Grafana (planned) | grafana.askknock.com reserved |

### Running Services
| Service | Type | Port | Status |
|---------|------|------|--------|
| knock-postgres | Docker | 5432 (localhost) | healthy |
| knock-redis | Docker | 6379 (localhost) | healthy |
| knock-meilisearch | Docker | 7700 (localhost) | running |
| knock-api | Docker | 4000 (localhost) | running |
| knock-caddy | Docker | 80, 443 (public) | running |
| openclaw (Janet) | systemd | 3000 (LAN) | active |
| matching engine | systemd | 4001 (localhost) | active |
| postfix | systemd | 25, 587 | active |
| dovecot | systemd | 143, 993 | active |
| opendkim | systemd | 12301 (localhost) | active |

---

## 3. Domain Configuration

| URL | Purpose | Auth |
|-----|---------|------|
| `askknock.com` | Public landing page + intake form | None |
| `askknock.com/start-search` | Search intake form (clean URL) | None |
| `askknock.com/status` | Client search-status lookup (reference # + email) | None (verified by email match) |
| `askknock.com/assess` | Candidate rating tool (Dan only) | Basic auth: `dan` / `knock2024assess` |
| `janet.askknock.com` | OpenClaw Gateway dashboard | Token auth |
| `api.askknock.com` | REST API | API key (X-API-Key header) |
| `grafana.askknock.com` | Monitoring (reserved) | Basic auth |

DNS managed by DigitalOcean (ns1/ns2/ns3.digitalocean.com). All A records point to `157.245.246.123`.

---

## 4. Database Schema

### Core Tables (with approximate row counts as of 2026-04-09)

**Schools & School Data:**
| Table | Rows | Purpose |
|-------|------|---------|
| `schools` | 23,821 | Primary school records (NCES + enrichment) |
| `school_accreditations` | 0 | Accreditation records |
| `school_programs` | 0 | Academic programs |
| `school_board_members` | 347 | Board of trustees members |
| `school_financials` | 0 | Financial data from 990s |
| `school_leadership_history` | 0 | Historical HOS timeline |

**People & Candidate Data:**
| Table | Rows | Purpose |
|-------|------|---------|
| `people` | 3,769 | Primary person records |
| `person_education` | 2,070 | Education history |
| `person_experience` | 3,385 | Work history |
| `person_certifications` | 0 | Professional certifications |
| `person_skills` | 0 | Skills and competencies |
| `person_references` | 0 | Professional references |
| `person_interactions` | 0 | Contact log |
| `person_compensation` | 0 | Compensation from 990s |
| `person_social_profiles` | 0 | Social media profiles |
| `person_publications` | 0 | Publications/articles |
| `inferred_emails` | 5,487 | Generated email addresses with verification status |

**Searches & Pipeline:**
| Table | Rows | Purpose |
|-------|------|---------|
| `searches` | 1 | Active search engagements (KNK-2026-001) |
| `search_candidates` | 1 | Candidates linked to searches |
| `search_activities` | 0 | Activity log per search |
| `placements` | 0 | Completed placements |

**Intelligence & Enrichment:**
| Table | Rows | Purpose |
|-------|------|---------|
| `industry_signals` | 243 | News monitoring alerts |
| `industry_events` | 0 | Conference/event tracking |
| `leadership_programs` | 23 | Ed leadership program registry |
| `program_graduates` | 0 | Program alumni tracking |
| `enrichment_provenance` | 0 | Field-level source tracking |

**Janet's Memory (NEW — migration 014):**
| Table | Rows | Purpose |
|-------|------|---------|
| `janet_memory` | 9 | Persistent facts, instructions, decisions, corrections |
| `janet_outputs` | 0 | Ledger of what Janet said to whom |

**System:**
| Table | Rows | Purpose |
|-------|------|---------|
| `pricing_bands` | 7 | Fixed-fee pricing configuration |
| `tag_categories` | 0 | Tagging taxonomy |
| `audit_log` | 0 | Data modification audit trail |
| `data_sync_log` | 5 | Data import tracking |
| `match_cache` | 0 | Precomputed match scores |
| `match_scores_log` | 0 | Match score audit trail |
| `transition_signals_log` | 0 | Transition prediction audit |
| `newsletter_lists` | 15 | Newsletter audience lists |
| `newsletter_subscriptions` | 1,845 | Individual subscriptions |
| `newsletter_campaigns` | 0 | Newsletter sends |
| `newsletter_sends` | 0 | Per-recipient delivery log |

### Key Columns on `schools`
- `nces_id` (UNIQUE) — NCES Private School Survey ID
- `school_segment` — Normalized religious/secular classification (17 values: secular, catholic, episcopal, quaker, jewish, islamic, baptist, lutheran, methodist, presbyterian, adventist, lds, anabaptist, pentecostal, evangelical_christian, orthodox_christian, other_religious)
- `pedagogy` — Educational philosophy (montessori, waldorf, classical, ib_world, reggio, progressive)
- `enrollment_total`, `student_teacher_ratio`, `total_teachers`
- `website`, `email`, `phone`
- `school_culture_tags[]`, `strategic_priorities[]`, `tags[]`
- `current_hos_name`, `current_hos_person_id`, `hos_tenure_years`
- `transition_prediction_score`, `predicted_transition_window`
- `search_vector` (tsvector, auto-updated by trigger)

### Key Columns on `people`
- `linkedin_id` (UNIQUE) — LinkedIn profile slug
- `primary_role` — head_of_school, division_head, academic_dean, cfo, etc.
- `career_stage` — emerging, mid_career, senior, veteran, retired
- `candidate_status` — active, passive, not_looking, placed, do_not_contact, retired
- `specializations[]` — fundraising, stem, dei, boarding, etc.
- `cultural_fit_tags[]` — progressive, traditional, faith-based, secular, etc.
- `leadership_style[]` — collaborative, visionary, transformational, etc.
- `knock_rating` (1-5) — Internal quality rating
- `data_completeness_score` (0-100) — Auto-computed quality metric
- `inferred_education_level` — doctorate, masters, bachelors
- `enrollment_experience_range` (INT4RANGE) — School sizes candidate has led
- `search_vector` (tsvector, auto-updated by trigger)

### Key Columns on `janet_memory`
- `kind` — standing_instruction, fact, decision, followup, preference, correction, context
- `subject` — Short label for retrieval
- `content` — The memory text
- `related_search_id`, `related_school_id`, `related_person_id` — Entity links
- `priority` (1-10) — Higher = more important, surfaced first
- `is_active` — FALSE when superseded
- `superseded_by` — Points to replacement memory
- `search_vector` (tsvector, auto-updated by trigger)

---

## 5. Janet — AI Office Manager

### Architecture
Janet runs on OpenClaw 2026.3.24 as a systemd service. Her configuration lives at `/root/.openclaw/openclaw.json`. Her workspace is at `/root/.openclaw/workspace/`.

### System Prompt (SOUL.md)
Located at `/root/.openclaw/workspace/SOUL.md` (4,539 chars). Contains:
1. **Memory-first protocol** — Janet MUST call `memory_recall` before responding
2. **Anti-hallucination rules** — Never invent data; say "not on file" for NULL fields
3. **Tool inventory** — 3 MCP servers, skill files, shell scripts
4. **Pricing bands** — The one reference worth inlining
5. **Style/confidentiality** — Match Dan's casual register, don't share candidate info

**CRITICAL:** SOUL.md must stay under 20,000 chars or OpenClaw truncates it from the bottom. Current: 4,539.

### MCP Servers (3 registered)

**1. knock-api** — Database access
- Location: `/root/.openclaw/mcp-servers/knock-api/server.mjs`
- Tools: search_schools, get_school, update_school, search_people, get_person, update_person, create_person, list_searches, create_search, score_candidate, find_candidates, get_pricing_quote, list_pricing_bands, get_stats
- Env: `KNOCK_API_URL=http://localhost:4000`

**2. knock-email** — Email (janet@askknock.com)
- Location: `/root/.openclaw/mcp-servers/knock-email/server.mjs`
- Tools: send_email, check_email, read_email, reply_email
- Uses local Postfix (localhost:25)

**3. knock-memory** — Persistent memory in Postgres
- Location: `/root/.openclaw/mcp-servers/knock-memory/server.mjs`
- Tools: memory_recall, memory_store, memory_supersede, ledger_log, ledger_recent
- Env: `DATABASE_URL=postgresql://knock_admin:...@127.0.0.1:5432/knock`

### Skills (in workspace)
Located at `/root/.openclaw/workspace/skills/`:
- `executive_search_workflow.yaml` — 11-phase search lifecycle
- `candidate_search.yaml` — Natural language candidate search
- `intake_interview.yaml` — Structured intake conversation
- `match_score.yaml` — Detailed scoring breakdown
- `generate_report.yaml` — Document generation
- `update_record.yaml` — Database updates
- `school_lookup.yaml` — School information
- `industry_monitor.yaml` — Signal detection
- `llm_enrich_candidate.yaml` — Claude-powered bio enrichment
- `plasmate` — Headless browser for web research

### Memory Architecture (post-2026-04-08 fix)
Janet's memory lives in Postgres, not markdown files. The prior design had SOUL.md bloating to 21K+ chars (getting truncated) and markdown memory files that Janet forgot to read.

**Current design:**
- `janet_memory` table — 9 memories seeded (standing instructions, facts, corrections)
- `memory_recall(query)` MCP tool — full-text search, returns memories ranked by relevance
- `memory_store(kind, subject, content)` — saves new memories with entity links
- `ledger_log(channel, recipient, summary)` — records what Janet said
- SOUL.md just says "call memory_recall before responding"
- Session digest cron runs every 20 min to capture Telegram conversations

### Telegram Integration
- Bot: @JanetKnockBot (token in .env)
- Group: Knock (-1003814956035)
- Chat ID file: `/opt/knock/.telegram_chat_id`
- Pairing: permissive (open)
- DM policy: open
- Streaming: partial

### Wiki (Karpathy LLM Wiki Pattern)
Located at `/opt/knock/wiki/`. Janet actively maintains this as a persistent knowledge base:
- `INDEX.md`, `LOG.md`, `SCHEMA.md` — Meta pages
- `market/` — 7 reference pages (salary benchmarks, transition patterns, school types, etc.)
- `people/` — 130+ individual candidate profiles
- `schools/` — 26+ individual school profiles
- `searches/` — 2 search engagement pages (KNK-2026-001, KNK-2026-002)
- `syntheses/` — Cross-cutting analyses

---

## 6. REST API (api.askknock.com)

Built with Fastify + TypeScript at `/services/api/`.

### Endpoints
```
# Schools
GET    /api/v1/schools                    # Search/filter (paginated)
GET    /api/v1/schools/:id                # Full detail
POST   /api/v1/schools                    # Create
PATCH  /api/v1/schools/:id                # Update
GET    /api/v1/schools/:id/leadership     # Leadership history
GET    /api/v1/schools/:id/financials     # Financial snapshots

# People
GET    /api/v1/people                     # Search/filter (paginated)
GET    /api/v1/people/:id                 # Full detail
POST   /api/v1/people                     # Create
PATCH  /api/v1/people/:id                 # Update
GET    /api/v1/people/:id/experience      # Work history
GET    /api/v1/people/:id/interactions    # Contact log

# Searches
GET    /api/v1/searches                   # List (filter by status)
GET    /api/v1/searches/:id               # Detail
POST   /api/v1/searches                   # Create
PATCH  /api/v1/searches/:id               # Update
POST   /api/v1/searches/status            # Public client-facing status lookup (search_number + contact_email, no API key) — returns phase, progress %, next milestone, last activity
GET    /api/v1/searches/:id/candidates    # Candidate pipeline
POST   /api/v1/searches/:id/candidates    # Add candidate
PATCH  /api/v1/searches/:id/candidates/:cid # Update status

# Matching
POST   /api/v1/match/score               # Score one candidate vs search
POST   /api/v1/match/find                 # Find top N candidates

# Pricing
GET    /api/v1/pricing/bands              # All 7 bands
GET    /api/v1/pricing/quote?salary=N     # Fee for a salary

# Other
POST   /api/v1/intake                     # Public intake form submission → creates search + Telegram notification
GET    /api/v1/signals                    # Industry signals
GET    /api/v1/stats                      # Database counts
GET    /health                            # Health check
```

### Matching Engine (scoring.ts)
10-factor weighted scoring (0-100):
| Factor | Weight | Source |
|--------|--------|--------|
| Position experience | 25% | person_experience table |
| School type alignment | 15% | school_type_experience array |
| Geography | 10% | state + preferred_states + willing_to_relocate |
| Education | 10% | person_education table |
| Enrollment match | 10% | enrollment_experience_range |
| Specializations | 10% | specializations array |
| Cultural fit | 10% | cultural_fit_tags array |
| Career stage | 5% | career_stage field |
| Availability | 5% | candidate_status + availability_date |

---

## 7. Data Sources & Enrichment Pipeline

### Primary Data Sources
| Source | Records | Method | Frequency |
|--------|---------|--------|-----------|
| NCES Private School Survey | 22,345 schools | CSV import | Biennial + weekly sync |
| LinkedIn Connections | 1,581 people | CSV import | One-time base |
| Independent School List | 786 schools + 1,747 people | CSV import | One-time |
| ACCS Directory | 435 schools | AJAX API endpoint | On-demand |
| Google News RSS | 243 signals | RSS monitoring | Daily |
| School Websites | ~100 enriched | Web scraping | Weekly |

### Enrichment Scripts (in /scripts/)

**SQL-based enrichment (idempotent, run in order):**
1. `enrich-01-school-linkage.sql` — 5-strategy fuzzy matching of people to schools
2. `enrich-02-dedup-quality.sql` — Duplicate detection + data completeness scoring
3. `enrich-03-infer-education-specializations.sql` — Parse degrees/specs from text fields
4. `enrich-04-backfill-experience.sql` — Populate person_experience from current data
5. `enrich-05-school-segments.sql` — Classify schools by religious/secular segment
6. `enrich-all.sh` — Master runner for all SQL scripts

**Python-based enrichment (cron-scheduled):**
| Script | Frequency | What | Cost |
|--------|-----------|------|------|
| `run-enrich-contacts.sh` (v2) | Every 4h | mailto/tel extraction from school sites | Free |
| `run-llm-enrich.sh` | Every 6h | Claude-powered HOS bio extraction | ~$0.40/day |
| `run-llm-board-scrape.sh` | Every 8h | Claude-powered board member extraction | ~$0.40/day |
| `run-newsletter-sync.sh` | Daily 6 AM | Refresh newsletter subscriber lists | Free |
| `run-session-digest.sh` | Every 20 min | Capture Telegram conversations to memory | ~$0.50/day |
| News monitor | Daily 7 AM | Google News RSS for HOS transitions | Free |
| School websites | Tuesday 6 AM | Scrape leadership pages | Free |
| Form 990 | Monthly 1st | ProPublica API for financials | Free |
| NCES sync | Sunday 4:17 AM | Check for new PSS data | Free |

### Association Scrapers (/services/association-scrapers/)
12 Python scrapers for school association directories:
- ACSI (Christian), Catholic/NCEA, Episcopal/NAES, Jewish/Prizmah
- Quaker/FCE, Montessori/AMS, Waldorf/AWSNA, Classical/ACCS
- IB Schools, NAEYC (early childhood), Learning Differences, Military

**Note:** Most HTML scrapers return 0 results because association websites use JS rendering. The ACSI, Montessori, and IB scrapers were rewritten to use NCES association codes (which work). The ACCS scraper uses a discovered AJAX endpoint.

---

## 8. Data Quality (as of 2026-04-09)

### Overall Distribution
| Tier | Count | Avg Score | % |
|------|-------|-----------|---|
| Poor (0-24) | 335 | 23.3 | 9% |
| Fair (25-49) | 1,086 | 30.7 | 29% |
| Good (50-74) | 1,993 | 61.4 | 53% |
| Excellent (75+) | 355 | 75.0 | 9% |

### Field Population
| Field | Populated | % |
|-------|-----------|---|
| Name/Title | 3,700+ | 99% |
| Career stage | 2,988 | 87% |
| Current school linked | 2,023 | 59% |
| Email (inferred + verified) | 1,932 | 57% |
| State/Location | 2,023 | 59% |
| Education records | 2,070 | 61% |
| Specializations | 172+ | 5% |
| Cultural fit tags | 1,245 | 37% |
| Knock rating | 0 | 0% |
| Phone | ~120 | 3% |

---

## 9. Newsletter System

### Lists (15 total)
**HOS lists (by school segment):**
- heads-of-school (umbrella): 1,835 subscribers
- hos-secular: 1,160
- hos-catholic: 305
- hos-evangelical: 245
- hos-montessori: 108
- hos-episcopal: 57
- hos-quaker: 49
- hos-jewish: 21
- hos-waldorf: 17

**Board member lists:** board-secular (1), board-catholic (1), board-jewish (0), board-episcopal (0), board-evangelical (0)

### Usage
```bash
python3 /opt/knock/scripts/newsletter.py sync          # refresh subscribers
python3 /opt/knock/scripts/newsletter.py lists          # show all lists
python3 /opt/knock/scripts/newsletter.py draft <slug> --subject "..." --body-file body.html
python3 /opt/knock/scripts/newsletter.py preview <id>
python3 /opt/knock/scripts/newsletter.py send <id> --test you@example.com
python3 /opt/knock/scripts/newsletter.py send <id>      # full send
```

---

## 10. Document Generation (/services/documents/)

Python-based PDF generation using WeasyPrint + Jinja2.

| Document | Script | Purpose |
|----------|--------|---------|
| Candidate Profile | `candidate_profile.py` | 1-2 page PDF for presenting to search committees |
| Opportunity Profile | `opportunity_profile.py` | Marketing document for the position |
| Committee Briefing | `committee_briefing.py` | Multi-candidate comparison packet |
| Search Status | `search_status_report.py` | Pipeline progress report |

```bash
python3 generate.py candidate-profile --person-id UUID -o output.pdf
python3 generate.py search-status --search-id UUID -o output.pdf
python3 generate.py opportunity-profile --search-id UUID -o output.pdf
python3 generate.py committee-briefing --search-id UUID -o output.pdf
```

---

## 11. CI/CD Pipeline

### GitHub Actions
- **deploy.yml** — Triggered on push to main: test → SSH deploy → docker compose up → migrate → health check
- **test.yml** — Triggered on PRs: typecheck + lint + test
- **data-sync.yml** — Weekly Sunday: Redis cache rebuild

### Manual Deploy
```bash
ssh root@157.245.246.123
cd /opt/knock
git pull origin main
docker compose build && docker compose up -d
# Run any new migrations
docker exec -i knock-postgres psql -U knock_admin -d knock < db/migrations/NNN_whatever.sql
```

### Server Access
```bash
ssh root@157.245.246.123    # root access
ssh deploy@157.245.246.123  # deploy user (docker group)
```

---

## 12. Cron Schedule (Complete)

| Schedule | Job | What |
|----------|-----|------|
| `*/5 * * * *` | check-email-cron.sh | Check janet@askknock.com inbox |
| `*/20 * * * *` | run-session-digest.sh | Capture Telegram → memory |
| `0 3 * * *` | qmd embed | Re-embed memory for semantic search |
| `0 3 * * *` | refresh-mail-certs.sh | TLS cert refresh |
| `0 */4 * * *` | run-enrich-contacts.sh | v2 contact scraping (mailto/tel) |
| `0 5 1 * *` | enrich.py form990 | Monthly Form 990 enrichment |
| `0 6 * * *` | run-newsletter-sync.sh | Newsletter audience sync |
| `0 6 * * 2` | enrich.py websites | Tuesday school website scraping |
| `0 7 * * *` | enrich.py news | Daily news monitoring |
| `0 */6 * * *` | run-llm-enrich.sh | Claude bio enrichment (5/run) |
| `0 */6 * * *` | check-followups.py | Follow-up reminders |
| `0 */8 * * *` | run-llm-board-scrape.sh | Board member extraction (10/run) |
| `15 */4 * * *` | run-wiki-writer.sh | Wiki page generation |
| `17 4 * * 0` | sync-nces.sh | Weekly NCES data check |
| `0 12 * * *` | daily-digest.py → Telegram | Morning briefing (8 AM ET) |
| `0 13 * * 1` | weekly-report.py → Telegram | Monday pipeline report (9 AM ET) |

---

## 13. File Structure (Key Directories)

```
knock/
├── .github/workflows/          # CI/CD (deploy, test, data-sync)
├── db/migrations/              # 17 SQL migration files
├── db/scripts/                 # migrate.sh, reset.sh
├── docs/                       # DEPLOYMENT.md
├── openclaw/                   # Janet agent configuration
│   ├── SOUL.md                 # System prompt (4.5K chars)
│   ├── config.yaml             # Agent configuration
│   ├── skills/                 # 9 YAML skill definitions
│   ├── prompts/                # Conversation templates
│   ├── tools/                  # TypeScript tools
│   ├── mcp-servers/knock-memory/  # Memory MCP server
│   └── workflows/              # Search lifecycle workflow
├── public/                     # Static site files
│   ├── index.html              # Landing page
│   ├── start-search.html       # Intake form
│   ├── assess.html             # Candidate rating tool
│   └── knock-logo.svg          # Lion door-knocker logo
├── scripts/                    # 24 operational scripts
│   ├── enrich-*.sql            # SQL enrichment pipeline (5 scripts)
│   ├── llm-enrich.py           # Claude-powered bio extraction
│   ├── llm-board-scrape.py     # LLM board member extraction
│   ├── enrich-contacts-v2.py   # Web scraping enrichment
│   ├── newsletter.py           # Newsletter management
│   ├── session-digest.py       # Telegram → memory capture
│   ├── import-accs.py          # ACCS directory importer
│   ├── daily-digest.py         # Morning briefing
│   ├── weekly-report.py        # Pipeline report
│   ├── check-followups.py      # Follow-up reminders
│   ├── notify-telegram.py      # Telegram notification helper
│   └── run-*.sh                # Cron wrappers
├── services/
│   ├── api/                    # REST API (TypeScript/Fastify)
│   ├── data-sync/              # NCES/LinkedIn importers (TypeScript)
│   ├── matching/               # Scoring engine (Python/FastAPI)
│   ├── enrichment/             # Enrichment pipeline (Python)
│   ├── association-scrapers/   # 12 school association scrapers (Python)
│   ├── people-sources/         # Candidate sourcing scripts (Python)
│   └── documents/              # PDF generation (Python/WeasyPrint)
├── docker-compose.yml          # Production services
├── docker-compose.dev.yml      # Development overrides
├── Caddyfile                   # Reverse proxy configuration
├── PRD.md                      # 86K original product spec
├── CLAUDE.md                   # This document
└── README.md                   # Quick start
```

---

## 14. Active Search Engagements

### KNK-2026-001: Covenant Christian Academy HOS Search
- **School:** COVENANT CHRISTIAN ACADEMY, Colleyville, TX (ID: `2b9769f0-...`)
- **Position:** Head of School
- **Status:** sourcing
- **Client contact:** Becca Thomas (Rebecca Thomas, Ed.D.) — current/departing HOS
- **Becca's DB ID:** `3ea5dc78-...`
- **Active candidate:** Angela Rimington (ID: `33c56846-...`)
  - Current: HOS at Veritas Christian Academy of Houston (since 2025)
  - Prior: Highlands Latin School (doubled enrollment in 5 years)
  - 30+ years classical Christian / independent school leadership
  - Flag: only 1 year at Veritas — committee will ask about short tenure
  - Email: angela.rimington@gmail.com, Phone: 202-746-6958

---

## 15. Known Issues & Technical Debt

### Critical
- **knock-api Docker health check fails** — Container shows "unhealthy" but API responds fine. Health check endpoint path or timing may be wrong.
- **knock-caddy Docker health check fails** — Same issue. Caddy works fine externally.
- **ProPublica Form 990 API v2** — Filing detail endpoints return 404 for all organizations. API may have changed URL structure. Compensation enrichment blocked.

### Data Gaps
- **Phone numbers:** 97% missing. v2 enrichment adds ~19/50 schools attempted.
- **Knock rating:** 0% — requires Dan's manual assessment via /assess tool.
- **Specializations:** Only 5% populated from keyword inference. LLM enrichment adds real specializations but slow (5/run × 4 runs/day).
- **Board member emails:** 0% — board records have names but no contact info yet.

### Architecture
- **Duplicate migration numbering:** 011 and 012 and 013 each have two files (different purposes, both applied). Should be renumbered.
- **Email verification:** first.last pattern only valid for ~20% of schools. Need to test flast/firstlast/custom patterns.
- **Association scrapers:** 9 of 12 return 0 results because target sites use JS rendering. Only ACSI, Montessori, and IB scrapers work.

---

## 16. Roadmap & Next Steps

### Stickiness Strategy
The 10–16-week search engagement is the key window. Each touchpoint that gives the client a reason to come back to a Knock-controlled surface (vs. waiting for an email) deepens habituation and reduces shop-around risk. Priorities are ordered to maximize return-visits per active search.

### Recently Shipped (2026-04-28)
- **Public search status page** at `askknock.com/status` (and deep-linkable via `?ref=KNK-XXXX-NNN`) — clients can self-check phase, candidate pipeline, and last-update date using their reference number plus contact email. Verifies via email match against `searches.client_contact_email` (404 on any mismatch — does not disclose existence). Backed by `POST /api/v1/searches/status`. The intake success screen now points new clients here directly.

### Recently Shipped (2026-04-29)
- **Stickier status page (v1.1)** — the public status response now also returns `progress_percent`, `next_milestone_label`, `last_activity_at`, and `last_activity_summary`. The page surfaces the next milestone after the phase tracker, shows a "Latest update" card sourced from a redacted whitelist of `search_activities` types (`status_change`, `candidate_added`, `presentation_sent`, `interview_scheduled`, `client_meeting`), remembers the client's email locally so refresh + return visits don't require retyping, and exposes a manual Refresh button. Each Janet-driven activity is now a reason for a return visit.
- **Build hygiene** — `/health` now returns `uptime_seconds`; the broken `health.test.ts` was rewritten to match the actual handler contract (status `'healthy'`/`'degraded'`, services block); `services/api/package.json` gained `lint` and `test` scripts so the PR Tests workflow doesn't silently no-op (integration tests run only when `API_URL` is set).

### Recently Shipped (2026-04-30)
- **Status-page activity timeline (v1.2)** — `POST /api/v1/searches/status` now returns `recent_activities` (up to 5 client-visible items, same redacted whitelist) instead of just one headline update. The status page renders the additional items as a small dated timeline below the "Latest update" card. The more often Janet logs an advancement, the richer each return visit feels.
- **Days-in-phase pacing hint** — Status response includes `days_in_phase` (computed from `status_changed_at` for progressing phases only). Status page surfaces it under the progress bar as "In this phase for N days" — an honest pacing signal that lets clients self-anchor without exposing pipeline internals.
- **Canonical `status_url` in intake response** — `POST /api/v1/intake` now returns `status_url` (e.g. `https://askknock.com/status?ref=KNK-2026-001`), one source of truth for the success screen, the planned welcome email, and the planned status-change reminder emails. Configurable via `PUBLIC_BASE_URL`.
- **Public-status endpoint test coverage** — added `services/api/src/__tests__/status.test.ts` with negative-path tests (unknown ref → 404, malformed email → 4xx/5xx, no enumeration: ref-mismatch and ref-missing return identical 404 shape). Protects the only auth-exempt search-data route from regressions that could leak existence.

### Recently Shipped (2026-05-01)
- **Auto-logged status transitions (v1.3 stickiness)** — `PATCH /api/v1/searches/:id` now writes a `search_activities` row whenever the `status` field actually changes (`'Search advanced: <from> → <to>'`, `performed_by='system'`, machine-readable `metadata.from`/`metadata.to`). The status page's timeline therefore self-populates as the pipeline advances — no longer dependent on Janet remembering to log each transition. Previously the timeline could read empty for weeks even on an active search; now it inherits every status change for free.
- **Phase explainer copy on status page** — each phase has a one-line plain-English description (e.g. "Actively researching candidates against your school's profile — most slates take 2–4 weeks to assemble"). Renders below the phase label. Solves the empty-state problem on early-stage searches where `search_activities` may not yet have rows: clients now always see something meaningful, not just a phase name. Pure frontend, no API change.
- **Dynamic tab title on status page** — when a search loads, the browser tab title becomes `KNK-2026-001 · Sourcing | Knock` (instead of the static "Search Status | Knock"). Pinned/duplicated tabs become legible reminders of where each search stands — a small but compounding stickiness primitive for clients who keep the page open across the day.
- **`Cache-Control: no-store, private` on `POST /api/v1/searches/status`** — personalized search data must never sit in shared/CDN/browser caches. Test coverage added: `Cache-Control` must include `no-store` + `private` on success and must never be `public`. Defensive header that complements the existing 404-on-mismatch contract.

### Recently Shipped (2026-05-02)
- **Auto-logged `candidate_added` activity (v1.4 stickiness)** — `POST /api/v1/searches/:id/candidates` now writes a redacted `search_activities` row (`'Candidate added to pipeline'`, `performed_by='system'`, `related_person_id` set) on every true insert. Detects insert-vs-upsert via the Postgres `xmax = 0` trick so re-PATCH-ing an existing candidate does not double-count. The public status timeline now self-populates as Janet sources candidates — closing roadmap item #5 for the `candidate_added` activity type.
- **Auto-logged `presentation_sent` activity (v1.4 stickiness)** — `PATCH /api/v1/searches/:id/candidates/:cid` now writes a redacted `search_activities` row (`'Candidate presented to committee'`) when a candidate transitions *into* `'presented'` status (idempotent — no log when already presented). Same redaction discipline as `candidate_added`: the description string is identical to what the public endpoint surfaces, so PII can never leak. Closes roadmap item #5 for `presentation_sent`.
- **Status-page background auto-refresh** — the status page now polls `POST /api/v1/searches/status` every 3 minutes while the tab is visible, and re-fetches immediately when the tab regains focus (Page Visibility API). With v1.3 + v1.4 auto-logging in place, the timeline genuinely updates throughout the day — turning the open tab from a one-shot lookup into a live dashboard. Polling is paused on backgrounded tabs to avoid wasted requests, and silently swallows failures so the manual Refresh button remains the recoverable fallback. A small "Auto-refreshes every 3 min while this tab is open" hint is shown next to the Refresh button so the behavior is discoverable.

### Immediate Priority
1. **Dan rates candidates** via /assess tool — until knock_rating is populated, matching can't distinguish quality
2. **Alternative email pattern testing** — flast, firstlast for the 1,484 schools where first.last was rejected
3. **Board member email enrichment** — once board emails exist, the board-segment newsletter lists will populate
4. **Status-page email reminders** — when a search's status changes, send the client a one-line "your search just moved to X — see details at askknock.com/status?ref=…" email. Closes the loop on the new status surface. The intake response exposes a canonical `status_url` field — reuse that exact string in the email body so the link, the success screen, and the reminder all agree. **The auto-logged status_change row from v1.3 is the natural trigger** — a single new cron/listener can transform "new system-authored status_change activity" into an outbound email without any new business logic. The same trigger pattern now also fires for `candidate_added` and `presentation_sent` — opening up "new candidate added to your pipeline" / "candidate just presented" reminder emails as natural extensions.
5. **Remaining client-visible activity types** — `status_change`, `candidate_added`, and `presentation_sent` are now auto-logged. The two remaining client-visible types — `interview_scheduled` and `client_meeting` — still rely on Janet writing rows. They are stickier still (each is a concrete forthcoming touchpoint the client will see on the timeline) and should follow the same v1.3/v1.4 pattern once the API surfaces them as first-class write paths.

### Short-term (Weeks)
5. **Outreach automation** — Janet sends first-touch emails to candidates for active searches
6. **Authenticated client portal v1** — extend status page with named-finalist cards, redacted committee notes, and a place for the client to leave reactions (graduated from the email-verified status lookup)
7. **LLM enrichment at scale** — Increase batch sizes, add cost tracking

### Medium-term (Months)
8. **LinkedIn integration** — Automated profile monitoring for career changes
9. **CRM features** — Full client relationship management
10. **Billing integration** — Invoice generation via Stripe or similar
11. **Multi-consultant** — Support for multiple search consultants beyond Dan

### Long-term
12. **Predictive transition model** — ML-based HOS transition prediction from signals
13. **Candidate self-service** — Candidates can update their own profiles
14. **Market analytics** — Public-facing industry reports to drive inbound

---

## 17. Environment Variables

See `.env.example` for the full list. Critical ones:
- `POSTGRES_PASSWORD` — Database password (contains +/= chars, needs URL encoding)
- `ANTHROPIC_API_KEY` — Claude API key (used by OpenClaw and enrichment scripts)
- `TELEGRAM_BOT_TOKEN` — Janet's Telegram bot token
- `OPENCLAW_TOKEN` — Gateway access token
- `MEILI_MASTER_KEY` — Meilisearch admin key

The working DATABASE_URL (with URL-encoded password) is stored at:
`/opt/knock/services/association-scrapers/.db_url`

---

## 18. Development Guide

### Local Setup
```bash
git clone https://github.com/dbhurley/knock.git
cd knock
cp .env.example .env  # Fill in secrets
docker compose up -d  # Start PostgreSQL, Redis, Meilisearch, API, Caddy
npm install           # Root workspace deps
bash db/scripts/migrate.sh  # Run all migrations
```

### Adding a New Migration
```bash
# Create numbered SQL file
touch db/migrations/015_whatever.sql
# Apply to production
ssh root@157.245.246.123
docker exec -i knock-postgres psql -U knock_admin -d knock < db/migrations/015_whatever.sql
```

### Adding a New Enrichment Script
```bash
# Write script in scripts/
# Create a run-*.sh wrapper
# Add to crontab on the server
# Commit and push — CI will deploy
```

### Adding a Janet Skill
1. Create YAML in `openclaw/skills/`
2. Copy to `/root/.openclaw/workspace/skills/` on server
3. Restart: `systemctl restart openclaw`

### Adding an MCP Tool to Janet
1. Edit `/root/.openclaw/mcp-servers/knock-api/server.mjs` (or create new MCP server)
2. Register in `/root/.openclaw/openclaw.json` under `mcp.servers`
3. Install deps: `cd /root/.openclaw/mcp-servers/<name> && npm install`
4. Restart: `systemctl restart openclaw`

---

*This document is the single source of truth for agents working on the Knock platform. When in doubt, query the database or SSH into the server — the code and data are the ultimate authority.*

---

## Claude Code Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Bias toward caution over speed.

### Think Before Coding
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — do not pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what is confusing. Ask.

### Simplicity First
- No features beyond what was asked.
- No abstractions for single-use code.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

### Surgical Changes
- Do not "improve" adjacent code, comments, or formatting.
- Do not refactor things that are not broken.
- Match existing style, even if you would do it differently.
- Every changed line should trace directly to the user's request.

### Goal-Driven Execution
- Transform tasks into verifiable goals with success criteria.
- For multi-step tasks, state a brief plan with verification checkpoints.
- Strong success criteria enable independent work. Weak criteria require constant clarification.
