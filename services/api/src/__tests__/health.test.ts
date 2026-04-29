import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

const baseUrl = process.env.API_URL ?? 'http://localhost:3000';

describe('GET /health', () => {
  it('should respond with healthy or degraded status', async () => {
    const res = await fetch(`${baseUrl}/health`);

    // 200 when all services connected; 503 if any are down. Both are valid
    // shapes — we just want to verify the contract is honored.
    assert.ok([200, 503].includes(res.status), `unexpected status ${res.status}`);

    const body = await res.json();
    assert.ok(['healthy', 'degraded'].includes(body.status), `unexpected status field: ${body.status}`);
  });

  it('should include uptime_seconds in the response', async () => {
    const res = await fetch(`${baseUrl}/health`);
    const body = await res.json();

    assert.ok(typeof body.uptime_seconds === 'number', 'uptime_seconds should be a number');
    assert.ok(body.uptime_seconds >= 0, 'uptime_seconds should be non-negative');
  });

  it('should include a valid ISO timestamp', async () => {
    const res = await fetch(`${baseUrl}/health`);
    const body = await res.json();

    assert.ok(body.timestamp, 'timestamp should be present');
    const parsed = new Date(body.timestamp);
    assert.ok(!isNaN(parsed.getTime()), 'timestamp should be a valid ISO date');
  });

  it('should report database and redis service state', async () => {
    const res = await fetch(`${baseUrl}/health`);
    const body = await res.json();

    assert.ok(body.services, 'services should be present');
    assert.ok(['connected', 'disconnected'].includes(body.services.database));
    assert.ok(['connected', 'disconnected'].includes(body.services.redis));
  });
});
