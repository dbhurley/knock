import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { query, queryOne } from '../lib/db.js';
import type { PaginatedResponse, Person, PersonExperience, PersonInteraction } from '../types/index.js';

// ─── Validation Schemas ────────────────────────────────────────────────────

const listQuerySchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  per_page: z.coerce.number().int().min(1).max(100).default(25),
  state: z.string().length(2).optional(),
  candidate_status: z.string().optional(),
  primary_role: z.string().optional(),
  career_stage: z.string().optional(),
  knock_rating_min: z.coerce.number().int().min(1).max(5).optional(),
  knock_rating: z.string().optional(),           // 'null' to filter unrated
  sort: z.string().optional(),                   // 'alpha', 'completeness', 'random'
  q: z.string().optional(),
});

const createBodySchema = z.object({
  full_name: z.string().min(1).max(300),
  first_name: z.string().max(100).optional(),
  last_name: z.string().max(100).optional(),
  preferred_name: z.string().max(100).optional(),
  prefix: z.string().max(20).optional(),
  suffix: z.string().max(20).optional(),
  email_primary: z.string().email().max(300).optional(),
  phone_primary: z.string().max(20).optional(),
  city: z.string().max(200).optional(),
  state: z.string().length(2).optional(),
  willing_to_relocate: z.boolean().optional(),
  preferred_regions: z.array(z.string()).optional(),
  preferred_states: z.array(z.string()).optional(),
  current_title: z.string().max(300).optional(),
  current_organization: z.string().max(300).optional(),
  current_school_id: z.string().uuid().optional(),
  career_stage: z.enum(['emerging', 'mid_career', 'senior', 'veteran', 'retired']).optional(),
  primary_role: z.string().max(50).optional(),
  specializations: z.array(z.string()).optional(),
  school_type_experience: z.array(z.string()).optional(),
  knock_rating: z.number().int().min(1).max(5).optional(),
  cultural_fit_tags: z.array(z.string()).optional(),
  leadership_style: z.array(z.string()).optional(),
  ideal_next_role: z.string().max(50).optional(),
  transition_readiness: z.string().max(30).optional(),
  candidate_status: z.enum(['active', 'passive', 'not_looking', 'placed', 'do_not_contact', 'retired']).optional(),
  availability_date: z.string().optional(),
  relationship_strength: z.enum(['strong', 'moderate', 'weak', 'new']).optional(),
  data_source: z.string().max(50).optional(),
  tags: z.array(z.string()).optional(),
  notes: z.string().optional(),
});

const updateBodySchema = createBodySchema.partial();

// ─── Routes ────────────────────────────────────────────────────────────────

