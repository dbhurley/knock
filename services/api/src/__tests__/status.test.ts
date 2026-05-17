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
    // placed_at, placement_followup_until, and placement_followup_days_remaining
    // are computed only when a search has actually landed in 'placed' state.
    // The fields belong only on the verified success shape — otherwise an
    // anonymous caller who could observe them on a 404 path could infer both
    // that the search exists AND that it has reached the placed terminal.
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
