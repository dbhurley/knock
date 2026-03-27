"""
Database connection and sync-log helpers for the Knock enrichment service.
Mirrors the patterns from services/data-sync/src/lib/db.ts but in Python.
"""

import os
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from uuid import uuid4

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Load .env from project root if present
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(_project_root, '.env'))

logger = logging.getLogger('knock.enrichment.db')

# ---------------------------------------------------------------------------
# Connection pool (simple; psycopg2 doesn't have a built-in pool, we reuse
# a single connection per process and reconnect on error)
# ---------------------------------------------------------------------------

_conn: Optional[psycopg2.extensions.connection] = None


def _dsn() -> str:
    """Build DSN from environment variables."""
    host = os.getenv('POSTGRES_HOST', os.getenv('PGHOST', 'localhost'))
    port = os.getenv('POSTGRES_PORT', os.getenv('PGPORT', '5432'))
    db = os.getenv('POSTGRES_DB', os.getenv('PGDATABASE', 'knock'))
    user = os.getenv('POSTGRES_USER', os.getenv('PGUSER', 'knock_admin'))
    password = os.getenv('POSTGRES_PASSWORD', os.getenv('PGPASSWORD', ''))
    return f"host={host} port={port} dbname={db} user={user} password={password}"


def get_conn() -> psycopg2.extensions.connection:
    """Get or create a database connection."""
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(_dsn())
        _conn.autocommit = False
        # Register UUID adapter
        psycopg2.extras.register_uuid()
        logger.info("Database connection established")
    return _conn


def close_conn() -> None:
    """Close the database connection."""
    global _conn
    if _conn and not _conn.closed:
        _conn.close()
        _conn = None
        logger.info("Database connection closed")


@contextmanager
def get_cursor():
    """Context manager that yields a cursor and commits on success."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


@contextmanager
def get_raw_cursor():
    """Context manager that yields a standard tuple cursor."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def execute(sql: str, params: Optional[tuple] = None) -> None:
    """Execute a statement (INSERT/UPDATE/DELETE) with auto-commit."""
    with get_raw_cursor() as cur:
        cur.execute(sql, params)


def fetch_all(sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
    """Execute a query and return all rows as list of dicts."""
    with get_cursor() as cur:
        start = time.time()
        cur.execute(sql, params)
        rows = cur.fetchall()
        elapsed = time.time() - start
        if elapsed > 1.0:
            logger.warning(f"Slow query ({elapsed:.1f}s): {sql[:120]}")
        return [dict(row) for row in rows]


def fetch_one(sql: str, params: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
    """Execute a query and return the first row as dict, or None."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Sync log helpers
# ---------------------------------------------------------------------------

def create_sync_log(source: str, sync_type: str) -> str:
    """Create a data_sync_log entry and return its id."""
    row = fetch_one(
        """INSERT INTO data_sync_log (source, sync_type, started_at, status)
           VALUES (%s, %s, NOW(), 'running')
           RETURNING id""",
        (source, sync_type),
    )
    log_id = str(row['id'])
    logger.info(f"Sync log created: {log_id} (source={source}, type={sync_type})")
    return log_id


def complete_sync_log(
    log_id: str,
    stats: Dict[str, int],
    status: str = 'completed',
    error_details: Optional[str] = None,
) -> None:
    """Update a data_sync_log entry with completion stats."""
    execute(
        """UPDATE data_sync_log
           SET completed_at = NOW(),
               records_processed = %s,
               records_created = %s,
               records_updated = %s,
               records_errored = %s,
               status = %s,
               error_details = %s
           WHERE id = %s""",
        (
            stats.get('records_processed', 0),
            stats.get('records_created', 0),
            stats.get('records_updated', 0),
            stats.get('records_errored', 0),
            status,
            error_details,
            log_id,
        ),
    )
    logger.info(f"Sync log completed: {log_id} status={status} stats={stats}")


# ---------------------------------------------------------------------------
# Enrichment provenance tracking
# ---------------------------------------------------------------------------

def record_provenance(
    entity_type: str,
    entity_id: str,
    field_name: str,
    field_value: Optional[str],
    source: str,
    source_url: Optional[str] = None,
    confidence: float = 1.0,
) -> None:
    """Record where an enriched data point came from."""
    execute(
        """INSERT INTO enrichment_provenance
               (entity_type, entity_id, field_name, field_value, source, source_url, confidence)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (entity_type, entity_id, field_name, source)
           DO UPDATE SET
               field_value = EXCLUDED.field_value,
               source_url = EXCLUDED.source_url,
               confidence = EXCLUDED.confidence,
               enriched_at = NOW()""",
        (entity_type, entity_id, field_name, field_value, source, source_url, confidence),
    )
