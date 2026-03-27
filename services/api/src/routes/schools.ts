import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { query, queryOne, execute } from '../lib/db.js';
import type { PaginatedResponse, School, SchoolLeadership, SchoolFinancial } from '../types/index.js';

// ─── Validation Schemas ────────────────────────────────────────────────────

const listQuerySchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  per_page: z.coerce.number().int().min(1).max(100).default(25),
  state: z.string().length(2).optional(),
  school_type: z.string().optional(),
  boarding_status: z.string().optional(),
  tier: z.string().optional(),
  nais_member: z.coerce.boolean().optional(),
  q: z.string().optional(),
});

const createBodySchema = z.object({
  name: z.string().min(1).max(500),
  nces_id: z.string().max(12).optional(),
  school_type: z.string().max(50).optional(),
  religious_affiliation: z.string().max(100).optional(),
  coed_status: z.enum(['coed', 'boys', 'girls']).optional(),
  boarding_status: z.enum(['day', 'boarding', 'day_boarding']).optional(),
  grade_low: z.string().max(5).optional(),
  grade_high: z.string().max(5).optional(),
  enrollment_total: z.number().int().optional(),
  street_address: z.string().max(500).optional(),
  city: z.string().max(200).optional(),
  state: z.string().length(2).optional(),
  zip: z.string().max(10).optional(),
  phone: z.string().max(20).optional(),
  website: z.string().max(500).optional(),
  email: z.string().email().max(300).optional(),
  tuition_low: z.number().int().optional(),
  tuition_high: z.number().int().optional(),
  endowment_size: z.number().int().optional(),
  nais_member: z.boolean().optional(),
  is_independent: z.boolean().optional(),
  tier: z.enum(['platinum', 'gold', 'silver', 'bronze', 'unranked']).optional(),
  tags: z.array(z.string()).optional(),
});

const updateBodySchema = createBodySchema.partial();

// ─── Routes ────────────────────────────────────────────────────────────────

export default async function schoolRoutes(app: FastifyInstance): Promise<void> {

  // GET /api/v1/schools — List schools (paginated + filtered)
  app.get('/api/v1/schools', async (request, reply) => {
    const params = listQuerySchema.parse(request.query);
    const { page, per_page } = params;
    const offset = (page - 1) * per_page;

    const conditions: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (params.state) {
      conditions.push(`state = $${idx++}`);
      values.push(params.state);
    }
    if (params.school_type) {
      conditions.push(`school_type = $${idx++}`);
      values.push(params.school_type);
    }
    if (params.boarding_status) {
      conditions.push(`boarding_status = $${idx++}`);
      values.push(params.boarding_status);
    }
    if (params.tier) {
      conditions.push(`tier = $${idx++}`);
      values.push(params.tier);
    }
    if (params.nais_member !== undefined) {
      conditions.push(`nais_member = $${idx++}`);
      values.push(params.nais_member);
    }
    if (params.q) {
      conditions.push(`search_vector @@ plainto_tsquery('english', $${idx++})`);
      values.push(params.q);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';

    const countRow = await queryOne<{ count: string }>(
      `SELECT COUNT(*) AS count FROM schools ${where}`,
      values,
    );
    const total = parseInt(countRow?.count ?? '0', 10);

    const rows = await query<School>(
      `SELECT * FROM schools ${where} ORDER BY name ASC LIMIT $${idx++} OFFSET $${idx++}`,
      [...values, per_page, offset],
    );

    const result: PaginatedResponse<School> = {
      data: rows,
      pagination: { page, per_page, total, total_pages: Math.ceil(total / per_page) },
    };
    reply.send(result);
  });

  // GET /api/v1/schools/:id — Get single school
  app.get('/api/v1/schools/:id', async (request, reply) => {
    const { id } = request.params as { id: string };
    const school = await queryOne<School>('SELECT * FROM schools WHERE id = $1', [id]);
    if (!school) return reply.code(404).send({ error: 'School not found' });
    reply.send({ data: school });
  });

  // POST /api/v1/schools — Create school
  app.post('/api/v1/schools', async (request, reply) => {
    const body = createBodySchema.parse(request.body);
    const keys = Object.keys(body) as (keyof typeof body)[];
    const cols = keys.join(', ');
    const placeholders = keys.map((_, i) => `$${i + 1}`).join(', ');
    const vals = keys.map((k) => body[k]);

    const row = await queryOne<School>(
      `INSERT INTO schools (${cols}) VALUES (${placeholders}) RETURNING *`,
      vals,
    );
    reply.code(201).send({ data: row });
  });

  // PATCH /api/v1/schools/:id — Update school
  app.patch('/api/v1/schools/:id', async (request, reply) => {
    const { id } = request.params as { id: string };
    const body = updateBodySchema.parse(request.body);
    const keys = Object.keys(body) as (keyof typeof body)[];
    if (keys.length === 0) return reply.code(400).send({ error: 'No fields to update' });

    const sets = keys.map((k, i) => `${k} = $${i + 2}`);
    const vals = keys.map((k) => body[k]);

    const row = await queryOne<School>(
      `UPDATE schools SET ${sets.join(', ')}, updated_at = NOW() WHERE id = $1 RETURNING *`,
      [id, ...vals],
    );
    if (!row) return reply.code(404).send({ error: 'School not found' });
    reply.send({ data: row });
  });

  // GET /api/v1/schools/:id/leadership — Leadership history
  app.get('/api/v1/schools/:id/leadership', async (request, reply) => {
    const { id } = request.params as { id: string };
    const rows = await query<SchoolLeadership>(
      `SELECT slh.*, p.full_name AS person_name
       FROM school_leadership_history slh
       LEFT JOIN people p ON p.id = slh.person_id
       WHERE slh.school_id = $1
       ORDER BY slh.start_date DESC NULLS LAST`,
      [id],
    );
    reply.send({ data: rows });
  });

  // GET /api/v1/schools/:id/financials — Financial history
  app.get('/api/v1/schools/:id/financials', async (request, reply) => {
    const { id } = request.params as { id: string };
    const rows = await query<SchoolFinancial>(
      `SELECT * FROM school_financials WHERE school_id = $1 ORDER BY fiscal_year DESC`,
      [id],
    );
    reply.send({ data: rows });
  });
}
