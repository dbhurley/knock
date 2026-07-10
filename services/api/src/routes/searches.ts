import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { query, queryOne, execute } from '../lib/db.js';
import { statusUrlFor } from '../lib/urls.js';
import type { PaginatedResponse, Search, SearchCandidate } from '../types/index.js';

// ─── Validation Schemas ────────────────────────────────────────────────────

const listQuerySchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  per_page: z.coerce.number().int().min(1).max(100).default(25),
  status: z.string().optional(),
  position_category: z.string().optional(),
  school_id: z.string().uuid().optional(),
  pricing_band: z.string().optional(),
});

const createBodySchema = z.object({
  school_id: z.string().uuid(),
  position_title: z.string().min(1).max(300),
  position_category: z.string().max(50).optional(),
  position_description: z.string().optional(),
  position_requirements: z.string().optional(),
  reports_to: z.string().max(200).optional(),
  salary_range_low: z.number().int().optional(),
  salary_range_high: z.number().int().optional(),
  target_start_date: z.string().optional(),
  search_urgency: z.enum(['immediate', 'standard', 'flexible']).optional(),
  required_education: z.array(z.string()).optional(),
  required_experience_years: z.number().int().optional(),
  preferred_school_types: z.array(z.string()).optional(),
  ideal_candidate_profile: z.string().optional(),
  dealbreakers: z.string().optional(),
  client_contact_name: z.string().max(300).optional(),
  client_contact_email: z.string().email().max(300).optional(),
  client_contact_phone: z.string().max(20).optional(),
  lead_consultant: z.string().max(200).optional(),
  tags: z.array(z.string()).optional(),
  notes: z.string().optional(),
});

const updateBodySchema = createBodySchema.partial().extend({
  status: z.string().max(30).optional(),
  pricing_band: z.string().max(20).optional(),
  fee_amount: z.number().int().optional(),
  fee_status: z.string().max(30).optional(),
  deposit_amount: z.number().int().optional(),
  deposit_paid: z.boolean().optional(),
});

const candidateCreateSchema = z.object({
  person_id: z.string().uuid(),
  status: z.string().max(30).default('identified'),
  match_score: z.number().min(0).max(100).optional(),
  match_reasoning: z.string().optional(),
  source: z.string().max(50).optional(),
  referred_by: z.string().max(300).optional(),
  notes: z.string().optional(),
});

const candidateUpdateSchema = z.object({
  status: z.string().max(30).optional(),
  match_score: z.number().min(0).max(100).optional(),
  interview_feedback: z.string().optional(),
  client_feedback: z.string().optional(),
  candidate_feedback: z.string().optional(),
  rejection_reason: z.string().optional(),
  notes: z.string().optional(),
});

const candidateListSchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  per_page: z.coerce.number().int().min(1).max(100).default(25),
  status: z.string().optional(),
  min_score: z.coerce.number().min(0).max(100).optional(),
});

// Manual write-path for activity types that aren't a side effect of another
// API call. Currently the only such type clients see on the public timeline
// is 'client_meeting' — every other PUBLIC_ACTIVITY_TYPES entry is auto-logged
// elsewhere in this file. The whitelist is intentionally narrow so this
// endpoint cannot become a backdoor for arbitrary activity rows.
const WRITABLE_ACTIVITY_TYPES = ['client_meeting'] as const;
const DEFAULT_ACTIVITY_DESCRIPTIONS: Record<(typeof WRITABLE_ACTIVITY_TYPES)[number], string> = {
  client_meeting: 'Client meeting scheduled',
};
const activityCreateSchema = z.object({
  activity_type: z.enum(WRITABLE_ACTIVITY_TYPES),
  description: z.string().min(1).max(500).optional(),
  related_person_id: z.string().uuid().optional(),
  performed_by: z.string().max(200).optional(),
  metadata: z.record(z.unknown()).optional(),
});

// Public client-facing status lookup. The client supplies their search number
// and the email used at intake; we only return redacted fields that are safe
// to share with the school (no candidate PII, no internal IDs, no fees).
const publicStatusSchema = z.object({
  search_number: z.string().min(3).max(50),
  contact_email: z.string().email().max(300),
});

const PUBLIC_STATUS_PHASES: Record<string, { label: string; step: number }> = {
  intake:        { label: 'Intake review',           step: 1 },
  scoping:       { label: 'Scoping & kickoff',       step: 2 },
  sourcing:      { label: 'Sourcing candidates',     step: 3 },
  screening:     { label: 'Screening interviews',    step: 4 },
  presenting:    { label: 'Presenting finalists',    step: 5 },
  client_interviews: { label: 'Client interviews',   step: 6 },
  offer:         { label: 'Offer & negotiation',     step: 7 },
  placed:        { label: 'Placed',                  step: 8 },
  closed_no_fill:{ label: 'Closed (no placement)',   step: 8 },
  cancelled:     { label: 'Cancelled',               step: 8 },
  on_hold:       { label: 'On hold',                 step: 0 },
};

// Plain-English explainer per phase. Lives in the API (not just the status
// page's frontend map) so the same copy can render in future surfaces — the
// status-change reminder email cron from roadmap #4 needs identical wording,
// and so will the eventual PDF status reports. One source of truth means a
// future copy edit doesn't have to chase three duplicates.
const PUBLIC_STATUS_EXPLAINERS: Record<string, string> = {
  intake:            'Janet is reviewing your intake and will confirm scope before kicking off.',
  scoping:           'Aligning on the search profile, committee process, and timeline before sourcing begins.',
  sourcing:          "Actively researching candidates against your school's profile — most slates take 2–4 weeks to assemble.",
  screening:         'Speaking with prospective candidates to gauge fit, motivation, and availability.',
  presenting:        'Preparing a curated slate of finalists for committee review.',
  client_interviews: 'Committee is meeting with finalists. Janet is collecting feedback after each round.',
  offer:             'Finalist selected. Negotiating offer terms, references, and start date.',
  placed:            "Placement complete. Janet stays in touch through the candidate's first 90 days.",
  closed_no_fill:    "Search closed without a placement. Reach out if you'd like to debrief or restart.",
  cancelled:         "Search cancelled at the school's request.",
  on_hold:           "Search paused. Reach out to Janet when you're ready to resume.",
};

// A progressing search is "stalled" when the public-visible timeline has been
// quiet for a full week *and* the current phase has dragged for two weeks.
// Both thresholds matter: a fresh phase shouldn't trigger the flag just
// because no activities have happened yet, and an active phase with recent
// chatter shouldn't trigger it just because it's been the current phase a while.
// Terminal/non-progressing states (placed, closed_no_fill, cancelled, on_hold)
// are never stalled — their lack of activity is the expected end-state. The
// "quiet for a full week" half of the test is carried by activity_count_last_7d
// (a fixed 7-day window) rather than a separate threshold constant.
const STALL_PHASE_DAYS = 14;

// Typical duration (in days) for each progressing phase. Drawn from the same
// pacing the explainer copy already commits to ("most slates take 2–4 weeks
// to assemble" → sourcing: 14–28). Surfacing this alongside `days_in_phase`
// turns the pacing line from "you've been here 18 days" (anchorless) into
// "18 days in phase (typically 14–28)" — concrete, honest pacing that lets
// the client self-anchor without exposing pipeline internals. Terminal /
// non-progressing phases intentionally have no typical duration.
const PUBLIC_STATUS_TYPICAL_DURATION: Record<string, { min_days: number; max_days: number }> = {
  intake:            { min_days: 1,  max_days: 5  },
  scoping:           { min_days: 5,  max_days: 14 },
  sourcing:          { min_days: 14, max_days: 28 },
  screening:         { min_days: 10, max_days: 21 },
  presenting:        { min_days: 3,  max_days: 10 },
  client_interviews: { min_days: 14, max_days: 28 },
  offer:             { min_days: 5,  max_days: 14 },
};

// Forward order of progressing phases — used to compute the "next milestone"
// label clients see on the status page. Terminal/non-progressing states
// (placed, closed_no_fill, cancelled, on_hold) intentionally have no next.
const PUBLIC_STATUS_FORWARD: string[] = [
  'intake', 'scoping', 'sourcing', 'screening',
  'presenting', 'client_interviews', 'offer', 'placed',
];

// The total number of phases in a complete search journey. Derived from the
// forward-phase list so the response's `phase_total`, the phases_completed /
// phases_remaining counts, and a placement's "whole journey" tally all read
// from one source — a future phase added to PUBLIC_STATUS_FORWARD updates
// every downstream count at once instead of leaving a hardcoded `8` behind.
const PHASE_TOTAL = PUBLIC_STATUS_FORWARD.length;

// Milliseconds in a day. The status handler does day-granularity date math in
// ~10 places (days_in_phase, days_since_last_activity, engagement_age_days,
// each phase_history duration, placement_age_days, the completion-window and
// next-milestone ETA projections, the target-start countdown). They all
// open-coded the same `86_400_000` literal; naming it once means the ms→days
// unit lives in a single place. Pure readability/one-source-of-truth hygiene —
// byte-identical to the literal — matching the PHASE_TOTAL and
// TARGET_TERMINAL_STATUSES constant hoists.
const DAY_MS = 86_400_000;

