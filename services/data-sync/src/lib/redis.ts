import Redis from 'ioredis';

let client: Redis | null = null;

export function getRedis(): Redis {
  if (!client) {
    client = new Redis({
      host: process.env.REDIS_HOST || 'localhost',
      port: parseInt(process.env.REDIS_PORT || '6379', 10),
      password: process.env.REDIS_PASSWORD || undefined,
      db: parseInt(process.env.REDIS_DB || '0', 10),
      maxRetriesPerRequest: 3,
      retryStrategy(times) {
        const delay = Math.min(times * 200, 5000);
        return delay;
      },
      lazyConnect: true,
    });

    client.on('error', (err) => {
      console.error('[redis] Connection error:', err.message);
    });

    client.on('connect', () => {
      console.log('[redis] Connected');
    });
  }
  return client;
}

export async function connectRedis(): Promise<void> {
  const r = getRedis();
  if (r.status !== 'ready' && r.status !== 'connecting') {
    await r.connect();
  }
}

export async function closeRedis(): Promise<void> {
  if (client) {
    await client.quit();
    client = null;
  }
}
