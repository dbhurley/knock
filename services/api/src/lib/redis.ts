import IORedis from 'ioredis';

const Redis = IORedis.default ?? IORedis;

const redis = new Redis(process.env.REDIS_URL ?? 'redis://localhost:6379', {
  maxRetriesPerRequest: 3,
  lazyConnect: true,
  retryStrategy(times: number) {
    const delay = Math.min(times * 200, 5_000);
    return delay;
  },
});

redis.on('error', (err: Error) => {
  console.error('[redis] Connection error:', err.message);
});

redis.on('connect', () => {
  console.log('[redis] Connected');
});

/** Check that Redis is reachable. */
export async function ping(): Promise<boolean> {
  try {
    const result = await redis.ping();
    return result === 'PONG';
  } catch {
    return false;
  }
}

/** Graceful disconnect. */
export async function close(): Promise<void> {
  await redis.quit();
}

export default redis;
