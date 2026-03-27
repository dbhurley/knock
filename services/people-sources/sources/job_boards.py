"""
Job Board Monitor

Monitors education job boards for open positions which reveal:
- Schools searching for leadership (business intelligence)
- Which search firms are engaged (competitive intel)
- Candidate profiles when visible

Sources:
- NAIS Career Center (careers.nais.org)
- Carney Sandoe job listings
- EdSurge Jobs

When a school posts for a head of school -> create industry_signal record.
Track which schools are searching and with which firms.
"""

import logging
import re
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import JOB_BOARD_SOURCES
from utils import (
    RateLimitedSession,
    find_school_by_name,
    clean_text,
    create_sync_log,
    complete_sync_log,
    execute,
    fetch_one,
    fetch_all,
    safe_date,
)

logger = logging.getLogger('knock.people_sources.job_boards')

# ---------------------------------------------------------------------------
# Job posting extraction
# ---------------------------------------------------------------------------

# Keywords indicating head of school / leadership positions
LEADERSHIP_KEYWORDS = [
    'head of school', 'headmaster', 'headmistress',
    'president', 'superintendent', 'chief executive',
    'division head', 'upper school director', 'lower school director',
    'middle school director', 'academic dean', 'dean of faculty',
    'chief financial officer', 'cfo', 'chief operating officer',
    'director of admission', 'director of advancement',
    'director of development', 'assistant head',
]

# Search firm names for competitive intelligence
SEARCH_FIRMS = [
    'carney sandoe', 'carney, sandoe',
    'resource group 175', 'rg175',
    'wickenden associates',
    'storbeck search',
    'educators collaborative',
    'deerfield associates',
    'isaacson miller',
    'heidrick & struggles', 'heidrick and struggles',
    'korn ferry',
    'spencer stuart',
    'caldwell partners',
    'promise54',
    'strategic leadership partners',
    'southern teachers agency',
    'john fairclough',
    'ed leadership search',
]


def _is_leadership_position(title: str) -> bool:
    """Check if a job title indicates a leadership position."""
    lower = title.lower()
    return any(kw in lower for kw in LEADERSHIP_KEYWORDS)


def _detect_search_firm(text: str) -> Optional[str]:
    """Detect if a search firm is mentioned in the posting text."""
    lower = text.lower()
    for firm in SEARCH_FIRMS:
        if firm in lower:
            return firm.title()
    return None


def _determine_signal_type(title: str) -> str:
    """Determine the industry signal type based on job title."""
    lower = title.lower()
    if any(kw in lower for kw in ['head of school', 'headmaster', 'headmistress', 'president', 'superintendent']):
        return 'leadership_search_announced'
    return 'leadership_search_announced'


# ---------------------------------------------------------------------------
# Scraper for generic job board pages
# ---------------------------------------------------------------------------

def _scrape_job_listings(
    session: RateLimitedSession,
    url: str,
    source_key: str,
) -> List[Dict[str, Any]]:
    """Scrape job listings from a search results page."""
    listings = []

    soup = session.get_soup(url)
    if not soup:
        logger.warning(f"[{source_key}] Could not fetch {url}")
        return listings

    # Try various job card selectors
    cards = []
    for selector in [
        '.job-listing', '.job-card', '.job-item', '.job-result',
        '.search-result', '.listing-item', 'div[class*="job"]',
        '.views-row', 'article', '.posting', 'li.result',
        'tr.job-row', '.opportunity',
    ]:
        found = soup.select(selector)
        if len(found) >= 1:
            cards = found
            logger.info(f"[{source_key}] Found {len(found)} job cards with '{selector}'")
            break

    if not cards:
        # Fallback: look for any links with leadership keywords
        for link in soup.find_all('a', href=True):
            text = clean_text(link.get_text())
            if text and _is_leadership_position(text):
                href = urljoin(url, link.get('href', ''))
                listings.append({
                    'title': text,
                    'url': href,
                    'school_name': None,
                    'location': None,
                    'posted_date': None,
                    'description': None,
                    'search_firm': None,
                })
        return listings

    for card in cards:
        listing = _parse_job_card(card, url)
        if listing:
            listings.append(listing)

    return listings


