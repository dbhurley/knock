"""
Shared utilities for the Knock people-sources service:
  - DB connection (reuses patterns from enrichment service)
  - Name normalization and fuzzy matching
  - Rate-limited HTTP session
  - Deduplication helpers
"""

import os
import re
import time
import logging
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

import psycopg2
import psycopg2.extras
import requests
from bs4 import BeautifulSoup
from thefuzz import fuzz
from dotenv import load_dotenv

# Load .env from project root if present
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(_project_root, '.env'))

logger = logging.getLogger('knock.people_sources')

# ---------------------------------------------------------------------------
# Database connection (matches enrichment/db.py patterns)
# ---------------------------------------------------------------------------

_conn: Optional[psycopg2.extensions.connection] = None


def _dsn() -> str:
    host = os.getenv('POSTGRES_HOST', os.getenv('PGHOST', 'localhost'))
    port = os.getenv('POSTGRES_PORT', os.getenv('PGPORT', '5432'))
    db = os.getenv('POSTGRES_DB', os.getenv('PGDATABASE', 'knock'))
    user = os.getenv('POSTGRES_USER', os.getenv('PGUSER', 'knock_admin'))
    password = os.getenv('POSTGRES_PASSWORD', os.getenv('PGPASSWORD', ''))
    return f"host={host} port={port} dbname={db} user={user} password={password}"


def get_conn() -> psycopg2.extensions.connection:
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(_dsn())
        _conn.autocommit = False
        psycopg2.extras.register_uuid()
        logger.info("Database connection established")
    return _conn


def close_conn() -> None:
    global _conn
    if _conn and not _conn.closed:
        _conn.close()
        _conn = None
        logger.info("Database connection closed")


@contextmanager
def get_cursor():
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
    with get_raw_cursor() as cur:
        cur.execute(sql, params)


