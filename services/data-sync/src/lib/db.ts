import pg from 'pg';

const { Pool } = pg;

let pool: pg.Pool | null = null;

export function getPool(): pg.Pool {
  if (!pool) {
    pool = new Pool({
      host: process.env.PGHOST || 'localhost',
      port: parseInt(process.env.PGPORT || '5432', 10),
      database: process.env.PGDATABASE || 'knock',
      user: process.env.PGUSER || 'knock',
      password: process.env.PGPASSWORD || 'knock',
      max: parseInt(process.env.PG_POOL_MAX || '10', 10),
      idleTimeoutMillis: 30_000,
      connectionTimeoutMillis: 5_000,
    });

    pool.on('error', (err) => {
      console.error('[db] Unexpected pool error:', err.message);
    });
  }
  return pool;
}

export async function query<T extends pg.QueryResultRow = any>(
  text: string,
  params?: any[],
): Promise<pg.QueryResult<T>> {
  const start = Date.now();
  const result = await getPool().query<T>(text, params);
  const duration = Date.now() - start;
  if (duration > 1000) {
    console.warn(`[db] Slow query (${duration}ms): ${text.slice(0, 120)}`);
  }
  return result;
}

export async function getClient(): Promise<pg.PoolClient> {
  return getPool().connect();
}

export async function closePool(): Promise<void> {
  if (pool) {
    await pool.end();
    pool = null;
  }
}

/**
 * Log a sync operation to the data_sync_log table.
 * Returns the log row id so callers can update it on completion.
 */
export async function createSyncLog(
  source: string,
  syncType: string,
): Promise<string> {
  const res = await query(
    `INSERT INTO data_sync_log (source, sync_type, started_at, status)
     VALUES ($1, $2, NOW(), 'running')
     RETURNING id`,
    [source, syncType],
  );
  return res.rows[0].id;
}

export async function completeSyncLog(
  id: string,
  stats: {
    records_processed: number;
    records_created: number;
    records_updated: number;
    records_errored: number;
  },
  status: 'completed' | 'failed' | 'partial' = 'completed',
  errorDetails?: string,
): Promise<void> {
  await query(
    `UPDATE data_sync_log
     SET completed_at = NOW(),
         records_processed = $2,
         records_created = $3,
         records_updated = $4,
         records_errored = $5,
         status = $6,
         error_details = $7
     WHERE id = $1`,
    [
      id,
      stats.records_processed,
      stats.records_created,
      stats.records_updated,
      stats.records_errored,
      status,
      errorDetails ?? null,
    ],
  );
}
