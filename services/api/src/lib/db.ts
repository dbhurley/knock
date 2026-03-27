import pg from 'pg';

const { Pool } = pg;

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 20,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 5_000,
});

pool.on('error', (err) => {
  console.error('[db] Unexpected error on idle client:', err.message);
});

/** Execute a parameterized query and return all rows. */
export async function query<T = Record<string, unknown>>(
  text: string,
  params?: unknown[],
): Promise<T[]> {
  const result = await pool.query(text, params);
  return result.rows as T[];
}

/** Execute a parameterized query and return the first row or null. */
export async function queryOne<T = Record<string, unknown>>(
  text: string,
  params?: unknown[],
): Promise<T | null> {
  const result = await pool.query(text, params);
  return (result.rows[0] as T) ?? null;
}

/** Execute a parameterized query and return the row count. */
export async function execute(
  text: string,
  params?: unknown[],
): Promise<number> {
  const result = await pool.query(text, params);
  return result.rowCount ?? 0;
}

/** Check that the database is reachable. */
export async function ping(): Promise<boolean> {
  try {
    await pool.query('SELECT 1');
    return true;
  } catch {
    return false;
  }
}

/** Drain all connections (for graceful shutdown). */
export async function close(): Promise<void> {
  await pool.end();
}

export default pool;
