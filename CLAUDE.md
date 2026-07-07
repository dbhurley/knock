# CLAUDE.md — Knock Executive Search Platform

> Complete system documentation for AI agents working on this codebase.
> Last updated: 2026-07-07

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
POST   /api/v1/searches/status            # Public client-facing status lookup (search_number + contact_email, no API key) — returns phase + canonical phase_explainer, progress % (now intra-phase aware: smooth day-to-day motion within a phase, not just at boundaries), next milestone + next_phase_explainer + next_phase_duration_typical (preview of the upcoming phase: a sentence + a typical-day range, so the page reads as a guided journey rather than a current-step indicator), last activity, activity_count_last_7d + activity_count_prev_7d (the previous 7-day window, days [-14, -7) — gives the status page a real week-over-week trend signal) + velocity_trend ('accelerating' | 'steady' | 'cooling' | 'quiet', server-derived from the week-over-week delta with a ±2 dead-band so day-to-day noise doesn't fire false trends) + is_ramping_up (canonical boolean — true on a progressing search whose previous 7-day window was empty but whose current one has activity; the precise "pipeline came alive this week" condition the status page uses to swap the velocity chip's "up from 0" for the friendlier "ramping up" copy, previously derived client-side from the raw prev-window count — and broader than velocity_trend === 'accelerating', since a first week with a single update lands the trend on 'steady' yet is still genuinely a ramp from quiet; false in terminal/non-progressing states and whenever there was prior-week activity, so a mid-engagement resume-after-quiet reads through the ordinary velocity_trend rather than a fresh-start ramp; lets the planned reminder email/PDF open a first-activity note off the same flag the chip uses) + activity_count_total (cumulative engagement-depth counter that monotonically increases across the whole search) + activity_breakdown (cumulative per-PUBLIC_ACTIVITY_TYPES counts, keyed by activity_type — drives the "Engagement at a glance" pill strip on the status page) + days_since_last_activity (exact recency anchor that pairs with the weekly count: "5 updates this week · latest 2 days ago") + weeks_since_last_activity (the canonical days→weeks rounding of days_since_last_activity via the shared daysToWeeks() helper — the recency anchor reads "latest ~4 weeks ago" once the latest update is a fortnight or more old, so a long-quiet/post-placement search scans better than a raw day count; null under a fortnight or when there's no public activity yet, mirroring days_since_last_activity), is_stalled pacing flag, phase_duration_typical (min/max days for current phase) + current_phase_on_pace (canonical boolean — the positive companion to is_stalled and the per-phase on_pace flag on completed phase_history entries: true when the current progressing phase's days_in_phase is at or within its typical-max benchmark, false once it slips past, null for terminal/non-progressing/placed phases or any phase without a typical duration; drives the gold "on pace" tag on the status page's current-phase pacing line and lets the reminder email/PDF quote "Sourcing is on pace — 18 of a typical 14–28 days" without re-deriving the benchmark) + phase_percent (canonical within-current-phase completion percent, 0–100 integer — the intra-phase fraction computeProgressPercent already blends into the whole-journey bar (days_in_phase against the phase's typical-max), surfaced on its own so a consumer can answer "how far through *this* phase am I?", a distinct signal from progress_percent (the whole 8-phase journey) and the anchorless days_in_phase; clamped to [0,100] so an over-typical phase caps at 100; drives the "· ~64% in" segment folded into the status page's current-phase pacing parenthetical and lets the reminder email/PDF quote the same percent; null in the same states as current_phase_on_pace — terminal/non-progressing/placed phases or any phase without a typical duration), estimated_completion_window (earliest/latest ISO dates summed from remaining typical phase durations) + estimated_days_remaining (the canonical { min_days, max_days } integer range those same dates are derived from, produced by the same computeCompletionWindow() call so they can never drift — the status page renders "(about 6–10 weeks out)" and the reminder email/PDF can quote the same integers) + estimated_weeks_remaining (the canonical { min_weeks, max_weeks } pair the page actually renders as "(about 6–10 weeks out)" — the same horizon pre-rounded to weeks so the days→weeks conversion that previously lived only in the frontend's fmtSpan() becomes one source of truth; rounding mirrors fmtSpan exactly, null when the window is null or under a fortnight where the page shows days), placed_at + placement_followup_until + placement_followup_days_remaining + placement_followup_weeks_remaining (the canonical days→weeks rounding of placement_followup_days_remaining via the shared daysToWeeks() helper — the placement card reads "~11 weeks remaining" while more than a fortnight of the 90-day window is left and switches back to the exact day countdown inside the final fortnight; null unless placed or inside the final fortnight) + placement_age_days (90-day post-placement follow-up window — populated only on placed status; placement_age_days is the canonical server-computed days-since-placement, the post-placement companion to engagement_age_days, so the status page's "Placed · 14 days ago" tag and the planned reminder email/PDF quote one source of truth) + placement_age_weeks (the canonical days→weeks rounding of placement_age_days via the shared daysToWeeks() helper — the placement card's age tag reads "Placed · ~11 weeks ago" once the placement is a fortnight or more old, so the card scans better across the 90-day follow-up window; null unless placed or inside the first fortnight where the page shows exact days), phase_history (ordered (phase, label, entered_at, duration_days, typical_min_days, typical_max_days, on_pace) array — one entry per phase the search has been in, with the opening phase seeded from searches.created_at and the rest sourced from status_change rows; duplicates collapse to first-arrival; label is the canonical human phase name from PUBLIC_STATUS_PHASES so the reminder email / PDF can quote dated milestones without re-deriving it; duration_days is the actual elapsed days a completed phase ran, null for the current/last phase; typical_min_days/typical_max_days are the canonical pace benchmark the entry's on_pace verdict was measured against (from PUBLIC_STATUS_TYPICAL_DURATION, null for phases with no typical duration) — surfacing it makes each entry self-describing so the reminder email/PDF can quote "12 of a typical 14–28 days" straight off phase_history without a second lookup keyed by phase code; on_pace is a canonical boolean — true when a completed phase's duration_days landed at or within that phase's typical-max benchmark, null for the current/last phase or any phase without a typical duration, so the status page's "on pace" tag and the planned reminder email/PDF quote one server-computed value instead of regex-parsing the benchmark string) + latest_completed_phase (canonical summary of the most-recently-completed phase — the last phase_history entry with a non-null duration_days, carrying that entry's phase/label/entered_at/duration_days/typical_min_days/typical_max_days/on_pace; the single-latest-completion lookup the reminder email most wants ("your search just moved to Sourcing — Scoping wrapped on pace · 8 days") so it doesn't re-scan phase_history, and the source for the status page's always-visible "Just wrapped: Scoping · 8 days · on pace" glance under the pacing line; null until at least one phase has completed), next_milestone_eta (single ISO date for when the next phase is expected to begin: now + remaining typical-max of the current phase; null for terminal phases — the near end of the same calc estimated_completion_window sums to its far end) + days_until_next_milestone (canonical server-computed integer companion to next_milestone_eta: the count of typical-max days still remaining in the current phase, floored at 0; the status page renders it as a glanceable "in ~5 days" countdown that decrements daily and reads as "any day now" at 0; null whenever next_milestone_eta is null) + weeks_until_next_milestone (the canonical days→weeks rounding of days_until_next_milestone — the same Math.max(1, Math.round(days / 7)) the status page applies inline to render "(in ~3 weeks)" once the countdown is at or past a fortnight; surfacing it makes that last client-side days→weeks read on the page one source of truth so the reminder email/PDF can quote "the next phase is about 3 weeks out" off the same integer, mirroring estimated_weeks_remaining and weeks_until_target_start; null whenever the countdown is null or under a fortnight where the page shows the exact days), engagement_age_days (canonical server-computed days since searches.created_at — one source of truth for the status page's "(N days ago)" tag and the planned reminder email / PDF) + engagement_age_weeks (the canonical days→weeks rounding of engagement_age_days via the shared daysToWeeks() helper — the "Search opened" tag reads "(~11 weeks ago)" once the engagement is at or past a fortnight, so long 10–16-week engagements scan better than a raw day count; null under a fortnight where the page shows exact days, mirroring estimated_weeks_remaining / weeks_until_target_start / weeks_until_next_milestone) + phases_completed (canonical server-computed count of finished phases — placed counts the whole 8-phase journey, an in-flight progressing phase counts the steps strictly before the current one, null for non-progressing/negative-terminal states; one source of truth for the status page's "3 of 8 phases complete" journey summary and the planned reminder email / PDF, same rationale as engagement_age_days) + phases_on_pace (canonical server-computed count of *completed* phases that landed on pace — the positive aggregate companion to phases_completed and the per-entry on_pace flag in phase_history: the number of finished phases whose actual duration_days was at or within their typical-max benchmark; null in the same non-progressing/negative-terminal states as phases_completed; drives the "· all on pace" / "· 2 of 3 on pace" suffix on the status page's collapsed journey summary so a return visitor gets a fresh positive glance without expanding the section, and lets the reminder email / PDF quote "3 of 3 completed phases on pace" without re-deriving it from phase_history) + phases_benchmarked (canonical server-computed count of *benchmarkable* completed phases — the denominator the "N of M on pace" tally is measured against, phases_on_pace being the numerator: the number of completed phases whose phase_history entry carries a non-null on_pace, i.e. has both an actual duration and a typical benchmark; equals phases_completed for an in-flight search but correctly excludes the un-benchmarkable placed terminal on a successful placement so a flawless run reads "all on pace" not "7 of 8 on pace" — the v1.35 concern, now one source of truth server-side instead of a client-side phase_history filter; null in the same non-progressing/negative-terminal states as phases_on_pace) + all_phases_on_pace (canonical boolean — the single-boolean form of the collapsed journey summary's "· all on pace" suffix: true when phases_on_pace === phases_benchmarked with at least one benchmarkable completed phase, so every completed phase landed within its typical-max benchmark; null — not false — whenever there's nothing benchmarkable to judge yet (phases_benchmarked null or 0, i.e. a non-forward state or a search still in its opening phase), so a brand-new search never reads a misleading "all on pace"; lets the status page and the planned reminder email/PDF quote the "all on pace" verdict off one boolean instead of re-comparing the numerator and denominator, positive-only by design like current_phase_on_pace). status_url (canonical deep-link back to the status surface — PUBLIC_BASE_URL + /status?ref=…, the same string POST /api/v1/intake returns, so the success screen, the page, and the planned reminder email all quote one source of truth instead of each rebuilding it; success shape only, never on 404) + days_until_target_start (canonical server-computed integer days from now to the client's target_start_date — positive while ahead, negative once passed; the status page's "(3 weeks away)" / "(4 days past target)" countdown reads this instead of computing it client-side, so the page and the planned reminder email/PDF quote one source of truth; null when there's no target date or the search is in a terminal state placed/cancelled/closed_no_fill, where the page already suppresses the countdown) + weeks_until_target_start (the canonical days→weeks rounding of days_until_target_start — the same Math.round(days / 7) the status page applies inline when the target is more than a month out and renders "(~6 weeks away)"; surfacing it makes that last client-side days→weeks read on the page one source of truth so the reminder email/PDF can quote "your target start date is about 6 weeks out" off the same integer, mirroring estimated_weeks_remaining; null whenever the page shows days rather than weeks — no target, terminal state, target within a month (days ≤ 30), or already past) + phases_remaining (the forward-looking complement to phases_completed — the canonical count of phases the search has not yet finished, defined so phases_completed + phases_remaining === phase_total always; includes the current in-flight phase, zero once placed, null in the same non-progressing/negative-terminal states as phases_completed; drives the always-visible next-milestone line's forward "· N phases to go" count on the status page and lets the reminder email/PDF quote "5 phases still ahead" without re-deriving phase_total − phases_completed). Cache-Control: no-store, private on every response shape including 404.
GET    /api/v1/searches/:id/candidates    # Candidate pipeline
POST   /api/v1/searches/:id/candidates    # Add candidate
PATCH  /api/v1/searches/:id/candidates/:cid # Update status
POST   /api/v1/searches/:id/activities    # Manual activity log (auth required) — currently whitelisted to client_meeting; description surfaces verbatim on public status timeline

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
│   ├── status.html             # Client search-status surface (PWA-installable; click-to-copy ref pill, live "Updated X ago" heartbeat, dated-milestone journey overview, "Email Janet" pre-filled mailto (subject + body carrying the canonical status link & ref), canonical days_until_target_start countdown, Google + .ics calendar links, #journey-details deep-link auto-expand, week-over-week velocity-trend chip, "Engagement at a glance" cumulative breakdown strip, hover-tooltip absolute timestamps on every relative-time string, durational journey archive (actual days-per-phase, with an "on pace" tag on completed phases that landed within their typical-max benchmark), gold "on pace" tag on the current-phase pacing line (sourced from the canonical current_phase_on_pace API field, with a screen-reader-legible space before the tag), within-phase completion "· ~N% in" segment folded into the pacing parenthetical ("typically 14–28 days · ~64% in", from the canonical phase_percent API field), always-visible "Just wrapped: Scoping · 8 days · on pace" glance under the pacing line (from the canonical latest_completed_phase API field — the single latest completion surfaced inline without expanding the journey archive), near-term next-phase ETA with glanceable "in ~N days / in ~N weeks" countdown (weeks past a fortnight, now sourced from the canonical weeks_until_next_milestone API field) + "any day now" copy for overdue phases, forward "· N phases to go" count on the always-visible next-milestone line (from the canonical phases_remaining API field), post-placement card with a "Placed · N days / ~N weeks ago" tag (weeks past a fortnight, from the canonical placement_age_weeks API field) and a canonical placement_followup_weeks_remaining "~N weeks remaining" follow-up countdown (weeks past a fortnight, exact days inside the final fortnight), recency anchor on the quiet-week velocity row in weeks past a fortnight (from the canonical weeks_since_last_activity API field), velocity-trend chip suppressed in terminal states (placed/cancelled/closed_no_fill), engagement-age "Search opened … (~N weeks ago)" tag in weeks past a fortnight (from the canonical engagement_age_weeks API field), "ramping up" velocity chip on a search's first active week (now sourced from the canonical is_ramping_up API field), "(about N weeks out)" relative placement horizon, ARIA progressbar for screen readers, dynamic "N of 8 phases complete" journey summary (now sourced from the canonical phases_completed API field, with an "· all on pace" / "· N of M on pace" pace suffix from the canonical phases_on_pace field and a forward "· N–M weeks to go" placement horizon from the canonical estimated_weeks_remaining field), canonical weeks_until_target_start rounding on the target-start countdown's "(~N weeks away)" branch, step-count in the pinned-tab title ("KNK-2026-001 · Sourcing (3/8)"), unread-count prefix in the pinned-tab title when there are updates since the last visit ("(2) KNK-2026-001 · Sourcing (3/8)"), last-update recency anchor on the quiet-week velocity row, screen-reader aria-labels on the velocity-trend chip and the "Engagement at a glance" breakdown strip)
│   ├── assess.html             # Candidate rating tool
│   ├── site.webmanifest        # PWA manifest for status page (Add to Home Screen)
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