// A search is "progressing" when it's in one of the forward phases but hasn't
// yet reached the `placed` terminal — i.e. still moving toward a placement.
// This exact predicate (`in the forward list AND not placed`) gates every
// forward-looking field on the status response: days_in_phase, is_stalled,
// current_phase_on_pace, the next-milestone ETA, and the completion window all
// only make sense while the search is still in flight. It was open-coded in
// four places; centralising it means a future phase-model change can't leave
// one of those fields using a subtly different notion of "still progressing".
// Same one-source-of-truth rationale as the daysToWeeks() and PHASE_TOTAL
// extractions — pure refactor, byte-identical to the inline expression.
function isProgressingPhase(status: string): boolean {
  return PUBLIC_STATUS_FORWARD.includes(status) && status !== 'placed';
}

// A search is on a "forward" phase when it's anywhere in the journey list —
// including the terminal `placed`, unlike isProgressingPhase() which excludes
// it. This is the exact predicate that gates the phase *count* fields
// (phases_completed, phases_on_pace, phases_benchmarked): a successful
// placement has finished phases to tally, but is no longer progressing. It was
// open-coded as `PUBLIC_STATUS_FORWARD.includes(status)` in three places;
// naming it makes the "forward incl. placed" vs "progressing excl. placed"
// distinction explicit so the two notions can't be confused at a call site.
// Same one-source-of-truth rationale as isProgressingPhase() — pure refactor,
// byte-identical to the inline expression.
function isForwardPhase(status: string): boolean {
  return PUBLIC_STATUS_FORWARD.includes(status);
}

// Length of Janet's post-placement follow-up window. The explainer copy
// already commits to "Janet stays in touch through the candidate's first
// 90 days" — surfacing the exact remaining-days countdown turns the
// post-placement period from a silent surface into one with concrete
// future dates the client can mark on a calendar. The status page stays
// useful for 90 days *after* the search closes, not just during it.
const PLACEMENT_FOLLOWUP_DAYS = 90;

// Terminal states in which the target-start countdown is suppressed: once a
// search is placed, cancelled, or closed without a fill, a "(3 weeks away)"
// countdown to the client's target start date is either moot or misleading.
// Module-level (like PUBLIC_ACTIVITY_TYPES) so it isn't re-allocated on every
// status request — same hoist-the-constant hygiene as PHASE_TOTAL.
const TARGET_TERMINAL_STATUSES = new Set(['placed', 'cancelled', 'closed_no_fill']);

// Compute the progress-bar fill percentage. Forward progressing phases
// get intra-phase smoothing (using `days_in_phase` against the typical
// max) so the bar moves day-to-day rather than jumping 12.5% at phase
// boundaries. A single phase typically runs 2–4 weeks, so without this
// the bar reads as static for most of an engagement — exactly the
// window when each return visit needs a fresh visible signal.
// Terminal phases keep the simple step/8 mapping: the frontend hides the
// bar for negative-terminals (cancelled, closed_no_fill); `placed`
// renders at a flat 100% as the celebration cap.
function computeProgressPercent(
  phaseStep: number,
  status: string,
  daysInPhase: number | null,
): number {
  if (phaseStep <= 0) return 0;
  if (isProgressingPhase(status)) {
    const typical = PUBLIC_STATUS_TYPICAL_DURATION[status];
    let intra = 0;
    if (typical && typeof daysInPhase === 'number' && daysInPhase >= 0) {
      intra = Math.min(1, daysInPhase / typical.max_days);
    }
    const combined = ((phaseStep - 1) + intra) / PHASE_TOTAL;
    return Math.max(0, Math.min(100, Math.round(combined * 100)));
  }
  return Math.min(100, Math.round((phaseStep / PHASE_TOTAL) * 100));
}

// Sum the typical duration of the remaining progressing phases (including the
// unused portion of the current phase) to produce a concrete completion-window
// range the client can mark on a calendar. Compounding stickiness primitive:
// every visit shows two dates, the dates stay stable across visits so the
// client builds an anchor, and as `days_in_phase` rises past the typical-max
// the upper bound walks forward — giving the same client a fresh reason to
// revisit when the window is about to slip. Returns null for terminal /
// non-progressing states (placed, cancelled, closed_no_fill, on_hold) where
// a forward-looking estimate is either meaningless or misleading.
//
// Returns both the ISO date pair (`estimated_completion_window`) and the raw
// day counts the dates were derived from. The integers are the canonical
// source the planned reminder email / PDF (roadmap #4) can quote as
// "about 6–10 weeks to placement" without re-deriving a day-count from the
// ISO dates — same one-source-of-truth rationale as engagement_age_days and
// days_until_next_milestone.
function computeCompletionWindow(
  currentStatus: string,
  daysInPhase: number | null,
  nowMs: number,
): { earliest: string; latest: string; min_days: number; max_days: number } | null {
  const idx = PUBLIC_STATUS_FORWARD.indexOf(currentStatus);
  // Skip terminal/unknown statuses (and `placed`, which is already done).
  if (idx < 0 || currentStatus === 'placed') return null;
  const remaining = PUBLIC_STATUS_FORWARD.slice(idx, -1); // exclude 'placed'
  let minDaysLeft = 0;
  let maxDaysLeft = 0;
  for (let i = 0; i < remaining.length; i++) {
    const phase = remaining[i];
    const span = PUBLIC_STATUS_TYPICAL_DURATION[phase];
    if (!span) return null;
    if (i === 0) {
      // For the current phase, subtract days already spent so the window
      // reflects how much of this phase still remains. Floor at zero so an
      // over-typical phase doesn't push the lower bound negative.
      const spent = Math.max(0, daysInPhase ?? 0);
      minDaysLeft += Math.max(0, span.min_days - spent);
      maxDaysLeft += Math.max(0, span.max_days - spent);
    } else {
      minDaysLeft += span.min_days;
      maxDaysLeft += span.max_days;
    }
  }
  return {
    earliest: new Date(nowMs + minDaysLeft * DAY_MS).toISOString(),
    latest:   new Date(nowMs + maxDaysLeft * DAY_MS).toISOString(),
    min_days: minDaysLeft,
    max_days: maxDaysLeft,
  };
}

// Canonical days→weeks rounding, shared by every weeks-valued status field
// (estimated_weeks_remaining, weeks_until_next_milestone, weeks_until_target_start,
// engagement_age_weeks, placement_followup_weeks_remaining, placement_age_weeks,
// weeks_since_last_activity). The status page
// applies exactly this `Math.max(1, Math.round(days / 7))` inline when it shows
// a span in weeks; centralising it here means the rounding lives in one place
// instead of being open-coded per field, so a future tweak can't leave one
// field rounding differently from the others. Same one-source-of-truth rationale as the v1.18 statusUrlFor()
// and v1.31 PHASE_TOTAL extractions — and it's byte-identical to the prior inline
// math (the floor-at-1 is a no-op everywhere the result was already ≥ 1).
function daysToWeeks(days: number): number {
  return Math.max(1, Math.round(days / 7));
}

// Activity types we surface to clients. Internal-only types (e.g. fee_paid,
// note_added) are filtered out so we never leak commercial or candidate detail.
const PUBLIC_ACTIVITY_TYPES = new Set([
  'status_change',
  'candidate_added',
  'presentation_sent',
  'interview_scheduled',
  'client_meeting',
]);

// Pick a description verb that actually fits the transition. Earlier code
// always wrote "Search advanced: X → Y" — fine for forward progress, badly
// wrong on the public timeline for "Sourcing → On hold" or "→ Cancelled".
// Branches are ordered most-specific first so terminal/pause states win
// over the default forward-progression label.
function describeStatusChange(fromStatus: string, toStatus: string): string {
  const fromLabel = PUBLIC_STATUS_PHASES[fromStatus]?.label ?? fromStatus;
  const toLabel = PUBLIC_STATUS_PHASES[toStatus]?.label ?? toStatus;
  if (toStatus === 'on_hold')        return `Search paused: ${fromLabel} → ${toLabel}`;
  if (toStatus === 'cancelled')      return `Search cancelled: ${fromLabel} → ${toLabel}`;
  if (toStatus === 'closed_no_fill') return `Search closed without placement: ${fromLabel} → ${toLabel}`;
  if (fromStatus === 'on_hold')      return `Search resumed: ${fromLabel} → ${toLabel}`;
  return `Search advanced: ${fromLabel} → ${toLabel}`;
}

// ─── Routes ────────────────────────────────────────────────────────────────

