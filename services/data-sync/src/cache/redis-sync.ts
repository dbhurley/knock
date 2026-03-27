/**
 * PostgreSQL to Redis cache sync.
 *
 * Reads active schools and people from PostgreSQL and writes them to Redis
 * as JSON objects with sorted set indexes for fast filtering.
 *
 * Redis key patterns (from PRD):
 *   knock:school:{id}                -> JSON (full school record)
 *   knock:person:{id}                -> JSON (full person record)
 *   knock:idx:schools:by_state:{ST}  -> Sorted Set (school_id, enrollment)
 *   knock:idx:schools:by_type:{type} -> Sorted Set (school_id, enrollment)
 *   knock:idx:schools:by_tier:{tier} -> Sorted Set (school_id, score)
 *   knock:idx:people:by_role:{role}  -> Sorted Set (person_id, rating)
 *   knock:idx:people:by_state:{ST}   -> Sorted Set (person_id, rating)
 *   knock:idx:people:by_stage:{stg}  -> Sorted Set (person_id, rating)
 *   knock:idx:people:active          -> Set (person_ids currently available)
 */

import { query, createSyncLog, completeSyncLog, closePool } from '../lib/db.js';
import { getRedis, connectRedis, closeRedis } from '../lib/redis.js';

// Tier weights for sorted set scoring
const TIER_SCORES: Record<string, number> = {
  platinum: 5,
  gold: 4,
  silver: 3,
  bronze: 2,
  unranked: 1,
};

// ---------------------------------------------------------------------------
// Full sync
// ---------------------------------------------------------------------------

export interface CacheSyncOptions {
  mode?: 'full' | 'incremental';
  /** For incremental: only sync records updated after this timestamp */
  since?: Date;
}

