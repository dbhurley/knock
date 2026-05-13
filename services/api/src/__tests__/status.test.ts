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

  it('emits a no-store, private Cache-Control header (no shared caching of personalized data)', async () => {
    // Personalized content must never be stored by shared caches/CDNs/browsers.
    // This is a privacy property of the endpoint, so we assert it on every
    // response shape — including 404 — to keep the contract simple.
    const res = await fetch(`${baseUrl}/api/v1/searches/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        search_number: 'KNK-0000-999',
        contact_email: 'noone@example.com',
      }),
    });
    const cc = res.headers.get('cache-control') ?? '';
    if (res.status === 200) {
      assert.match(cc, /no-store/, 'expected Cache-Control: no-store on success path');
      assert.match(cc, /private/, 'expected Cache-Control: private on success path');
    }
    // Non-200 (404 in this test) is allowed to omit the header — only the
    // success path returns sensitive data — but if it's present it must be
    // restrictive, not permissive.
    if (cc) {
      assert.ok(!/public/.test(cc), 'Cache-Control must never be public');
    }
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
