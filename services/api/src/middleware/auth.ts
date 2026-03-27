import type { FastifyRequest, FastifyReply } from 'fastify';

const API_KEY = process.env.API_KEY;

/**
 * Simple API-key authentication middleware.
 * Checks the `X-API-Key` header against the API_KEY environment variable.
 * Health endpoint is exempt.
 */
export async function authenticate(
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<void> {
  // Skip auth for health check
  if (request.url === '/health') return;

  if (!API_KEY) {
    request.log.warn('API_KEY env var is not set — auth is disabled');
    return;
  }

  const provided = request.headers['x-api-key'];

  if (!provided || provided !== API_KEY) {
    reply.code(401).send({
      error: 'Unauthorized',
      message: 'Missing or invalid X-API-Key header',
    });
  }
}
