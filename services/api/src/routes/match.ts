import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { scoreCandidate, findCandidates } from '../lib/scoring.js';

const scoreBodySchema = z.object({
  search_id: z.string().uuid(),
  person_id: z.string().uuid(),
});

const findBodySchema = z.object({
  search_id: z.string().uuid(),
  limit: z.number().int().min(1).max(200).default(50),
  min_score: z.number().min(0).max(100).default(0),
});

export default async function matchRoutes(app: FastifyInstance): Promise<void> {

  // POST /api/v1/match/score — Score a single candidate against a search
  app.post('/api/v1/match/score', async (request, reply) => {
    const { search_id, person_id } = scoreBodySchema.parse(request.body);

    const result = await scoreCandidate(search_id, person_id);
    if (!result) {
      return reply.code(404).send({
        error: 'Search or person not found',
      });
    }

    reply.send({ data: result });
  });

  // POST /api/v1/match/find — Find and rank candidates for a search
  app.post('/api/v1/match/find', async (request, reply) => {
    const { search_id, limit, min_score } = findBodySchema.parse(request.body);

    const results = await findCandidates(search_id, limit, min_score);

    reply.send({
      data: results,
      meta: {
        search_id,
        total_scored: results.length,
        min_score,
        limit,
      },
    });
  });
}
