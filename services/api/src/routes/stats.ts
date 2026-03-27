import type { FastifyInstance } from 'fastify';
import { queryOne } from '../lib/db.js';
import type { SystemStats } from '../types/index.js';

export default async function statsRoutes(app: FastifyInstance): Promise<void> {

  // GET /api/v1/stats — Database statistics
  app.get('/api/v1/stats', async (_request, reply) => {
    const [schools, people, activeSearches, totalSearches, placements, signals] =
      await Promise.all([
        queryOne<{ count: string }>('SELECT COUNT(*) AS count FROM schools'),
        queryOne<{ count: string }>('SELECT COUNT(*) AS count FROM people'),
        queryOne<{ count: string }>(
          `SELECT COUNT(*) AS count FROM searches WHERE status NOT IN ('placed', 'closed_no_fill', 'cancelled')`,
        ),
        queryOne<{ count: string }>('SELECT COUNT(*) AS count FROM searches'),
        queryOne<{ count: string }>('SELECT COUNT(*) AS count FROM placements'),
        queryOne<{ count: string }>('SELECT COUNT(*) AS count FROM industry_signals'),
      ]);

    const stats: SystemStats = {
      schools: parseInt(schools?.count ?? '0', 10),
      people: parseInt(people?.count ?? '0', 10),
      active_searches: parseInt(activeSearches?.count ?? '0', 10),
      total_searches: parseInt(totalSearches?.count ?? '0', 10),
      placements: parseInt(placements?.count ?? '0', 10),
      signals: parseInt(signals?.count ?? '0', 10),
    };

    reply.send({
      data: stats,
      timestamp: new Date().toISOString(),
    });
  });
}
