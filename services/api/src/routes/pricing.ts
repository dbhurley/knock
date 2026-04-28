import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import type { PricingBand, PricingQuote } from '../types/index.js';

// ─── Pricing Bands (from PRD Section 8) ────────────────────────────────────

const PRICING_BANDS: PricingBand[] = [
  { band: 'A', label: 'Band A', salary_low: 70_000,  salary_high: 100_000,  fee: 20_000,  deposit: 10_000 },
  { band: 'B', label: 'Band B', salary_low: 100_001, salary_high: 150_000,  fee: 30_000,  deposit: 15_000 },
  { band: 'C', label: 'Band C', salary_low: 150_001, salary_high: 200_000,  fee: 40_000,  deposit: 20_000 },
  { band: 'D', label: 'Band D', salary_low: 200_001, salary_high: 275_000,  fee: 55_000,  deposit: 27_500 },
  { band: 'E', label: 'Band E', salary_low: 275_001, salary_high: 375_000,  fee: 75_000,  deposit: 37_500 },
  { band: 'F', label: 'Band F', salary_low: 375_001, salary_high: 500_000,  fee: 100_000, deposit: 50_000 },
  { band: 'G', label: 'Band G', salary_low: 500_001, salary_high: null,     fee: 125_000, deposit: 62_500 },
];

function findBandForSalary(salary: number): PricingBand | null {
  for (const band of PRICING_BANDS) {
    if (salary >= band.salary_low && (band.salary_high === null || salary <= band.salary_high)) {
      return band;
    }
  }
  return null;
}

const quoteQuerySchema = z.object({
  salary: z.coerce.number().int().min(1),
});

// ─── Routes ────────────────────────────────────────────────────────────────

export default async function pricingRoutes(app: FastifyInstance): Promise<void> {

  // GET /api/v1/pricing/bands — Return all pricing bands
  app.get('/api/v1/pricing/bands', async (_request, reply) => {
    reply.send({
      data: PRICING_BANDS,
      meta: {
        deposit_percent: 50,
        guarantee_months: 12,
        notes: 'Deposit is non-refundable but applicable to future search within 24 months. Guarantee: replacement search at no additional fee if placed candidate departs within 12 months.',
      },
    });
  });

  // GET /api/v1/pricing/quote?salary=N — Get quote for a salary
  app.get('/api/v1/pricing/quote', async (request, reply) => {
    const { salary } = quoteQuerySchema.parse(request.query);
    const band = findBandForSalary(salary);

    if (!band) {
      return reply.code(400).send({
        error: 'Salary is below minimum band threshold',
        message: `Minimum salary for pricing is $${PRICING_BANDS[0].salary_low.toLocaleString()}`,
      });
    }

    const quote: PricingQuote = {
      salary,
      band,
      fee: band.fee,
      deposit: band.deposit,
    };

    reply.send({ data: quote });
  });
}
