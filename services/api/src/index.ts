import Fastify from 'fastify';
import cors from '@fastify/cors';
import { ZodError } from 'zod';

import { authenticate } from './middleware/auth.js';
import { close as closeDb } from './lib/db.js';
import redis, { close as closeRedis } from './lib/redis.js';

import healthRoutes from './routes/health.js';
import schoolRoutes from './routes/schools.js';
import peopleRoutes from './routes/people.js';
import searchRoutes from './routes/searches.js';
import matchRoutes from './routes/match.js';
import pricingRoutes from './routes/pricing.js';
import signalRoutes from './routes/signals.js';
import statsRoutes from './routes/stats.js';
import intakeRoutes from './routes/intake.js';

const PORT = parseInt(process.env.PORT ?? '3000', 10);
const HOST = process.env.HOST ?? '0.0.0.0';

async function main(): Promise<void> {
  const app = Fastify({
    logger: {
      level: process.env.LOG_LEVEL ?? 'info',
    },
    requestTimeout: 30_000,
  });

  // ─── CORS ──────────────────────────────────────────────────────────────
  await app.register(cors, {
    origin: process.env.CORS_ORIGIN ?? true,
    methods: ['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'X-API-Key', 'Authorization'],
  });

  // ─── Auth Hook ─────────────────────────────────────────────────────────
  app.addHook('onRequest', authenticate);

  // ─── Global Error Handler ──────────────────────────────────────────────
  app.setErrorHandler((error: Error & { statusCode?: number; validation?: unknown }, _request, reply) => {
    if (error instanceof ZodError) {
      return reply.code(400).send({
        error: 'Validation Error',
        details: error.errors.map((e) => ({
          path: e.path.join('.'),
          message: e.message,
        })),
      });
    }

    // Fastify validation errors
    if (error.validation) {
      return reply.code(400).send({
        error: 'Validation Error',
        message: error.message,
      });
    }

    app.log.error(error);

    const statusCode = error.statusCode ?? 500;
    reply.code(statusCode).send({
      error: statusCode >= 500 ? 'Internal Server Error' : error.message,
      ...(process.env.NODE_ENV !== 'production' && { stack: error.stack }),
    });
  });

  // ─── Routes ────────────────────────────────────────────────────────────
  await app.register(healthRoutes);
  await app.register(schoolRoutes);
  await app.register(peopleRoutes);
  await app.register(searchRoutes);
  await app.register(matchRoutes);
  await app.register(pricingRoutes);
  await app.register(signalRoutes);
  await app.register(statsRoutes);
  await app.register(intakeRoutes);

  // ─── Connect Redis (lazy) ──────────────────────────────────────────────
  try {
    await redis.connect();
  } catch (err) {
    app.log.warn('Redis connection failed at startup — will retry on demand');
  }

  // ─── Start ─────────────────────────────────────────────────────────────
  await app.listen({ port: PORT, host: HOST });
  app.log.info(`Knock API listening on ${HOST}:${PORT}`);

  // ─── Graceful Shutdown ─────────────────────────────────────────────────
  const shutdown = async (signal: string) => {
    app.log.info(`Received ${signal}, shutting down gracefully...`);
    await app.close();
    await closeRedis();
    await closeDb();
    process.exit(0);
  };

  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

main().catch((err) => {
  console.error('Failed to start server:', err);
  process.exit(1);
});
