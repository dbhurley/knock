"""
Shared utilities for the Knock enrichment service:
  - Name normalization and fuzzy matching
  - Rate limiting
  - HTTP helpers
"""

import re
import time
import logging
import unicodedata
from typing import Optional, List, Dict, Any

import requests
from thefuzz import fuzz

logger = logging.getLogger('knock.enrichment.utils')

# ---------------------------------------------------------------------------
# Name normalization  (mirrors data-sync/src/utils/normalize.ts)
# ---------------------------------------------------------------------------

# Common prefixes/suffixes to strip for matching
PREFIXES = {'dr', 'mr', 'mrs', 'ms', 'rev', 'fr', 'sr', 'prof', 'hon'}
SUFFIXES = {
    'jr', 'sr', 'ii', 'iii', 'iv', 'v',
    'phd', 'edd', 'md', 'jd', 'esq',
    'cpa', 'mba', 'ma', 'ms', 'bs', 'ba', 'med',
}


def normalize_name(name: Optional[str]) -> str:
    """Normalize a name: lowercase, strip accents, remove punctuation."""
    if not name:
        return ''
    # Decompose accents and strip combining marks
    nfkd = unicodedata.normalize('NFKD', name)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase
    result = stripped.lower()
    # Strip non-alpha chars except spaces
    result = re.sub(r'[^a-z\s]', '', result)
    # Collapse whitespace
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def strip_honorifics(name: str) -> str:
    """Remove common prefixes and suffixes from a name for matching."""
    parts = name.lower().replace('.', '').split()
    parts = [p for p in parts if p not in PREFIXES and p not in SUFFIXES]
    return ' '.join(parts)


def name_similarity(a: str, b: str) -> float:
    """
    Compute similarity between two names (0-100 scale).
    Uses a combination of token_sort_ratio and partial_ratio for robustness.
    """
    na = strip_honorifics(normalize_name(a))
    nb = strip_honorifics(normalize_name(b))
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    # token_sort_ratio handles reordering ("John Smith" vs "Smith, John")
    # partial_ratio handles substring matching ("Robert" vs "Robert J.")
    score_sort = fuzz.token_sort_ratio(na, nb)
    score_partial = fuzz.partial_ratio(na, nb)
    return max(score_sort, score_partial)


def fuzzy_name_match(a: str, b: str, threshold: float = 80.0) -> bool:
    """Check if two names match above a threshold (0-100 scale)."""
    return name_similarity(a, b) >= threshold


def org_similarity(a: str, b: str) -> float:
    """
    Compare two organization names.
    Handles common patterns: "XYZ School" vs "The XYZ School", abbreviations, etc.
    """
    na = normalize_name(a)
    nb = normalize_name(b)
    if not na or not nb:
        return 0.0
    # Strip common prefixes
    for prefix in ['the ', 'a ']:
        na = na.removeprefix(prefix)
        nb = nb.removeprefix(prefix)
    if na == nb:
        return 100.0
    return max(fuzz.token_sort_ratio(na, nb), fuzz.partial_ratio(na, nb))


def fuzzy_org_match(a: str, b: str, threshold: float = 75.0) -> bool:
    """Check if two organization names match above a threshold."""
    return org_similarity(a, b) >= threshold


# ---------------------------------------------------------------------------
# Rate-limited HTTP session
# ---------------------------------------------------------------------------

class RateLimitedSession:
    """
    A requests.Session wrapper that enforces a minimum delay between requests
    and automatically retries on 429 (Too Many Requests).
    """

    def __init__(
        self,
        min_delay: float = 1.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        user_agent: str = 'Knock Data Enrichment (askknock.com)',
    ):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'application/json',
        })
        self.min_delay = min_delay
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._last_request_time = 0.0

    def _wait(self) -> None:
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

    def get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET request with retry on 429."""
        for attempt in range(self.max_retries + 1):
            self._wait()
            self._last_request_time = time.time()
            try:
                resp = self.session.get(url, timeout=30, **kwargs)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error (attempt {attempt+1}): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor ** attempt)
                    continue
                raise

            if resp.status_code == 429:
                wait_time = self.backoff_factor ** (attempt + 2)
                logger.warning(f"Rate limited (429). Waiting {wait_time:.0f}s...")
                time.sleep(wait_time)
                continue

            resp.raise_for_status()
            return resp

        raise requests.exceptions.HTTPError(f"Max retries exceeded for {url}")

    def get_html(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET for HTML content."""
        kwargs.setdefault('headers', {})
        kwargs['headers']['Accept'] = 'text/html,application/xhtml+xml'
        return self.get(url, **kwargs)

    def close(self) -> None:
        """Close the underlying session."""
        self.session.close()


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def extract_email_from_text(text: str) -> Optional[str]:
    """Extract the first email address from a block of text."""
    match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return match.group(0).lower() if match else None


def extract_phone_from_text(text: str) -> Optional[str]:
    """Extract a US phone number from text. Returns 10-digit string or None."""
    # Match patterns like (555) 123-4567, 555-123-4567, 555.123.4567
    match = re.search(r'[\(]?(\d{3})[\)\s.\-]*(\d{3})[\s.\-]*(\d{4})', text)
    if match:
        return match.group(1) + match.group(2) + match.group(3)
    return None


def clean_html_text(text: str) -> str:
    """Clean text extracted from HTML: normalize whitespace, strip artifacts."""
    if not text:
        return ''
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    # Strip leading/trailing
    text = text.strip()
    return text


def parse_name_parts(full_name: str) -> Dict[str, str]:
    """
    Attempt to split a full name into first, last, prefix, suffix.
    Handles "Dr. John Smith Ed.D." and "Smith, John" formats.
    """
    if not full_name:
        return {'first_name': '', 'last_name': '', 'prefix': '', 'suffix': ''}

    name = full_name.strip()
    prefix = ''
    suffix = ''

    # Extract prefix
    parts = name.split()
    if parts and parts[0].lower().rstrip('.') in PREFIXES:
        prefix = parts.pop(0)

    # Extract suffix (from end)
    suffixes_found = []
    while parts:
        candidate = parts[-1].lower().rstrip('.').rstrip(',')
        # Also handle compound like "Ed.D." -> "edd"
        candidate_no_dots = candidate.replace('.', '')
        if candidate in SUFFIXES or candidate_no_dots in SUFFIXES:
            suffixes_found.insert(0, parts.pop())
        else:
            break
    suffix = ' '.join(suffixes_found)

    # Rebuild name from remaining parts
    name = ' '.join(parts)

    # Handle "Last, First" format
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
