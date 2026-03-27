import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { query, queryOne } from '../lib/db.js';
import type { PaginatedResponse, Signal } from '../types/index.js';

const listQuerySchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  per_page: z.coerce.number().int().min(1).max(100).default(25),
  signal_type: z.string().optional(),
  school_id: z.string().uuid().optional(),
  confidence: z.string().optional(),
  impact: z.string().optional(),
  actioned: z.coerce.boolean().optional(),
});

const createBodySchema = z.object({
  signal_type: z.string().min(1).max(50),
  school_id: z.string().uuid().optional(),
  person_id: z.string().uuid().optional(),
  headline: z.string().max(500).optional(),
  description: z.string().optional(),
  source_url: z.string().max(500).optional(),
  source_name: z.string().max(200).optional(),
  signal_date: z.string().optional(),
  confidence: z.enum(['confirmed', 'likely', 'rumor']).optional(),
  impact: z.enum(['high', 'medium', 'low']).optional(),
});

export default async function signalRoutes(app: FastifyInstance): Promise<void> {

  // GET /api/v1/signals — List signals (paginated + filtered)
  app.get('/api/v1/signals', async (request, reply) => {
    const params = listQuerySchema.parse(request.query);
    const { page, per_page } = params;
    const offset = (page - 1) * per_page;

    const conditions: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (params.signal_type) {
      conditions.push(`sig.signal_type = $${idx++}`);
      values.push(params.signal_type);
    }
    if (params.school_id) {
      conditions.push(`sig.school_id = $${idx++}`);
      values.push(params.school_id);
    }
    if (params.confidence) {
      conditions.push(`sig.confidence = $${idx++}`);
      values.push(params.confidence);
    }
    if (params.impact) {
      conditions.push(`sig.impact = $${idx++}`);
      values.push(params.impact);
    }
    if (params.actioned !== undefined) {
      conditions.push(`sig.actioned = $${idx++}`);
      values.push(params.actioned);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';

    const countRow = await queryOne<{ count: string }>(
      `SELECT COUNT(*) AS count FROM industry_signals sig ${where}`,
      values,
    );
    const total = parseInt(countRow?.count ?? '0', 10);

    const rows = await query<Signal & { school_name: string | null; person_name: string | null }>(
      `SELECT sig.*, sch.name AS school_name, p.full_name AS person_name
       FROM industry_signals sig
       LEFT JOIN schools sch ON sch.id = sig.school_id
       LEFT JOIN people p ON p.id = sig.person_id
       ${where}
       ORDER BY sig.signal_date DESC NULLS LAST, sig.created_at DESC
       LIMIT $${idx++} OFFSET $${idx++}`,
      [...values, per_page, offset],
    );

    const result: PaginatedResponse<Signal & { school_name: string | null; person_name: string | null }> = {
      data: rows,
      pagination: { page, per_page, total, total_pages: Math.ceil(total / per_page) },
    };
    reply.send(result);
  });

  // POST /api/v1/signals — Create signal
  app.post('/api/v1/signals', async (request, reply) => {
    const body = createBodySchema.parse(request.body);
    const keys = Object.keys(body).filter(
      (k) => body[k as keyof typeof body] !== undefined,
    );
    const cols = keys.join(', ');
    const placeholders = keys.map((_, i) => `$${i + 1}`).join(', ');
    const vals = keys.map((k) => body[k as keyof typeof body]);

    const row = await queryOne<Signal>(
      `INSERT INTO industry_signals (${cols}) VALUES (${placeholders}) RETURNING *`,
      vals,
    );
    reply.code(201).send({ data: row });
  });
}