export default async function peopleRoutes(app: FastifyInstance): Promise<void> {

  // GET /api/v1/people — List people (paginated + filtered)
  app.get('/api/v1/people', async (request, reply) => {
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
    if (params.candidate_status) {
      conditions.push(`candidate_status = $${idx++}`);
      values.push(params.candidate_status);
    }
    if (params.primary_role) {
      conditions.push(`primary_role = $${idx++}`);
      values.push(params.primary_role);
    }
    if (params.career_stage) {
      conditions.push(`career_stage = $${idx++}`);
      values.push(params.career_stage);
    }
    if (params.knock_rating_min !== undefined) {
      conditions.push(`knock_rating >= $${idx++}`);
      values.push(params.knock_rating_min);
    }
    if (params.knock_rating === 'null') {
      conditions.push(`knock_rating IS NULL`);
    }
    if (params.q) {
      conditions.push(`search_vector @@ plainto_tsquery('english', $${idx++})`);
      values.push(params.q);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';

    // Sort options
    let orderBy = 'ORDER BY last_name ASC, first_name ASC';
    if (params.sort === 'completeness') {
      orderBy = 'ORDER BY data_completeness_score DESC NULLS LAST, last_name ASC';
    } else if (params.sort === 'random') {
      orderBy = 'ORDER BY RANDOM()';
    }

    const countRow = await queryOne<{ count: string }>(
      `SELECT COUNT(*) AS count FROM people ${where}`,
      values,
    );
    const total = parseInt(countRow?.count ?? '0', 10);

    const rows = await query<Person>(
      `SELECT * FROM people ${where} ${orderBy} LIMIT $${idx++} OFFSET $${idx++}`,
      [...values, per_page, offset],
    );

    const result: PaginatedResponse<Person> = {
      data: rows,
      pagination: { page, per_page, total, total_pages: Math.ceil(total / per_page) },
    };
    reply.send(result);
  });

  // GET /api/v1/people/:id — Get single person
  app.get('/api/v1/people/:id', async (request, reply) => {
    const { id } = request.params as { id: string };
    const person = await queryOne<Person>('SELECT * FROM people WHERE id = $1', [id]);
    if (!person) return reply.code(404).send({ error: 'Person not found' });
    reply.send({ data: person });
  });

  // POST /api/v1/people — Create person
  app.post('/api/v1/people', async (request, reply) => {
    const body = createBodySchema.parse(request.body);
    const keys = Object.keys(body) as (keyof typeof body)[];
    const cols = keys.join(', ');
    const placeholders = keys.map((_, i) => `$${i + 1}`).join(', ');
    const vals = keys.map((k) => body[k]);

    const row = await queryOne<Person>(
      `INSERT INTO people (${cols}) VALUES (${placeholders}) RETURNING *`,
      vals,
    );
    reply.code(201).send({ data: row });
  });

  // PATCH /api/v1/people/:id — Update person
  app.patch('/api/v1/people/:id', async (request, reply) => {
    const { id } = request.params as { id: string };
    const body = updateBodySchema.parse(request.body);
    const keys = Object.keys(body) as (keyof typeof body)[];
    if (keys.length === 0) return reply.code(400).send({ error: 'No fields to update' });

    const sets = keys.map((k, i) => `${k} = $${i + 2}`);
    const vals = keys.map((k) => body[k]);

    const row = await queryOne<Person>(
      `UPDATE people SET ${sets.join(', ')}, updated_at = NOW() WHERE id = $1 RETURNING *`,
      [id, ...vals],
    );
    if (!row) return reply.code(404).send({ error: 'Person not found' });
    reply.send({ data: row });
  });

  // GET /api/v1/people/:id/experience — Work history
  app.get('/api/v1/people/:id/experience', async (request, reply) => {
    const { id } = request.params as { id: string };
    const rows = await query<PersonExperience>(
      `SELECT pe.*, s.name AS school_name
       FROM person_experience pe
       LEFT JOIN schools s ON s.id = pe.school_id
       WHERE pe.person_id = $1
       ORDER BY pe.is_current DESC, pe.start_date DESC NULLS LAST`,
      [id],
    );
    reply.send({ data: rows });
  });

  // GET /api/v1/people/:id/interactions — Interaction log
  app.get('/api/v1/people/:id/interactions', async (request, reply) => {
    const { id } = request.params as { id: string };
    const qp = z.object({
      page: z.coerce.number().int().min(1).default(1),
      per_page: z.coerce.number().int().min(1).max(100).default(25),
    }).parse(request.query);

    const offset = (qp.page - 1) * qp.per_page;

    const countRow = await queryOne<{ count: string }>(
      'SELECT COUNT(*) AS count FROM person_interactions WHERE person_id = $1',
      [id],
    );
    const total = parseInt(countRow?.count ?? '0', 10);

    const rows = await query<PersonInteraction>(
      `SELECT * FROM person_interactions
       WHERE person_id = $1
       ORDER BY created_at DESC
       LIMIT $2 OFFSET $3`,
      [id, qp.per_page, offset],
    );

    const result: PaginatedResponse<PersonInteraction> = {
      data: rows,
      pagination: { page: qp.page, per_page: qp.per_page, total, total_pages: Math.ceil(total / qp.per_page) },
    };
    reply.send(result);
  });
}