export default async function searchRoutes(app: FastifyInstance): Promise<void> {

  // POST /api/v1/searches/status — Public status lookup (no API key)
  // Clients verify ownership by supplying their search number plus the
  // contact email captured at intake. Returns 404 on any mismatch so we
  // don't disclose whether a search exists.
  app.post('/api/v1/searches/status', async (request, reply) => {
    const body = publicStatusSchema.parse(request.body);

    // Personalized client data — never cache in shared/CDN/browser caches,
    // including on the 404 path. Setting the header up front keeps the
    // privacy contract uniform: a leaked cache entry on *any* response shape
    // could disclose the verified/unverified status of a (ref, email) pair.
    reply.header('Cache-Control', 'no-store, private');

    // Pipeline counts are computed live from search_candidates rather than
    // read off the searches.candidates_* columns. Two reasons: (a) only
    // candidates_identified is currently kept in sync (POST /candidates writes
    // it back), so candidates_presented/candidates_interviewed would otherwise
    // sit at 0 forever on the one surface clients actually see; (b) a single
    // FILTER subquery is cheap and atomic, so the three numbers are always
    // mutually consistent with each other and with the redacted timeline above.
    const row = await queryOne<{
      id: string;
      search_number: string;
      position_title: string;
      status: string;
      status_changed_at: string;
      created_at: string;
      target_start_date: string | null;
      search_urgency: string | null;
      candidates_identified: number;
      candidates_presented: number;
      candidates_interviewing: number;
      school_name: string | null;
      school_city: string | null;
      school_state: string | null;
      client_contact_email: string | null;
    }>(
      `SELECT s.id, s.search_number, s.position_title, s.status, s.status_changed_at,
              s.created_at, s.target_start_date, s.search_urgency,
              (SELECT COUNT(*) FROM search_candidates WHERE search_id = s.id)::int
                AS candidates_identified,
              (SELECT COUNT(*) FROM search_candidates
                 WHERE search_id = s.id AND presented_at IS NOT NULL)::int
                AS candidates_presented,
              (SELECT COUNT(*) FROM search_candidates
                 WHERE search_id = s.id AND status = 'interviewing')::int
                AS candidates_interviewing,
              sch.name AS school_name, sch.city AS school_city, sch.state AS school_state,
              s.client_contact_email
       FROM searches s
       LEFT JOIN schools sch ON sch.id = s.school_id
       WHERE s.search_number = $1`,
      [body.search_number],
    );

    const expectedEmail = row?.client_contact_email?.trim().toLowerCase();
    const providedEmail = body.contact_email.trim().toLowerCase();
    if (!row || !expectedEmail || expectedEmail !== providedEmail) {
      return reply.code(404).send({
        error: 'Not found',
        message: 'No search matches that reference number and email. Double-check both, or reply to your last note from Janet.',
      });
    }

    // One request-time instant drives every relative-time field below
    // (days_in_phase, next_milestone_eta, estimated_completion_window,
    // engagement_age_days, days_since_last_activity, the placement countdown).
    // Sharing a single `nowMs` means these fields are computed against the same
    // moment, so a request that happens to straddle a UTC day boundary can't
    // hand back internally-inconsistent day counts — the same "can never drift"
    // discipline the estimated_completion_window / estimated_days_remaining pair
    // already follows by sharing one computeCompletionWindow() call.
    const nowMs = Date.now();

    const phase = PUBLIC_STATUS_PHASES[row.status] ?? { label: row.status, step: 0 };

    // Typical-duration benchmark for the *current* phase, resolved once. The
    // same PUBLIC_STATUS_TYPICAL_DURATION[row.status] lookup was previously
    // repeated across current_phase_on_pace, phase_percent, the next-milestone
    // ETA, and the phase_duration_typical response field — this hoist gives
    // them one shared value, matching the handler's "compute once" hygiene
    // (nowMs, the resolved search id, the single GROUP BY scan). Null for
    // terminal/non-progressing phases with no typical duration; byte-identical
    // to the prior per-site `?? null` lookups.
    const currentPhaseTypical = PUBLIC_STATUS_TYPICAL_DURATION[row.status] ?? null;

    // Compute the next milestone (label only — clients don't see internal codes).
    const forwardIdx = PUBLIC_STATUS_FORWARD.indexOf(row.status);
    const nextStatus = forwardIdx >= 0 && forwardIdx < PUBLIC_STATUS_FORWARD.length - 1
      ? PUBLIC_STATUS_FORWARD[forwardIdx + 1]
      : null;
    const nextMilestoneLabel = nextStatus
      ? PUBLIC_STATUS_PHASES[nextStatus]?.label ?? null
      : null;

    // progressPercent is computed after daysInPhase below so it can include
    // intra-phase smoothing — see computeProgressPercent().

    // Recent client-visible activity. Filtering inside SQL keeps internal
    // notes and commercial activity out of the response by construction.
    // We return up to 5 so the status page can render a small timeline —
    // each return visit feels richer than "one stale last update".
    const activityTypes = Array.from(PUBLIC_ACTIVITY_TYPES);
    const activities = await query<{
      activity_type: string;
      description: string | null;
      created_at: string;
    }>(
      `SELECT activity_type, description, created_at
       FROM search_activities
       WHERE search_id = $1
         AND activity_type = ANY($2::text[])
       ORDER BY created_at DESC
       LIMIT 5`,
      [row.id, activityTypes],
    );

    const latest = activities[0] ?? null;

    // 7-day public-activity count — concrete proof-of-life on the status page.
    // The page renders this as "5 updates this week" / "Quiet stretch — no
    // updates this week", which gives clients a real reason to feel the
    // pipeline is alive (or to prompt a check-in if it isn't). Filtered to
    // PUBLIC_ACTIVITY_TYPES to match what's already visible in recent_activities,
    // so the number can never include internal/commercial rows.
    //
    // `activity_count_total` is the cumulative count since the search opened
    // — a monotonically-increasing number that gives the client a tangible
    // metric of engagement depth. Pairs with v1.8's weekly count and v1.13's
    // days_since_last_activity to give the Activity row three honest anchors:
    // weekly tempo, exact recency, and cumulative depth.
    //
    // `activity_count_prev_7d` is the count for the *previous* 7-day window
    // (days [-14, -7) relative to now). Pairs with the current-week count to
    // give the page a real week-over-week trend signal: "5 updates this week
    // · up from 2" creates a fresh visible signal each time the tempo shifts,
    // even when the weekly absolute count happens to be unchanged.
    //
    // The per-type breakdown, the cumulative total, and both 7-day windows are
    // all derived from a single GROUP BY scan of the same rows: each group row
    // carries its own count plus windowed FILTER counts, and the totals are the
    // column sums in JS. One round-trip instead of two, and — because the
    // breakdown total is literally the sum of the per-type counts — every number
    // on the Activity surface stays mutually consistent by construction. The
    // window boundaries are anchored to the request-time `nowMs` (passed as
    // $3), not SQL NOW(), so they share the same instant as days_in_phase /
    // days_since_last_activity and a request straddling a UTC day boundary can't
    // hand back a 7-day count that disagrees with the recency anchor beside it.
    const nowIso = new Date(nowMs).toISOString();
    const breakdownRows = await query<{
      activity_type: string;
      n: string;
      last_7d: string;
      prev_7d: string;
    }>(
      `SELECT activity_type,
              COUNT(*)::text AS n,
              COUNT(*) FILTER (WHERE created_at >= $3::timestamptz - INTERVAL '7 days')::text AS last_7d,
              COUNT(*) FILTER (WHERE created_at >= $3::timestamptz - INTERVAL '14 days'
                                 AND created_at <  $3::timestamptz - INTERVAL '7 days')::text AS prev_7d
       FROM search_activities
       WHERE search_id = $1
         AND activity_type = ANY($2::text[])
       GROUP BY activity_type`,
      [row.id, activityTypes, nowIso],
    );
    // Per-type breakdown — types with a zero count are seeded so the frontend
    // can decide what to show. The three scalar counts are the column sums.
    const activityBreakdown: Record<string, number> = {};
    for (const t of PUBLIC_ACTIVITY_TYPES) activityBreakdown[t] = 0;
    let activityCountTotal = 0;
    let activityCountLast7d = 0;
    let activityCountPrev7d = 0;
    for (const r of breakdownRows) {
      const n = parseInt(r.n, 10);
      activityBreakdown[r.activity_type] = n;
      activityCountTotal += n;
      activityCountLast7d += parseInt(r.last_7d, 10);
      activityCountPrev7d += parseInt(r.prev_7d, 10);
    }

    // Categorical week-over-week trend. The thresholds are deliberately
    // generous: a "trend" only fires when both numbers are non-trivial AND
    // the change is at least 2 (small day-to-day noise shouldn't read as a
    // surge or drop). 'quiet' is the only label that fires on a zero week
    // when the prior week was also zero — otherwise low-activity weeks would
    // always read as a "drop" and visually punish the client. The frontend
    // can use these labels to swap one short visible chip ("up from 2 last
    // week" / "steady" / "down from 5 last week") without doing the math.
    let velocityTrend: 'accelerating' | 'steady' | 'cooling' | 'quiet';
    const delta = activityCountLast7d - activityCountPrev7d;
    if (activityCountLast7d === 0 && activityCountPrev7d === 0) velocityTrend = 'quiet';
    else if (delta >= 2)        velocityTrend = 'accelerating';
    else if (delta <= -2)       velocityTrend = 'cooling';
    else                        velocityTrend = 'steady';

    // Canonical "the pipeline just came alive this week" flag — true on a
    // progressing search whose previous 7-day window was empty but whose
    // current one has activity (activity_count_prev_7d === 0 && activity_count_
    // last_7d > 0). It's the precise condition the status page uses to swap the
    // velocity chip's "up from 0" for the friendlier "ramping up" copy, which
    // it previously derived client-side from the raw prev-window count. Note
    // this is broader than velocity_trend === 'accelerating': a first week with
    // a single update lands the trend on 'steady' (delta 1 < the ±2 dead-band)
    // yet is still genuinely a ramp from quiet, so a lone client-side
    // `prev === 0` check inside the accelerating branch under-fired. Surfacing
    // the boolean makes that read one source of truth (same rationale as
    // current_phase_on_pace / velocity_trend): the planned reminder email / PDF
    // (roadmap #4) can open a first-activity note ("your search is ramping up —
    // first updates logged this week") off the same flag the chip uses instead
    // of re-deriving it. False in terminal/non-progressing states and whenever
    // there was prior-week activity, so a mid-engagement resume-after-quiet
    // still reads through the ordinary velocity_trend rather than a fresh-start
    // ramp. The status page prefers this field and falls back to the local
    // prev-window check only on older API versions.
    const isRampingUp = isProgressingPhase(row.status)
      && activityCountPrev7d === 0
      && activityCountLast7d > 0;

    // Time spent in the current phase — a simple, honest pacing signal.
    // Only computed when status_changed_at is populated and the search is
    // still in a progressing phase (terminal/non-progressing → null).
    let daysInPhase: number | null = null;
    if (row.status_changed_at && isProgressingPhase(row.status)) {
      const ms = nowMs - new Date(row.status_changed_at).getTime();
      if (!Number.isNaN(ms) && ms >= 0) {
        daysInPhase = Math.floor(ms / DAY_MS);
      }
    }

    // Days since the most recent client-visible activity. Pairs with
    // `activity_count_last_7d` + `is_stalled` to give the status page a
    // concrete anchor on the "Activity" row: "Latest update: 3 days ago"
    // instead of just relying on the timeline's relative-time formatter.
    // Same redaction discipline — derived from `latest.created_at`, which
    // is already part of the public response. Null when there are no
    // public-visible activities yet (typical on day-1 searches).
    let daysSinceLastActivity: number | null = null;
    if (latest?.created_at) {
      const ms = nowMs - new Date(latest.created_at).getTime();
      if (!Number.isNaN(ms) && ms >= 0) {
        daysSinceLastActivity = Math.floor(ms / DAY_MS);
      }
    }

    // Canonical weeks rounding of days_since_last_activity — the recency anchor
    // the velocity row renders as "· latest N days ago". On a long-quiet (but
    // not stalled) or post-placement search "latest 30 days ago" scans worse
    // than "latest ~4 weeks ago", so the page reads it in weeks past a fortnight
    // — the same convention engagement_age_weeks / placement_age_weeks already
    // use for their age tags. Surfacing the integer here makes that read one
    // source of truth (the planned reminder email / PDF can quote it too) rather
    // than another inline frontend days→weeks conversion. Null under a fortnight,
    // where the page still shows exact days, and null when there's no public
    // activity yet — mirroring days_since_last_activity.
    let weeksSinceLastActivity: number | null = null;
    if (daysSinceLastActivity !== null && daysSinceLastActivity >= 14) {
      weeksSinceLastActivity = daysToWeeks(daysSinceLastActivity);
    }

    // Honest stall signal: progressing phase, no public activity in a week,
    // and the same phase has been the current phase for two-plus weeks. The
    // status page uses this to soften "Quiet stretch" into a concrete prompt
    // for the client to nudge Janet. Pre-paves the email-reminder cron from
    // roadmap #4 (a "your search has gone quiet — want a check-in?" message
    // is exactly what should fire when this trips).
    const isStalled = isProgressingPhase(row.status)
      && activityCountLast7d === 0
      && typeof daysInPhase === 'number'
      && daysInPhase >= STALL_PHASE_DAYS;

    // Canonical "is the current phase still on pace?" flag — the positive
    // companion to is_stalled, mirroring the per-completed-phase on_pace field
    // in phase_history (v1.23). Completed phases already earn an "on pace" tag
    // on the journey archive, but the *current* in-flight phase — the one a
    // return visitor cares about most — had no canonical comparative signal:
    // the status page rendered "18 days in phase (typically 14–28 days)" and
    // left the client to do the comparison. true when the current progressing
    // phase's days_in_phase is at or within its typical-max benchmark, false
    // once it slips past, null for terminal/non-progressing/placed phases or
    // any phase without a typical duration (same null-semantics as the
    // phase_history on_pace flag). One source of truth: the planned reminder
    // email / PDF (roadmap #4) can quote "Sourcing is on pace — 18 of a
    // typical 14–28 days" off this boolean instead of re-deriving the benchmark.
    let currentPhaseOnPace: boolean | null = null;
    if (typeof daysInPhase === 'number' && isProgressingPhase(row.status)) {
      if (currentPhaseTypical) currentPhaseOnPace = daysInPhase <= currentPhaseTypical.max_days;
    }

    // Canonical within-current-phase completion percent (0–100). It's the
    // intra-phase fraction computeProgressPercent already blends into the
    // whole-journey bar (days_in_phase against the phase's typical-max),
    // surfaced on its own so a consumer can answer "how far through *this*
    // phase am I?" — a genuinely distinct signal from progress_percent (the
    // whole 8-phase journey) and from days_in_phase (which is anchorless
    // without dividing by the typical max). Clamped to [0, 100] so an
    // over-typical phase caps at 100 rather than running past it. One source
    // of truth: the status page can render "~64% through this phase" on the
    // pacing line, and the planned reminder email / PDF (roadmap #4) can quote
    // the same integer instead of re-deriving it from days_in_phase and the
    // typical range. Null in exactly the same states as current_phase_on_pace
    // — terminal/non-progressing/placed phases, or any phase without a typical
    // duration — so a paused or closed search never reads a misleading percent.
    let phasePercent: number | null = null;
    if (typeof daysInPhase === 'number' && isProgressingPhase(row.status)) {
      if (currentPhaseTypical) {
        phasePercent = Math.round(Math.min(1, Math.max(0, daysInPhase / currentPhaseTypical.max_days)) * 100);
      }
    }

    const progressPercent = computeProgressPercent(phase.step, row.status, daysInPhase);

    // One computation drives two response fields: the ISO date pair the page
    // renders as a calendar-markable window, and the canonical integer day
    // range the planned reminder email / PDF can quote ("about 6–10 weeks to
    // placement") without re-deriving from the dates.
    const completionWindow = computeCompletionWindow(row.status, daysInPhase, nowMs);
    const estimatedDaysRemaining = completionWindow
      ? { min_days: completionWindow.min_days, max_days: completionWindow.max_days }
      : null;

    // Canonical weeks-remaining range — the same horizon estimated_days_remaining
    // carries, pre-rounded to the weeks the status page already renders as
    // "(about 6–10 weeks out)". That weeks conversion previously lived only in
    // the frontend's fmtSpan(), so the planned reminder email / PDF (roadmap #4)
    // would have had to re-implement the days→weeks rounding to quote the same
    // horizon the page shows — a drift risk the days-only integer pair didn't
    // close. Surfacing the weeks here makes them one source of truth (same
    // rationale as estimated_days_remaining and engagement_age_days). Null when
    // the window is null or under a fortnight, where the page shows days rather
    // than weeks; rounding mirrors fmtSpan exactly so the two never disagree.
    let estimatedWeeksRemaining: { min_weeks: number; max_weeks: number } | null = null;
    if (estimatedDaysRemaining && estimatedDaysRemaining.max_days >= 14) {
      const minWeeks = daysToWeeks(estimatedDaysRemaining.min_days);
      const maxWeeks = Math.max(minWeeks, daysToWeeks(estimatedDaysRemaining.max_days));
      estimatedWeeksRemaining = { min_weeks: minWeeks, max_weeks: maxWeeks };
    }

    // Expected start date of the *next* phase — a near-term, single-date
    // anchor that complements the v1.11 cumulative completion window (which
    // is the far end of the same calculation). Computed as now + however much
    // of the current phase's typical-max duration still remains, floored at
    // zero so an over-typical phase reads as "any day now" rather than a past
    // date. Only meaningful for progressing phases that have a next phase:
    // null for terminal/non-progressing states and for `placed`. Gives the
    // client one concrete date to look forward to between visits, closer in
    // than the placement window — a fresh reason to revisit as it approaches.
    //
    // `days_until_next_milestone` is the same calculation expressed as a
    // canonical server-computed integer (the count of typical-max days still
    // remaining in the current phase). Same one-source-of-truth rationale as
    // engagement_age_days: the status page can render a glanceable "in ~5
    // days" countdown that decrements daily (a fresh reason to revisit), and
    // the planned reminder email / PDF can quote the same integer instead of
    // re-deriving it from the ISO date. Zero means "any day now" — the phase
    // has reached or passed its typical max. Null whenever the ETA is null.
    let nextMilestoneEta: string | null = null;
    let daysUntilNextMilestone: number | null = null;
    if (nextStatus && isProgressingPhase(row.status)) {
      if (currentPhaseTypical) {
        const remaining = Math.max(0, currentPhaseTypical.max_days - Math.max(0, daysInPhase ?? 0));
        nextMilestoneEta = new Date(nowMs + remaining * DAY_MS).toISOString();
        daysUntilNextMilestone = remaining;
      }
    }

    // Canonical weeks rounding of the next-milestone countdown — the same
    // days→weeks conversion the status page applies inline (`Math.max(1,
    // Math.round(days / 7))`) to render "(in ~3 weeks)" once the countdown is
    // at or past a fortnight. That inline rounding was the last client-side
    // days→weeks read left on the page after v1.30 canonicalized the
    // target-start one; surfacing the weeks integer here makes it one source
    // of truth, so the planned reminder email / PDF (roadmap #4) can quote
    // "the next phase is about 3 weeks out" off the same integer the page
    // shows. Same rationale and threshold as estimated_weeks_remaining (v1.27):
    // null whenever the page shows days rather than weeks — i.e. when there's
    // no countdown at all or when the next phase is close in (< 14 days, where
    // the page renders the exact "(in ~N days)"). The page prefers this field
    // and falls back to local rounding only on older API versions.
    let weeksUntilNextMilestone: number | null = null;
    if (typeof daysUntilNextMilestone === 'number' && daysUntilNextMilestone >= 14) {
      weeksUntilNextMilestone = daysToWeeks(daysUntilNextMilestone);
    }

    // Canonical server-computed count of phases the search has finished.
    // The status page already derives this client-side for its collapsed
    // journey summary ("3 of 8 phases complete"), but surfacing it from the
    // API makes it the single source of truth — the planned status-change
    // reminder email (roadmap #4) and future PDF status reports can quote the
    // same "3 of 8 phases complete" the page shows instead of re-deriving it
    // from phase_step. Same one-source-of-truth rationale as engagement_age_days
    // and days_until_next_milestone. A successful placement counts the whole
    // journey; for an in-flight progressing phase it's the steps strictly
    // before the current one. Null for non-progressing/negative-terminal
    // states (on_hold, cancelled, closed_no_fill), where "N phases complete"
    // would misrepresent a pause or a close-without-placement as progress —
    // the status page hides the journey overview for those states anyway.
    let phasesCompleted: number | null = null;
    if (row.status === 'placed') {
      phasesCompleted = PHASE_TOTAL; // journey fully complete
    } else if (isForwardPhase(row.status)) {
      phasesCompleted = Math.max(0, phase.step - 1);
    }

    // Canonical count of phases the search has *not* yet finished — the
    // forward-looking complement to phases_completed, defined so the two
    // always sum to the full 8-phase journey (phases_completed + phases_remaining
    // === phase_total). For an in-flight progressing phase this includes the
    // current phase (it isn't complete yet); a successful placement leaves
    // zero remaining. Null in exactly the same non-progressing/negative-terminal
    // states as phases_completed (on_hold, cancelled, closed_no_fill), where a
    // "N to go" count would misrepresent a paused or closed-without-placement
    // search as still on track. Same one-source-of-truth rationale as
    // phases_completed and phases_on_pace: the planned status-change reminder
    // email / PDF (roadmap #4) can quote "5 phases still ahead" off the same
    // integer instead of re-deriving phase_total − phases_completed itself.
    const phasesRemaining: number | null =
      phasesCompleted === null ? null : PHASE_TOTAL - phasesCompleted;

    // Canonical server-computed engagement length (days since the search
    // opened). The status page already derives this client-side for its
    // "(11 days ago)" tag, but surfacing it from the API makes it the single
    // source of truth — the planned status-change reminder email (roadmap #4)
    // and future PDF status reports can quote the same "your search has been
    // running 18 days" number the page shows, instead of each surface doing
    // its own date math. Same one-source-of-truth rationale as v1.9's
    // phase_explainer. Null when created_at is missing or unparseable.
    let engagementAgeDays: number | null = null;
    if (row.created_at) {
      const ms = nowMs - new Date(row.created_at).getTime();
      if (!Number.isNaN(ms) && ms >= 0) engagementAgeDays = Math.floor(ms / DAY_MS);
    }

    // Canonical weeks rounding of engagement_age_days — the days→weeks read for
    // the "Search opened … (N weeks ago)" tag. The 10–16-week engagement is the
    // stickiness window CLAUDE.md keeps returning to, and on a long-running
    // search "(80 days ago)" scans worse than "(~11 weeks ago)". Surfacing the
    // weeks integer makes that read one source of truth (same rationale and
    // fortnight threshold as estimated_weeks_remaining / weeks_until_next_milestone /
    // weeks_until_target_start): the planned reminder email / PDF (roadmap #4) can
    // quote "your search has been running about 11 weeks" off the same integer the
    // page renders. Null under a fortnight, where the page still shows exact days.
    let engagementAgeWeeks: number | null = null;
    if (engagementAgeDays !== null && engagementAgeDays >= 14) {
      engagementAgeWeeks = daysToWeeks(engagementAgeDays);
    }

    // Phase-transition history. Drawn from the `status_change` rows in
    // search_activities (one per actual transition, auto-logged by the v1.3
    // PATCH /api/v1/searches/:id handler) plus a synthetic initial entry at
    // `searches.created_at` for whatever phase the search opened in. Sorted
    // ascending and de-duplicated on the (phase) key — same phase visited
    // twice in a row collapses to the first entry, since `entered_at` for
    // the journey overview means "first arrival in this phase". Hidden on
    // 404 like every other personalized field.
    //
    // What it unlocks on the status page: the full-journey overview can
    // render real dated milestones on completed phases ("Sourcing · Apr 22"
    // instead of just a checkmark). A long engagement (10–16 weeks) ends up
    // as a permanent dated archive the client can scroll back through —
    // every successful transition becomes a dated artifact, not just an
    // ephemeral "step 5 of 8" cursor. Compounds with v1.5's new-since-last-
    // visit indicator (which surfaces *recent* changes) by giving the
    // *historical* changes equal visual weight.
    const phaseTransitions = await query<{
      from_phase: string | null;
      to_phase: string;
      entered_at: string;
    }>(
      `SELECT (metadata->>'from') AS from_phase,
              (metadata->>'to')   AS to_phase,
              created_at          AS entered_at
       FROM search_activities
       WHERE search_id = $1
         AND activity_type = 'status_change'
         AND metadata ? 'to'
       ORDER BY created_at ASC`,
      [row.id],
    );
    // Map (phase → first-entered-at). Same phase visited twice in a row
    // (e.g. paused → resumed) collapses to the first arrival so the journey
    // overview's dated milestones reflect when each phase first began.
    const phaseHistoryMap = new Map<string, string>();
    // Seed the phase the search opened in — the first status_change row
    // only fires on the next transition, so without seeding from created_at
    // the original opening phase would render undated on the journey
    // overview. If there are no transitions yet, the search is still in
    // its opening phase, so that phase is `row.status`. Once any transition
    // exists, the opening phase is the `from` of the first transition.
    const openingPhase = phaseTransitions[0]?.from_phase ?? row.status;
    if (openingPhase) phaseHistoryMap.set(openingPhase, row.created_at);
    for (const t of phaseTransitions) {
      if (!phaseHistoryMap.has(t.to_phase)) {
        phaseHistoryMap.set(t.to_phase, t.entered_at);
      }
    }
    const phaseHistorySorted = Array.from(phaseHistoryMap.entries())
      .map(([phase, entered_at]) => ({ phase, entered_at }))
      .sort((a, b) => new Date(a.entered_at).getTime() - new Date(b.entered_at).getTime());
    // Attach how long each *completed* phase actually ran — the gap between
    // its own entry date and the next phase's entry date. The last entry is
    // the current phase (still running), so its duration is null. This turns
    // the v1.16 dated journey from "Entered Apr 22" into "Entered Apr 22 ·
    // 12 days", giving the client a real elapsed-time archive they can compare
    // against the "Typically 14–28 days" benchmark already shown per phase.
    // A long engagement reads as a story with concrete durations, not just a
    // list of dates. Nested inside phase_history, so the existing 404-leak
    // test for phase_history already covers it.
    //
    // Each entry also carries the canonical human `label` for its phase
    // (sourced from PUBLIC_STATUS_PHASES, the same map that drives phase_label).
    // Same one-source-of-truth rationale as engagement_age_days / phases_completed:
    // the planned status-change reminder email and future PDF status reports can
    // quote real dated milestones — "Sourcing ran Apr 22 → May 4 · 12 days" —
    // without re-deriving the label from the raw status code. The status page
    // already shows labels from its own forward-phase list, so this is purely a
    // pre-pave for those other surfaces.
    // Each completed phase also carries a canonical `on_pace` flag: true when
    // its actual elapsed days landed at or within the phase's typical-max
    // benchmark from PUBLIC_STATUS_TYPICAL_DURATION. The status page's
    // durational journey archive previously derived this client-side by
    // regex-parsing the "14–28 days" benchmark string it renders — fragile and
    // duplicated. Surfacing the boolean server-side makes it one source of
    // truth (same rationale as `label` and `phases_completed`): the planned
    // reminder email / PDF can quote "Sourcing wrapped on pace · 12 days"
    // without re-deriving the benchmark. Null for the current/last phase (still
    // running, no duration yet) and for any phase without a typical duration.
    // Each entry also carries the canonical typical-duration benchmark its
    // on_pace verdict was measured against (typical_min_days/typical_max_days,
    // null for phases with no typical duration). Without it, phase_history says
    // "12 days, on pace" but a consumer can't render "12 of a typical 14–28
    // days" without a *second* lookup keyed by the raw phase code — the exact
    // re-derivation the label/on_pace fields were surfaced to avoid. Making the
    // entry self-describing lets the planned reminder email / PDF (roadmap #4)
    // quote a fully-benchmarked dated milestone ("Sourcing ran Apr 22 → May 4 ·
    // 12 of a typical 14–28 days") straight off phase_history. Same
    // one-source-of-truth rationale as `label` (v1.22) and `on_pace` (v1.23);
    // nested inside phase_history, so the existing 404-leak test covers it.
    const phaseHistory = phaseHistorySorted.map((entry, i) => {
      const next = phaseHistorySorted[i + 1];
      const typical = PUBLIC_STATUS_TYPICAL_DURATION[entry.phase] ?? null;
      let durationDays: number | null = null;
      let onPace: boolean | null = null;
      if (next) {
        const ms = new Date(next.entered_at).getTime() - new Date(entry.entered_at).getTime();
        if (!Number.isNaN(ms) && ms >= 0) durationDays = Math.floor(ms / DAY_MS);
        if (typical && durationDays !== null) onPace = durationDays <= typical.max_days;
      }
      return {
        phase: entry.phase,
        label: PUBLIC_STATUS_PHASES[entry.phase]?.label ?? entry.phase,
        entered_at: entry.entered_at,
        duration_days: durationDays,
        typical_min_days: typical?.min_days ?? null,
        typical_max_days: typical?.max_days ?? null,
        on_pace: onPace,
      };
    });

    // Canonical summary of the most-recently-completed phase — the last
    // phase_history entry that has actually finished (a non-null duration_days;
    // the current/last phase is still running and so is skipped). It's the one
    // entry the planned status-change reminder email (roadmap #4) most wants to
    // quote: when a search advances, the natural line is "your search just moved
    // to Sourcing — Scoping wrapped on pace · 8 days", which otherwise forces the
    // consumer to re-scan phase_history for the last entry carrying a duration.
    // Surfacing it here makes that read one source of truth — same rationale as
    // phases_completed / all_phases_on_pace — and gives the status page a
    // fresh, always-visible "just wrapped" glance without expanding the journey
    // archive. Carries the same self-describing benchmark fields as its
    // phase_history entry (label, typical_min/max_days, on_pace). Null until at
    // least one phase has completed (a search still in its opening phase has no
    // finished phase yet), and null in the same non-forward states where
    // phase_history carries no completed entry. Nested-shape parity with
    // phase_history, so the existing phase_history 404-leak test already covers it.
    let latestCompletedPhase:
      | {
          phase: string;
          label: string;
          entered_at: string;
          duration_days: number;
          typical_min_days: number | null;
          typical_max_days: number | null;
          on_pace: boolean | null;
        }
      | null = null;
    for (let i = phaseHistory.length - 1; i >= 0; i--) {
      const h = phaseHistory[i];
      if (h.duration_days !== null) {
        latestCompletedPhase = {
          phase: h.phase,
          label: h.label,
          entered_at: h.entered_at,
          duration_days: h.duration_days,
          typical_min_days: h.typical_min_days,
          typical_max_days: h.typical_max_days,
          on_pace: h.on_pace,
        };
        break;
      }
    }

    // Canonical count of *completed* phases that landed on pace — the positive
    // aggregate companion to phases_completed (v1.21) and the per-entry on_pace
    // flag (v1.23). The status page's journey archive already shows a gold "on
    // pace" tag per completed phase, but the collapsed summary only carried the
    // phases-complete count; a return visitor had to expand the section to see
    // how the search was tracking against its benchmarks. Surfacing the count
    // server-side makes it one source of truth: the journey summary can read
    // "3 of 8 phases complete · all on pace" at a glance, and the planned
    // reminder email / PDF (roadmap #4) can quote the same "3 of 3 completed
    // phases on pace" without re-deriving it from phase_history. Null in the
    // same non-progressing/negative-terminal states as phases_completed
    // (on_hold, cancelled, closed_no_fill), where a pace tally would
    // misrepresent a paused or closed-without-placement search as progress.
    // PUBLIC_STATUS_FORWARD includes 'placed', so this covers both the
    // in-flight progressing phases and a completed placement; the
    // non-progressing/negative-terminal states (on_hold, cancelled,
    // closed_no_fill) fall through to null, matching phases_completed.
    //
    // phases_on_pace and phases_benchmarked are tallied together in a single
    // pass over phase_history: an on_pace===true entry is always also
    // on_pace!==null, so folding both counters in one loop guarantees the
    // numerator can never exceed the denominator (phasesOnPace <=
    // phasesBenchmarked by construction) and scans the array once instead of
    // twice — same one-scan hygiene as the v1.25 merged activity query.
    // phases_benchmarked is the *benchmarkable* denominator the "N of M on
    // pace" tally is measured against — a completed phase is benchmarkable
    // when its phase_history entry carries a non-null on_pace (it has both an
    // actual duration and a typical benchmark). It differs from phases_completed
    // only on a successful placement, where the terminal `placed` phase has no
    // typical duration and so can never be "on pace"; using phases_completed as
    // the denominator would understate a flawless run as "7 of 8 on pace"
    // instead of "all on pace" on the exact celebration moment (the v1.35 fix).
    let phasesOnPace: number | null = null;
    let phasesBenchmarked: number | null = null;
    if (isForwardPhase(row.status)) {
      let onPaceCount = 0;
      let benchmarkedCount = 0;
      for (const h of phaseHistory) {
        if (h.on_pace !== null) {
          benchmarkedCount += 1;
          if (h.on_pace === true) onPaceCount += 1;
        }
      }
      phasesOnPace = onPaceCount;
      phasesBenchmarked = benchmarkedCount;
    }

    // Canonical "flawless run so far" boolean — true when every benchmarkable
    // completed phase landed on pace (phases_on_pace === phases_benchmarked with
    // at least one benchmarkable phase). It's the single-boolean form of the
    // "· all on pace" suffix the collapsed journey summary renders, which the
    // status page currently derives client-side by comparing the two integers
    // (phases_on_pace >= phases_benchmarked). Surfacing it server-side makes
    // that positive celebration signal one source of truth (same rationale as
    // phases_on_pace / phases_benchmarked): the planned reminder email / PDF
    // (roadmap #4) can quote "every completed phase is on pace" off one boolean
    // instead of re-comparing the numerator and denominator itself. Null — not
    // false — whenever there's nothing benchmarkable to judge yet (phases_
    // benchmarked null or 0, i.e. a non-forward state or a search still in its
    // opening phase), so a brand-new search never reads a misleading "all on
    // pace" before any phase has actually completed. Positive-only by design,
    // mirroring current_phase_on_pace and the archive's on-pace tags.
    let allPhasesOnPace: boolean | null = null;
    if (phasesBenchmarked !== null && phasesBenchmarked > 0) {
      allPhasesOnPace = phasesOnPace === phasesBenchmarked;
    }

    // Post-placement 90-day follow-up window. Only populated when the
    // search has actually landed — terminal-but-not-placed statuses leave
    // these fields null so the status page can keep its placed-state
    // celebration distinct from a cancellation or no-fill close.
    //
    // `placement_age_days` is the canonical server-computed count of days
    // since the placement landed — the post-placement companion to
    // engagement_age_days, floored from the same shared `nowMs` instant. The
    // status page already derives this client-side for its "Placed … · 14
    // days ago" tag; surfacing it from the API makes it one source of truth
    // so the planned post-placement reminder email / PDF (roadmap #4) can
    // quote "your placement landed 14 days ago — 76 days of follow-up remain"
    // off the same integer the page shows instead of re-doing the date math.
    // Null unless placed, like the other placement fields.
    // `placement_followup_weeks_remaining` is the canonical weeks rounding of
    // the day countdown — the post-placement card stays live for the full 90-day
    // window, where a two-digit "76 days remaining" scans worse than a glanceable
    // "~11 weeks remaining". Same days→weeks one-source-of-truth + fortnight
    // threshold as engagement_age_weeks and the other weeks fields: the planned
    // post-placement reminder email / PDF (roadmap #4) can quote the same weeks
    // the page shows. Null when not placed or inside the final fortnight, where
    // the card keeps the exact day countdown that matters most as the window closes.
    // `placement_age_weeks` is the canonical weeks rounding of placement_age_days —
    // the days-since-placement companion to placement_followup_weeks_remaining and
    // the post-placement mirror of engagement_age_weeks. The placement card's
    // "Placed · 14 days ago" tag reads in raw days, but the card stays live for the
    // whole 90-day window, where "(76 days ago)" scans worse than "(~11 weeks ago)".
    // Same days→weeks one-source-of-truth + fortnight threshold as the other weeks
    // fields: the planned post-placement reminder email / PDF (roadmap #4) can quote
    // "your placement landed about 11 weeks ago" off the same integer the page shows.
    // Null when not placed or inside the first fortnight, where the page still shows
    // the exact day count.
    let placedAt: string | null = null;
    let placementFollowupUntil: string | null = null;
    let placementFollowupDaysRemaining: number | null = null;
    let placementFollowupWeeksRemaining: number | null = null;
    let placementAgeDays: number | null = null;
    let placementAgeWeeks: number | null = null;
    if (row.status === 'placed' && row.status_changed_at) {
      const placedTs = new Date(row.status_changed_at).getTime();
      if (!Number.isNaN(placedTs)) {
        placedAt = row.status_changed_at;
        const untilTs = placedTs + PLACEMENT_FOLLOWUP_DAYS * DAY_MS;
        placementFollowupUntil = new Date(untilTs).toISOString();
        placementFollowupDaysRemaining = Math.max(
          0,
          Math.ceil((untilTs - nowMs) / DAY_MS),
        );
        if (placementFollowupDaysRemaining >= 14) {
          placementFollowupWeeksRemaining = daysToWeeks(placementFollowupDaysRemaining);
        }
        placementAgeDays = Math.max(0, Math.floor((nowMs - placedTs) / DAY_MS));
        if (placementAgeDays >= 14) {
          placementAgeWeeks = daysToWeeks(placementAgeDays);
        }
      }
    }

    // Canonical server-computed countdown to the client's target start date —
    // the integer the status page's "(3 weeks away)" / "(4 days past target)"
    // countdown previously derived entirely client-side. Surfacing it from the
    // API makes it the single source of truth, so the planned status-change
    // reminder email / PDF (roadmap #4) can quote "your target start date is
    // about 3 weeks out" off the same integer the page shows instead of
    // re-doing the date math. Positive = days until the target, negative once
    // the target has passed (the page reads that as "N days past target"),
    // rounded the same way the frontend rounds it so the two never disagree.
    // Null when there's no target date or the search has reached a terminal
    // state (placed/cancelled/closed_no_fill) — exactly the cases where the
    // page already suppresses the countdown. Same one-source-of-truth and
    // null-in-terminal rationale as engagement_age_days and placement_age_days.
    // (TARGET_TERMINAL_STATUSES is a module-level constant — see its definition.)
    let daysUntilTargetStart: number | null = null;
    if (row.target_start_date && !TARGET_TERMINAL_STATUSES.has(row.status)) {
      const targetTs = new Date(row.target_start_date).getTime();
      if (!Number.isNaN(targetTs)) {
        daysUntilTargetStart = Math.round((targetTs - nowMs) / DAY_MS);
      }
    }

    // Canonical weeks rounding of the target-start countdown — the same
    // days→weeks conversion the status page applies inline (`Math.round(days
    // / 7)`) when the target is more than a month out and it renders
    // "(~6 weeks away)". That conversion was the last client-side days→weeks
    // read on the page; surfacing it here makes it one source of truth, so
    // the planned reminder email / PDF (roadmap #4) can quote "your target
    // start date is about 6 weeks out" off the same integer the page shows.
    // Same rationale and rounding as estimated_weeks_remaining (v1.27): null
    // whenever the page shows days rather than weeks — i.e. when there's no
    // countdown at all, or when the target is within a month (days ≤ 30,
    // where the page renders the exact "(N days away)") or already past
    // (negative, always rendered in days). Only the > 30-day case rounds to
    // weeks, matching the frontend branch exactly so the two never disagree.
    let weeksUntilTargetStart: number | null = null;
    if (daysUntilTargetStart !== null && daysUntilTargetStart > 30) {
      // days > 30 here, so the floor-at-1 in daysToWeeks never triggers —
      // byte-identical to the prior bare Math.round(days / 7).
      weeksUntilTargetStart = daysToWeeks(daysUntilTargetStart);
    }

    // Canonical deep-link back to this status surface. POST /api/v1/intake
    // already returns this exact shape (PUBLIC_BASE_URL + /status?ref=…); echoing
    // it here makes the status response itself a single source of truth for the
    // link, so the intake success screen, the status page, and the planned
    // status-change reminder email / PDF all quote the same string rather than
    // each rebuilding it. Same one-source-of-truth rationale as engagement_age_days
    // and phases_completed. Lives on the verified success shape only — never on
    // the 404 path — to keep the response envelope uniform with every other field.
    // Built by the shared statusUrlFor() helper so the status response and the
    // intake response can never drift on the link format.
    const statusUrl = statusUrlFor(row.search_number);

    reply.send({
      data: {
        search_number: row.search_number,
        status_url: statusUrl,
        position_title: row.position_title,
        school_name: row.school_name,
        school_location: [row.school_city, row.school_state].filter(Boolean).join(', ') || null,
        status: row.status,
        phase_label: phase.label,
        phase_explainer: PUBLIC_STATUS_EXPLAINERS[row.status] ?? null,
        phase_step: phase.step,
        phase_total: PHASE_TOTAL,
        phases_completed: phasesCompleted,
        phases_remaining: phasesRemaining,
        phases_on_pace: phasesOnPace,
        phases_benchmarked: phasesBenchmarked,
        all_phases_on_pace: allPhasesOnPace,
        progress_percent: progressPercent,
        next_milestone_label: nextMilestoneLabel,
        next_milestone_eta: nextMilestoneEta,
        days_until_next_milestone: daysUntilNextMilestone,
        weeks_until_next_milestone: weeksUntilNextMilestone,
        next_phase_explainer: nextStatus ? PUBLIC_STATUS_EXPLAINERS[nextStatus] ?? null : null,
        next_phase_duration_typical: nextStatus ? PUBLIC_STATUS_TYPICAL_DURATION[nextStatus] ?? null : null,
        status_changed_at: row.status_changed_at,
        days_in_phase: daysInPhase,
        days_since_last_activity: daysSinceLastActivity,
        weeks_since_last_activity: weeksSinceLastActivity,
        phase_duration_typical: currentPhaseTypical,
        current_phase_on_pace: currentPhaseOnPace,
        phase_percent: phasePercent,
        estimated_completion_window: completionWindow
          ? { earliest: completionWindow.earliest, latest: completionWindow.latest }
          : null,
        estimated_days_remaining: estimatedDaysRemaining,
        estimated_weeks_remaining: estimatedWeeksRemaining,
        is_stalled: isStalled,
        opened_at: row.created_at,
        engagement_age_days: engagementAgeDays,
        engagement_age_weeks: engagementAgeWeeks,
        phase_history: phaseHistory,
        latest_completed_phase: latestCompletedPhase,
        target_start_date: row.target_start_date,
        days_until_target_start: daysUntilTargetStart,
        weeks_until_target_start: weeksUntilTargetStart,
        placed_at: placedAt,
        placement_followup_until: placementFollowupUntil,
        placement_followup_days_remaining: placementFollowupDaysRemaining,
        placement_followup_weeks_remaining: placementFollowupWeeksRemaining,
        placement_age_days: placementAgeDays,
        placement_age_weeks: placementAgeWeeks,
        candidates_identified: row.candidates_identified ?? 0,
        candidates_presented: row.candidates_presented ?? 0,
        candidates_interviewing: row.candidates_interviewing ?? 0,
        search_urgency: row.search_urgency ?? null,
        last_activity_at: latest?.created_at ?? null,
        last_activity_summary: latest?.description ?? null,
        activity_count_last_7d: activityCountLast7d,
        activity_count_prev_7d: activityCountPrev7d,
        activity_count_total: activityCountTotal,
        velocity_trend: velocityTrend,
        is_ramping_up: isRampingUp,
        activity_breakdown: activityBreakdown,
        recent_activities: activities.map((a) => ({
          activity_type: a.activity_type,
          description: a.description,
          created_at: a.created_at,
        })),
      },
    });
  });

  // GET /api/v1/searches — List searches
  app.get('/api/v1/searches', async (request, reply) => {
    const params = listQuerySchema.parse(request.query);
    const { page, per_page } = params;
    const offset = (page - 1) * per_page;

    const conditions: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (params.status) {
      conditions.push(`s.status = $${idx++}`);
      values.push(params.status);
    }
    if (params.position_category) {
      conditions.push(`s.position_category = $${idx++}`);
      values.push(params.position_category);
    }
    if (params.school_id) {
      conditions.push(`s.school_id = $${idx++}`);
      values.push(params.school_id);
    }
    if (params.pricing_band) {
      conditions.push(`s.pricing_band = $${idx++}`);
      values.push(params.pricing_band);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';

    const countRow = await queryOne<{ count: string }>(
      `SELECT COUNT(*) AS count FROM searches s ${where}`,
      values,
    );
    const total = parseInt(countRow?.count ?? '0', 10);

    const rows = await query<Search & { school_name: string }>(
      `SELECT s.*, sch.name AS school_name
       FROM searches s
       LEFT JOIN schools sch ON sch.id = s.school_id
       ${where}
       ORDER BY s.created_at DESC
       LIMIT $${idx++} OFFSET $${idx++}`,
      [...values, per_page, offset],
    );

    const result: PaginatedResponse<Search & { school_name: string }> = {
      data: rows,
      pagination: { page, per_page, total, total_pages: Math.ceil(total / per_page) },
    };
    reply.send(result);
  });

  // GET /api/v1/searches/:id — Get single search
  app.get('/api/v1/searches/:id', async (request, reply) => {
    const { id } = request.params as { id: string };
    const row = await queryOne<Search & { school_name: string }>(
      `SELECT s.*, sch.name AS school_name
       FROM searches s
       LEFT JOIN schools sch ON sch.id = s.school_id
       WHERE s.id = $1`,
      [id],
    );
    if (!row) return reply.code(404).send({ error: 'Search not found' });
    reply.send({ data: row });
  });

  // POST /api/v1/searches — Create search
  app.post('/api/v1/searches', async (request, reply) => {
    const body = createBodySchema.parse(request.body);

    // Auto-assign pricing band based on salary_range_high
    let pricing_band: string | null = null;
    let fee_amount: number | null = null;
    let deposit_amount: number | null = null;

    if (body.salary_range_high) {
      const high = body.salary_range_high;
      if (high <= 100_000) { pricing_band = 'band_a'; fee_amount = 20_000; }
      else if (high <= 150_000) { pricing_band = 'band_b'; fee_amount = 30_000; }
      else if (high <= 200_000) { pricing_band = 'band_c'; fee_amount = 40_000; }
      else if (high <= 275_000) { pricing_band = 'band_d'; fee_amount = 55_000; }
      else if (high <= 375_000) { pricing_band = 'band_e'; fee_amount = 75_000; }
      else if (high <= 500_000) { pricing_band = 'band_f'; fee_amount = 100_000; }
      else { pricing_band = 'band_g'; fee_amount = 125_000; }
      deposit_amount = fee_amount / 2;
    }

    // Generate search number
    const yearStr = new Date().getFullYear().toString();
    const seqRow = await queryOne<{ seq: string }>(
      `SELECT COUNT(*)::text AS seq FROM searches WHERE search_number LIKE $1`,
      [`KNK-${yearStr}-%`],
    );
    const seq = parseInt(seqRow?.seq ?? '0', 10) + 1;
    const search_number = `KNK-${yearStr}-${String(seq).padStart(3, '0')}`;

    const allFields = {
      ...body,
      search_number,
      pricing_band,
      fee_amount,
      deposit_amount,
    };

    const keys = Object.keys(allFields).filter(
      (k) => allFields[k as keyof typeof allFields] !== undefined,
    );
    const cols = keys.join(', ');
    const placeholders = keys.map((_, i) => `$${i + 1}`).join(', ');
    const vals = keys.map((k) => allFields[k as keyof typeof allFields]);

    const row = await queryOne<Search>(
      `INSERT INTO searches (${cols}) VALUES (${placeholders}) RETURNING *`,
      vals,
    );
    reply.code(201).send({ data: row });
  });

  // PATCH /api/v1/searches/:id — Update search
  app.patch('/api/v1/searches/:id', async (request, reply) => {
    const { id } = request.params as { id: string };
    const body = updateBodySchema.parse(request.body);
    const keys = Object.keys(body).filter(
      (k) => body[k as keyof typeof body] !== undefined,
    ) as (keyof typeof body)[];
    if (keys.length === 0) return reply.code(400).send({ error: 'No fields to update' });

    // Capture the prior status so we can log a status_change row that names
    // both endpoints. The status surface only renders activities, so an
    // implicit log here means every transition appears on the client's
    // timeline — no reliance on Janet remembering to write a row.
    const prior = body.status
      ? await queryOne<{ status: string }>(
          `SELECT status FROM searches WHERE id = $1`,
          [id],
        )
      : null;

    // If status is changing, also update status_changed_at
    const extraSets: string[] = [];
    if (body.status) {
      extraSets.push(`status_changed_at = NOW()`);
    }

    const sets = keys.map((k, i) => `${k} = $${i + 2}`);
    const vals = keys.map((k) => body[k]);

    const allSets = [...sets, ...extraSets, 'updated_at = NOW()'].join(', ');

    const row = await queryOne<Search>(
      `UPDATE searches SET ${allSets} WHERE id = $1 RETURNING *`,
      [id, ...vals],
    );
    if (!row) return reply.code(404).send({ error: 'Search not found' });

    // Log the transition only when the status actually changed. The label
    // uses public phase names so the same string can render verbatim on the
    // client's status timeline. Verb varies by direction so a pause/cancel
    // doesn't read as "advanced" — see describeStatusChange().
    if (body.status && prior && prior.status !== body.status) {
      await execute(
        `INSERT INTO search_activities (search_id, activity_type, description, performed_by, metadata)
         VALUES ($1, 'status_change', $2, 'system', $3::jsonb)`,
        [id, describeStatusChange(prior.status, body.status), JSON.stringify({ from: prior.status, to: body.status })],
      );
    }

    reply.send({ data: row });
  });

  // ─── Search Candidates ─────────────────────────────────────────────────

  // GET /api/v1/searches/:id/candidates — List candidates for search
  app.get('/api/v1/searches/:id/candidates', async (request, reply) => {
    const { id } = request.params as { id: string };
    const params = candidateListSchema.parse(request.query);
    const { page, per_page } = params;
    const offset = (page - 1) * per_page;

    const conditions: string[] = ['sc.search_id = $1'];
    const values: unknown[] = [id];
    let idx = 2;

    if (params.status) {
      conditions.push(`sc.status = $${idx++}`);
      values.push(params.status);
    }
    if (params.min_score !== undefined) {
      conditions.push(`sc.match_score >= $${idx++}`);
      values.push(params.min_score);
    }

    const where = `WHERE ${conditions.join(' AND ')}`;

    const countRow = await queryOne<{ count: string }>(
      `SELECT COUNT(*) AS count FROM search_candidates sc ${where}`,
      values,
    );
    const total = parseInt(countRow?.count ?? '0', 10);

    const rows = await query<SearchCandidate & { person_name: string; current_title: string }>(
      `SELECT sc.*, p.full_name AS person_name, p.current_title
       FROM search_candidates sc
       JOIN people p ON p.id = sc.person_id
       ${where}
       ORDER BY sc.match_score DESC NULLS LAST, sc.created_at DESC
       LIMIT $${idx++} OFFSET $${idx++}`,
      [...values, per_page, offset],
    );

    const result: PaginatedResponse<SearchCandidate & { person_name: string; current_title: string }> = {
      data: rows,
      pagination: { page, per_page, total, total_pages: Math.ceil(total / per_page) },
    };
    reply.send(result);
  });

  // POST /api/v1/searches/:id/candidates — Add candidate to search
  app.post('/api/v1/searches/:id/candidates', async (request, reply) => {
    const { id } = request.params as { id: string };
    const body = candidateCreateSchema.parse(request.body);

    // xmax = 0 on a row returned by an upsert means it was newly inserted (vs.
    // updated). We only want to log a candidate_added activity on a true new
    // add — re-PATCH-ing an existing search_candidate must not double-count.
    const row = await queryOne<SearchCandidate & { is_new: boolean }>(
      `INSERT INTO search_candidates (search_id, person_id, status, match_score, match_reasoning, source, referred_by, notes)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       ON CONFLICT (search_id, person_id) DO UPDATE SET
         status = EXCLUDED.status,
         match_score = COALESCE(EXCLUDED.match_score, search_candidates.match_score),
         updated_at = NOW()
       RETURNING *, (xmax = 0) AS is_new`,
      [id, body.person_id, body.status, body.match_score ?? null, body.match_reasoning ?? null, body.source ?? null, body.referred_by ?? null, body.notes ?? null],
    );

    // Update search candidate count
    await queryOne(
      `UPDATE searches SET candidates_identified = (
        SELECT COUNT(*) FROM search_candidates WHERE search_id = $1
      ) WHERE id = $1`,
      [id],
    );

    // Auto-log a redacted candidate_added row so the public status timeline
    // self-populates as Janet sources candidates — same pattern v1.3 used for
    // status_change. Description is intentionally PII-free: the public
    // endpoint never exposes candidate names, so this string must not either.
    if (row?.is_new) {
      await execute(
        `INSERT INTO search_activities (search_id, activity_type, description, performed_by, related_person_id)
         VALUES ($1, 'candidate_added', 'Candidate added to pipeline', 'system', $2)`,
        [id, body.person_id],
      );
    }

    reply.code(201).send({ data: row });
  });

  // PATCH /api/v1/searches/:id/candidates/:cid — Update candidate status
  app.patch('/api/v1/searches/:id/candidates/:cid', async (request, reply) => {
    const { id, cid } = request.params as { id: string; cid: string };
    const body = candidateUpdateSchema.parse(request.body);
    const keys = Object.keys(body).filter(
      (k) => body[k as keyof typeof body] !== undefined,
    ) as (keyof typeof body)[];
    if (keys.length === 0) return reply.code(400).send({ error: 'No fields to update' });

    // Capture the prior status + person_id so we can log a presentation_sent
    // row only on the actual transition into 'presented' (and only once).
    const prior = body.status
      ? await queryOne<{ status: string; person_id: string }>(
          `SELECT status, person_id FROM search_candidates WHERE search_id = $1 AND id = $2`,
          [id, cid],
        )
      : null;

    const sets = keys.map((k, i) => `${k} = $${i + 3}`);
    const vals = keys.map((k) => body[k]);

    // If status is 'presented', set presented_at
    const extraSets: string[] = ['updated_at = NOW()'];
    if (body.status === 'presented') {
      extraSets.push('presented_at = NOW()');
    }

    const allSets = [...sets, ...extraSets].join(', ');

    const row = await queryOne<SearchCandidate>(
      `UPDATE search_candidates SET ${allSets}
       WHERE search_id = $1 AND id = $2
       RETURNING *`,
      [id, cid, ...vals],
    );
    if (!row) return reply.code(404).send({ error: 'Search candidate not found' });

    // Auto-log presentation_sent on the transition into 'presented'. Mirrors
    // the v1.3 status_change pattern: the client status timeline self-populates
    // as the pipeline advances, with no reliance on Janet logging by hand.
    // Description stays PII-free — the public endpoint redacts candidate names.
    if (body.status === 'presented' && prior && prior.status !== 'presented') {
      await execute(
        `INSERT INTO search_activities (search_id, activity_type, description, performed_by, related_person_id)
         VALUES ($1, 'presentation_sent', 'Candidate presented to committee', 'system', $2)`,
        [id, prior.person_id],
      );
    }

    // Auto-log interview_scheduled when a candidate moves into 'interviewing'.
    // Same idempotent pattern: only the actual transition fires the row.
    // Closes the v1.4 → v1.5 stickiness loop for client_interviews phase —
    // the public timeline now self-populates through the full pipeline.
    if (body.status === 'interviewing' && prior && prior.status !== 'interviewing') {
      await execute(
        `INSERT INTO search_activities (search_id, activity_type, description, performed_by, related_person_id)
         VALUES ($1, 'interview_scheduled', 'Committee interview scheduled', 'system', $2)`,
        [id, prior.person_id],
      );
    }

    reply.send({ data: row });
  });

  // POST /api/v1/searches/:id/activities — Manual activity log (auth required)
  // Closes the last roadmap stickiness item: 'client_meeting' is the only
  // public-timeline activity that isn't a side effect of another endpoint, so
  // Janet (or any API-keyed caller) needs an explicit write path to surface
  // a forthcoming committee touchpoint before it happens. The same redaction
  // discipline applies — descriptions go straight onto the public status page,
  // so callers must keep them PII-free.
  app.post('/api/v1/searches/:id/activities', async (request, reply) => {
    const { id } = request.params as { id: string };
    const body = activityCreateSchema.parse(request.body);

    const exists = await queryOne<{ id: string }>(
      `SELECT id FROM searches WHERE id = $1`,
      [id],
    );
    if (!exists) return reply.code(404).send({ error: 'Search not found' });

    const description = body.description ?? DEFAULT_ACTIVITY_DESCRIPTIONS[body.activity_type];
    const row = await queryOne(
      `INSERT INTO search_activities (search_id, activity_type, description, performed_by, related_person_id, metadata)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb)
       RETURNING *`,
      [
        id,
        body.activity_type,
        description,
        body.performed_by ?? 'janet',
        body.related_person_id ?? null,
        body.metadata ? JSON.stringify(body.metadata) : null,
      ],
    );
    reply.code(201).send({ data: row });
  });
}