export async function syncCache(options: CacheSyncOptions = {}): Promise<void> {
  const mode = options.mode || 'full';
  console.log(`[cache] Starting ${mode} Redis cache sync`);

  await connectRedis();
  const redis = getRedis();

  const syncLogId = await createSyncLog('redis_cache', mode);
  const stats = { records_processed: 0, records_created: 0, records_updated: 0, records_errored: 0 };

  try {
    if (mode === 'full') {
      // Clear existing indexes before full rebuild
      await clearIndexes(redis);
    }

    // Sync schools
    await syncSchools(redis, mode, options.since, stats);

    // Sync people
    await syncPeople(redis, mode, options.since, stats);

    await completeSyncLog(syncLogId, stats, 'completed');
    console.log('[cache] Sync complete:', stats);
  } catch (err) {
    await completeSyncLog(syncLogId, stats, 'failed', String(err));
    console.error('[cache] Sync failed:', err);
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Clear all knock: indexes
// ---------------------------------------------------------------------------

async function clearIndexes(redis: ReturnType<typeof getRedis>): Promise<void> {
  console.log('[cache] Clearing existing indexes...');

  // Use SCAN to find and delete index keys
  const patterns = [
    'knock:idx:schools:*',
    'knock:idx:people:*',
  ];

  for (const pattern of patterns) {
    let cursor = '0';
    do {
      const [nextCursor, keys] = await redis.scan(cursor, 'MATCH', pattern, 'COUNT', 200);
      cursor = nextCursor;
      if (keys.length > 0) {
        await redis.del(...keys);
      }
    } while (cursor !== '0');
  }
}

// ---------------------------------------------------------------------------
// School sync
// ---------------------------------------------------------------------------

async function syncSchools(
  redis: ReturnType<typeof getRedis>,
  mode: string,
  since: Date | undefined,
  stats: { records_processed: number; records_created: number; records_updated: number; records_errored: number },
): Promise<void> {
  let schoolQuery: string;
  let schoolParams: any[];

  if (mode === 'incremental' && since) {
    schoolQuery = `
      SELECT * FROM schools
      WHERE is_active = true AND updated_at > $1
      ORDER BY id
    `;
    schoolParams = [since.toISOString()];
  } else {
    schoolQuery = `
      SELECT * FROM schools
      WHERE is_active = true
      ORDER BY id
    `;
    schoolParams = [];
  }

  const BATCH_SIZE = 500;
  let offset = 0;
  let hasMore = true;

  while (hasMore) {
    const batchQuery = `${schoolQuery} LIMIT ${BATCH_SIZE} OFFSET ${offset}`;
    const result = await query(batchQuery, schoolParams);
    const schools = result.rows;

    if (schools.length === 0) {
      hasMore = false;
      break;
    }

    const pipeline = redis.pipeline();

    for (const school of schools) {
      stats.records_processed++;

      try {
        const key = `knock:school:${school.id}`;

        // Store full school record as JSON
        const schoolJson = JSON.stringify(school);
        pipeline.set(key, schoolJson);
        // Set TTL of 25 hours (allows daily rebuild with overlap)
        pipeline.expire(key, 90_000);

        // Build indexes
        const enrollment = school.enrollment_total || 0;
        const tierScore = TIER_SCORES[school.tier || 'unranked'] || 1;

        if (school.state) {
          pipeline.zadd(
            `knock:idx:schools:by_state:${school.state}`,
            enrollment,
            school.id,
          );
        }

        if (school.school_type) {
          pipeline.zadd(
            `knock:idx:schools:by_type:${school.school_type}`,
            enrollment,
            school.id,
          );
        }

        if (school.tier) {
          pipeline.zadd(
            `knock:idx:schools:by_tier:${school.tier}`,
            tierScore,
            school.id,
          );
        }

        if (school.coed_status) {
          pipeline.zadd(
            `knock:idx:schools:by_coed:${school.coed_status}`,
            enrollment,
            school.id,
          );
        }

        if (school.boarding_status) {
          pipeline.zadd(
            `knock:idx:schools:by_boarding:${school.boarding_status}`,
            enrollment,
            school.id,
          );
        }

        if (school.religious_affiliation) {
          pipeline.zadd(
            `knock:idx:schools:by_religion:${school.religious_affiliation.toLowerCase().replace(/\s+/g, '_')}`,
            enrollment,
            school.id,
          );
        }

        stats.records_created++;
      } catch (err) {
        stats.records_errored++;
        console.error(`[cache] Error caching school ${school.id}:`, err);
      }
    }

    await pipeline.exec();
    offset += BATCH_SIZE;

    console.log(`[cache] Schools: ${stats.records_processed} processed`);
  }
}

// ---------------------------------------------------------------------------
// People sync
// ---------------------------------------------------------------------------

async function syncPeople(
  redis: ReturnType<typeof getRedis>,
  mode: string,
  since: Date | undefined,
  stats: { records_processed: number; records_created: number; records_updated: number; records_errored: number },
): Promise<void> {
  let peopleQuery: string;
  let peopleParams: any[];

  if (mode === 'incremental' && since) {
    peopleQuery = `
      SELECT * FROM people
      WHERE updated_at > $1
      ORDER BY id
    `;
    peopleParams = [since.toISOString()];
  } else {
    peopleQuery = `
      SELECT * FROM people
      ORDER BY id
    `;
    peopleParams = [];
  }

  const BATCH_SIZE = 500;
  let offset = 0;
  let hasMore = true;

  while (hasMore) {
    const batchQuery = `${peopleQuery} LIMIT ${BATCH_SIZE} OFFSET ${offset}`;
    const result = await query(batchQuery, peopleParams);
    const people = result.rows;

    if (people.length === 0) {
      hasMore = false;
      break;
    }

    const pipeline = redis.pipeline();

    for (const person of people) {
      stats.records_processed++;

      try {
        const key = `knock:person:${person.id}`;

        // Store full person record as JSON
        const personJson = JSON.stringify(person);
        pipeline.set(key, personJson);
        pipeline.expire(key, 90_000);

        const rating = person.knock_rating || 0;

        // Build indexes
        if (person.primary_role) {
          pipeline.zadd(
            `knock:idx:people:by_role:${person.primary_role}`,
            rating,
            person.id,
          );
        }

        if (person.state) {
          pipeline.zadd(
            `knock:idx:people:by_state:${person.state}`,
            rating,
            person.id,
          );
        }

        if (person.career_stage) {
          pipeline.zadd(
            `knock:idx:people:by_stage:${person.career_stage}`,
            rating,
            person.id,
          );
        }

        if (person.candidate_status === 'active') {
          pipeline.sadd('knock:idx:people:active', person.id);
        }

        if (person.current_school_id) {
          pipeline.sadd(
            `knock:idx:people:by_school:${person.current_school_id}`,
            person.id,
          );
        }

        stats.records_created++;
      } catch (err) {
        stats.records_errored++;
        console.error(`[cache] Error caching person ${person.id}:`, err);
      }
    }

    await pipeline.exec();
    offset += BATCH_SIZE;

    console.log(`[cache] People: ${stats.records_processed} processed`);
  }
}

// ---------------------------------------------------------------------------
// CLI entry point
// ---------------------------------------------------------------------------

const isMainModule =
  process.argv[1] &&
  (process.argv[1].endsWith('/redis-sync.ts') || process.argv[1].endsWith('/redis-sync.js'));

if (isMainModule) {
  const mode = (process.argv[2] === 'incremental' ? 'incremental' : 'full') as 'full' | 'incremental';
  const sinceArg = process.argv[3];
  const since = sinceArg ? new Date(sinceArg) : undefined;

  syncCache({ mode, since })
    .then(() => {
      console.log('[cache] Done.');
      return Promise.all([closePool(), closeRedis()]);
    })
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('[cache] Fatal error:', err);
      process.exit(1);
    });
}