### Recently Shipped (2026-07-07)
- **Canonical `is_ramping_up` flag (v1.40 stickiness)** — `POST /api/v1/searches/status` now also returns `is_ramping_up`, a server-computed boolean that is `true` on a progressing search whose previous 7-day activity window was empty (`activity_count_prev_7d === 0`) but whose current one has activity (`activity_count_last_7d > 0`). It's the exact "the pipeline just came alive this week" condition the status page uses to swap the velocity chip's awkward "up from 0" for the friendlier "ramping up" copy — a read the page previously derived client-side from the raw prev-window count inside its `accelerating` branch. That local check was subtly narrower than the real signal: a first active week with a single update lands `velocity_trend` on `'steady'` (delta 1 falls inside the ±2 dead-band) yet is still genuinely a ramp from quiet, so the chip's `prev === 0` test only fired when the week also happened to trip `'accelerating'`. Surfacing the boolean makes that read one source of truth (same rationale as `current_phase_on_pace` (v1.24) and `velocity_trend` (v1.17)): the planned status-change reminder email / PDF (roadmap #4) can open a first-activity note ("your search is ramping up — first updates logged this week") off the same flag the chip uses instead of re-deriving it from the two 7-day counts. `false` in terminal/non-progressing states and whenever there was prior-week activity, so a mid-engagement resume-after-quiet reads through the ordinary `velocity_trend` rather than a misleading fresh-start ramp. The status page prefers the canonical field and falls back to the local `prev === 0` check only on older API versions. Covered by a new negative-path 404 test: the flag is keyed by the search's activity tempo, so it must never leak on the unauthenticated path — observing it would let an anonymous caller infer both that the search exists AND that it just started seeing activity.
- **Terminal-status arrays hoisted to two named constants on the status page (v1.40 hygiene)** — the status page open-coded the same terminal-state array literal in five render branches: `['placed', 'cancelled', 'closed_no_fill']` twice (the velocity-chip suppression and the journey terminal check) and `['cancelled', 'closed_no_fill']` three times (the step-count suppression, the progress-bar hide, and the journey "you are here" pin gate). They now all reference two module-level constants — `TERMINAL_STATUSES` (every concluded state) and `NEGATIVE_TERMINAL_STATUSES` (ended without a placement) — defined once beside `PHASE_EXPLAINERS`, so a future terminal state added to the model updates every gate at once instead of leaving a stale literal behind. Mirrors the API's module-level `TARGET_TERMINAL_STATUSES` hoist (v1.35 hygiene). Pure refactor — byte-identical behavior, all script blocks parse clean.

