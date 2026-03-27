import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

describe('GET /health', () => {
  it('should return 200 with status ok', async () => {
    const baseUrl = process.env.API_URL ?? 'http://localhost:3000';
    const res = await fetch(`${baseUrl}/health`);

    assert.equal(res.status, 200);

    const body = await res.json();
    assert.equal(body.status, 'ok');
  });

  it('should include uptime in the response', async () => {
    const baseUrl = process.env.API_URL ?? 'http://localhost:3000';
    const res = await fetch(`${baseUrl}/health`);
    const body = await res.json();

    assert.ok(typeof body.uptime === 'number', 'uptime should be a number');
    assert.ok(body.uptime >= 0, 'uptime should be non-negative');
  });

  it('should include a timestamp', async () => {
    const baseUrl = process.env.API_URL ?? 'http://localhost:3000';
    const res = await fetch(`${baseUrl}/health`);
    const body = await res.json();

    assert.ok(body.timestamp, 'timestamp should be present');
    const parsed = new Date(body.timestamp);
    assert.ok(!isNaN(parsed.getTime()), 'timestamp should be a valid ISO date');
  });
});
