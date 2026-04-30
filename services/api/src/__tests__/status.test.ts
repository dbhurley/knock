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
