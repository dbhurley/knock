import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

const baseUrl = process.env.API_URL ?? 'http://localhost:3000';

// The status endpoint is the only auth-exempt route that returns search data,
// so the priority of these tests is verifying the negative paths: invalid
// payloads, unknown refs, and email mismatches must never disclose existence.

describe('POST /api/v1/searches/status', () => {
  it('returns 404 for unknown reference number (does not disclose existence)', async () => {
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-999',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404, `expected 404, got ${res.status}`);

    const body = await res.json();
    // Response must not leak which of the two fields was wrong.
    assert.ok(body.error, 'should include an error field');
    assert.ok(!('data' in body), 'must not include a data field');
  });

  it('rejects malformed email with 400', async () => {
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-2026-001',
        contact_email: 'not-an-email',
      }),
    });
    // Zod throws on invalid input, which Fastify surfaces as 500 by default
    // unless an error handler maps it. Either 400 or 500 is acceptable —
    // what matters is that no data is returned.
    assert.ok([400, 500].includes(res.status), `expected 400/500, got ${res.status}`);
    const body = await res.json();
    assert.ok(!('data' in body), 'must not return data on validation error');
  });

  it('rejects missing search_number with 400/500', async () => {
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contact_email: 'someone@example.com' }),
    });
    assert.ok([400, 500].includes(res.status), `expected 400/500, got ${res.status}`);
  });

  it('emits a no-store, private Cache-Control header on every response shape (including 404)', async () => {
    // Personalized content must never be stored by shared caches/CDNs/browsers.
    // The header is set unconditionally at the start of the handler so the
    // privacy contract is uniform: a leaked cache entry on *any* response
    // shape could disclose the verified/unverified status of a (ref, email)
    // pair, so the 404 path needs the same protection as the 200 path.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-999',
        contact_email: 'noone@example.com',
      }),
    });
    const cc = res.headers.get('cache-control') ?? '';
    assert.match(cc, /no-store/, 'expected Cache-Control: no-store on every path');
    assert.match(cc, /private/, 'expected Cache-Control: private on every path');
    assert.ok(!/public/.test(cc), 'Cache-Control must never be public');
  });

  it('does not leak activity_count_last_7d on 404 (negative paths return no data)', async () => {
    // The proof-of-life velocity field must only appear on the verified
    // success shape, alongside other personalized fields. A 404 must not
    // expose any signal about whether/how active a search has been.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-998',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('data' in body), 'must not include data on 404');
    assert.ok(!('activity_count_last_7d' in body), 'velocity field must not leak on 404');
  });

  it('does not leak activity_count_prev_7d on 404 (no week-over-week tempo hints to anonymous callers)', async () => {
    // The previous-window count is the other half of the week-over-week
    // velocity signal (with activity_count_last_7d / velocity_trend /
    // is_ramping_up, all already covered). It's the one week-over-week field
    // that lacked a dedicated 404-leak assertion — observing it on the
    // unauthenticated path would let an anonymous caller infer both that the
    // search exists AND how its tempo was moving a week ago.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-998',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('data' in body), 'must not include data on 404');
    assert.ok(!('activity_count_prev_7d' in body), 'prev-window velocity field must not leak on 404');
  });

  it('does not leak is_stalled or phase_explainer on 404 (no pacing/state hints to anonymous callers)', async () => {
    // is_stalled is a derived pacing signal; phase_explainer is the API's
    // canonical phase-copy. Both belong only on the verified success shape.
    // A 404 must remain a flat error envelope so an anonymous caller cannot
    // infer anything about a search's tempo or current phase from the response.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-997',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('is_stalled' in body), 'stall flag must not leak on 404');
    assert.ok(!('phase_explainer' in body), 'phase explainer must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak estimated_completion_window on 404 (no forward-looking dates to anonymous callers)', async () => {
    // estimated_completion_window is the API's server-computed earliest/latest
    // placement-date pair, derived from the current phase + typical phase
    // durations. The pair belongs only on the verified success shape: an
    // anonymous caller who could observe these dates on a 404 path could infer
    // both that the search exists AND its current phase (since the date math
    // only works once you know how many phases are still ahead).
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-995',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('estimated_completion_window' in body), 'completion window must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak estimated_days_remaining on 404 (no time-to-placement hints to anonymous callers)', async () => {
    // estimated_days_remaining is the canonical integer min/max day range to
    // placement — the same calculation estimated_completion_window expresses
    // as dates. Like that window, the pair belongs only on the verified
    // success shape: observing it on the 404 path would let an anonymous
    // caller infer both that the search exists AND how far along it is (the
    // remaining-days math is keyed by the current phase).
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-984',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('estimated_days_remaining' in body), 'estimated_days_remaining must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak estimated_weeks_remaining on 404 (no time-to-placement hints to anonymous callers)', async () => {
    // estimated_weeks_remaining is the canonical weeks range to placement —
    // the same horizon estimated_days_remaining carries, pre-rounded to the
    // weeks the status page renders. Like that pair, it belongs only on the
    // verified success shape: observing it on the 404 path would let an
    // anonymous caller infer both that the search exists AND how far along it
    // is (the remaining-time math is keyed by the current phase).
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-978',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('estimated_weeks_remaining' in body), 'estimated_weeks_remaining must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak phase_duration_typical on 404 (no pacing benchmarks to anonymous callers)', async () => {
    // phase_duration_typical is the API's canonical typical-duration map for
    // the current phase. It must only appear on the verified success shape —
    // otherwise an anonymous caller could infer the current phase of an
    // arbitrary search from the response's min_days/max_days pair (different
    // phases have distinct ranges).
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-996',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('phase_duration_typical' in body), 'typical-duration map must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak placement-window fields on 404 (no post-placement signals to anonymous callers)', async () => {
    // placed_at, placement_followup_until, placement_followup_days_remaining,
    // and placement_age_days are computed only when a search has actually
    // landed in 'placed' state. The fields belong only on the verified success
    // shape — otherwise an anonymous caller who could observe them on a 404
    // path could infer both that the search exists AND that it has reached the
    // placed terminal.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-994',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('placed_at' in body), 'placed_at must not leak on 404');
    assert.ok(!('placement_followup_until' in body), 'placement_followup_until must not leak on 404');
    assert.ok(!('placement_followup_days_remaining' in body), 'placement_followup_days_remaining must not leak on 404');
    assert.ok(!('placement_followup_weeks_remaining' in body), 'placement_followup_weeks_remaining must not leak on 404');
    assert.ok(!('placement_followup_percent' in body), 'placement_followup_percent must not leak on 404');
    assert.ok(!('placement_age_days' in body), 'placement_age_days must not leak on 404');
    assert.ok(!('placement_age_weeks' in body), 'placement_age_weeks must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak days_since_last_activity on 404 (no recency hints to anonymous callers)', async () => {
    // days_since_last_activity is a derived recency anchor for the public
    // velocity row. It must only appear on the verified success shape:
    // observing a non-null integer on the 404 path would let an anonymous
    // caller infer both that the search exists AND roughly when it was
    // last touched — exactly the kind of side-channel signal the no-
    // enumeration contract is designed to prevent.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-993',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('days_since_last_activity' in body), 'recency field must not leak on 404');
    assert.ok(!('weeks_since_last_activity' in body), 'recency weeks field must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak activity_count_total on 404 (no engagement-depth hints to anonymous callers)', async () => {
    // activity_count_total is the cumulative count of public-visible
    // activities since a search opened. The integer must only appear on the
    // verified success shape: observing it on the 404 path would let an
    // anonymous caller infer both that the search exists AND how deep the
    // engagement has gone — same side-channel concern as the v1.13 days_since
    // and v1.8 last-7d fields it accompanies.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-991',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('activity_count_total' in body), 'cumulative-count field must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak next-phase preview fields on 404 (no roadmap hints to anonymous callers)', async () => {
    // next_phase_explainer and next_phase_duration_typical describe the
    // phase *after* the current one. Together they let a caller infer the
    // current phase (since the next-phase pair is keyed by it). The fields
    // belong only on the verified success shape, like phase_explainer and
    // phase_duration_typical before them.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-992',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('next_phase_explainer' in body), 'next_phase_explainer must not leak on 404');
    assert.ok(!('next_phase_duration_typical' in body), 'next_phase_duration_typical must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak velocity-trend fields on 404 (no week-over-week hints to anonymous callers)', async () => {
    // activity_count_prev_7d and velocity_trend describe the previous 7-day
    // window and the categorical comparison against it. Both belong only on
    // the verified success shape: observing them on the 404 path would let
    // an anonymous caller infer the existence + tempo of a search, same
    // side-channel concern as v1.8's activity_count_last_7d before them.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-989',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('activity_count_prev_7d' in body), 'prev-week count must not leak on 404');
    assert.ok(!('velocity_trend' in body), 'velocity_trend must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak activity_delta_7d on 404 (no week-over-week tempo change to anonymous callers)', async () => {
    // activity_delta_7d is the signed week-over-week change in public-visible
    // activity (activity_count_last_7d − activity_count_prev_7d) — the raw
    // magnitude the velocity family (velocity_trend, is_ramping_up) is derived
    // from. It belongs only on the verified success shape: observing the
    // integer on the 404 path would let an anonymous caller infer both that a
    // search exists AND how its tempo is changing week over week, the same
    // side-channel concern as activity_count_prev_7d / velocity_trend above.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-976',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('activity_delta_7d' in body), 'week-over-week delta must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak activity_breakdown on 404 (no per-type counts to anonymous callers)', async () => {
    // activity_breakdown is the cumulative per-type counts the public status
    // page renders as the "Engagement at a glance" strip. Observing the
    // object on the 404 path would let an anonymous caller infer not just
    // that a search exists, but the shape of the engagement so far (how
    // many candidates sourced, presented, interviewed, etc.). Belongs only
    // on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-988',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('activity_breakdown' in body), 'activity_breakdown must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak current_phase_on_pace on 404 (no pacing-verdict hints to anonymous callers)', async () => {
    // current_phase_on_pace is the server-computed boolean verdict on whether
    // the current phase is still within its typical-max benchmark. Like the
    // phase_duration_typical it derives from, the flag is keyed by the current
    // phase, so observing it on the 404 path would let an anonymous caller
    // infer both that the search exists AND something about its pacing.
    // Belongs only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-981',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('current_phase_on_pace' in body), 'current_phase_on_pace must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak phase_percent on 404 (no within-phase progress hints to anonymous callers)', async () => {
    // phase_percent is the server-computed within-current-phase completion
    // percent (days_in_phase against the phase's typical-max). Like the
    // current_phase_on_pace and phase_duration_typical it derives from, the
    // integer is keyed by the current phase, so observing it on the 404 path
    // would let an anonymous caller infer both that the search exists AND how
    // far through its current phase it is. Belongs only on the success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-982',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('phase_percent' in body), 'phase_percent must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak is_on_track on 404 (no health-verdict hints to anonymous callers)', async () => {
    // is_on_track is the server-computed AND of current_phase_on_pace === true
    // and !is_stalled — a single "is the search healthy right now?" verdict.
    // Like the two pacing signals it's derived from, the boolean is keyed by
    // the current phase, so observing it on the 404 path would let an anonymous
    // caller infer both that the search exists AND whether it's progressing on
    // schedule. Belongs only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-951',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('is_on_track' in body), 'is_on_track must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak is_ramping_up on 404 (no activity-tempo hints to anonymous callers)', async () => {
    // is_ramping_up is the server-computed "the pipeline came alive this week"
    // flag (empty prior 7-day window, active current one). Like the velocity
    // and activity counts it derives from, it must appear only on the verified
    // success shape: observing it on the 404 path would let an anonymous caller
    // infer both that the search exists AND that it just started seeing
    // activity. Belongs behind email verification like every other field.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-981',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('is_ramping_up' in body), 'is_ramping_up must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak phase_history on 404 (no transition-archive hints to anonymous callers)', async () => {
    // phase_history is the API's per-phase entry-date archive (one entry per
    // phase the search has been in, ordered ascending). The array must only
    // appear on the verified success shape: observing it on the 404 path
    // would let an anonymous caller infer both that the search exists AND
    // when it entered each phase — exactly the kind of historical signal the
    // no-enumeration contract is designed to keep behind email verification.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-990',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('phase_history' in body), 'phase_history must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak next_milestone_eta on 404 (no forward-date hints to anonymous callers)', async () => {
    // next_milestone_eta is the server-computed expected start date of the
    // next phase, derived from the current phase + its typical duration. The
    // single date belongs only on the verified success shape: observing it on
    // the 404 path would let an anonymous caller infer both that the search
    // exists AND its current phase (the date math is keyed by the current phase).
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-987',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('next_milestone_eta' in body), 'next_milestone_eta must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak days_until_next_milestone on 404 (no forward-countdown hints to anonymous callers)', async () => {
    // days_until_next_milestone is the canonical integer companion to
    // next_milestone_eta — the count of typical-max days still remaining in
    // the current phase. Like the ISO date it accompanies, the integer is
    // keyed by the current phase, so observing it on the 404 path would let
    // an anonymous caller infer both that the search exists AND its current
    // phase. Belongs only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-985',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('days_until_next_milestone' in body), 'days_until_next_milestone must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak weeks_until_next_milestone on 404 (no forward-countdown hints to anonymous callers)', async () => {
    // weeks_until_next_milestone is the canonical weeks rounding of
    // days_until_next_milestone — the same forward countdown, pre-rounded to
    // the weeks the status page renders past a fortnight. Like the day count it
    // accompanies, the integer is keyed by the current phase, so observing it on
    // the 404 path would let an anonymous caller infer both that the search
    // exists AND its current phase. Belongs only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-971',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('weeks_until_next_milestone' in body), 'weeks_until_next_milestone must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak engagement_age_days on 404 (no engagement-length hints to anonymous callers)', async () => {
    // engagement_age_days is the canonical days-since-opened integer. It must
    // only appear on the verified success shape: observing it on the 404 path
    // would let an anonymous caller infer both that the search exists AND how
    // long it has been running — same side-channel concern as the v1.14
    // activity_count_total and v1.13 days_since_last_activity fields.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-986',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('engagement_age_days' in body), 'engagement_age_days must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak engagement_age_weeks on 404 (no engagement-length hints to anonymous callers)', async () => {
    // engagement_age_weeks is the canonical weeks rounding of engagement_age_days
    // — the same days-since-opened signal, pre-rounded to the weeks the status
    // page renders past a fortnight. Like the day count it accompanies, observing
    // it on the 404 path would let an anonymous caller infer both that the search
    // exists AND how long it has been running. Belongs only on the verified
    // success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-969',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('engagement_age_weeks' in body), 'engagement_age_weeks must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak phases_completed on 404 (no progress hints to anonymous callers)', async () => {
    // phases_completed is the canonical count of finished phases — the same
    // calculation the journey summary renders as "3 of 8 phases complete".
    // The integer is keyed by the current phase (completed = step - 1), so
    // observing it on the 404 path would let an anonymous caller infer both
    // that the search exists AND how far along it is. Belongs only on the
    // verified success shape, like phase_step and phases_completed's sibling
    // canonical integers (engagement_age_days, days_until_next_milestone).
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-983',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('phases_completed' in body), 'phases_completed must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak phases_on_pace on 404 (no pacing-tally hints to anonymous callers)', async () => {
    // phases_on_pace is the canonical count of completed phases that landed on
    // pace — the positive aggregate companion to phases_completed. Like every
    // other progress signal it is keyed by how far the search has advanced, so
    // observing it on the 404 path would let an anonymous caller infer both that
    // the search exists AND how it has tracked against its benchmarks. Belongs
    // only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-979',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('phases_on_pace' in body), 'phases_on_pace must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak phases_benchmarked on 404 (no pacing-tally hints to anonymous callers)', async () => {
    // phases_benchmarked is the canonical count of *benchmarkable* completed
    // phases — the denominator the "N of M on pace" tally is measured against.
    // Like phases_on_pace it is keyed by how far the search has advanced, so
    // observing it on the 404 path would let an anonymous caller infer both that
    // the search exists AND how many phases it has completed against benchmark.
    // Belongs only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-978',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('phases_benchmarked' in body), 'phases_benchmarked must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak all_phases_on_pace on 404 (no pacing-verdict hints to anonymous callers)', async () => {
    // all_phases_on_pace is the canonical "every completed phase landed on
    // pace" boolean — the single-boolean form of the collapsed journey
    // summary's "· all on pace" suffix. Like phases_on_pace / phases_benchmarked
    // it is keyed by how far the search has advanced and how it tracked against
    // benchmark, so observing it on the 404 path would let an anonymous caller
    // infer both that the search exists AND that it has completed phases on
    // pace. Belongs only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-972',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('all_phases_on_pace' in body), 'all_phases_on_pace must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak phases_remaining on 404 (no progress hints to anonymous callers)', async () => {
    // phases_remaining is the forward-looking complement to phases_completed —
    // the count of phases the search has not yet finished. Like every other
    // progress signal it is keyed by how far the search has advanced, so
    // observing it on the 404 path would let an anonymous caller infer both
    // that the search exists AND how far along it is. Belongs only on the
    // verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-975',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('phases_remaining' in body), 'phases_remaining must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak weeks_until_target_start on 404 (no scheduling hints to anonymous callers)', async () => {
    // weeks_until_target_start is the canonical weeks rounding of the target
    // countdown — the same scheduling signal as days_until_target_start, just
    // pre-rounded to weeks. Like that integer it is keyed to a real search, so
    // observing it on the 404 path would let an anonymous caller infer both
    // that the search exists AND roughly when the client wants the role filled.
    // Belongs only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-973',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('weeks_until_target_start' in body), 'weeks_until_target_start must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak days_until_target_start on 404 (no scheduling hints to anonymous callers)', async () => {
    // days_until_target_start is the canonical countdown to the client's target
    // start date. Like every other derived scheduling/progress field it is
    // keyed to a real search, so observing the integer on the 404 path would let
    // an anonymous caller infer both that the search exists AND roughly when the
    // client wants the role filled. Belongs only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-977',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('days_until_target_start' in body), 'days_until_target_start must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak status_url on 404 (verified success shape only)', async () => {
    // status_url is the canonical deep-link back to the status surface,
    // echoed from POST /api/v1/intake so the success screen, the page, and
    // the planned reminder email share one string. It belongs only on the
    // verified success shape: a 404 must stay a flat error envelope so the
    // response never confirms a (ref, email) pair by handing back a
    // ready-made link to the search it didn't disclose.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-982',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('status_url' in body), 'status_url must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak pipeline counts or recent_activities on 404 (no candidate-pipeline hints to anonymous callers)', async () => {
    // candidates_identified/presented/interviewing and recent_activities are
    // the most directly candidate-revealing fields on the success shape: the
    // counts disclose how deep the pipeline is, and the timeline discloses
    // dated engagement activity. Both belong only behind email verification —
    // observing either on the 404 path would let an anonymous caller infer that
    // a search exists and how much candidate work has happened on it.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-980',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('candidates_identified' in body), 'candidates_identified must not leak on 404');
    assert.ok(!('candidates_presented' in body), 'candidates_presented must not leak on 404');
    assert.ok(!('candidates_interviewing' in body), 'candidates_interviewing must not leak on 404');
    assert.ok(!('recent_activities' in body), 'recent_activities must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak last_activity_at / last_activity_summary / search_urgency on 404 (no recency or pacing hints to anonymous callers)', async () => {
    // last_activity_at and last_activity_summary disclose exactly when the
    // search was last touched and a verbatim description of that update;
    // search_urgency discloses the intake pacing enum. All three are keyed to
    // a real search, so observing any of them on the 404 path would let an
    // anonymous caller infer that the search exists (and, for the activity
    // fields, when it was last active). They belong only on the verified
    // success shape, like every other personalized field.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-967',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('last_activity_at' in body), 'last_activity_at must not leak on 404');
    assert.ok(!('last_activity_summary' in body), 'last_activity_summary must not leak on 404');
    assert.ok(!('search_urgency' in body), 'search_urgency must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak last_activity_type or the raw status on 404 (no recency-type or current-phase hints to anonymous callers)', async () => {
    // last_activity_type is the machine-readable enum of the most recent
    // public activity (the canonical key roadmap #4's per-type reminder emails
    // branch on); `status` is the raw current-phase code — the most directly
    // phase-revealing field of all, even more so than the derived phase_label /
    // phase_step already covered. Both are keyed to a real search, so observing
    // either on the 404 path would let an anonymous caller infer that the search
    // exists (and, for status, exactly which phase it's in / for
    // last_activity_type what kind of update it last saw). They belong only on
    // the verified success shape, like every other personalized field.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-953',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('last_activity_type' in body), 'last_activity_type must not leak on 404');
    assert.ok(!('status' in body), 'raw status must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak identity fields on 404 (no school/position disclosure to anonymous callers)', async () => {
    // position_title, school_name, and school_location name the actual client
    // and role — the most directly-identifying fields on the success shape.
    // They must only appear behind email verification: observing any of them
    // on the 404 path would let an anonymous caller confirm a search exists AND
    // learn which school and role it is. Previously covered only by the generic
    // no-`data` assertion; locked here alongside the rest of the response surface.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-965',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('position_title' in body), 'position_title must not leak on 404');
    assert.ok(!('school_name' in body), 'school_name must not leak on 404');
    assert.ok(!('school_location' in body), 'school_location must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak phase fields on 404 (no current-phase disclosure to anonymous callers)', async () => {
    // phase_label, phase_step, and next_milestone_label all reveal where the
    // search currently is in the journey. Like every other progress signal they
    // are keyed by the current phase, so observing them on the 404 path would let
    // an anonymous caller infer both that the search exists AND its current phase.
    // They belong only on the verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-963',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('phase_label' in body), 'phase_label must not leak on 404');
    assert.ok(!('phase_step' in body), 'phase_step must not leak on 404');
    assert.ok(!('next_milestone_label' in body), 'next_milestone_label must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak latest_completed_phase on 404 (no journey-progress disclosure to anonymous callers)', async () => {
    // latest_completed_phase names the most-recently-finished phase plus its
    // actual duration and on-pace verdict — a direct signal of how far a search
    // has advanced and how it tracked against benchmark. Like phase_history and
    // the phase-count fields it is keyed by the search's progress, so observing
    // it on the 404 path would let an anonymous caller infer both that the
    // search exists AND where it is in the journey. It belongs only on the
    // verified success shape.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-961',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('latest_completed_phase' in body), 'latest_completed_phase must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak progress_percent on 404 (no journey-progress disclosure to anonymous callers)', async () => {
    // progress_percent is the 0–100 whole-journey completion figure the status
    // page renders as the phase progress bar — a direct signal of how far a
    // search has advanced. It had no dedicated 404-leak assertion, relying only
    // on the generic no-`data` check; observing it on the 404 path would let an
    // anonymous caller infer both that the search exists AND roughly how far
    // along it is. Locks the no-enumeration contract for it in CI the same way
    // the phase-count and identity fields already do.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-959',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('progress_percent' in body), 'progress_percent must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak raw scheduling/timestamp fields on 404 (no date disclosure to anonymous callers)', async () => {
    // target_start_date is the raw ISO date the client wants the role filled —
    // the most directly-revealing scheduling field, even more so than the
    // days_until/weeks_until countdowns derived from it. status_changed_at and
    // opened_at are the raw phase-entry and engagement-open timestamps. All
    // three had no dedicated 404-leak assertion, relying only on the generic
    // no-`data` check; observing any of them on the 404 path would let an
    // anonymous caller infer both that the search exists AND when the client
    // wants the role filled / when the search last moved / how long it has run.
    // Locks the no-enumeration contract for them in CI the same way the v1.35
    // identity fields and v1.42 progress_percent tests already do.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-957',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('target_start_date' in body), 'target_start_date must not leak on 404');
    assert.ok(!('status_changed_at' in body), 'status_changed_at must not leak on 404');
    assert.ok(!('opened_at' in body), 'opened_at must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak days_in_phase on 404 (no in-phase-duration hints to anonymous callers)', async () => {
    // days_in_phase is the anchorless count of days the search has spent in its
    // current phase — the raw pacing signal the "In this phase for N days"
    // line and the current_phase_on_pace / phase_percent fields are all derived
    // from. It was a success-shape field with no dedicated 404-leak assertion,
    // relying only on the generic no-`data` check. Observing it on the 404 path
    // would let an anonymous caller infer both that the search exists AND how
    // long it has been sitting in its current phase. Locks the no-enumeration
    // contract for it in CI the same way the v1.42 progress_percent and v1.43
    // raw-date tests already do.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-955',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('days_in_phase' in body), 'days_in_phase must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('does not leak is_terminal / is_negative_terminal on 404 (no conclusion-state hints to anonymous callers)', async () => {
    // is_terminal and is_negative_terminal are the canonical "has the search
    // concluded?" booleans (v1.49) — is_terminal true for placed/cancelled/
    // closed_no_fill, is_negative_terminal true for the placement-less subset.
    // They're keyed to a real search's state, so observing either on the
    // unauthenticated path would let an anonymous caller infer both that the
    // search exists AND whether it has ended (and, for the negative flag,
    // whether it ended without a placement). Locks the no-enumeration contract
    // for them in CI the same way the v1.48 is_on_track and v1.44 days_in_phase
    // tests already do for the other state-derived booleans.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-953',
        contact_email: 'noone@example.com',
      }),
    });
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.ok(!('is_terminal' in body), 'is_terminal must not leak on 404');
    assert.ok(!('is_negative_terminal' in body), 'is_negative_terminal must not leak on 404');
    assert.ok(!('data' in body), 'must not include data on 404');
  });

  it('returns identical 404 shape for email mismatch as for unknown ref (no enumeration)', async () => {
    // Use a real-looking ref but a clearly bogus email. The endpoint must
    // not differentiate "ref exists, wrong email" from "ref does not exist".
    const refExists = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-2026-001',
        contact_email: 'definitely-not-the-client@example.com',
      }),
    });
    const refMissing = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-9999-999',
        contact_email: 'definitely-not-the-client@example.com',
      }),
    });
    assert.equal(refExists.status, refMissing.status, 'mismatch and missing must return same status');
    assert.equal(refExists.status, 404);
  });
});
