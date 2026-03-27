"""
Shared utilities for Knock association scrapers:
  - Database connection (psycopg2, DATABASE_URL)
  - Fuzzy matching for school and person dedup
  - Name parsing
  - Rate-limited HTTP session with retry
  - Data sync log tracking
"""

import os
import re
import time
import logging
import unicodedata
from typing import Optional, Dict, Any, List, Tuple
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import requests
from thefuzz import fuzz
from bs4 import BeautifulSoup

from config import DEFAULT_USER_AGENT, DEFAULT_REQUEST_DELAY, MAX_RETRIES, BACKOFF_FACTOR, REQUEST_TIMEOUT, US_STATES

logger = logging.getLogger('knock.scrapers')

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

_conn: Optional[psycopg2.extensions.connection] = None

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgres://knock_admin:PASSWORD@localhost:5432/knock'
)


def get_db_conn() -> psycopg2.extensions.connection:
    """Get or create a database connection using DATABASE_URL."""
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(DATABASE_URL)
        _conn.autocommit = False
        psycopg2.extras.register_uuid()
        logger.info("Database connection established")
    return _conn


def close_db_conn() -> None:
    """Close the database connection."""
    global _conn
    if _conn and not _conn.closed:
        _conn.close()
        _conn = None
        logger.info("Database connection closed")


@contextmanager
def get_cursor(conn=None):
    """Context manager: yields a RealDictCursor, commits on success."""
    c = conn or get_db_conn()
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        cur.close()


def execute(sql: str, params: Optional[tuple] = None, conn=None) -> None:
    """Execute an INSERT/UPDATE/DELETE with auto-commit."""
    c = conn or get_db_conn()
    cur = c.cursor()
    try:
        cur.execute(sql, params)
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        cur.close()


def fetch_all(sql: str, params: Optional[tuple] = None, conn=None) -> List[Dict[str, Any]]:
    """Execute a SELECT and return all rows as list of dicts."""
    with get_cursor(conn) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def fetch_one(sql: str, params: Optional[tuple] = None, conn=None) -> Optional[Dict[str, Any]]:
    """Execute a SELECT and return the first row as dict, or None."""
    with get_cursor(conn) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Name normalization & parsing
# ---------------------------------------------------------------------------

PREFIXES = {'dr', 'mr', 'mrs', 'ms', 'rev', 'fr', 'sr', 'prof', 'hon', 'sister', 'brother'}
SUFFIXES = {
    'jr', 'sr', 'ii', 'iii', 'iv', 'v',
    'phd', 'edd', 'md', 'jd', 'esq',
    'cpa', 'mba', 'ma', 'ms', 'bs', 'ba', 'med',
}


