"""
News & Transition Monitor

Monitors Google News RSS feeds for leadership transitions at independent schools.
Detects head of school departures, appointments, retirements, and other signals
that represent business opportunities.

Monitored topics:
  - "[school name] head of school"
  - "head of school appointed" OR "head of school named"
  - "head of school retiring" OR "head of school departure"
  - "independent school leadership"

Creates industry_signals records for detected transitions and flags
schools where the current HOS may be departing (opportunity detection).
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

import feedparser
from dateutil import parser as dateparser

from ..db import (
    fetch_all, fetch_one, execute,
    create_sync_log, complete_sync_log, record_provenance,
)
from ..utils import (
    RateLimitedSession, normalize_name, fuzzy_org_match,
    org_similarity, name_similarity, parse_name_parts,
)

logger = logging.getLogger('knock.enrichment.news_monitor')

# Google News RSS base URL
GOOGLE_NEWS_RSS = 'https://news.google.com/rss/search'

# Search queries for leadership transitions
TRANSITION_QUERIES = [
    '"head of school" appointed',
    '"head of school" named',
    '"head of school" retiring',
    '"head of school" departure',
    '"head of school" hired',
    '"head of school" selected',
    '"headmaster" appointed OR named OR retiring',
    '"independent school" "new head"',
    '"independent school" leadership transition',
    'private school "head of school" announcement',
]

# Queries specific to school names (generated dynamically)
SCHOOL_QUERY_TEMPLATE = '"{school_name}" "head of school"'

# Signal type classification keywords
SIGNAL_KEYWORDS = {
    'head_departure': [
        'retiring', 'departure', 'departing', 'leaving', 'stepping down',
        'resign', 'resigned', 'resignation', 'last day', 'farewell',
    ],
    'head_appointment': [
        'appointed', 'named', 'hired', 'selected', 'chosen', 'announced as',
        'new head', 'incoming', 'will lead', 'joins', 'tapped to lead',
    ],
    'leadership_search_announced': [
        'search committee', 'head search', 'leadership search',
        'seeking', 'search firm', 'open position',
    ],
    'school_expansion': [
        'expansion', 'new campus', 'capital campaign', 'building',
        'renovation', 'growth',
    ],
    'school_closing': [
        'closing', 'closure', 'shutting down', 'merging', 'merger',
    ],
}


class NewsMonitor:
    """Monitors news for school leadership transitions and industry signals."""

    def __init__(self, max_entries: int = 200):
        self.max_entries = max_entries
        self.http = RateLimitedSession(
            min_delay=2.0,
            user_agent='Knock News Monitor (askknock.com)',
        )
        self.stats = {
            'records_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'records_errored': 0,
        }
        # Cache of processed article URLs to avoid duplicates
        self._processed_urls: set = set()

    def run(self, school_ids: Optional[List[str]] = None, **kwargs) -> Dict[str, int]:
        """
        Run the news monitoring enrichment.

        Args:
            school_ids: Optional list of specific school IDs to monitor.
                        If None, monitors all active schools + general queries.
        """
        sync_log_id = create_sync_log('news_monitor', 'incremental')
        logger.info("Starting news & transition monitoring")

        try:
            # Load already-processed URLs to skip duplicates
            self._load_processed_urls()

            # Phase 1: General transition queries
            logger.info("Phase 1: Scanning general transition queries")
            for query in TRANSITION_QUERIES:
                try:
                    entries = self._fetch_news_feed(query)
                    for entry in entries:
                        self._process_news_entry(entry)
                except Exception as e:
                    self.stats['records_errored'] += 1
                    logger.error(f"Error processing query '{query}': {e}")

            # Phase 2: School-specific queries for high-priority schools
            logger.info("Phase 2: Scanning school-specific queries")
            schools = self._get_priority_schools(school_ids)
            for school in schools:
                try:
                    query = SCHOOL_QUERY_TEMPLATE.format(school_name=school['name'])
                    entries = self._fetch_news_feed(query)
                    for entry in entries:
                        self._process_news_entry(entry, school_context=school)
                except Exception as e:
                    self.stats['records_errored'] += 1
                    logger.error(f"Error monitoring {school['name']}: {e}")

            status = 'partial' if self.stats['records_errored'] > 0 else 'completed'
            complete_sync_log(sync_log_id, self.stats, status)
            logger.info(f"News monitoring complete: {self.stats}")

        except Exception as e:
            complete_sync_log(sync_log_id, self.stats, 'failed', str(e))
            logger.error(f"News monitoring failed: {e}", exc_info=True)
            raise

        finally:
            self.http.close()

        return self.stats

    def _load_processed_urls(self) -> None:
        """Load URLs of articles we've already processed to avoid duplicates."""
        rows = fetch_all(
            """SELECT source_url FROM industry_signals
               WHERE source_name = 'google_news'
                 AND created_at > NOW() - INTERVAL '90 days'""",
        )
        self._processed_urls = {row['source_url'] for row in rows if row.get('source_url')}
        logger.debug(f"Loaded {len(self._processed_urls)} previously processed URLs")

    def _get_priority_schools(self, school_ids: Optional[List[str]] = None) -> List[Dict]:
        """Get schools to monitor individually."""
        if school_ids:
            return fetch_all(
                """SELECT id, name, city, state FROM schools
                   WHERE id = ANY(%s) AND is_active = true""",
                (school_ids,),
            )

        # Monitor platinum/gold tier schools and those with expected transitions
        return fetch_all(
            """SELECT id, name, city, state FROM schools
               WHERE is_active = true
                 AND (tier IN ('platinum', 'gold')
                      OR next_head_change_expected IS NOT NULL)
               ORDER BY tier ASC NULLS LAST
               LIMIT 100""",
        )

    def _fetch_news_feed(self, query: str) -> List[Dict]:
        """Fetch and parse a Google News RSS feed for a query."""
        url = f"{GOOGLE_NEWS_RSS}?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"

        try:
            resp = self.http.get(url, headers={'Accept': 'application/rss+xml, application/xml, text/xml'})
            feed = feedparser.parse(resp.text)
        except Exception as e:
            logger.warning(f"Failed to fetch news for query '{query}': {e}")
            return []

        entries = []
        for entry in feed.entries[:self.max_entries]:
            entries.append({
                'title': entry.get('title', ''),
                'link': entry.get('link', ''),
                'published': entry.get('published', ''),
                'summary': entry.get('summary', ''),
                'source': entry.get('source', {}).get('title', ''),
            })

        return entries

    def _process_news_entry(self, entry: Dict, school_context: Optional[Dict] = None) -> None:
        """Process a single news entry, extracting signals."""
        url = entry.get('link', '')
        title = entry.get('title', '')

        if not title or not url:
            return

        # Skip already-processed articles
        if url in self._processed_urls:
            return
        self._processed_urls.add(url)

        self.stats['records_processed'] += 1

        # Classify the signal type
        signal_type = self._classify_signal(title, entry.get('summary', ''))
        if not signal_type:
            return  # Not a relevant signal

        # Try to identify the school
        school = school_context
        if not school:
            school = self._identify_school_from_text(title + ' ' + entry.get('summary', ''))

        # Try to identify the person mentioned
        person_name = self._extract_person_name(title, entry.get('summary', ''))
        person_id = None
        if person_name and school:
            person = self._find_or_create_person(person_name, school, signal_type)
            if person:
                person_id = person.get('id')

        # Parse publication date
        signal_date = None
        if entry.get('published'):
            try:
                signal_date = dateparser.parse(entry['published']).date()
            except Exception:
                signal_date = datetime.now().date()
        else:
            signal_date = datetime.now().date()

        # Check for duplicate signals (same school + type within 7 days)
        existing = fetch_one(
            """SELECT id FROM industry_signals
               WHERE school_id = %s AND signal_type = %s
                 AND signal_date > %s - INTERVAL '7 days'
                 AND source_url = %s""",
            (school['id'] if school else None, signal_type,
             signal_date, url),
        )
        if existing:
            return

        # Create the industry signal
        execute(
            """INSERT INTO industry_signals
                   (signal_type, school_id, person_id, headline, description,
                    source_url, source_name, signal_date, confidence, impact)
               VALUES (%s, %s, %s, %s, %s, %s, 'google_news', %s, %s, %s)""",
            (
                signal_type,
                school['id'] if school else None,
                person_id,
                title[:500],
                entry.get('summary', '')[:2000] or None,
                url,
                signal_date,
                'likely' if school else 'rumor',
                self._assess_impact(signal_type),
            ),
        )
        self.stats['records_created'] += 1
        logger.info(f"New signal [{signal_type}]: {title[:80]}")

        # Flag opportunity: if a departure is detected at a school we track
        if signal_type in ('head_departure', 'leadership_search_announced') and school:
            execute(
                """UPDATE schools
                   SET next_head_change_expected = COALESCE(
                       next_head_change_expected,
                       %s::date + INTERVAL '6 months'
                   ),
                   updated_at = NOW()
                   WHERE id = %s""",
                (signal_date, school['id']),
            )
            logger.info(f"Flagged opportunity: {school['name']} may have upcoming HOS transition")

    def _classify_signal(self, title: str, summary: str) -> Optional[str]:
        """Classify the signal type based on article text."""
        text = (title + ' ' + summary).lower()

        # Score each signal type
        best_type = None
        best_score = 0

        for signal_type, keywords in SIGNAL_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score = score
                best_type = signal_type

        return best_type if best_score > 0 else None

    def _identify_school_from_text(self, text: str) -> Optional[Dict]:
        """Try to identify a school mentioned in article text."""
        if not text:
            return None

        # Extract potential school names (look for patterns)
        # Common patterns: "at XYZ School", "XYZ Academy", etc.
        school_patterns = [
            r'(?:at|of|from|for|joins?)\s+([A-Z][A-Za-z\s\'-]+(?:School|Academy|Institute|Prep|Preparatory|Day School|Country Day))',
            r'([A-Z][A-Za-z\s\'-]+(?:School|Academy|Institute|Prep|Preparatory))\s+(?:announced|named|appointed|selected)',
        ]

        candidates = []
        for pattern in school_patterns:
            matches = re.findall(pattern, text)
            candidates.extend(matches)

        if not candidates:
            return None

        # Try to match against our database
        for candidate_name in candidates:
            candidate_name = candidate_name.strip()
            if len(candidate_name) < 5:
                continue

            results = fetch_all(
                """SELECT id, name, city, state
                   FROM schools
                   WHERE name_normalized %% %s
                   ORDER BY similarity(name_normalized, %s) DESC
                   LIMIT 3""",
                (normalize_name(candidate_name), normalize_name(candidate_name)),
            )

            for result in results:
                if org_similarity(candidate_name, result['name']) >= 70:
                    return result

        return None

    def _extract_person_name(self, title: str, summary: str) -> Optional[str]:
        """Try to extract a person's name from the article title/summary."""
        text = title + ' ' + summary

        # Patterns: "John Smith appointed...", "...named John Smith as..."
        name_patterns = [
            r'([A-Z][a-z]+\s+(?:[A-Z]\.?\s+)?[A-Z][a-z]+)\s+(?:appointed|named|selected|hired|chosen|tapped)',
            r'(?:appointed|named|selected|hired|chosen)\s+([A-Z][a-z]+\s+(?:[A-Z]\.?\s+)?[A-Z][a-z]+)',
            r'([A-Z][a-z]+\s+(?:[A-Z]\.?\s+)?[A-Z][a-z]+)\s+(?:retiring|departing|leaving|stepping down)',
            r'(?:Dr\.|Rev\.)\s+([A-Z][a-z]+\s+(?:[A-Z]\.?\s+)?[A-Z][a-z]+)',
        ]

        for pattern in name_patterns:
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip()
                # Validate: should be 2-4 words, not common non-name phrases
                words = name.split()
                if 2 <= len(words) <= 4:
                    return name

        return None

    def _find_or_create_person(
        self,
        name: str,
        school: Dict,
        signal_type: str,
    ) -> Optional[Dict]:
        """Find or create a person record from a news mention."""
        # Try to find existing
        candidates = fetch_all(
            """SELECT id, full_name, current_school_id
               FROM people
               WHERE current_school_id = %s OR name_normalized %% %s
               LIMIT 20""",
            (school['id'], normalize_name(name)),
        )

        for c in candidates:
            score = name_similarity(name, c['full_name'])
            if str(c.get('current_school_id', '')) == str(school['id']):
                score = min(score + 15, 100)
            if score >= 80:
                return c

        # For appointments, create new person records
        if signal_type == 'head_appointment':
            parts = parse_name_parts(name)
            row = fetch_one(
                """INSERT INTO people
                       (full_name, first_name, last_name, name_normalized,
                        current_title, current_organization, current_school_id,
                        primary_role, data_source, candidate_status)
                   VALUES (%s, %s, %s, %s, 'Head of School', %s, %s,
                           'head_of_school', 'news_monitor', 'passive')
                   RETURNING id, full_name, current_school_id""",
                (name, parts['first_name'], parts['last_name'],
                 normalize_name(name), school['name'], school['id']),
            )
            if row:
                logger.info(f"Created person from news: {name} at {school['name']}")
                record_provenance('person', str(row['id']), 'full_name', name,
                                'news_monitor', confidence=0.7)
                return dict(row)

        return None

    @staticmethod
    def _assess_impact(signal_type: str) -> str:
        """Assess the business impact level of a signal."""
        high_impact = {'head_departure', 'leadership_search_announced', 'head_appointment'}
        medium_impact = {'school_expansion', 'school_closing'}
        if signal_type in high_impact:
            return 'high'
        if signal_type in medium_impact:
            return 'medium'
        return 'low'


def run(max_entries: int = 200, school_ids: Optional[List[str]] = None, **kwargs) -> Dict[str, int]:
    """Entry point for the enrichment runner."""
    monitor = NewsMonitor(max_entries=max_entries)
    return monitor.run(school_ids=school_ids)
