import type { FastifyInstance } from 'fastify';
import { ping as dbPing } from '../lib/db.js';
import { ping as redisPing } from '../lib/redis.js';

export default async function healthRoutes(app: FastifyInstance): Promise<void> {
  app.get('/health', async (_request, reply) => {
    const [dbOk, redisOk] = await Promise.all([dbPing(), redisPing()]);

    const status = dbOk && redisOk ? 'healthy' : 'degraded';
    const code = dbOk && redisOk ? 200 : 503;

    reply.code(code).send({
      status,
      uptime_seconds: Math.floor(process.uptime()),
      timestamp: new Date().toISOString(),
      services: {
        database: dbOk ? 'connected' : 'disconnected',
        redis: redisOk ? 'connected' : 'disconnected',
      },
    });
  });
}