def normalize_name(name: Optional[str]) -> str:
    """Lowercase, strip accents, remove punctuation."""
    if not name:
        return ''
    nfkd = unicodedata.normalize('NFKD', name)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    result = stripped.lower()
    result = re.sub(r'[^a-z\s]', '', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def strip_honorifics(name: str) -> str:
    """Remove common prefixes and suffixes for matching."""
    parts = name.lower().replace('.', '').split()
    parts = [p for p in parts if p not in PREFIXES and p not in SUFFIXES]
    return ' '.join(parts)


def parse_name_parts(full_name: str) -> Dict[str, str]:
    """Split a full name into first_name, last_name, prefix, suffix."""
    if not full_name:
        return {'first_name': '', 'last_name': '', 'prefix': '', 'suffix': ''}

    name = full_name.strip()
    prefix = ''
    suffix = ''

    parts = name.split()
    if parts and parts[0].lower().rstrip('.') in PREFIXES:
        prefix = parts.pop(0)

    suffixes_found = []
    while parts:
        candidate = parts[-1].lower().rstrip('.').rstrip(',')
        candidate_no_dots = candidate.replace('.', '')
        if candidate in SUFFIXES or candidate_no_dots in SUFFIXES:
            suffixes_found.insert(0, parts.pop())
        else:
            break
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
# Fuzzy matching
# ---------------------------------------------------------------------------

def name_similarity(a: str, b: str) -> float:
    """Compute similarity between two names (0-100 scale)."""
    na = strip_honorifics(normalize_name(a))
    nb = strip_honorifics(normalize_name(b))
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    return max(fuzz.token_sort_ratio(na, nb), fuzz.partial_ratio(na, nb))


def org_similarity(a: str, b: str) -> float:
    """Compare two organization/school names (0-100 scale)."""
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


def normalize_state(state_str: Optional[str]) -> str:
    """Normalize a US state to its 2-letter abbreviation."""
    if not state_str:
        return ''
    s = state_str.strip().lower()
    if len(s) == 2:
        return s.upper()
    return US_STATES.get(s, s.upper())


def normalize_city(city: Optional[str]) -> str:
    """Normalize a city name for matching."""
    if not city:
        return ''
    return re.sub(r'\s+', ' ', city.strip().lower())


# ---------------------------------------------------------------------------
# School dedup: match on name + city + state, threshold 0.7 (70/100)
# ---------------------------------------------------------------------------

def find_matching_school(
    school_name: str,
    city: str,
    state: str,
    conn=None,
    threshold: float = 70.0,
) -> Optional[Dict[str, Any]]:
    """
    Search schools table for a fuzzy match.
    Returns the matching row if found, None otherwise.
    Uses name + city + state with 0.7 threshold on name.
    """
    norm_state = normalize_state(state)
    norm_city = normalize_city(city)

    # First try exact state match to narrow the search
    candidates = fetch_all(
        """SELECT id, name, city, state, website, phone, enrollment,
                  grade_low, grade_high, data_source
           FROM schools
           WHERE LOWER(state) = LOWER(%s)""",
        (norm_state,),
        conn=conn,
    )

    best_match = None
    best_score = 0.0

    for school in candidates:
        name_score = org_similarity(school_name, school.get('name', ''))
        if name_score < threshold:
            continue

        # Boost score if city also matches
        city_score = 0.0
        if norm_city and school.get('city'):
            city_score = fuzz.ratio(norm_city, normalize_city(school['city']))

        combined = name_score * 0.7 + city_score * 0.3

        if combined > best_score:
            best_score = combined
            best_match = school

    if best_match and best_score >= threshold:
        return best_match
    return None


# ---------------------------------------------------------------------------
# Person dedup: match on name + org, threshold 0.8 (80/100)
# ---------------------------------------------------------------------------

def find_matching_person(
    first_name: str,
    last_name: str,
    organization: str,
    conn=None,
    threshold: float = 80.0,
) -> Optional[Dict[str, Any]]:
    """
    Search people table for a fuzzy match on name + organization.
    Returns the matching row if found, None otherwise.
    """
    full_name = f"{first_name} {last_name}".strip()
    if not full_name:
        return None

    # Narrow by last name similarity first
    candidates = fetch_all(
        """SELECT id, first_name, last_name, organization, title, email, phone,
                  data_source
           FROM people
           WHERE LOWER(last_name) = LOWER(%s)
           LIMIT 100""",
        (last_name,),
        conn=conn,
    )

    # If no exact last-name match, try fuzzy on broader set
    if not candidates and last_name:
        candidates = fetch_all(
            """SELECT id, first_name, last_name, organization, title, email, phone,
                      data_source
               FROM people
               WHERE LOWER(last_name) LIKE LOWER(%s)
               LIMIT 200""",
            (f"{last_name[:3]}%",),
            conn=conn,
        )

    best_match = None
    best_score = 0.0

    for person in candidates:
        p_full = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
        name_score = name_similarity(full_name, p_full)
        if name_score < threshold:
            continue

        # Boost if org matches
        org_score = 0.0
        if organization and person.get('organization'):
            org_score = org_similarity(organization, person['organization'])

        combined = name_score * 0.6 + org_score * 0.4

        if combined > best_score:
            best_score = combined
            best_match = person

    if best_match and best_score >= (threshold * 0.8):
        return best_match
    return None


# ---------------------------------------------------------------------------
# Insert / update helpers
# ---------------------------------------------------------------------------

def insert_school(data: Dict[str, Any], conn=None) -> Optional[str]:
    """
    Insert a new school record. Returns the new school id.
    data keys: name, city, state, address, zip_code, phone, website, email,
               enrollment, grade_low, grade_high, school_type, affiliation,
               accreditation, data_source, tags (list)
    """
    row = fetch_one(
        """INSERT INTO schools
           (name, city, state, address, zip_code, phone, website, email,
            enrollment, grade_low, grade_high, school_type, affiliation,
            accreditation, data_source, tags, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
           RETURNING id""",
        (
            data.get('name', ''),
            data.get('city', ''),
            normalize_state(data.get('state', '')),
            data.get('address', ''),
            data.get('zip_code', ''),
            data.get('phone', ''),
            data.get('website', ''),
            data.get('email', ''),
            data.get('enrollment'),
            data.get('grade_low', ''),
            data.get('grade_high', ''),
            data.get('school_type', 'private'),
            data.get('affiliation', ''),
            data.get('accreditation', ''),
            data.get('data_source', 'association_scrape'),
            data.get('tags', []),
        ),
        conn=conn,
    )
    return str(row['id']) if row else None


def update_school(school_id: str, updates: Dict[str, Any], conn=None) -> None:
    """Update an existing school with non-empty values from updates dict."""
    set_clauses = []
    values = []
    for field in ['phone', 'website', 'email', 'enrollment', 'grade_low', 'grade_high',
                   'affiliation', 'accreditation', 'school_type', 'address', 'zip_code']:
        if updates.get(field):
            set_clauses.append(f"{field} = %s")
            values.append(updates[field])

    # Always merge tags if provided
    if updates.get('tags'):
        set_clauses.append("tags = ARRAY(SELECT DISTINCT unnest(COALESCE(tags, ARRAY[]::text[]) || %s::text[]))")
        values.append(updates['tags'])

    if not set_clauses:
        return

    set_clauses.append("updated_at = NOW()")
    values.append(school_id)

    execute(
        f"UPDATE schools SET {', '.join(set_clauses)} WHERE id = %s",
        tuple(values),
        conn=conn,
    )


def insert_person(data: Dict[str, Any], conn=None) -> Optional[str]:
    """
    Insert a new person record. Returns the new person id.
    data keys: first_name, last_name, title, organization, email, phone,
               school_id, data_source, linkedin_url
    """
    row = fetch_one(
        """INSERT INTO people
           (first_name, last_name, title, organization, email, phone,
            school_id, data_source, linkedin_url, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
           RETURNING id""",
        (
            data.get('first_name', ''),
            data.get('last_name', ''),
            data.get('title', ''),
            data.get('organization', ''),
            data.get('email', ''),
            data.get('phone', ''),
            data.get('school_id'),
            data.get('data_source', 'association_directory'),
            data.get('linkedin_url', ''),
        ),
        conn=conn,
    )
    return str(row['id']) if row else None


def update_person(person_id: str, updates: Dict[str, Any], conn=None) -> None:
    """Update an existing person with non-empty values from updates dict."""
    set_clauses = []
    values = []
    for field in ['title', 'email', 'phone', 'organization', 'school_id', 'linkedin_url']:
        if updates.get(field):
            set_clauses.append(f"{field} = %s")
            values.append(updates[field])

    if not set_clauses:
        return

    set_clauses.append("updated_at = NOW()")
    values.append(person_id)

    execute(
        f"UPDATE people SET {', '.join(set_clauses)} WHERE id = %s",
        tuple(values),
        conn=conn,
    )


# ---------------------------------------------------------------------------
# Rate-limited HTTP session
# ---------------------------------------------------------------------------

class ScraperSession:
    """
    requests.Session wrapper with rate limiting, retries, and polite headers.
    """

    def __init__(
        self,
        min_delay: float = DEFAULT_REQUEST_DELAY,
        max_retries: int = MAX_RETRIES,
        backoff_factor: float = BACKOFF_FACTOR,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
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
        """Rate-limited GET with retry on 429 and transient errors."""
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)
        for attempt in range(self.max_retries + 1):
            self._wait()
            self._last_request_time = time.time()
            try:
                resp = self.session.get(url, **kwargs)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor ** attempt)
                    continue
                raise

            if resp.status_code == 429:
                wait_time = self.backoff_factor ** (attempt + 2)
                logger.warning(f"Rate limited (429). Waiting {wait_time:.0f}s...")
                time.sleep(wait_time)
                continue

            if resp.status_code >= 500 and attempt < self.max_retries:
                time.sleep(self.backoff_factor ** attempt)
                continue

            resp.raise_for_status()
            return resp

        raise requests.exceptions.HTTPError(f"Max retries exceeded for {url}")

    def get_soup(self, url: str, **kwargs) -> BeautifulSoup:
        """GET a page and return a BeautifulSoup object."""
        resp = self.get(url, **kwargs)
        return BeautifulSoup(resp.text, 'lxml')

    def post(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited POST with retry."""
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)
        for attempt in range(self.max_retries + 1):
            self._wait()
            self._last_request_time = time.time()
            try:
                resp = self.session.post(url, **kwargs)
            except requests.exceptions.RequestException as e:
                logger.warning(f"POST error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor ** attempt)
                    continue
                raise

            if resp.status_code == 429:
                wait_time = self.backoff_factor ** (attempt + 2)
                time.sleep(wait_time)
                continue

            if resp.status_code >= 500 and attempt < self.max_retries:
                time.sleep(self.backoff_factor ** attempt)
                continue

            resp.raise_for_status()
            return resp

        raise requests.exceptions.HTTPError(f"Max retries exceeded for POST {url}")

    def post_json(self, url: str, json_data: dict, **kwargs) -> requests.Response:
        """POST JSON data."""
        kwargs['json'] = json_data
        self.session.headers.update({'Content-Type': 'application/json'})
        resp = self.post(url, **kwargs)
        self.session.headers.pop('Content-Type', None)
        return resp

    def close(self) -> None:
        self.session.close()


# ---------------------------------------------------------------------------
# Data sync log tracking
# ---------------------------------------------------------------------------

def create_sync_log(source: str, sync_type: str = 'association_scrape', conn=None) -> str:
    """Create a data_sync_log entry and return its id."""
    row = fetch_one(
        """INSERT INTO data_sync_log (source, sync_type, started_at, status)
           VALUES (%s, %s, NOW(), 'running')
           RETURNING id""",
        (source, sync_type),
        conn=conn,
    )
    log_id = str(row['id'])
    logger.info(f"Sync log created: {log_id} (source={source})")
    return log_id


def complete_sync_log(
    log_id: str,
    stats: Dict[str, int],
    status: str = 'completed',
    error_details: Optional[str] = None,
    conn=None,
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
            stats.get('processed', 0),
            stats.get('created', 0),
            stats.get('updated', 0),
            stats.get('errored', 0),
            status,
            error_details,
            log_id,
        ),
        conn=conn,
    )
    logger.info(f"Sync log {log_id}: status={status} stats={stats}")


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def extract_email(text: str) -> Optional[str]:
    """Extract the first email address from text."""
    if not text:
        return None
    match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return match.group(0).lower() if match else None


def extract_phone(text: str) -> Optional[str]:
    """Extract a US phone number. Returns 10-digit string or None."""
    if not text:
        return None
    match = re.search(r'[\(]?(\d{3})[\)\s.\-]*(\d{3})[\s.\-]*(\d{4})', text)
    if match:
        return match.group(1) + match.group(2) + match.group(3)
    return None


def clean_text(text: str) -> str:
    """Collapse whitespace, strip leading/trailing space."""
    if not text:
        return ''
    return re.sub(r'\s+', ' ', text).strip()


def parse_enrollment(text: str) -> Optional[int]:
    """Parse enrollment number from text like '450 students' or '1,200'."""
    if not text:
        return None
    cleaned = text.replace(',', '').strip()
    match = re.search(r'(\d+)', cleaned)
    if match:
        val = int(match.group(1))
        if 1 <= val <= 50000:  # sanity check
            return val
    return None


def parse_grades(text: str) -> Tuple[str, str]:
    """Parse grade range from text like 'PK-12', 'K-8', 'Grades 9-12'."""
    if not text:
        return ('', '')
    text = text.upper().strip()
    text = re.sub(r'GRADES?\s*', '', text)

    match = re.search(r'(PK|PRE-?K|TK|K|\d{1,2})\s*[-\u2013]\s*(PK|K|\d{1,2})', text)
    if match:
        low = match.group(1).replace('PRE-K', 'PK').replace('PREK', 'PK')
        high = match.group(2)
        return (low, high)

    # Single grade
    match = re.search(r'(PK|PRE-?K|TK|K|\d{1,2})', text)
    if match:
        g = match.group(1).replace('PRE-K', 'PK').replace('PREK', 'PK')
        return (g, g)

    return ('', '')