### Recently Shipped (2026-07-06)
- **Canonical `phase_percent` within-phase completion (v1.39 stickiness)** — `POST /api/v1/searches/status` now also returns `phase_percent`, the within-current-phase completion percent as a 0–100 integer: `days_in_phase` measured against the current phase's typical-max duration, clamped to `[0, 100]`. It's the intra-phase fraction `computeProgressPercent()` already blends into the whole-journey progress bar, surfaced on its own so a consumer can answer the one question neither existing field does — "how far through *this* phase am I?" `progress_percent` is the whole 8-phase journey (a return visitor sees it barely move within a single 2–4-week phase), and `days_in_phase` is anchorless without dividing by the typical max; `phase_percent` is the honest per-phase glance that walks forward every day inside a phase. The status page folds it into the current-phase pacing parenthetical — "In this phase for 18 days (typically 14–28 days · ~64% in)" — so the anchorless day count now reads as a glanceable proportion (prefers the canonical field; the segment simply doesn't append on older API versions or terminal/non-progressing phases). Same one-source-of-truth rationale as `current_phase_on_pace` (v1.24): the planned reminder email / PDF (roadmap #4) can quote "about 64% through the current phase" off the same integer the page renders. `null` in exactly the same states as `current_phase_on_pace` — terminal/non-progressing/`placed` phases or any phase without a typical duration — so a paused or closed search never reads a misleading percent. Covered by a new negative-path 404 test alongside `current_phase_on_pace` / `phase_duration_typical`: the integer is keyed by the current phase, so it must never leak on the unauthenticated path.
- **`computeProgressPercent()` reads `PHASE_TOTAL`, not a hardcoded `8` (v1.39 hygiene)** — the v1.31 `PHASE_TOTAL = PUBLIC_STATUS_FORWARD.length` extraction replaced the hardcoded journey length in the response's `phase_total` and the `phases_completed` / `phases_remaining` math, but `computeProgressPercent()` still divided by a literal `8` in both its intra-phase and terminal branches — the exact stale-hardcoded-`8` the extraction was meant to eliminate, just missed in this one function. Both denominators now derive from `PHASE_TOTAL`, so a future phase added to `PUBLIC_STATUS_FORWARD` updates the progress-bar math along with every other downstream count instead of leaving this function behind. Pure refactor — byte-identical output (the forward list is currently 8 long), covered by the existing status-endpoint tests. Same one-source-of-truth rationale as the original v1.31 extraction.

### Recently Shipped (2026-07-05)
- **Canonical `latest_completed_phase` object + always-visible "just wrapped" glance (v1.38 stickiness)** — `POST /api/v1/searches/status` now also returns `latest_completed_phase`, a canonical summary of the most-recently-completed phase: the last `phase_history` entry that has actually finished (a non-null `duration_days` — the current/last phase is still running and is skipped), carrying the same self-describing fields as its `phase_history` entry (`phase`, `label`, `entered_at`, `duration_days`, `typical_min_days`, `typical_max_days`, `on_pace`). It's the single entry the planned status-change reminder email (roadmap #4) most wants to quote: when a search advances, the natural line is "your search just moved to *Sourcing* — *Scoping* wrapped on pace · 8 days", which otherwise forces the consumer to re-scan `phase_history` for the last entry carrying a duration. Surfacing it makes that read one source of truth — same rationale as `phases_completed` (v1.21) / `all_phases_on_pace` (v1.37) — where the v1.23 `on_pace` and v1.34 `typical_*` benchmark fields per `phase_history` entry gave the pace *tally* its canonical form, this canonicalizes the *single-latest-completion* lookup those same consumers need most. The status page now renders it inline as an always-visible "Just wrapped: **Scoping** · 8 days · on pace" line under the current-phase pacing (prefers the canonical field, falls back to the last completed `phase_history` entry on older API versions): the full durational archive still lives in the collapsed journey `<details>`, but this surfaces just the single latest completion so a return visitor gets a fresh, concrete backward glance without expanding anything. `null` until at least one phase has completed (a search still in its opening phase has no finished phase yet). Nested-shape parity with `phase_history`, so its existing negative-path 404 test already covers the leak surface; a dedicated `latest_completed_phase` 404 assertion was also added, since observing it would let an anonymous caller infer both that the search exists AND where it is in the journey.
- **Current-phase "on pace" tag is screen-reader legible (v1.38 a11y)** — the gold "on pace" tag appended to the current-phase pacing line (v1.24) was separated from the day count only by a CSS `margin-left`, so a screen reader announced "…days)on pace" as one run-on token. A real space text node is now inserted before the tag (on both the current-phase pacing line and the new "just wrapped" glance) so assistive tech announces "…days) on pace" as two distinct tokens. Same v1.20/v1.26 accessibility rationale as the progress-bar and velocity-chip ARIA passes — the status page is the one Knock surface clients return to unprompted, so every committee member should read it, not most of them. Pure frontend, no API change.

### Recently Shipped (2026-07-04)
- **Canonical `all_phases_on_pace` boolean (v1.37 stickiness)** — `POST /api/v1/searches/status` now also returns `all_phases_on_pace`, the single-boolean form of the collapsed journey summary's "· all on pace" suffix: `true` when `phases_on_pace === phases_benchmarked` with at least one benchmarkable completed phase (every completed phase landed within its typical-max benchmark), otherwise `false`. The status page derived this celebration verdict client-side by comparing the v1.26 `phases_on_pace` numerator against the v1.36 `phases_benchmarked` denominator (`phases_on_pace >= benchmarkedDone`); surfacing the boolean server-side makes that positive signal one source of truth alongside the two integers it's derived from — the exact one-source-of-truth completion of the v1.35/v1.36 "all on pace" work (which canonicalized the numerator and denominator but left the *verdict* a client-side comparison). The planned status-change reminder email / PDF (roadmap #4) can now quote "every completed phase is on pace" off one boolean instead of re-comparing the pair. `null` — not `false` — whenever there's nothing benchmarkable to judge yet (`phases_benchmarked` null or 0, i.e. a non-forward state or a search still in its opening phase), so a brand-new search never reads a misleading "all on pace" before any phase has actually completed; positive-only by design, mirroring `current_phase_on_pace` and the archive's on-pace tags. The status page now prefers the canonical field (falling back to the integer comparison on older API versions). Covered by a new negative-path 404 test alongside `phases_on_pace` / `phases_benchmarked` — the verdict is keyed by how far the search has advanced and how it tracked against benchmark, so it must never leak on the unauthenticated path.
- **`isForwardPhase()` predicate for the phase-count guards (v1.37 hygiene)** — the three phase-*count* fields (`phases_completed`'s in-flight branch, `phases_on_pace`, and `phases_benchmarked`) each open-coded the same `PUBLIC_STATUS_FORWARD.includes(row.status)` guard — the "on a forward phase, including the terminal `placed`" test, distinct from the existing `isProgressingPhase()`'s "forward *excluding* `placed`" test that gates the forward-looking fields. They now all call one `isForwardPhase(status)` helper defined next to `isProgressingPhase()`, so the "forward incl. placed" vs "progressing excl. placed" distinction is explicit and can't be confused at a call site. Pure refactor — byte-identical output, covered by the existing status-endpoint tests. Same one-source-of-truth rationale as the v1.34 `isProgressingPhase()` and v1.32 `daysToWeeks()` extractions.
- **Single-pass `phases_on_pace` / `phases_benchmarked` tally (v1.37 hygiene)** — the two pace-tally counts were each a separate `phase_history.filter(...).length` scan (`on_pace === true` for the numerator, `on_pace !== null` for the denominator). They're now folded into one loop over `phase_history`: because an `on_pace === true` entry is always also `on_pace !== null`, computing both counters in a single pass guarantees the numerator can never exceed the denominator (`phases_on_pace <= phases_benchmarked` by construction) and scans the array once instead of twice. Pure efficiency/consistency refactor — no response-shape change, covered by the existing status-endpoint tests. Same one-scan hygiene as v1.25's merged activity `GROUP BY`.

### Recently Shipped (2026-07-03)
- **Canonical `phases_benchmarked` count (v1.36 stickiness)** — `POST /api/v1/searches/status` now also returns `phases_benchmarked`, the canonical count of *benchmarkable* completed phases: the denominator the collapsed journey summary's "N of M on pace" pace tally is measured against (`phases_on_pace` being the numerator). A completed phase is benchmarkable when its `phase_history` entry carries a non-null `on_pace` — i.e. it has both an actual `duration_days` and a typical-duration benchmark to compare against. The v1.35 fix established that this denominator must be the benchmarkable count, not `phases_completed` (the two differ only on a successful placement, where the terminal `placed` phase has no typical duration and so can never be "on pace" — using `phases_completed` would understate a flawless run as "7 of 8 on pace" instead of "all on pace" on the exact celebration moment). But v1.35 shipped that count as a client-side `phase_history.filter(...)` derivation — the exact re-derivation the per-entry `on_pace` (v1.23) and the `phases_on_pace` aggregate (v1.26) were surfaced to eliminate. Surfacing it server-side makes the pace tally's *denominator* one source of truth alongside its numerator: the status page now prefers the canonical field (falling back to the local filter, then to `phases_completed`, on older API versions), and the planned status-change reminder email / PDF (roadmap #4) can quote "3 of 3 completed phases on pace" with the same denominator the page shows instead of re-deriving it from `phase_history`. Null in exactly the same non-progressing/negative-terminal states as `phases_on_pace` / `phases_completed` (`on_hold`, `cancelled`, `closed_no_fill`). Covered by a new negative-path 404 test alongside `phases_on_pace` — the count is keyed by how far the search has advanced, so it must never leak on the unauthenticated path.

### Recently Shipped (2026-07-02)
- **"All on pace" reads correctly on a successful placement (v1.35 stickiness fix)** — the collapsed journey summary's pace tally ("· all on pace" / "· 2 of 3 on pace") used `phases_completed` as its denominator. That's correct for an in-flight search (every completed progressing phase before the current one has a pace benchmark), but wrong the moment a search reaches `placed`: `phases_completed` counts the whole 8-phase journey, yet the terminal `placed` phase has no typical duration and so can never be "on pace" (its `phase_history` `on_pace` is null). A flawless run therefore read "**7 of 8 on pace**" instead of "**all on pace**" on the exact celebration moment — the same "don't render a misleading negative on the moment that matters most" concern as v1.33's terminal-state velocity-chip suppression and v1.11's hidden progress bar for negative-terminals. The denominator is now the count of *benchmarkable* completed phases (`phase_history` entries with a non-null `on_pace`), which equals `phases_completed` in the in-flight case and correctly excludes the un-benchmarkable `placed` terminal — so a fully-on-pace placement now reads "all on pace". Falls back to `phases_completed` when `phase_history` is absent (older API). Pure frontend, no API change.
- **`TARGET_TERMINAL_STATUSES` hoisted to module scope (v1.35 hygiene)** — the status handler built the `new Set(['placed', 'cancelled', 'closed_no_fill'])` that gates the target-start countdown *inside* the request handler, re-allocating it on every status request even though the set is a fixed classification constant. It now lives at module level alongside `PUBLIC_ACTIVITY_TYPES` and the other status-classification constants, matching the codebase's convention that these live once at module scope. Pure refactor — byte-identical behavior, covered by the existing status-endpoint tests. Same hoist-the-constant hygiene as the v1.31 `PHASE_TOTAL` and v1.34 `isProgressingPhase()` extractions.
- **Negative-path 404 coverage for identity + phase fields (v1.35 hardening)** — the success shape's most directly-identifying fields — `position_title`, `school_name`, `school_location` (which name the actual client and role) and `phase_label` / `phase_step` / `next_milestone_label` (which reveal where the search sits in the journey) — had no dedicated 404-leak assertion; they relied only on the generic no-`data` check. Two new negative-path tests now assert each is absent on the unauthenticated 404 path, locking the no-enumeration contract for the identity and current-phase fields in CI the same way v1.34 did for `last_activity_at` / `search_urgency` and v1.25 did for the pipeline counts. Observing any of them would let an anonymous caller confirm a search exists and learn which school/role it is or how far along it is.

### Recently Shipped (2026-07-01)
- **Self-describing pace benchmark on each `phase_history` entry (v1.34 stickiness)** — each entry in the `phase_history` array returned by `POST /api/v1/searches/status` now also carries `typical_min_days` and `typical_max_days`: the canonical typical-duration benchmark its `on_pace` verdict (v1.23) was measured against (null for phases with no typical duration — the opening/terminal phases). Before this, a `phase_history` entry could say "Sourcing · 12 days · on pace" but a consumer couldn't render "12 of a typical 14–28 days" without a *second* lookup keyed by the raw phase code against `PUBLIC_STATUS_TYPICAL_DURATION` — the exact re-derivation the per-entry `label` (v1.22) and `on_pace` (v1.23) fields were surfaced to eliminate. Making the entry self-describing lets the planned status-change reminder email / PDF (roadmap #4) quote a fully-benchmarked dated milestone — "Sourcing ran Apr 22 → May 4 · 12 of a typical 14–28 days, on pace" — straight off `phase_history` with no keyed re-lookup. Pure API pre-pave (no page consumer needed — the journey archive already shows the benchmark on its own line and prefers the canonical `on_pace` flag; same pre-pave-only precedent as v1.30's `phases_remaining` and v1.22's `label`). Nested inside `phase_history`, so the existing negative-path 404 test for `phase_history` already covers the new sub-fields.
- **One `isProgressingPhase()` predicate for the "still in flight" test (v1.34 hygiene)** — the status handler open-coded the same `PUBLIC_STATUS_FORWARD.includes(row.status) && row.status !== 'placed'` predicate in four places (the `days_in_phase`, `is_stalled`, `current_phase_on_pace`, and next-milestone-ETA computations — every forward-looking field that only makes sense while the search is still moving toward a placement). They now all call one `isProgressingPhase(status)` helper, so a future phase-model change can't leave one of those fields using a subtly different notion of "still progressing". Pure refactor — byte-identical output, covered by the existing status-endpoint tests. Same one-source-of-truth rationale as the v1.32 `daysToWeeks()` and v1.31 `PHASE_TOTAL` extractions.
- **Negative-path 404 coverage for `last_activity_at` / `last_activity_summary` / `search_urgency` (v1.34 hardening)** — these three sensitive success-shape fields (the exact timestamp of the last update, a verbatim description of it, and the intake pacing enum) had no dedicated 404-leak assertion — they relied only on the generic no-`data` check. A new negative-path test now asserts each is absent on the unauthenticated 404 path, locking the no-enumeration contract for the recency/description fields in CI the same way v1.25 did for the pipeline counts and `recent_activities`. Observing any of them would let an anonymous caller infer that a search exists (and, for the activity fields, when it was last touched).

### Recently Shipped (2026-06-30)
- **Canonical `placement_age_weeks` rounding (v1.33 stickiness)** — `POST /api/v1/searches/status` now also returns `placement_age_weeks`, the canonical days→weeks rounding of v1.28's `placement_age_days`. The placement card's "Placed on Jun 14 · 14 days ago" tag was the one age display still locked to raw days after v1.32 took the engagement-age and follow-up countdowns to weeks — and the card stays live for the full 90-day follow-up window, where "(76 days ago)" scans worse than "(~11 weeks ago)". The headline now reads in weeks once the placement is at or past a fortnight, sourced from the canonical field (falling back to the same local rounding only on older API versions), and keeps exact days inside the first fortnight. Same days→weeks one-source-of-truth + fortnight-threshold rationale as `engagement_age_weeks` (v1.32) and the rest of the weeks family (all six now share the one `daysToWeeks()` helper): the planned post-placement reminder email / PDF (roadmap #4) can quote "your placement landed about 11 weeks ago" off the same integer the page renders. Null unless placed or inside the first fortnight. Covered by the existing placement-window negative-path 404 test (extended to assert the new field) — the integer would otherwise let an anonymous caller infer both that the search exists AND that it has reached the placed terminal.
- **Canonical `weeks_since_last_activity` rounding (v1.33 stickiness)** — `POST /api/v1/searches/status` now also returns `weeks_since_last_activity`, the canonical days→weeks rounding of v1.13's `days_since_last_activity`. The Activity row's recency anchor ("· latest N days ago") still rendered in raw days; on a long-quiet (but not stalled) or post-placement search "latest 30 days ago" scans worse than "latest ~4 weeks ago", out of step with the weeks-past-fortnight convention the engagement-age and placement-age tags already follow. The anchor now reads in weeks once the latest update is at or past a fortnight, sourced from the canonical field (falling back to local rounding only on older API versions), keeping exact days inside the first fortnight. Same one-source-of-truth + fortnight-threshold rationale as the rest of the weeks family (now seven fields through one `daysToWeeks()` helper): the planned reminder email / PDF (roadmap #4) can quote the same recency in weeks. Null under a fortnight and null when there's no public activity yet, mirroring `days_since_last_activity`. Covered by the existing recency negative-path 404 test (extended to assert the new field) — the integer would otherwise let an anonymous caller infer both that the search exists AND roughly when it was last touched.
- **Velocity-trend chip suppressed in terminal states (v1.33 polish)** — the week-over-week velocity-trend chip (v1.17) was hidden only when the search was quiet across both windows (`'quiet'`) or `is_stalled`. But `is_stalled` is false for terminal states, so a freshly `placed`/`cancelled`/`closed_no_fill` search could still render a "↓ down from 5" chip — activity naturally tapers once a search concludes, so on what's most often a successful placement that delta read as a downer rather than a signal of pipeline health. The chip is now also suppressed for the three terminal statuses, letting the placement-celebration card and the phase explainer carry the conclusion on their own. Same "don't render a misleading negative on the moment that matters most" rationale as v1.11's hidden progress bar for negative-terminals and v1.6's `on_hold` cleanup. Pure frontend, no API change.

### Recently Shipped (2026-06-29)
- **Canonical `engagement_age_weeks` rounding (v1.32 stickiness)** — `POST /api/v1/searches/status` now also returns `engagement_age_weeks`, the canonical days→weeks rounding of v1.18's `engagement_age_days`. The status page's "Search opened Apr 28, 2026 (11 days ago)" tag rendered the engagement length in raw days — fine early on, but the 10–16-week engagement is the stickiness window CLAUDE.md keeps returning to, and on a long-running search "(80 days ago)" scans worse than "(~11 weeks ago)". The tag now reads in weeks once the engagement is at or past a fortnight, sourced from the canonical field (falling back to the same local rounding only on older API versions). Same one-source-of-truth + fortnight-threshold rationale as `estimated_weeks_remaining` (v1.27), `weeks_until_target_start` (v1.30), and `weeks_until_next_milestone` (v1.31): the planned status-change reminder email / PDF (roadmap #4) can quote "your search has been running about 11 weeks" off the same integer the page renders. Null under a fortnight, where the page still shows the exact day count. Covered by a new negative-path 404 test — the integer is keyed to a real search and would otherwise let an anonymous caller infer both that the search exists AND how long it has been running.
- **Canonical `placement_followup_weeks_remaining` rounding (v1.32 stickiness)** — `POST /api/v1/searches/status` now also returns `placement_followup_weeks_remaining`, the canonical days→weeks rounding of the post-placement follow-up countdown (v1.12's `placement_followup_days_remaining`). The placement card stays live for the full 90-day post-placement window, where a two-digit "76 days remaining" scans worse than a glanceable "~11 weeks remaining". The card now reads in weeks while more than a fortnight of the window is left, and switches back to the exact day countdown inside the final fortnight where the precise number matters most. Prefers the canonical field, falls back to local rounding on older API versions. Same days→weeks one-source-of-truth rationale as `engagement_age_weeks` above: the planned post-placement reminder email / PDF (roadmap #4) can quote the same weeks the page shows. Null unless placed or inside the final fortnight. Covered by the existing placement-window negative-path 404 test (extended to assert the new field) — the integer would otherwise let an anonymous caller infer both that the search exists AND that it has reached the placed terminal.
- **One `daysToWeeks()` helper for every weeks rounding (v1.32 hygiene)** — the status handler open-coded the same `Math.max(1, Math.round(days / 7))` days→weeks conversion in five places (`estimated_weeks_remaining`, `weeks_until_next_milestone`, `weeks_until_target_start`, and the two new v1.32 fields). They now all call one `daysToWeeks()` helper, so the rounding lives in one place instead of five and a future tweak can't leave one weeks field rounding differently from the others. Pure refactor — byte-identical output (the floor-at-1 is a no-op everywhere the result was already ≥ 1, including the `weeks_until_target_start` branch that only fires when days > 30), covered by the existing status-endpoint tests. Same one-source-of-truth rationale as the v1.18 `statusUrlFor()` and v1.31 `PHASE_TOTAL` extractions.

### Recently Shipped (2026-06-28)
- **Canonical `weeks_until_next_milestone` rounding (v1.31 stickiness)** — `POST /api/v1/searches/status` now also returns `weeks_until_next_milestone`, the canonical days→weeks rounding of v1.19's `days_until_next_milestone`. The next-phase preview block's "Expected to begin around Jun 5 (in ~3 weeks)" countdown rendered its weeks via an inline `Math.max(1, Math.round(days / 7))` (added in v1.28) — and after v1.30 canonicalized the target-start days→weeks read, that was the *last* client-side days→weeks conversion left on the page. Surfacing the weeks integer makes it one source of truth, exactly as v1.27's `estimated_weeks_remaining` and v1.30's `weeks_until_target_start` did for the placement horizon and the target-start countdown: the planned status-change reminder email / PDF (roadmap #4) can quote "the next phase is about 3 weeks out" off the same integer the page renders. The page now prefers the canonical field and falls back to local rounding only on older API versions; rounding mirrors the frontend exactly so the two never disagree. Null whenever the page shows days rather than weeks — no countdown at all, or the next phase close in (`days < 14`, where the page renders the exact "(in ~N days)"). Covered by a new negative-path 404 test: the integer is keyed by the current phase and would otherwise let an anonymous caller infer both that the search exists AND its current phase.
- **Forward "· N phases to go" count on the always-visible next-milestone line (v1.31 stickiness)** — the status page's `phases_remaining` field (v1.30) shipped as a pure API pre-pave with no page consumer. The always-visible "→ Next: Screening interviews" line now appends a glanceable, shrinking forward count — "→ Next: Screening interviews · 5 phases to go" — sourced from the canonical `phases_remaining`. It's the always-visible companion to the collapsed journey summary's *backward* "3 of 8 phases complete" count (which a return visitor only sees on the card, not expanded): the next-milestone line a client reads on every visit now carries both *what's next* and *how much is left*. The segment includes the current in-flight phase and simply doesn't append in terminal/non-progressing states (where `phases_remaining` is null or zero), so a placed or paused search never reads a misleading "0 phases to go". Pure frontend, no API change.
- **One `PHASE_TOTAL` constant for the 8-phase count (v1.31 hygiene)** — the status handler hardcoded the journey length as a literal `8` in the response's `phase_total` and as `PUBLIC_STATUS_FORWARD.length` in the `phases_completed` / `phases_remaining` math. They're now all derived from one `PHASE_TOTAL = PUBLIC_STATUS_FORWARD.length` constant, so a future phase added to the forward-phase list updates `phase_total` and every downstream count at once instead of leaving a stale hardcoded `8` behind. Pure refactor — byte-identical output (the forward list is currently 8 long), covered by the existing status-endpoint tests. Same one-source-of-truth rationale as the v1.18 `statusUrlFor()` extraction.

### Recently Shipped (2026-06-27)
- **Canonical `weeks_until_target_start` rounding (v1.30 stickiness)** — `POST /api/v1/searches/status` now also returns `weeks_until_target_start`, the canonical days→weeks rounding of v1.29's `days_until_target_start`. When the target start date is more than a month out, the status page's countdown reads "(~6 weeks away)" — and the `Math.round(days / 7)` behind that was the *last* client-side days→weeks conversion left on the page after v1.29 canonicalized the raw day count. Surfacing the weeks integer makes it one source of truth, exactly as v1.27's `estimated_weeks_remaining` did for the placement horizon: the planned status-change reminder email / PDF (roadmap #4) can quote "your target start date is about 6 weeks out" off the same integer the page renders. The page now prefers the canonical field and falls back to local rounding only on older API versions. Null whenever the page shows days rather than weeks — no target date, terminal state, the target within a month (`days ≤ 30`, where the page renders the exact "(N days away)"), or already passed (negative, always shown in days). Covered by a new negative-path 404 test: the integer is keyed to a real search and would otherwise let an anonymous caller infer both that the search exists AND roughly when the client wants the role filled.
- **Canonical `phases_remaining` count (v1.30 stickiness)** — `POST /api/v1/searches/status` now also returns `phases_remaining`, the forward-looking complement to v1.21's `phases_completed`: the server-computed count of phases the search has *not* yet finished, defined so `phases_completed + phases_remaining === phase_total` always holds. For an in-flight progressing phase it includes the current phase (it isn't complete yet); a successful placement leaves zero remaining. Null in exactly the same non-progressing/negative-terminal states as `phases_completed` (`on_hold`, `cancelled`, `closed_no_fill`), where a "N to go" count would misrepresent a paused or closed-without-placement search as still on track. Same one-source-of-truth rationale as `phases_completed` and `phases_on_pace`: the planned reminder email / PDF (roadmap #4) can quote "5 phases still ahead" off the integer instead of re-deriving `phase_total − phases_completed` itself. Covered by a new negative-path 404 test — the count is keyed by how far the search has advanced, so it must never leak on the unauthenticated path.
- **Forward placement horizon on the collapsed journey summary (v1.30 stickiness)** — the full-journey `<details>` summary read "The full search journey · 3 of 8 phases complete · all on pace" — entirely a *backward* count of phases done. It now also appends a *forward* horizon — "· 6–10 weeks to go" — sourced from the canonical `estimated_weeks_remaining` (v1.27), the same weeks the placement-window line already renders, so the two never disagree. A return visitor now gets a fresh time-to-placement glance from the collapsed control without expanding the section — compounding the v1.20/v1.26 phases-complete and on-pace counts already on that line. The segment simply doesn't append in terminal/non-progressing states where the horizon is null (the journey is hidden for negative-terminals anyway, and `placed` has no remaining horizon). Pure frontend, no API change.

### Recently Shipped (2026-06-26)
- **Canonical `days_until_target_start` countdown (v1.29 stickiness)** — `POST /api/v1/searches/status` now also returns `days_until_target_start`, the server-computed integer count of days between now and the client's `target_start_date` (positive while the date is ahead, negative once it has passed). The status page's target-start countdown — "(3 weeks away)" / "(today)" / "(4 days past target)" — was the last relative-time read on the page still derived entirely client-side from the raw date; it now prefers the canonical field and falls back to local math only on older API versions. Surfacing it makes it one source of truth so the planned status-change reminder email / PDF (roadmap #4) can quote "your target start date is about 3 weeks out" off the same integer the page renders rather than re-doing the date math. Rounded with the same `Math.round(days / 7)` the frontend already uses, so the two never disagree. Null when there's no target date or the search has reached a terminal state (`placed`/`cancelled`/`closed_no_fill`) — exactly the cases where the page already suppresses the countdown, the same null-in-terminal rationale as `engagement_age_days` and `placement_age_days`. Covered by a new negative-path 404 test: the integer is keyed to a real search and would otherwise let an anonymous caller infer both that the search exists AND roughly when the client wants the role filled.
- **"Email Janet" mailto gains a pre-filled body (v1.29 stickiness)** — the v1.16 "✉ Email Janet" button pre-filled only the subject line (`Re: KNK-2026-001 — …`); the body opened blank. It now also carries a short body — a blank-line opener the client types into, followed by `(Search KNK-2026-001 — live status: https://askknock.com/status?ref=…)`. Every outbound client email therefore lands in Janet's inbox already tagged with the search it's about *and* a one-tap link back to the live status, and each message quietly reinforces the canonical deep-link as the way back to the Knock surface — the same habituation effect as the v1.15 click-to-copy pill. The link prefers the API's canonical `status_url` (one source of truth with the intake success screen and the planned reminder email) and falls back to a deep-link built from the current origin on older API responses. Pure frontend, no API change.
- **Status page consumes the canonical countdown (v1.29 hygiene)** — paired with the new `days_until_target_start` field above: `public/status.html`'s target-start countdown now reads the canonical integer instead of computing `Math.round((target − now) / 86_400_000)` inline, closing the last client-side date-math countdown so the page, the canonical integer, and the planned reminder email can never drift on the days-to-target read. Gracefully falls back to the local computation when the field is absent (older API).

### Recently Shipped (2026-06-23)
- **Canonical `placement_age_days` (v1.28 stickiness)** — `POST /api/v1/searches/status` now also returns `placement_age_days`, the server-computed count of days since a search landed in `placed` state (floored from the same shared `nowMs` instant the rest of the handler uses). It's the post-placement companion to `engagement_age_days` and the canonical source for the placement card's "Placed on Jun 14 · 14 days ago" age tag, which the status page previously derived client-side from `placed_at`. Surfacing it from the API makes it one source of truth: the planned post-placement reminder email / PDF (roadmap #4) can quote "your placement landed 14 days ago — 76 days of follow-up remain" off the same integer the page shows instead of re-doing the date math. Null unless placed, like the other placement fields; the status page prefers the canonical value and falls back to local math on older API versions. Covered by the existing placement-window negative-path 404 test (extended to assert the new field), since observing it would let an anonymous caller infer both that the search exists AND that it has reached the placed terminal.
- **Next-phase ETA countdown reads in weeks past a fortnight (v1.28 stickiness)** — the next-phase preview block's "Expected to begin around Jun 5 (in ~N days)" countdown rendered raw days even at the start of a long phase, where "(in ~21 days)" scans worse than "(in ~3 weeks)". It now expresses the countdown in weeks once `days_until_next_milestone` is at or past a fortnight, using the exact same days→weeks rounding (`Math.round(days / 7)`, floored at 1 week) the v1.20/v1.27 completion-window horizon already uses — so the two relative-time reads on the page never disagree. Days are still shown when the next phase is close in. Pure frontend, no API change; gracefully falls back to the bare date on older API versions missing the countdown integer.
- **Intake success screen prefers the canonical `status_url` (v1.28 hygiene)** — `public/start-search.html`'s success overlay re-derived the status-page link as `/status?ref=…` locally instead of using the canonical `status_url` field `POST /api/v1/intake` already returns (built by the shared `statusUrlFor()` helper, the same string the status response and planned reminder email quote). The success-screen link now prefers `result.status_url` and falls back to local derivation only on older API responses — closing the last surface that rebuilt the status link by hand, so the intake confirmation, the status page, and the reminder email genuinely cannot drift on the link format. Same one-source-of-truth rationale as the v1.18 `statusUrlFor()` extraction. Pure frontend, no API change.

### Recently Shipped (2026-06-22)
- **Canonical `estimated_weeks_remaining` range (v1.27 stickiness)** — `POST /api/v1/searches/status` now also returns `estimated_weeks_remaining`, a `{ min_weeks, max_weeks }` pair carrying the same time-to-placement horizon `estimated_days_remaining` (v1.20) expresses in days, pre-rounded to the *weeks* the status page already renders as "(about 6–10 weeks out)". That weeks conversion previously lived only in the frontend's `fmtSpan()`, so the planned reminder email / PDF (roadmap #4) would have had to re-implement the days→weeks rounding to quote the same horizon the page shows — a drift risk the days-only integer pair didn't close. Both fields are now derived from one `computeCompletionWindow()` call, and the weeks rounding mirrors `fmtSpan()` exactly (`Math.round(days / 7)`, floored at 1 week, `max ≥ min`), so the page, the integers, and the planned email can never disagree. Null when the window is null or under a fortnight (where the page shows days, not weeks); the status page prefers the canonical field and falls back to local rounding on older API versions. Same one-source-of-truth rationale as `estimated_days_remaining` and `engagement_age_days`. Covered by a new negative-path 404 test — the range is keyed by how far the search has advanced, so it must never leak on the unauthenticated path.
- **Unread-count badge in the pinned-tab title (v1.27 stickiness)** — the dynamic tab title (v1.3/v1.21) carries the ref + phase + step count, but only changed at phase/step boundaries. When the v1.5 "new since you last visited" high-water mark shows unread updates, the title is now also prefixed with the count: `(2) KNK-2026-001 · Sourcing (3/8) | Knock`, so a pinned or backgrounded tab signals "something changed" at a glance without the client switching to it — the same pinned-tab return-visit rationale as the v1.21 step-count, but keyed to what's new since the *last visit* rather than the phase. The high-water mark is committed only on the initial submit (not auto-refresh re-renders), so the badge persists through a session until the page is reopened, and the title is rebuilt from scratch each render so the prefix never stacks across auto-refreshes. Pure frontend, no API change.
- **Dead `STALL_QUIET_DAYS` constant removed (v1.27 hygiene)** — the stall detector declared both `STALL_QUIET_DAYS = 7` and `STALL_PHASE_DAYS = 14`, but only the latter was ever referenced: the "quiet for a full week" half of the `is_stalled` test (v1.9) is carried by `activity_count_last_7d` (a fixed 7-day window), not a threshold constant. The unused constant was removed and its rationale folded into the surviving comment, so the two thresholds no longer read as if both are live. Pure cleanup, no behavior change, covered by the existing status-endpoint tests.

### Recently Shipped (2026-06-21)
- **Canonical `phases_on_pace` count (v1.26 stickiness)** — `POST /api/v1/searches/status` now also returns `phases_on_pace`, the server-computed count of *completed* phases whose actual `duration_days` landed at or within their typical-max benchmark. It's the positive aggregate companion to `phases_completed` (v1.21) and the per-entry `on_pace` flag in `phase_history` (v1.23): the journey archive already showed a gold "on pace" tag per completed phase, but the *collapsed* journey summary only carried the phases-complete count, so a return visitor had to expand the section to see how the search was tracking against its benchmarks. The status page's collapsed summary now reads "The full search journey · 3 of 8 phases complete · all on pace" (or "· 2 of 3 on pace" when a phase ran long), giving a fresh positive glance without an expand. Null in the same non-progressing/negative-terminal states as `phases_completed` (`on_hold`, `cancelled`, `closed_no_fill`), where a pace tally would misrepresent a paused or closed-without-placement search as progress. Same one-source-of-truth rationale as `phases_completed` and `current_phase_on_pace`: the planned reminder email / PDF (roadmap #4) can quote "3 of 3 completed phases on pace" off the integer instead of re-deriving it from `phase_history`. Covered by a new negative-path 404 test — the count is keyed by how far the search has advanced, so it must never leak on the unauthenticated path.
- **Velocity-trend chip is screen-reader legible + dead-state cleanup (v1.26 a11y)** — the week-over-week velocity-trend chip (v1.17) conveyed its momentum signal only visually and via a hover `title`, which screen readers announce inconsistently. It now also carries an explicit `aria-label` ("Activity trend: 5 updates the week before — pipeline is picking up") so a committee member on a screen reader gets the same week-over-week signal sighted clients do — extending the v1.20 progress-bar accessibility rationale to the chip. Same pass also removed the dead `.velocity-trend.quiet` CSS rule (the JS never applies a `quiet` class — a quiet-on-quiet week leaves the chip hidden by default), and fixed a self-contradictory tooltip on the `steady`/zero-prior-week edge (the ±2 dead-band can classify a 0→1 uptick as "steady", where "0 updates the week before — tempo unchanged" read as a contradiction; that case now reads "A similar quiet tempo to the week before"). Pure frontend, no API change.
- **"Engagement at a glance" strip is screen-reader legible (v1.26 a11y)** — the cumulative per-type breakdown strip (v1.17) rendered as a row of pills with no SR-accessible framing, so a screen reader announced a bare run of numbers and nouns. The pills container is now marked `role="img"` with an `aria-label` summarizing the strip as one described unit ("Engagement so far: 8 candidates sourced, 3 candidates presented"), built from the same `activity_breakdown` data that draws the visible pills. The role/label are set in JS (not the static markup) so an empty container before first render isn't announced as a label-less image, and cleared when the strip is hidden. Same v1.20 accessibility rationale as the velocity-chip change above. Pure frontend, no API change.

### Recently Shipped (2026-06-20)
- **One GROUP BY scan powers the whole Activity surface (v1.25 hygiene)** — the status handler ran two separate scans of `search_activities` to populate the Activity row: one aggregate query for the weekly/prev-week/cumulative counts and a second `GROUP BY activity_type` query for the per-type breakdown (the two middle downstream queries v1.24's resolved-id reuse named). They're now a single `GROUP BY` scan: each group row carries its own count plus the two windowed `FILTER` counts, and the three scalar totals (`activity_count_total`, `activity_count_last_7d`, `activity_count_prev_7d`) are computed as the column sums in JS. One round-trip instead of two, and because the cumulative total is now literally the sum of the per-type breakdown, the breakdown strip and the total counter can never disagree. Pure efficiency/consistency refactor — no response-shape change, covered by the existing status-endpoint tests. Same one-fewer-redundant-query rationale as v1.24's resolved-id reuse.
- **Activity-window counts anchored to the request-time `nowMs` (v1.25 hygiene)** — the merged velocity query's 7-day / 14-day window boundaries previously came from SQL `NOW()`, evaluated independently of the single `nowMs` instant the rest of the handler shares (v1.23). A request that straddled a UTC day boundary mid-handler could therefore return an `activity_count_last_7d` whose window edge disagreed with the `days_since_last_activity` recency anchor rendered right beside it. The window boundaries are now derived from `nowMs` (passed as a `$3::timestamptz` parameter), so every time-derived field on the response — phase ages, the recency anchor, and the weekly counts — shares one instant. Extends the v1.23 single-now discipline to the last fields that still used a server-side clock.
- **Status-page `fmtRelative()` floors hours from raw ms (v1.25 hygiene)** — v1.24 floored the *day* bucket so the timeline agreed with the server's floored `days_since_last_activity`, but it still derived that day count from a *rounded* hour value (`Math.round(min / 60)`), leaving a residual edge: a ~23.6-hour-old item rounded up to "24 hr" and then read as "1 day ago" on the timeline while the server's floored recency anchor still said 0 days. `fmtRelative()` now floors both the hour and day buckets straight from the raw millisecond difference, so the timeline and the server recency anchor stay in lockstep across the full 0–7 day range. Also adds a negative-path 404 test covering the pipeline counts (`candidates_identified`/`presented`/`interviewing`) and `recent_activities` — the most directly candidate-revealing success-shape fields, which previously relied only on the generic no-`data` assertion. Pure frontend + test, no API change.

### Recently Shipped (2026-06-19)
- **Canonical `current_phase_on_pace` flag (v1.24 stickiness)** — `POST /api/v1/searches/status` now also returns `current_phase_on_pace`, the positive companion to `is_stalled` and the mirror of the per-completed-phase `on_pace` flag in `phase_history` (v1.23). Completed phases already earned an "on pace" tag on the durational journey archive, but the *current* in-flight phase — the one a return visitor cares about most — had no canonical comparative signal: the pacing line rendered "18 days in phase (typically 14–28 days)" and left the client to do the comparison. The flag is `true` when the current progressing phase's `days_in_phase` is at or within its typical-max benchmark, `false` once it slips past, and `null` for terminal/non-progressing/`placed` phases or any phase without a typical duration (same null-semantics as the `phase_history` `on_pace` flag). The status page now appends a small gold "on pace" tag to the current-phase pacing line (positive-only by design — an over-typical phase shows the bare day count with no tag, since `is_stalled` already carries the negative signal). Same one-source-of-truth rationale as `phases_completed` and `engagement_age_days`: the planned reminder email / PDF (roadmap #4) can quote "Sourcing is on pace — 18 of a typical 14–28 days" off the boolean instead of re-deriving the benchmark. Covered by a new negative-path 404 test — the flag is keyed by the current phase, so it must never leak on the unauthenticated path.
- **One resolved search `id` reused across the status handler's queries (v1.24 hygiene)** — the status handler's main row query already locates the search by `search_number`, but the four downstream queries (recent activities, the velocity/total counts, the per-type breakdown, and the phase-transition history) each independently re-resolved the same search with a `WHERE search_id = (SELECT id FROM searches WHERE search_number = $1)` correlated subquery. The main query now also selects `s.id`, and the four downstream queries take that resolved id directly as a parameter — eliminating four redundant primary-key lookups per status request with no change to the response shape. Pure efficiency/clarity refactor, covered by the existing status-endpoint tests.
- **Frontend relative-time floor matches the server (v1.24 hygiene)** — `public/status.html`'s `fmtRelative()` rounded its day count (`Math.round(hr / 24)`) while the server computes `days_since_last_activity` with `Math.floor`. A ~2.6-day-old activity therefore read "latest 2 days ago" on the velocity-row recency anchor (server, floored) but "3 days ago" in the timeline row just below it (client, rounded). The timeline now floors too — both surfaces agree, and the result also matches the conventional relative-time read (a 2.6-day-old item is "2 days ago", not rounded up). Pure frontend, no API change.

### Recently Shipped (2026-06-18)
- **Shared `statusUrlFor()` helper — one *code* source of truth for the status link (v1.23 hygiene)** — both `POST /api/v1/intake` and `POST /api/v1/searches/status` returned the canonical `status_url` string, but each route *independently* rebuilt it from `PUBLIC_BASE_URL` + `/status?ref=…`. The doc claimed "one source of truth"; the code had two. Extracted `publicBaseUrl()` + `statusUrlFor(searchNumber)` into `services/api/src/lib/urls.ts` and pointed both routes at it, so the link format genuinely cannot drift between the intake success screen and the status page (and the planned reminder email / PDF inherits the same single builder). Pure refactor — byte-identical output, covered by the existing `status_url`-on-404 negative-path test. No API-shape change.
- **Canonical `on_pace` flag on each completed `phase_history` entry (v1.23 stickiness)** — each completed entry in the `phase_history` array returned by `POST /api/v1/searches/status` now also carries `on_pace`: a server-computed boolean, true when that phase's actual `duration_days` landed at or within its typical-max benchmark from `PUBLIC_STATUS_TYPICAL_DURATION`. The status page's durational journey archive (v1.22) previously derived its gold "on pace" tag client-side by regex-parsing the `"14–28 days"` benchmark string it renders — fragile and duplicated. The page now prefers the canonical flag (falling back to the regex parse on older API versions), making it one source of truth: the planned status-change reminder email / PDF (roadmap #4) can quote "Sourcing wrapped on pace · 12 days" without re-deriving the benchmark. Same rationale as v1.22's `label` and v1.21's `phases_completed`. Null for the current/last phase (still running) and any phase without a typical duration. Nested inside `phase_history`, so the existing negative-path 404 test for `phase_history` already covers it.
- **Single request-time `now` across all status time-derived fields (v1.23 hygiene)** — the status handler computed `days_in_phase`, `next_milestone_eta`, `estimated_completion_window`, `engagement_age_days`, `days_since_last_activity`, and the placement-followup countdown from seven independent `Date.now()` calls. A request that straddled a UTC day boundary mid-handler could therefore hand back internally-inconsistent day counts (e.g. an `engagement_age_days` one day ahead of `days_in_phase`). All of them now share a single `nowMs` instant captured once after email verification — the same "can never drift" discipline the `estimated_completion_window` / `estimated_days_remaining` pair already follows by sharing one `computeCompletionWindow()` call. Pure consistency fix, no response-shape change.

### Recently Shipped (2026-06-17)
- **Canonical `status_url` in the status response (v1.22 stickiness)** — `POST /api/v1/searches/status` now also returns `status_url`, the canonical deep-link back to the status surface (`PUBLIC_BASE_URL` + `/status?ref=…`). It's the exact string `POST /api/v1/intake` already returns, so the intake success screen, the status page, and the planned status-change reminder email / PDF (roadmap #4) all quote one source of truth instead of each rebuilding the link from the bare reference number. Same one-source-of-truth rationale as `engagement_age_days` and `phases_completed`. Lives on the verified success shape only — covered by a new negative-path 404 test, so the response never hands an anonymous caller a ready-made link to a search it declined to disclose.
- **Canonical `label` on each `phase_history` entry (v1.22 stickiness)** — each entry in the `phase_history` array returned by `POST /api/v1/searches/status` now also carries `label`, the canonical human phase name sourced from `PUBLIC_STATUS_PHASES` (the same map that drives `phase_label`). The status page already renders labels from its own forward-phase list, so this is a pure pre-pave for the other surfaces: the planned reminder email / PDF can quote real dated milestones — "Sourcing ran Apr 22 → May 4 · 12 days" — without re-deriving the label from the raw status code. Same one-source-of-truth rationale as `engagement_age_days` / `phases_completed`. Nested inside `phase_history`, so the existing negative-path 404 test for `phase_history` already covers it.
- **"On pace" tag on the durational journey archive (v1.22 stickiness)** — each completed phase on the full-journey overview already showed its actual elapsed days (v1.18: "✓ Sourcing · Entered Apr 22 · 12 days"). It now also earns a small gold "on pace" tag when that duration landed at or within the phase's typical-max benchmark (parsed from the same `FORWARD_PHASES` "14–28 days" string already shown on the row). Turns the *durational* archive into a *comparative* one — a return visitor opening the journey section gets a fresh, encouraging read of how the search is tracking against its own benchmarks, not just a list of elapsed times. Positive-only by design: over-typical phases get no tag (stay neutral) so the archive never reads as punitive on the rows a client revisits most. Pure frontend, no API change.

### Recently Shipped (2026-06-16)
- **Canonical `phases_completed` count (v1.21 stickiness)** — `POST /api/v1/searches/status` now also returns `phases_completed`, the server-computed count of finished phases: a successful placement counts the whole 8-phase journey, an in-flight progressing phase counts the steps strictly before the current one, and non-progressing/negative-terminal states (`on_hold`, `cancelled`, `closed_no_fill`) return null so a paused or closed-without-placement search never reads as "N phases complete." The status page's collapsed journey summary ("3 of 8 phases complete") previously derived this client-side; it now prefers the API value and falls back to local math on older API versions. Same one-source-of-truth rationale as `engagement_age_days` and `days_until_next_milestone`: the planned status-change reminder email / PDF (roadmap #4) can quote the same "3 of 8 phases complete" the page shows instead of re-deriving it from `phase_step`. Covered by a new negative-path 404 test alongside the rest of the response surface — the integer is keyed by the current phase (completed = step − 1), so it must never leak on the unauthenticated path.
- **Step-count in the pinned-tab title (v1.21 stickiness)** — the dynamic tab title (v1.3) read `KNK-2026-001 · Sourcing | Knock` — static for the entire duration of a phase. For an in-flight progressing phase it now also carries the step count: `KNK-2026-001 · Sourcing (3/8) | Knock`, so a pinned tab shows visible *movement* between visits at a glance, without the client opening the tab — the same compounding return-visit value as the v1.20 journey-summary count, but in the one place a client habitually leaves Knock open. Suppressed on negative-terminal states (`cancelled`/`closed_no_fill`, which carry `phase_step` 8) so the tab never reads a misleading "(8/8)" on a search that closed without a placement. Pure frontend, no API change.
- **Last-update recency anchor on the quiet-week velocity row (v1.21 stickiness)** — v1.13's "5 updates this week · latest 2 days ago" recency anchor only appended when the weekly count was non-zero; a quiet week rendered the bare "Quiet stretch — no updates this week" with no sense of *how* quiet. The anchor now also appends on the zero-week case whenever any public activity exists ("Quiet stretch — no updates this week · latest 9 days ago"), turning a potentially worrying blank into an honest between-beats signal: the pipeline isn't dead, just paused. Day-1 searches with no activity yet (`days_since_last_activity` null) still show the bare line. Pure frontend, no API change.

### Recently Shipped (2026-05-24)
- **Canonical `estimated_days_remaining` integer range (v1.20 stickiness)** — `POST /api/v1/searches/status` now also returns `estimated_days_remaining`, a `{ min_days, max_days }` pair carrying the raw day counts that `estimated_completion_window` (v1.11) already converts to ISO dates. Both fields are now produced by one call to `computeCompletionWindow()`, so the dates and the integers can never drift. The status page appends a glanceable "(about 6–10 weeks out)" to the placement-window line — turning two absolute dates into a relative horizon at a glance — and the planned reminder email / PDF (roadmap #4) can quote the same integers as "about 6–10 weeks to placement" instead of re-deriving a day-count from the dates. Same one-source-of-truth rationale as `engagement_age_days` and `days_until_next_milestone`. Null for terminal/non-progressing states, like the window it accompanies. Covered by a new negative-path 404 test: the pair must never leak on the unauthenticated path, since it would otherwise let an anonymous caller infer how far along a search is.
- **Accessible progress bar for screen readers (v1.20 stickiness)** — the status page's phase progress track is now a proper ARIA `role="progressbar"` with `aria-valuemin`/`aria-valuemax` on the element and `aria-valuenow` + `aria-valuetext` set in JS on every render ("Sourcing candidates — step 3 of 8, 31% complete"). A committee member using a screen reader previously heard only a silent bar; now the same "you are here" signal sighted clients get is announced aloud. Pure frontend, no API change — but the status page is the one Knock surface clients return to unprompted, so it should be legible to every committee member, not most of them.
- **Phases-complete count on the journey summary (v1.20 stickiness)** — the collapsed "The full search journey" `<details>` summary now reads "The full search journey · 3 of 8 phases complete", derived from the server's `phase_step` (and counting all 8 on a successful placement). The summary line was previously static — identical on visit #1 and visit #5 until the section was expanded. Now the collapsed control itself carries a monotonically-growing number that advances as the search progresses, giving a return visitor a fresh glanceable signal without having to open the section. Pure frontend, no API change.

### Recently Shipped (2026-05-23)
- **Canonical `days_until_next_milestone` countdown (v1.19 stickiness)** — `POST /api/v1/searches/status` now also returns `days_until_next_milestone`, the integer companion to v1.18's `next_milestone_eta`: the count of the current phase's typical-max days still remaining, floored at 0 (and null whenever the ETA is null). Same one-source-of-truth rationale as `engagement_age_days` — the status page renders a glanceable "Expected to begin around **Jun 5** (in ~5 days)" that decrements daily (a fresh reason to revisit between visits), and the planned reminder email / PDF (roadmap #4) can quote the same integer instead of re-deriving it from the ISO date. Covered by a new negative-path 404 test alongside the rest of the response surface — the integer is keyed by the current phase, so it must never leak on the unauthenticated path.
- **"Any day now" copy for overdue phases (v1.19 stickiness)** — when the current phase has reached or passed its typical-max duration, the API hands back a zero `days_until_next_milestone` (and today's `next_milestone_eta`). The status page previously rendered the literal — and increasingly stale — date in that case; it now reads "Expected to begin **any day now**" instead, matching the API's documented intent. Pure frontend, gracefully falls back to the bare date on older API versions. Turns the moment a phase slips into a *reason* to keep checking back rather than a frozen past date.
- **"Ramping up" velocity chip on a search's first active week (v1.19 stickiness)** — the week-over-week velocity-trend chip read "↑ up from 0" on the first week a brand-new search saw activity, which parsed awkwardly (there was nothing to be "up from"). When the prior 7-day window was empty, the chip now reads "↑ ramping up" with matching hover copy, so the very first burst of activity reads as a fresh start rather than a delta against zero. Pure frontend, no API change.

### Recently Shipped (2026-05-22)
- **Actual phase durations on the journey archive (v1.18 stickiness)** — each entry in the `phase_history` array returned by `POST /api/v1/searches/status` now also carries `duration_days`: the actual elapsed days a *completed* phase ran, computed server-side as the gap between that phase's `entered_at` and the next phase's `entered_at`. The current (last) phase is still running, so its `duration_days` is null. The full-journey overview on `public/status.html` renders it inline on done phases — "✓ Sourcing · Entered Apr 22 · 12 days" — turning the v1.16 *dated* archive into a *durational* one the client can read directly against the "Typically 14–28 days" benchmark already shown on the same row. A long engagement (10–16 weeks) now reads as a story with concrete elapsed times per phase, not just a list of arrival dates. Nested inside `phase_history`, so the existing negative-path 404 test for `phase_history` already covers the new sub-field — an anonymous caller still can't observe either that the search exists OR how long each phase took.
- **Near-term next-phase ETA (v1.18 stickiness)** — `POST /api/v1/searches/status` now also returns `next_milestone_eta`, a single ISO date for when the next phase is expected to begin: `now + max(0, current-phase typical-max − days_in_phase)`, floored at zero so an over-typical phase reads as "any day now" rather than a past date. Null for terminal/non-progressing states and for searches with no next phase. The status page renders it in the v1.13 next-phase preview block as "Expected to begin around **Jun 5**." It's the near end of the same calculation the v1.11 `estimated_completion_window` sums to its far end — giving the client one concrete, closer-in date to look forward to between visits, and one that walks forward as the current phase progresses (a fresh reason to revisit as it approaches). Covered by a new negative-path 404 test: the date must never leak on the unauthenticated path, since it would otherwise let an anonymous caller infer the search's current phase.
- **Canonical `engagement_age_days` (v1.18 stickiness)** — `POST /api/v1/searches/status` now also returns `engagement_age_days`, the server-computed integer days since `searches.created_at`. The status page already derived this client-side for its "(11 days ago)" tag on the *Search opened* row; the page now prefers the API value (falling back to local date math on older API versions). Same one-source-of-truth rationale as v1.9's `phase_explainer`: the planned status-change reminder email (roadmap #4) and future PDF status reports can quote the same "your search has been running 18 days" number the page shows, instead of each surface doing its own date math. Covered by a new negative-path 404 test alongside `next_milestone_eta` — the integer must never leak on the unauthenticated path, since it would let an anonymous caller infer both that the search exists and how long it's been running.

### Recently Shipped (2026-05-21)
- **Week-over-week velocity-trend chip (v1.17 stickiness)** — `POST /api/v1/searches/status` now also returns `activity_count_prev_7d` (the public-activity count for the previous 7-day window, days `[-14, -7)` relative to now) and `velocity_trend`, a categorical label (`'accelerating'` / `'steady'` / `'cooling'` / `'quiet'`) derived from the week-over-week delta with a ±2 dead-band so single-row day-to-day noise doesn't fire false trends. The status page renders a small chip next to the v1.8 weekly count: "5 updates this week · ↑ up from 2", "3 updates this week · steady", or "2 updates this week · ↓ down from 5". The weekly absolute count was already a fresh number to revisit, but it could read as static when the headline number happened to land the same value two weeks running — the trend chip adds a *second* axis of movement, so even a flat headline produces a fresh visible signal when the underlying tempo shifts. The chip stays hidden when the API flags `is_stalled` (the existing stalled copy already carries the pacing message) and when both windows are zero (a brand-new search shouldn't read as "down from 0"). Same redaction discipline as the rest of the response: both `activity_count_prev_7d` and `velocity_trend` are covered by the same negative-path 404 test pattern as v1.8's `activity_count_last_7d` before them — an anonymous caller must never be able to infer either that the search exists OR how its tempo is changing.
- **"Engagement at a glance" cumulative breakdown strip (v1.17 stickiness)** — `POST /api/v1/searches/status` now also returns `activity_breakdown`, an object of cumulative per-type counts (`{ status_change, candidate_added, presentation_sent, interview_scheduled, client_meeting }`) computed from the same `PUBLIC_ACTIVITY_TYPES` filter that powers every other count on the response, so the breakdown can never reflect internal/commercial rows. The status page renders the non-zero entries as a horizontal pill strip under the meta-rows: "8 candidates sourced · 3 presented · 2 committee interviews · 1 client meeting". The total + weekly counts already tell the client *how much* is happening; the breakdown tells the engagement *story* in concrete nouns and verbs the committee chair can quote back to Janet ("we've seen 8 candidates sourced — when do we get to the next round?"). Pill order matches the natural search-engagement narrative so the row reads left-to-right as the arc of the search (sourcing → presenting → interviewing → meetings → phase transitions). Zero-count types stay hidden so a day-1 search doesn't render five "0" pills. Negative-path 404 test added — the per-type object must never leak on the unauthenticated path, since observing it would let an anonymous caller infer the shape of an arbitrary engagement.
- **Hover-tooltip absolute timestamps on every relative-time string (v1.17 stickiness)** — every `fmtRelative()` output on the status page (`"3 days ago"`, `"5 min ago"`, the headline activity card, every row of the timeline) now also carries a `title` attribute with the precise local timestamp (`"May 18, 2026 at 3:24 PM"`). Pure frontend touch — but it solves a real friction the timeline has had since v1.2: committee chairs occasionally want the exact date of a specific update (to quote in a meeting, paste into a board packet, or correlate against an email thread) and were previously forced back to the underlying email thread to find it. Now hovering the timestamp surfaces the absolute date inline, with no visual clutter for normal scanning. Helper `setRelativeWithTooltip(el, iso)` is the single point that maintains the contract, so future timestamp surfaces (status-change reminder emails, PDF status reports) inherit it for free. No API change.

### Recently Shipped (2026-05-20)
- **Dated phase-history archive + dated journey overview (v1.16 stickiness)** — `POST /api/v1/searches/status` now returns `phase_history`, an ordered `[{ phase, entered_at }]` array — one entry per phase the search has been in, sourced from the existing v1.3 `status_change` rows in `search_activities` (no schema change required) plus a synthetic opening-phase entry seeded from `searches.created_at` so the very first phase the search opened in still renders dated on the journey overview. Same-phase revisits (paused → resumed → paused) collapse to the first arrival so each phase's `entered_at` is the canonical "when did we first get here" date. The full-journey overview on `public/status.html` now renders these dates inline on every done/current entry — "✓ Sourcing · Entered Apr 22 · Typically 14–28 days" / "● Screening (current) · Started May 04" — turning what was previously a static checklist (identical on every visit until the next phase boundary) into a *permanent dated archive* of the engagement's progress. Long engagements (10–16 weeks) end up reading as a story the client can scroll back through, not just a "step 5 of 8" cursor. Upcoming phases stay dateless (hidden via CSS) so the overview doesn't pretend to predict exact future dates — that's still the `estimated_completion_window`'s job. Same redaction discipline as the rest of the response, and the new `phase_history` array is covered by the same negative-path 404 test pattern as v1.9–v1.15 fields: an anonymous caller must never be able to infer either that the search exists OR when it entered each phase.
- **"Email Janet" pre-filled mailto button (v1.16 stickiness)** — adjacent to Refresh/Share on the status card, a new "✉ Email Janet" button opens the client's mail composer with `mailto:janet@askknock.com` pre-filled with a `Re: KNK-2026-001 — Head of School at Covenant Christian Academy` subject line (URL-encoded, falls back to the bare ref + position title pattern when school name is missing). The status page used to be a *read-only* surface — see the status, close the tab. With v1.16 it becomes an *action surface*: a question, concern, or committee update is one tap away from Janet's inbox, and the canonical reference number rides into the thread automatically so nothing has to be hunted down. Every outbound email pre-tagged with `KNK-XXXX-NNN` also reinforces the canonical reference as *the* way to talk about the search, mirroring the v1.15 click-to-copy pill's habituation effect. Hidden in the print stylesheet so committee-packet prints stay clean. Pure frontend, no API change.
- **`#journey-details` URL-hash auto-expand on the journey overview (v1.16 stickiness)** — when a status-page URL ends with `#journey-details` (e.g. `/status?ref=KNK-2026-001#journey-details`), the previously-collapsed full-journey `<details>` section auto-opens on initial render and smooth-scrolls itself into view 80ms later. Pre-paves the planned status-change reminder email from roadmap #4 (CLAUDE.md already named this exact hook): the upcoming "your search just moved to *Screening interviews* — see the whole arc" email can now deep-link directly to the journey view, landing the committee chair on the page with the new v1.16 dated milestone right in their viewport instead of folded below. Gated on `commitHighWaterMark` so an auto-refresh poll doesn't re-scroll the page underneath the client mid-read — only the initial form submission (or the v1.13 zero-click auto-submit) triggers the scroll. Pure frontend, no API change.

### Recently Shipped (2026-05-19)
- **Universal .ics calendar fallback (v1.15 stickiness)** — `public/status.html` now ships an "Apple / Outlook (.ics)" link alongside the v1.14 Google Calendar add-to-calendar affordance, generated inline as a `data:text/calendar` URI from the same `target_start_date` the Google link already uses. Independent-school committees skew heavily toward macOS/iOS, so a Google-only link was leaving a meaningful fraction of clients without the calendar primitive at all. The .ics emits the RFC 5545 minimum required fields (VERSION, PRODID, UID, DTSTAMP, DTSTART/DTEND as `VALUE=DATE`, SUMMARY) with CRLF line endings and proper escaping of commas/semicolons/backslashes in the title — without this an em-dash-laden position title silently breaks the feed in Outlook (Apple Calendar is more forgiving). UID is deterministic (`knock-<search_number>-target@askknock.com`) so a re-import overwrites rather than duplicates. URL property embeds the deep-link back to `/status?ref=…` so any calendar alert on that date carries a one-click return path to the Knock surface — same compounding stickiness as the Google link, now reaching every client. Pure frontend, no API change.
- **Click-to-copy reference-number pill (v1.15 stickiness)** — the `KNK-XXXX-NNN` pill at the top of the status card is now a clickable button (keyboard-accessible, `role="button"`, Enter/Space trigger) that copies the canonical reference to the clipboard, with a transient "✓ copied" affordance that reverts after 1.4 seconds. Clients re-type the reference every time they email Janet, paste it into a board packet, or forward it to a search-committee member — a micro-shortcut, but every visit to the status page becomes *the* place to grab the canonical reference rather than digging through past emails or the original intake confirmation. `user-select: all` is also set as a graceful-degradation path for environments without a clipboard API.
- **Live "Updated X ago" timestamp on the status card (v1.15 stickiness)** — the silent v1.4 auto-refresh now has a visible trust signal: a small green pulse-dot + "Updated 14 seconds ago" line under the Refresh button, stamped on every successful fetch and re-rendered every 15 seconds so the text walks forward naturally between API polls. With v1.4 auto-refresh, the page already updates every 3 minutes — but the client had no way to *see* that without timing it themselves. The visible heartbeat closes the loop: a pinned tab now reads as a continuously-fresh live dashboard, with the same compounding return-visit value as the v1.13 zero-click auto-submit. `aria-live="polite"` on the wrapper means the ticker is also announced (gently) to screen readers. Hidden in the print stylesheet so committee-packet prints stay clean.
- **Full-journey overview, collapsed by default (v1.15 stickiness)** — under the status card, a new `<details>` section ("The full search journey") expands to show all 8 phases at once with a vertical timeline rail: done phases get a filled gold ✓ marker, the current phase a pulsing gold pin, upcoming phases an outline ring. Each entry carries the same `PHASE_EXPLAINERS` copy that drives the active-phase explainer (single source of truth across both surfaces) plus the canonical typical-duration range. The page previously committed to *what's now* and *what's next* but never showed the whole arc — meaning a return visitor on visit #5 saw the exact same horizon as on visit #1. With the journey overview, every visit can drill into the full path; clients with longer engagements (10–16 weeks) increasingly use it as the orienting reference. Hidden for non-progressing (`on_hold`) and negative-terminal (`cancelled`, `closed_no_fill`) statuses where a "you are here" pin would be misleading.

### Recently Shipped (2026-05-18)
- **Cumulative engagement-depth counter (v1.14 stickiness)** — `POST /api/v1/searches/status` now also returns `activity_count_total`, a count of *all* public-visible activities since a search opened (same `PUBLIC_ACTIVITY_TYPES` filter as the v1.8 weekly count, so internal/commercial rows still never leak). Computed in a single query with the weekly count via a `FILTER` clause — one round-trip, two numbers that are atomically consistent. The status page renders it as a new "Total updates" meta-row beneath the existing Activity row ("12 updates since opened") only when `total > weekly` and `total > 0`, so a fresh search doesn't show the same number twice on adjacent rows. The weekly count tells the client whether the pipeline is moving *right now*; the cumulative count is what monotonically grows across the whole engagement — every return visit shows a number with nowhere to go but up, including on the days the weekly count happens to be zero. Compounds with the v1.13 `days_since_last_activity` and v1.8 weekly count into a three-axis honest-pacing surface: tempo, recency, depth. Negative-path test added: the integer must never leak on 404, since observing it on the 404 path would let an anonymous caller infer both that the search exists AND how deep the engagement has gone.
- **"Add to calendar" affordance for `target_start_date` (v1.14 stickiness)** — when the status page renders a non-terminal `target_start_date`, it now adds a small "Add to calendar" link next to the countdown that opens a pre-filled Google Calendar all-day event. The event title carries the position + school name, the description embeds a deep-link back to `/status?ref=…`, and the event lands on the actual target date (end-date advanced by one day to satisfy Google Calendar's exclusive-end semantics). Pure frontend, no API change. Compounding stickiness primitive that creates a *new external surface* Knock now lives on: every calendar alert or weekly-agenda glance that mentions the target start date becomes an organic return-visit prompt, with the Knock URL one click away. The link is hidden in print stylesheets and gracefully no-ops when `target_start_date` isn't a parseable ISO date.
- **PWA Web App Manifest + "Add to Home Screen" support (v1.14 stickiness)** — added `public/site.webmanifest` (scope: `/status`, theme `#b8860b`, Knock-gold standalone display) and wired it into `public/status.html` via `<link rel="manifest">` plus the iOS-specific `apple-mobile-web-app-capable` + `apple-mobile-web-app-title` meta tags. Mobile clients on Safari/Chrome can now "Add to Home Screen" and get a Knock-branded launcher icon that opens the status page in standalone app mode — no browser chrome, full-screen Knock gold. Caddyfile updated to (a) keep `.webmanifest` and `.json` out of the `/foo → /foo.html` clean-URL rewrite, and (b) serve `.webmanifest` with the spec-blessed `application/manifest+json` content type (Caddy's default mime DB doesn't include it, so without the header iOS Safari falls back to `text/plain` and refuses the manifest). Compounds with the v1.13 zero-click auto-submit: a mobile user who installs the page sees a Knock icon on their home screen, taps it once, and the latest status loads instantly — no browser, no form, no friction. Pure additive: desktop users and non-installing mobile visitors see no change.

### Recently Shipped (2026-05-17)
- **Next-phase preview on the status page (v1.13 stickiness)** — `POST /api/v1/searches/status` now also returns `next_phase_explainer` (the same canonical phase-copy that powers the current-phase explainer, but for the upcoming phase) and `next_phase_duration_typical` (the same `{ min_days, max_days }` shape as `phase_duration_typical`, but for the next status in the forward sequence). The status page renders both beneath the existing "Next: …" line as a small indented preview block: a sentence about what that phase entails plus "Typically 14–28 days." The page used to commit to *what's next* but not *what next means* — a client reading "Next: Screening interviews" had no way to know whether that meant another two weeks or another two months. With v1.13 it now reads as a guided journey with concrete pacing throughout, rather than a current-step indicator with a one-word breadcrumb. Compounds with v1.11's `estimated_completion_window`: the per-phase typical durations the window already sums are now visible one phase at a time. Both fields covered by the same 404-leak negative-path test pattern as v1.9–v1.12, since together they let an anonymous caller infer the current phase.
- **Exact-recency anchor on the activity-velocity row (v1.13 stickiness)** — `POST /api/v1/searches/status` now also returns `days_since_last_activity`, a server-computed integer derived from the latest public-visible activity's timestamp (null when there are no public activities yet). The status page's "Activity" row used to read "5 updates this week" — a useful weekly count, but the *exact recency* of the latest update was only visible by reading the timeline below. v1.13 anchors the row with both: "5 updates this week · latest 2 days ago." Pairs naturally with v1.9's `is_stalled` flag — together they give every state of the row (active, stalled, day-1, terminal) a concrete numeric anchor instead of vague qualitative copy. Same redaction discipline as the rest of the response: derived from `latest.created_at`, which is already part of the public response. Negative-path test added: the field must never leak on 404, since the integer would otherwise let an anonymous caller infer both that the search exists AND roughly when it was last touched.
- **Zero-click return visits on a pinned status tab (v1.13 stickiness)** — when both `?ref=KNK-…` and the v1.12-seeded `knock.status.email` localStorage key are present at page load, the status page now auto-submits the form on its own. Pure UX shortcut — the server still verifies the (ref, email) pair on every submission — but the cumulative effect with v1.12's intake email seed is that the *very first* status check is one-click, and every subsequent visit to a deep-linked URL is zero-click. A pinned tab effectively becomes a live dashboard the client can glance at without any interaction. First-time visitors (or any caller missing either piece) still see the manual form, so the change is purely additive.

### Recently Shipped (2026-05-16)
- **Intra-phase progress bar (v1.12 stickiness)** — `progress_percent` on `POST /api/v1/searches/status` now factors in `days_in_phase` against the current phase's typical-max duration, so the bar moves day-to-day inside a phase rather than jumping 12.5% only at phase boundaries. A single phase typically runs 2–4 weeks, so the previous coarse mapping meant a return visitor saw the same bar every time for most of a phase — exactly the opposite of what each return visit should reinforce. Now each day inside `sourcing` walks the fill forward by ~0.4 percentage points (for a 28-day-max phase), giving the visual a real, monotone-increasing reason to look. Formula: `((phase_step - 1) + min(1, days_in_phase / max_days)) / 8 * 100`. Negative-terminal phases (`cancelled`, `closed_no_fill`) still have the bar hidden by the frontend so they don't read as triumphant 100% fills (v1.11 contract preserved); `placed` still pins at 100% as the celebration cap.
- **Post-placement 90-day follow-up window (v1.12 stickiness)** — `POST /api/v1/searches/status` now returns `placed_at`, `placement_followup_until`, and `placement_followup_days_remaining` (all null unless `status === 'placed'`). Status page renders a Knock-gold placement card under the phase tracker that reads "Placed on **Jun 14, 2026** · 14 days ago. Janet's 90-day follow-up window runs through **Sep 12, 2026** — **76 days** remaining." The status page used to go silent the moment a search closed — but placement is exactly when stickiness should *deepen*, not stop. With the explainer already committing to a 90-day follow-up window, surfacing the exact countdown extends the page's useful life by three months past every successful placement. Compounds with the v1.5 "new since last visited" indicator: any check-in from Janet during that 90-day window now shows up as a fresh New badge on a still-anchored placement card. The fields are also covered by the same negative-path test pattern as v1.9–v1.11 (must never leak on 404, since their presence would otherwise let an anonymous caller infer that a search exists *and* has reached the placed terminal).
- **Intake form seeds the status-page email (v1.12 stickiness)** — `public/start-search.html` now writes the submitted `contact_email` to `localStorage` under the same key the status page reads on load (`knock.status.email`). The first click from the intake success screen to `/status?ref=…` therefore lands on a form with both fields already filled — the client just hits "Check Status" instead of retyping their email. Tiny touch, but it closes the loop on the intake → status-page transition that's the first habituation moment of every engagement, removing the only piece of friction left on the success → first-status-check path.

### Recently Shipped (2026-05-15)
- **Estimated placement window on the status page (v1.11 stickiness)** — `POST /api/v1/searches/status` now also returns `estimated_completion_window`, an `{ earliest, latest }` pair of ISO dates computed server-side from the typical durations of the remaining progressing phases (subtracting `days_in_phase` from the current phase so the window reflects only what's still ahead). The status page renders it as "Typical placement window: **Jun 14 – Aug 11**" right under the pacing line. Compounding stickiness primitive: every visit shows two dates the client can mark on a calendar, the dates stay stable across visits so the client builds an anchor, and as `days_in_phase` rises past the typical max the upper bound walks forward — giving the same client a fresh reason to revisit whenever the window is about to slip. Returns null (and is hidden by the frontend) for terminal/non-progressing states where a forward-looking estimate would be meaningless. Negative-path test added: the field must never leak on 404, since the pair would otherwise let an anonymous caller infer how far along a search is.
- **Negative-terminal phases no longer render a full Knock-gold progress bar** — `cancelled` and `closed_no_fill` come back with `phase_step === 8`, which previously produced a triumphant 100%-filled progress bar above what's actually a cancellation or close-without-placement. That misread the moment most likely to drive a return visit. The status page now treats them like `on_hold`: hide the bar and the step counter, let the phase label + explainer ("Search closed without a placement…") carry the state on its own. Pure frontend, no API change. Mirrors the v1.6 polish for `on_hold`.
- **Test coverage for the new privacy contract** — the v1.11 `estimated_completion_window` field gets the same 404-leak negative-path test as v1.9's `phase_explainer` / `is_stalled` and v1.10's `phase_duration_typical`. Locks the contract in CI before any future regression silently widens the response surface.

### Recently Shipped (2026-05-14)
- **Typical-phase-duration benchmarks on the pacing line (v1.10 stickiness)** — `POST /api/v1/searches/status` now also returns `phase_duration_typical` (a `{ min_days, max_days }` pair for the current phase: e.g. `sourcing → 14–28`, `client_interviews → 14–28`, `offer → 5–14`). The status page's pacing line was previously anchorless — "In this phase for 18 days" left clients with no way to know if that was on-track or worrying. With v1.10 it now reads "In this phase for 18 days (typically 14–28 days)" — honest pacing benchmarks that let clients self-anchor without exposing pipeline internals. As `days_in_phase` approaches `max_days`, the same line keeps generating a fresh reason to revisit. The map lives next to `PUBLIC_STATUS_EXPLAINERS` in the API so future surfaces (status-change reminder emails, PDF status reports) can quote the same benchmarks the page shows. Negative-path test added: `phase_duration_typical` must never leak on 404, since different phases have distinct ranges that would otherwise let an anonymous caller infer a search's current phase.
- **Uniform `Cache-Control: no-store, private` on every response shape, including 404** — the header was previously set only right before the success-path `reply.send()`. Setting it unconditionally at the start of the handler closes a small but real privacy gap: a leaked cache entry on the 404 path could otherwise disclose the verified/unverified status of a `(ref, email)` pair (cached 404 → "we already tried this and it didn't work"). Test coverage updated to assert the header on every response, not just the 200 path.
- **Hide target-start countdown for terminal phases** — once a search reaches a terminal state (`placed`, `cancelled`, `closed_no_fill`), the previous status page still rendered the "(N days past target)" or "(N weeks away)" countdown next to the target-start date. On a successful placement that read as slightly punitive; on a cancelled search it was just noise. The countdown row is now suppressed entirely in terminal states, so the page reads cleanly on the days that matter most (right after a placement/cancellation/close). Pure frontend change.

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

### Recently Shipped (2026-05-06)
- **Auto-logged `interview_scheduled` activity (v1.5 stickiness)** — `PATCH /api/v1/searches/:id/candidates/:cid` now writes a redacted `search_activities` row (`'Committee interview scheduled'`, `performed_by='system'`, `related_person_id` set) when a candidate transitions *into* `'interviewing'` status. Same idempotent + PII-redacted pattern as v1.4. Three of the four remaining client-visible activity types (`status_change`, `candidate_added`, `presentation_sent`, `interview_scheduled`) are now self-populating; only `client_meeting` still requires Janet to write a row by hand. Roadmap item #5 is now down to a single remaining type.
- **"New since you last visited" indicator on status page** — the status page persists a per-search high-water mark in `localStorage` (keyed `knock.status.lastSeen.<ref>`) and on subsequent visits surfaces a banner ("X new updates since you last checked") plus per-row "New" badges and a gold accent on the headline activity card. The mark is anchored at first-load only; auto-refresh re-renders within a session intentionally do **not** bump the anchor, so a banner that appears mid-session persists until the page is closed. Rewards return visits with concrete novelty rather than a static "last updated" date.
- **Activity-type icons on the status timeline** — each timeline entry now carries a one-character glyph (`→ + ★ # ☎`) keyed to its `activity_type`, rendered in the Knock-gold marker on the left rail. Pure visual hierarchy — no API change — but it turns the timeline from a flat list into something the client can scan at a glance, reinforcing the live-dashboard feel introduced by v1.4 auto-refresh.
- **Target-start countdown on status page** — when `target_start_date` is set on a search, the status page now suffixes the date with a context-aware countdown: `(~6 weeks away)`, `(28 days away)` (urgent ≤30d), `(today)`, or `(target passed)`. Gives clients a concrete reason to revisit as the target approaches — natural urgency layered on the existing v1.2 `target_start_date` field with no API changes.

### Recently Shipped (2026-05-13)
- **Canonical `phase_explainer` in the status response (v1.9 stickiness)** — the plain-English per-phase copy ("Actively researching candidates against your school's profile — most slates take 2–4 weeks to assemble", etc.) previously lived only in `public/status.html` as a frontend constant. It now ships from `POST /api/v1/searches/status` as a `phase_explainer` field, with the status page using the API value and gracefully falling back to its local map when the field is missing. One source of truth means the planned status-change reminder emails (roadmap #4) and any future PDF status reports can quote the same phrasing the page shows — a copy edit no longer has to chase three duplicates. Negative-path test added: the field must never leak on 404.
- **`is_stalled` pacing flag + softened stall prompt on the status page (v1.9 stickiness)** — the API now flags a search as `is_stalled` when (a) it's in a progressing phase (not `placed`/`closed_no_fill`/`cancelled`/`on_hold`), (b) `activity_count_last_7d === 0`, and (c) `days_in_phase >= 14`. Both thresholds matter: a brand-new phase shouldn't trip the flag just because nothing's happened yet, and an active phase with recent chatter shouldn't trip it just because it's been the current phase a while. The status page swaps the muted "Quiet stretch — no updates this week" line for a concrete prompt ("Quiet for 18 days — reply to Janet if you'd like a check-in") in a warmer `.stalled` tone whenever the flag fires. Honest pacing for clients, and the same field is the natural trigger for the future "your search has gone quiet — want a check-in?" reminder email from roadmap #4 — pre-paving without committing to the cron yet.
- **Share-link affordance on the status page (v1.9 stickiness)** — a new "Share link" button next to Refresh emits a deep-linked URL (`/status?ref=KNK-…`) via the native Web Share API on mobile, falling back to clipboard, falling back to a window prompt. Every share is a new return-visitor surface: a board chair or search-committee member who lands on the page still has to supply their own contact email to see anything (the link itself is harmless if leaked), but each one becomes another habituated touchpoint for the engagement. Pairs naturally with v1.8's OG/Twitter preview metadata so a forwarded link looks polished in any messaging surface.
- **Print stylesheet for committee meetings (v1.9 stickiness)** — `@media print` rules hide the form, share/refresh buttons, banners, and footer chrome, and add page-break-inside protection so the status card and timeline render cleanly on paper. A client who wants to bring "where the search stands" to a committee meeting can now Cmd-P the status page and get a single, branded page instead of the messy default browser print. Small touch, but the printed artifact is its own habituation primitive — the same Knock-gold mark sits on the committee chair's desk every time the search is discussed.

### Recently Shipped (2026-05-09)
- **Activity-velocity signal on the status page (v1.8 stickiness)** — `POST /api/v1/searches/status` now returns `activity_count_last_7d`, a count of public-visible activities in the trailing 7 days (filtered to `PUBLIC_ACTIVITY_TYPES` so it can never reflect internal/commercial rows). The status page renders it as `5 updates this week` (warm gold) or `Quiet stretch — no updates this week` (muted) on a new "Activity" meta-row. With v1.3+ auto-logging populating the underlying activities for free, this is a pure surfacing change — but it converts the rich underlying timeline into a one-glance proof-of-life signal that anchors return-visit expectations: a healthy active search now has a number that *moves* between visits, and a stalled search shows it honestly so the client can prompt a check-in. Negative-path test added: the field must never appear on the 404 shape.
- **Friendly empty-state for brand-new searches (v1.8 stickiness)** — when a status check returns no public activities yet (typical on day-1/intake-phase searches before scoping kicks off), the page used to render a blank space below the pipeline stats. It now shows a small dashed-border explainer card ("Janet just got your search. Activity logs typically begin appearing within 24-48 hours…") that explicitly invites pinning the tab. Solves the day-1 visit problem where a client could land on the page, see an empty surface, and never come back. The card auto-hides the moment any timeline entry exists, so it costs nothing on mature searches.
- **Relative age on `Search opened` line + page polish for pinned/shared tabs (v1.8 stickiness)** — the "Search opened" meta-row now suffixes the absolute date with a relative-age tag (e.g. `Apr 28, 2026 (11 days ago)`), so clients get an at-a-glance sense of engagement length without doing calendar math. Same pattern as v1.6's target-start countdown but for the engagement-start anchor. Status page also gained a favicon, `theme-color: #b8860b`, OG/Twitter card meta tags, and an apple-touch-icon — so v1.3's dynamic phase-based tab title now ships with a Knock-gold mark, mobile browser chrome turns gold while the page is open, and any board member who shares the URL gets a clean preview card. Pure polish, but the cumulative effect is that pinning/sharing the status page now produces a recognizable Knock surface across every browser, OS, and chat tool.

### Recently Shipped (2026-05-08)
- **Live-computed pipeline counts + new `candidates_interviewing` field (v1.7 stickiness)** — `POST /api/v1/searches/status` now computes `candidates_identified`, `candidates_presented`, and the new `candidates_interviewing` directly from `search_candidates` via three subqueries instead of reading `searches.candidates_*` columns. Two reasons: only `candidates_identified` was being kept in sync (POST /candidates writes it back), so `candidates_presented` was reading a stale column that never moved off zero on the only surface clients see. The status page now renders a third pipeline card ("Currently interviewing") that bumps every time v1.5's `interview_scheduled` auto-log fires — closing the visual loop between "Janet logs an interview" and "the client sees a number change". Layout collapses to 2-col on narrow screens with the third card spanning both columns.
- **`search_urgency` badge on the status page** — the public response now also returns `search_urgency` (the existing intake enum: `immediate` / `standard` / `flexible`). The status page renders a small pill near the reference number — "Immediate" (red), "Standard pace" (gold), "Flexible timing" (grey). Sets honest pacing expectations from the moment the client lands on the page; an immediate-urgency client doesn't have to guess why Janet checks in often, and a flexible-timing client isn't surprised by a longer slate. Pure additive — invisible when the field is null.
- **Past-target countdown is honest about *how* past** — `target_start_date < now` previously rendered as a vague `(target passed)` tag. Now reads `(4 days past target)` / `(11 days past target)`. The exact moment a client cares about the target date is when it's slipped, and a number is more actionable than a flag. Same `.past` styling preserves the muted visual register so it doesn't read as alarm.
- **Activity-type glyph on the headline `Latest update` card** — small visual continuity fix. Each timeline row already carries an icon glyph (`→ + ★ # ☎`), but the headline activity card above the timeline didn't, so the headline read as the only iconless entry. The same `ACTIVITY_ICONS` map now powers the headline label too — the visual rhythm reads as one timeline rather than "headline + list".

### Recently Shipped (2026-05-07)
- **Direction-aware `status_change` descriptions** — the auto-logged status_change row in `PATCH /api/v1/searches/:id` previously always read "Search advanced: X → Y" regardless of direction. A pause now reads "Search paused: Sourcing → On hold", a cancellation reads "Search cancelled: …", a no-fill close reads "Search closed without placement: …", and a resume from `on_hold` reads "Search resumed: …". The verb selection lives in `describeStatusChange()` next to `PUBLIC_STATUS_PHASES` so future statuses can extend it in one place. Public-timeline copy quality directly affects how the status page reads on the days that matter most (a pause or cancellation is exactly when the client is paying attention) — the prior wording made bad news look like progress.
- **`client_meeting` write-path: `POST /api/v1/searches/:id/activities`** — closes the last roadmap item under #5: every client-visible activity type now has a write surface. The endpoint requires API auth and intentionally whitelists only `client_meeting` (the one PUBLIC_ACTIVITY_TYPES entry that isn't a side effect of another endpoint), so it cannot become a backdoor for arbitrary activity rows. Defaults `description` to `'Client meeting scheduled'` and `performed_by` to `'janet'` for terse callers. Same redaction discipline as v1.3/v1.4/v1.5: the description string is what the public status page renders verbatim. Janet now has a single MCP-friendly call to surface a forthcoming committee touchpoint on the client's timeline before it happens.
- **Status-page polish: paused phases stop showing "Step 0 of 8"** — `on_hold` and unknown statuses come back from the API with `phase_step === 0`. The previous render still drew a stub progress bar (clamped to 4%) and printed "Step 0 of 8", which read like a bug. The status page now hides the progress track and step counter when `phase_step === 0`, letting the phase label + explainer ("Search paused. Reach out to Janet…") carry the state on its own. Surgical UI fix that improves how the page reads in the exact moment a client is most likely to revisit (after a pause).

### Immediate Priority
1. **Dan rates candidates** via /assess tool — until knock_rating is populated, matching can't distinguish quality
2. **Alternative email pattern testing** — flast, firstlast for the 1,484 schools where first.last was rejected
3. **Board member email enrichment** — once board emails exist, the board-segment newsletter lists will populate
4. **Status-page email reminders** — when a search's status changes, send the client a one-line "your search just moved to X — see details at askknock.com/status?ref=…" email. Closes the loop on the new status surface. The intake response **and (as of v1.22) the status response** both expose a canonical `status_url` field — reuse that exact string in the email body so the link, the success screen, the status page, and the reminder all agree. **The auto-logged status_change row from v1.3 is the natural trigger** — a single new cron/listener can transform "new system-authored status_change activity" into an outbound email without any new business logic. The same trigger pattern now also fires for `candidate_added`, `presentation_sent`, and `interview_scheduled` — opening up "new candidate added to your pipeline" / "candidate just presented" / "committee interview scheduled" reminder emails as natural extensions. **v1.9 + v1.10 + v1.11 + v1.14 + v1.15 + v1.16 + v1.17 + v1.18 + v1.19 + v1.21 + v1.22 + v1.27 + v1.28 + v1.29 + v1.30 + v1.31 + v1.32 + v1.33 + v1.37 + v1.38 + v1.39 + v1.40 pre-paved twenty-three pieces of this:** the `phase_explainer` field gives the email body a canonical phrasing for the new phase ("your search just moved to *Sourcing candidates* — actively researching candidates against your school's profile…"), the new `phase_duration_typical` range lets the same email quote an honest expected window for the current phase ("…most slates take 14–28 days to assemble"), the v1.11 `estimated_completion_window` gives the email a forward-looking placement-window line clients can mark on a calendar ("Typical placement window: Jun 14 – Aug 11") — with the v1.27 `estimated_weeks_remaining` letting the same line quote the relative horizon as "about 6–10 weeks to placement" off the same canonical weeks the page renders, `is_stalled` is the natural trigger for a separate "your search has gone quiet — want a check-in?" weekly cron, the v1.14 `activity_count_total` lets the email quote a tangible engagement-depth number ("12 updates logged on your search so far") that grows with every send, the v1.15 full-journey overview pairs with the v1.16 `#journey-details` deep-link hash so the email can land readers on the status page with the journey section already auto-expanded and scrolled into their viewport (the hook is *already shipped* — the email just has to use the URL fragment), the v1.16 `phase_history` archive — now carrying a canonical `label` per entry as of v1.22 and a canonical `on_pace` boolean per completed entry as of v1.23 — lets the same email quote real dated milestones for prior transitions ("Sourcing ran from Apr 22 → May 04 · 12 days, on pace · Screening began May 04") without re-deriving the phase name or the pace benchmark, and the v1.17 `velocity_trend` + `activity_breakdown` give every reminder a fresh "tempo is picking up — 5 updates this week, up from 2" or "Engagement so far: 8 candidates sourced, 3 presented" line so successive reminders don't read as identical alerts even when the phase hasn't moved, and the v1.18 `next_milestone_eta` + `engagement_age_days` give every reminder a forward "next phase expected around Jun 5" anchor and a tangible "your search has been running 18 days" depth line (the latter from the same canonical integer the page shows, so no surface re-does the date math), and the v1.19 `days_until_next_milestone` lets the reminder phrase that forward anchor as a countdown ("next phase expected in ~5 days") off the same canonical integer the page renders, so each reminder reads as a continuation of the engagement's story rather than an isolated alert, and the v1.21 `phases_completed` lets every reminder quote a tangible "3 of 8 phases complete" progress line off the same canonical integer the journey summary renders (now paired with the v1.26 `phases_on_pace` so the same line can add "· all on pace" off a second canonical integer instead of re-deriving the pace tally from `phase_history` — and the v1.36 `phases_benchmarked` supplies the tally's *denominator* so the reminder can quote "3 of 3 completed phases on pace" without re-deriving the benchmarkable count either, and the v1.37 `all_phases_on_pace` boolean lets the reminder quote the "every completed phase is on pace" celebration verdict off one flag instead of re-comparing that numerator and denominator itself), and the v1.22 `status_url` gives the email body its deep-link from the same canonical string the page and success screen use (no per-surface URL assembly), and the v1.28 `placement_age_days` gives the *post-placement* reminder (the one that fires during the 90-day follow-up window) a tangible "your placement landed 14 days ago — 76 days of follow-up remain" line off the same canonical integer the placement card shows, so even after a search closes the reminder cadence has a fresh anchor to quote, and the v1.29 `days_until_target_start` lets a reminder quote the client's own deadline as a countdown ("your target start date is about 3 weeks out") off the same canonical integer the page's target-start countdown renders — with the v1.30 `weeks_until_target_start` letting that same line read in weeks ("about 6 weeks out") off one canonical integer, and the v1.30 `phases_remaining` letting a reminder add a forward "5 phases still ahead" line beside the v1.21 "3 of 8 phases complete" backward count, and the v1.31 `weeks_until_next_milestone` letting the forward next-phase anchor read in weeks ("the next phase is about 3 weeks out") off one canonical integer the page also renders, and the v1.32 `engagement_age_weeks` letting the "your search has been running …" depth line read in weeks ("about 11 weeks") off the same canonical integer the page renders for long engagements, with the v1.32 `placement_followup_weeks_remaining` letting the *post-placement* reminder phrase the follow-up countdown in weeks ("~11 weeks of follow-up remain") off one canonical integer the placement card shows, and the v1.33 `placement_age_weeks` letting that same post-placement reminder read its "your placement landed about 11 weeks ago" line in weeks off one canonical integer the placement card shows, with the v1.33 `weeks_since_last_activity` letting a quiet-week reminder phrase the recency anchor in weeks ("last update about 4 weeks ago") off the same canonical integer the Activity row renders, and the v1.38 `latest_completed_phase` gives every status-advance reminder its most natural single line — "your search just moved to *Sourcing* — *Scoping* wrapped on pace · 8 days" — off one canonical object instead of re-scanning `phase_history` for the last entry carrying a duration, and the v1.39 `phase_percent` lets every mid-phase reminder add a glanceable "about 64% through the current phase" line off one canonical integer the page's pacing parenthetical renders, so a reminder that fires while a phase is still in flight has a fresh proportional anchor to quote, and the v1.40 `is_ramping_up` gives the *first* reminder of an engagement its natural opener — "your search is ramping up — first updates logged this week" — off one canonical boolean the velocity chip already reads, so a fresh-start reminder reads as a kickoff rather than a delta against zero. Pair the email with the status page's "X new updates since you last checked" banner: clicking the email link arrives on a page that explicitly shows what's new since the last visit.
5. **Janet skill emits `client_meeting`** — the API write-path landed (`POST /api/v1/searches/:id/activities`), so the remaining work is a small Janet skill that calls it whenever Dan or the committee schedules a touchpoint. Once that skill exists, every client-visible activity type self-populates the public status timeline end-to-end with no manual SQL. Pair with item #4: the same listener that sends "your search just moved to X" can fire a "client meeting scheduled for [date]" reminder off the new row.

### Short-term (Weeks)
6. **Outreach automation** — Janet sends first-touch emails to candidates for active searches
7. **Authenticated client portal v1** — extend status page with named-finalist cards, redacted committee notes, and a place for the client to leave reactions (graduated from the email-verified status lookup)
8. **LLM enrichment at scale** — Increase batch sizes, add cost tracking

### Medium-term (Months)
9.  **LinkedIn integration** — Automated profile monitoring for career changes
10. **CRM features** — Full client relationship management
11. **Billing integration** — Invoice generation via Stripe or similar
12. **Multi-consultant** — Support for multiple search consultants beyond Dan

### Long-term
13. **Predictive transition model** — ML-based HOS transition prediction from signals
14. **Candidate self-service** — Candidates can update their own profiles
15. **Market analytics** — Public-facing industry reports to drive inbound

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