def _parse_job_card(card, base_url: str) -> Optional[Dict[str, Any]]:
    """Parse a job card element."""
    # Title
    title = None
    job_url = None
    for tag in card.find_all(['h2', 'h3', 'h4', 'a', 'strong']):
        text = clean_text(tag.get_text())
        if text and len(text) > 5 and len(text) < 300:
            title = text
            if tag.name == 'a':
                job_url = urljoin(base_url, tag.get('href', ''))
            elif tag.find('a'):
                job_url = urljoin(base_url, tag.find('a').get('href', ''))
            break

    if not title:
        return None

    # School/organization name
    school_name = None
    for tag in card.find_all(['span', 'p', 'div', 'a']):
        cls = ' '.join(tag.get('class', []))
        text = clean_text(tag.get_text())
        if any(kw in cls.lower() for kw in ['org', 'company', 'school', 'employer', 'institution']):
            school_name = text
            break

    # If title contains school name pattern "Title - School Name" or "Title at School"
    if not school_name:
        match = re.search(r'(?:[-\|@]|at)\s+(.+?)$', title)
        if match:
            candidate = clean_text(match.group(1))
            if any(kw in candidate.lower() for kw in ['school', 'academy', 'prep', 'institute']):
                school_name = candidate

    # Location
    location = None
    for tag in card.find_all(['span', 'p', 'div']):
        cls = ' '.join(tag.get('class', []))
        text = clean_text(tag.get_text())
        if 'location' in cls.lower() or re.search(r',\s*[A-Z]{2}\b', text):
            if len(text) < 100:
                location = text
                break

    # Date
    posted_date = None
    for tag in card.find_all(['time', 'span', 'p']):
        if tag.name == 'time':
            posted_date = safe_date(tag.get('datetime', tag.get_text()))
            break
        cls = ' '.join(tag.get('class', []))
        if 'date' in cls.lower() or 'posted' in cls.lower():
            posted_date = safe_date(clean_text(tag.get_text()))
            break

    # Description snippet
    description = None
    for tag in card.find_all(['p', 'div']):
        cls = ' '.join(tag.get('class', []))
        if 'description' in cls.lower() or 'summary' in cls.lower() or 'snippet' in cls.lower():
            description = clean_text(tag.get_text())[:500]
            break

    # Detect search firm
    full_text = clean_text(card.get_text())
    search_firm = _detect_search_firm(full_text)

    return {
        'title': title,
        'url': job_url or base_url,
        'school_name': school_name,
        'location': location,
        'posted_date': posted_date,
        'description': description,
        'search_firm': search_firm,
    }


# ---------------------------------------------------------------------------
# Database import
# ---------------------------------------------------------------------------

def import_job_listings(source_key: str) -> Dict[str, int]:
    """Scrape and import job listings from a single source."""
    stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    if source_key not in JOB_BOARD_SOURCES:
        logger.error(f"Unknown job board source: {source_key}")
        return stats

    source = JOB_BOARD_SOURCES[source_key]
    session = RateLimitedSession(min_delay=source.get('rate_limit', 3.0))

    all_listings = []
    for url in source.get('search_urls', []):
        try:
            listings = _scrape_job_listings(session, url, source_key)
            all_listings.extend(listings)
        except Exception as e:
            logger.error(f"[{source_key}] Error scraping {url}: {e}")

    session.close()

    if not all_listings:
        logger.info(f"[{source_key}] No listings found")
        return stats

    # Filter for leadership positions
    leadership_listings = [l for l in all_listings if _is_leadership_position(l['title'])]
    logger.info(f"[{source_key}] Found {len(all_listings)} total listings, {len(leadership_listings)} leadership positions")

    for listing in leadership_listings:
        stats['records_processed'] += 1
        try:
            # Find matching school
            school_id = None
            if listing.get('school_name'):
                school = find_school_by_name(listing['school_name'])
                if school:
                    school_id = str(school['id'])

            # Check for existing signal
            existing = fetch_one(
                """SELECT id FROM industry_signals
                   WHERE signal_type = 'leadership_search_announced'
                   AND headline = %s
                   LIMIT 1""",
                (listing['title'],),
            )

            if existing:
                stats['records_updated'] += 1
                continue

            # Create industry signal
            description_parts = []
            if listing.get('school_name'):
                description_parts.append(f"School: {listing['school_name']}")
            if listing.get('location'):
                description_parts.append(f"Location: {listing['location']}")
            if listing.get('search_firm'):
                description_parts.append(f"Search firm: {listing['search_firm']}")
            if listing.get('description'):
                description_parts.append(listing['description'][:300])

            execute(
                """INSERT INTO industry_signals
                       (signal_type, school_id, headline, description,
                        source_url, source_name, signal_date, confidence, impact)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'confirmed', 'high')""",
                (
                    _determine_signal_type(listing['title']),
                    school_id,
                    listing['title'],
                    '\n'.join(description_parts) if description_parts else None,
                    listing.get('url'),
                    source['name'],
                    listing.get('posted_date') or date.today().isoformat(),
                ),
            )
            stats['records_created'] += 1

        except Exception as e:
            stats['records_errored'] += 1
            logger.error(f"[{source_key}] Error processing listing '{listing.get('title', '?')}': {e}")

    return stats


def monitor_all_job_boards() -> Dict[str, int]:
    """Monitor all configured job boards."""
    log_id = create_sync_log('job_boards', 'incremental')
    total_stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    for source_key in JOB_BOARD_SOURCES:
        try:
            stats = import_job_listings(source_key)
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception as e:
            logger.error(f"Failed to monitor job board {source_key}: {e}")
            total_stats['records_errored'] += 1

    status = 'completed' if total_stats['records_errored'] == 0 else 'partial'
    complete_sync_log(log_id, total_stats, status=status)

    logger.info(f"All job boards completed: {total_stats}")
    return total_stats


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in JOB_BOARD_SOURCES:
        stats = import_job_listings(sys.argv[1])
        print(f"Results: {stats}")
    else:
        monitor_all_job_boards()
