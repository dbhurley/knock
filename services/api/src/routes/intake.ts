import type { FastifyInstance } from 'fastify';
import { query, queryOne, execute } from '../lib/db.js';

interface IntakeBody {
  school_name: string;
  city: string;
  state: string;
  contact_name: string;
  contact_title?: string;
  contact_email: string;
  contact_phone?: string;
  position_category: string;
  position_other?: string;
  salary_band: string;
  target_start_date?: string;
  search_urgency?: string;
  description?: string;
  requirements?: string;
  referral_source?: string;
}

const BANDS: Record<string, { low: number; high: number; fee: number }> = {
  band_a: { low: 70000, high: 100000, fee: 20000 },
  band_b: { low: 100001, high: 150000, fee: 30000 },
  band_c: { low: 150001, high: 200000, fee: 40000 },
  band_d: { low: 200001, high: 275000, fee: 55000 },
  band_e: { low: 275001, high: 375000, fee: 75000 },
  band_f: { low: 375001, high: 500000, fee: 100000 },
  band_g: { low: 500001, high: 9999999, fee: 125000 },
};

export default async function intakeRoutes(app: FastifyInstance): Promise<void> {

  // Public intake endpoint — no API key required
  app.post<{ Body: IntakeBody }>('/api/v1/intake', async (request, reply) => {
    const b = request.body;

    if (!b.school_name || !b.city || !b.state || !b.contact_name || !b.contact_email || !b.position_category || !b.salary_band) {
      return reply.code(400).send({ error: 'Missing required fields' });
    }

    // 1. Find or create school
    let school = await queryOne(
      `SELECT id FROM schools WHERE LOWER(name_normalized) = LOWER($1) AND LOWER(state) = LOWER($2) LIMIT 1`,
      [b.school_name.toLowerCase().trim(), b.state.trim()]
    );

    let schoolId: string;
    if (school) {
      schoolId = String(school.id);
    } else {
      const newSchool = await queryOne(
        `INSERT INTO schools (name, name_normalized, city, state, is_private, is_independent, data_source)
         VALUES ($1, $2, $3, $4, TRUE, TRUE, 'intake_form') RETURNING id`,
        [b.school_name.trim(), b.school_name.toLowerCase().trim(), b.city.trim(), b.state.trim()]
      );
      schoolId = String(newSchool!.id);
    }

    // 2. Find or create contact person
    const person = await queryOne(
      `SELECT id FROM people WHERE LOWER(name_normalized) = LOWER($1) LIMIT 1`,
      [b.contact_name.toLowerCase().trim()]
    );

    let personId: string;
    if (person) {
      personId = String(person.id);
      await execute(
        `UPDATE people SET email_primary = COALESCE(email_primary, $1), phone_primary = COALESCE(phone_primary, $2),
         current_organization = $3, current_title = COALESCE($4, current_title), updated_at = NOW() WHERE id = $5`,
        [b.contact_email, b.contact_phone || null, b.school_name, b.contact_title || null, personId]
      );
    } else {
      const parts = b.contact_name.trim().split(' ');
      const firstName = parts[0] || '';
      const lastName = parts.slice(1).join(' ') || '';
      const newPerson = await queryOne(
        `INSERT INTO people (first_name, last_name, full_name, name_normalized, email_primary, phone_primary,
         current_title, current_organization, current_school_id, data_source, tags)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'intake_form', ARRAY['client_contact'])
         RETURNING id`,
        [firstName, lastName, b.contact_name.trim(), b.contact_name.toLowerCase().trim(),
         b.contact_email, b.contact_phone || null, b.contact_title || null, b.school_name, schoolId]
      );
      personId = String(newPerson!.id);
    }

    // 3. Generate search number
    const year = new Date().getFullYear();
    const countResult = await queryOne(
      `SELECT COUNT(*) as c FROM searches WHERE EXTRACT(YEAR FROM created_at) = $1`,
      [year]
    );
    const num = parseInt(String(countResult?.c ?? '0'), 10) + 1;
    const searchNumber = `KNK-${year}-${String(num).padStart(3, '0')}`;

    // 4. Get pricing band info
    const band = BANDS[b.salary_band];
    const positionTitle = b.position_category === 'other'
      ? (b.position_other || 'Executive Position')
      : b.position_category.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

    // 5. Create search record
    const search = await queryOne(
      `INSERT INTO searches (
        search_number, school_id, position_title, position_category,
        position_description, position_requirements,
        salary_range_low, salary_range_high, salary_band, pricing_band, fee_amount,
        target_start_date, search_urgency, status,
        client_contact_name, client_contact_title, client_contact_email, client_contact_phone,
        notes
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'intake', $14, $15, $16, $17, $18)
      RETURNING id, search_number`,
      [
        searchNumber, schoolId, positionTitle, b.position_category,
        b.description || null, b.requirements || null,
        band?.low || null, band?.high || null, b.salary_band, b.salary_band, band?.fee || null,
        b.target_start_date || null, b.search_urgency || 'standard',
        b.contact_name, b.contact_title || null, b.contact_email, b.contact_phone || null,
        b.referral_source ? `Referral source: ${b.referral_source}` : null
      ]
    );

    // 6. Log the activity
    await execute(
      `INSERT INTO search_activities (search_id, activity_type, description, performed_by)
       VALUES ($1, 'status_change', 'New search intake received via web form', 'system')`,
      [search!.id]
    );

    // 7. Send Telegram notification
    const telegramToken = process.env.TELEGRAM_BOT_TOKEN;
    const chatId = process.env.TELEGRAM_CHAT_ID || '-1003814956035';
    if (telegramToken) {
      const msg = [
        `🔔 *New Search Inquiry*`,
        ``,
        `*School:* ${b.school_name} (${b.city}, ${b.state})`,
        `*Position:* ${positionTitle}`,
        `*Salary Band:* ${b.salary_band} (Fee: $${(band?.fee || 0).toLocaleString()})`,
        `*Contact:* ${b.contact_name}${b.contact_title ? ` — ${b.contact_title}` : ''}`,
        `*Email:* ${b.contact_email}`,
        b.contact_phone ? `*Phone:* ${b.contact_phone}` : '',
        b.search_urgency ? `*Urgency:* ${b.search_urgency}` : '',
        b.target_start_date ? `*Target Start:* ${b.target_start_date}` : '',
        ``,
        `*Search #:* \`${searchNumber}\``,
        b.description ? `\n*Description:*\n${b.description.substring(0, 500)}` : '',
      ].filter(Boolean).join('\n');

      try {
        await globalThis.fetch(`https://api.telegram.org/bot${telegramToken}/sendMessage`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: 'Markdown' }),
        });
      } catch (e) {
        request.log.error(`Telegram notification failed: ${String(e)}`);
      }
    }

    return reply.code(201).send({
      success: true,
      search_number: searchNumber,
      search_id: search!.id,
      message: 'Search inquiry received. Janet will be in touch within 24 hours.',
    });
  });
}