def fetch_all(sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def fetch_one(sql: str, params: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Sync log helpers
# ---------------------------------------------------------------------------

def create_sync_log(source: str, sync_type: str) -> str:
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
# Name normalization & matching
# ---------------------------------------------------------------------------

PREFIXES = {'dr', 'mr', 'mrs', 'ms', 'rev', 'fr', 'sr', 'prof', 'hon'}
SUFFIXES = {
    'jr', 'sr', 'ii', 'iii', 'iv', 'v',
    'phd', 'edd', 'md', 'jd', 'esq',
    'cpa', 'mba', 'ma', 'ms', 'bs', 'ba', 'med',
}


def normalize_name(name: Optional[str]) -> str:
    if not name:
        return ''
    nfkd = unicodedata.normalize('NFKD', name)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    result = stripped.lower()
    result = re.sub(r'[^a-z\s]', '', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def strip_honorifics(name: str) -> str:
    parts = name.lower().replace('.', '').split()
    parts = [p for p in parts if p not in PREFIXES and p not in SUFFIXES]
    return ' '.join(parts)


def name_similarity(a: str, b: str) -> float:
    na = strip_honorifics(normalize_name(a))
    nb = strip_honorifics(normalize_name(b))
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    return max(fuzz.token_sort_ratio(na, nb), fuzz.partial_ratio(na, nb))


def fuzzy_name_match(a: str, b: str, threshold: float = 80.0) -> bool:
    return name_similarity(a, b) >= threshold


def org_similarity(a: str, b: str) -> float:
    na = normalize_name(a)
    nb = normalize_name(b)
    if not na or not nb:
        return 0.0
    for prefix in ['the ', 'a ']:
        na = na.removeprefix(prefix)
        nb = nb.removeprefix(prefix)
    if na == nb:
        return 100.0
    return max(fuzz.token_sort_ratio(na, nb), fuzz.partial_ratio(na, nb))


def fuzzy_org_match(a: str, b: str, threshold: float = 75.0) -> bool:
    return org_similarity(a, b) >= threshold


def parse_name_parts(full_name: str) -> Dict[str, str]:
    if not full_name:
        return {'first_name': '', 'last_name': '', 'prefix': '', 'suffix': ''}
    name = full_name.strip()
    prefix = ''
    suffix = ''
    parts = name.split()
    if parts and parts[0].lower().rstrip('.') in PREFIXES:
        prefix = parts[0]
        parts = parts[1:]
    suffixes_found = []
    while parts and parts[-1].lower().rstrip('.').rstrip(',') in SUFFIXES:
        suffixes_found.insert(0, parts.pop())
    suffix = ' '.join(suffixes_found)
    name = ' '.join(parts)
    if ',' in name:
        last_first = name.split(',', 1)
        last_name = last_first[0].strip()
        first_name = last_first[1].strip()
    elif len(parts) >= 2:
        first_name = parts[0]
        last_name = ' '.join(parts[1:])
    elif len(parts) == 1:
        first_name = parts[0]
        last_name = ''
    else:
        first_name = ''
        last_name = ''
    return {
        'first_name': first_name,
        'last_name': last_name,
        'prefix': prefix,
        'suffix': suffix,
    }


# ---------------------------------------------------------------------------
# Rate-limited HTTP session
# ---------------------------------------------------------------------------

class RateLimitedSession:
    def __init__(
        self,
        min_delay: float = 2.5,
        max_retries: int = 2,
        backoff_factor: float = 2.0,
        user_agent: str = 'Knock Research Bot (askknock.com)',
    ):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        self.min_delay = min_delay
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._last_request_time = 0.0

    def _wait(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

    def get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault('timeout', 30)
        for attempt in range(self.max_retries + 1):
            self._wait()
            self._last_request_time = time.time()
            try:
                resp = self.session.get(url, **kwargs)
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout (attempt {attempt+1}/{self.max_retries+1}): {url}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor ** attempt)
                    continue
                raise
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error (attempt {attempt+1}): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor ** (attempt + 1))
                    continue
                raise
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error: {e}")
                raise

            if resp.status_code == 429:
                wait_time = self.backoff_factor ** (attempt + 2)
                logger.warning(f"Rate limited (429) from {url}. Waiting {wait_time:.0f}s...")
                time.sleep(wait_time)
                continue

            if resp.status_code == 403:
                logger.warning(f"Access denied (403) from {url}. Site may block scraping.")
                return resp  # Return it; caller decides

            if resp.status_code >= 500:
                logger.warning(f"Server error ({resp.status_code}) from {url}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor ** attempt)
                    continue

            return resp

        raise requests.exceptions.HTTPError(f"Max retries exceeded for {url}")

    def get_soup(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        """Fetch URL and return BeautifulSoup, or None on error."""
        try:
            resp = self.get(url, **kwargs)
            if resp.status_code != 200:
                logger.warning(f"Non-200 status ({resp.status_code}) for {url}")
                return None
            return BeautifulSoup(resp.text, 'lxml')
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def get_json(self, url: str, **kwargs) -> Optional[Any]:
        """Fetch URL and return parsed JSON, or None on error."""
        try:
            self.session.headers['Accept'] = 'application/json'
            resp = self.get(url, **kwargs)
            self.session.headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch JSON from {url}: {e}")
            return None

    def close(self) -> None:
        self.session.close()


# ---------------------------------------------------------------------------
# Person upsert / dedup
# ---------------------------------------------------------------------------

def find_existing_person(
    full_name: str,
    organization: Optional[str] = None,
    title: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Try to find an existing person record by name match.
    If organization is provided, use it to disambiguate.
    Returns the person dict or None.
    """
    normalized = normalize_name(full_name)
    if not normalized:
        return None

    # First try exact normalized name match
    candidates = fetch_all(
        """SELECT * FROM people
           WHERE name_normalized = %s
           LIMIT 10""",
        (normalized,),
    )

    if not candidates:
        # Try trigram search
        candidates = fetch_all(
            """SELECT * FROM people
               WHERE name_normalized %% %s
               ORDER BY similarity(name_normalized, %s) DESC
               LIMIT 10""",
            (normalized, normalized),
        )

    if not candidates:
        return None

    # If we have an organization, prefer matching on org too
    if organization:
        for c in candidates:
            if c.get('current_organization') and fuzzy_org_match(
                c['current_organization'], organization
            ):
                return c

    # Otherwise return best name match
    best = None
    best_score = 0.0
    for c in candidates:
        score = name_similarity(full_name, c['full_name'])
        if score > best_score and score >= 85.0:
            best = c
            best_score = score

    return best


def upsert_person(
    full_name: str,
    data_source: str,
    title: Optional[str] = None,
    organization: Optional[str] = None,
    school_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Tuple[str, bool]:
    """
    Find or create a person record.
    Returns (person_id, was_created).
    """
    existing = find_existing_person(full_name, organization, title)
    if existing:
        person_id = str(existing['id'])
        # Update tags if new ones provided
        if tags:
            existing_tags = existing.get('tags') or []
            new_tags = list(set(existing_tags + tags))
            if new_tags != existing_tags:
                execute(
                    "UPDATE people SET tags = %s WHERE id = %s",
                    (new_tags, person_id),
                )
        # Update title/org if currently empty
        updates = []
        params = []
        if title and not existing.get('current_title'):
            updates.append("current_title = %s")
            params.append(title)
        if organization and not existing.get('current_organization'):
            updates.append("current_organization = %s")
            params.append(organization)
        if school_id and not existing.get('current_school_id'):
            updates.append("current_school_id = %s")
            params.append(school_id)
        if updates:
            params.append(person_id)
            execute(
                f"UPDATE people SET {', '.join(updates)} WHERE id = %s",
                tuple(params),
            )
        return person_id, False

    # Create new person
    name_parts = parse_name_parts(full_name)
    all_tags = tags or []

    row = fetch_one(
        """INSERT INTO people
               (full_name, first_name, last_name, prefix, suffix,
                name_normalized, current_title, current_organization,
                current_school_id, data_source, tags, candidate_status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'passive')
           RETURNING id""",
        (
            full_name,
            name_parts['first_name'],
            name_parts['last_name'],
            name_parts['prefix'] or None,
            name_parts['suffix'] or None,
            normalize_name(full_name),
            title,
            organization,
            school_id,
            data_source,
            all_tags if all_tags else None,
        ),
    )
    person_id = str(row['id'])
    logger.info(f"Created person: {full_name} (id={person_id}, source={data_source})")
    return person_id, True


def find_school_by_name(school_name: str) -> Optional[Dict[str, Any]]:
    """Find a school by fuzzy name match."""
    normalized = normalize_name(school_name)
    if not normalized:
        return None

    candidates = fetch_all(
        """SELECT id, name, name_normalized, city, state
           FROM schools
           WHERE name_normalized %% %s
           ORDER BY similarity(name_normalized, %s) DESC
           LIMIT 5""",
        (normalized, normalized),
    )

    for c in candidates:
        if org_similarity(school_name, c['name']) >= 80.0:
            return c

    return None


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_email(text: str) -> Optional[str]:
    match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return match.group(0).lower() if match else None


def safe_date(date_str: Optional[str]) -> Optional[str]:
    """Try to parse a date string into YYYY-MM-DD format. Return None on failure."""
    if not date_str:
        return None
    try:
        from dateutil import parser as dateparser
        dt = dateparser.parse(date_str)
        return dt.strftime('%Y-%m-%d') if dt else None
    except Exception:
        return None


def record_provenance(
    entity_type: str,
    entity_id: str,
    field_name: str,
    field_value: Optional[str],
    source: str,
    source_url: Optional[str] = None,
    confidence: float = 1.0,
) -> None:
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
