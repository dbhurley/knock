"""
State / Regional Association Directory Scrapers

Scrapes member school directories from independent school associations to extract
school names and listed leadership (head of school at minimum).

Uses a registry pattern so new associations can be added via config.py.
"""

import logging
import re
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ASSOCIATION_REGISTRY
from utils import (
    RateLimitedSession,
    upsert_person,
    find_school_by_name,
    clean_text,
    create_sync_log,
    complete_sync_log,
    record_provenance,
    logger as root_logger,
)

logger = logging.getLogger('knock.people_sources.state_associations')

# ---------------------------------------------------------------------------
# Generic extraction helpers
# ---------------------------------------------------------------------------

# Patterns that commonly indicate a head of school name on directory pages
HEAD_TITLE_PATTERNS = [
    re.compile(r'head\s+of\s+school', re.I),
    re.compile(r'head\s*:', re.I),
    re.compile(r'director', re.I),
    re.compile(r'principal', re.I),
    re.compile(r'president', re.I),
    re.compile(r'headmaster', re.I),
    re.compile(r'headmistress', re.I),
    re.compile(r'superintendent', re.I),
]

# Patterns to identify school name vs. head name in text blocks
SCHOOL_SUFFIXES = [
    'school', 'academy', 'institute', 'college', 'preparatory', 'prep',
    'day school', 'country day', 'montessori', 'waldorf', 'friends',
]


def _looks_like_school_name(text: str) -> bool:
    lower = text.lower().strip()
    return any(s in lower for s in SCHOOL_SUFFIXES)


def _looks_like_person_name(text: str) -> bool:
    """Basic heuristic: 2-4 words, starts with uppercase, no school keywords."""
    text = text.strip()
    if not text or len(text) < 3:
        return False
    words = text.split()
    if len(words) < 2 or len(words) > 6:
        return False
    if _looks_like_school_name(text):
        return False
    # Should start with uppercase
    if not text[0].isupper():
        return False
    return True


def _extract_head_from_text(text: str) -> Optional[str]:
    """Try to extract head of school name from a text block."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    for i, line in enumerate(lines):
        for pat in HEAD_TITLE_PATTERNS:
            if pat.search(line):
                # The name might be on the same line or the next
                # Try "Head of School: Dr. Jane Smith" format
                colon_match = re.search(r':\s*(.+)', line)
                if colon_match:
                    candidate = colon_match.group(1).strip()
                    if _looks_like_person_name(candidate):
                        return candidate
                # Try next line
                if i + 1 < len(lines):
                    candidate = lines[i + 1]
                    if _looks_like_person_name(candidate):
                        return candidate
    return None


# ---------------------------------------------------------------------------
# Generic directory page scraper
# ---------------------------------------------------------------------------

def scrape_member_list_page(
    session: RateLimitedSession,
    url: str,
    assoc_code: str,
) -> List[Dict[str, str]]:
    """
    Generic scraper for association member directory pages.
    Returns list of dicts: {school_name, head_name, head_title, url, location}
    """
    results = []
    soup = session.get_soup(url)
    if not soup:
        logger.warning(f"[{assoc_code}] Could not fetch directory page: {url}")
        return results

    # Strategy 1: Look for structured card/list items
    # Many association sites use cards, list items, or table rows
    for selector in [
        'div.school-card', 'div.member-card', 'div.school-listing',
        'div.school-item', 'div.directory-item', 'li.school-item',
        'article.school', 'div.views-row', 'div.member-listing',
        'tr.school-row', 'div[class*="school"]', 'div[class*="member"]',
        'div[class*="directory"]', '.card', '.listing-item',
    ]:
        cards = soup.select(selector)
        if len(cards) >= 3:  # Likely found the right pattern
            logger.info(f"[{assoc_code}] Found {len(cards)} items with selector '{selector}'")
            for card in cards:
                result = _parse_school_card(card, url)
                if result and result.get('school_name'):
                    results.append(result)
            if results:
                return results

    # Strategy 2: Look for heading + paragraph patterns
    headings = soup.find_all(['h2', 'h3', 'h4', 'h5'])
    for h in headings:
        school_name = clean_text(h.get_text())
        if _looks_like_school_name(school_name):
            # Look for head name in sibling elements
            head_name = None
            sibling = h.find_next_sibling()
            if sibling:
                text = clean_text(sibling.get_text())
                head_name = _extract_head_from_text(text)
                if not head_name and _looks_like_person_name(text):
                    head_name = text

            result = {
                'school_name': school_name,
                'head_name': head_name,
                'head_title': 'Head of School' if head_name else None,
                'url': url,
                'location': None,
            }
            if school_name:
                results.append(result)

    # Strategy 3: Look for links that go to school detail pages
    if not results:
        links = soup.find_all('a', href=True)
        school_links = []
        for link in links:
            text = clean_text(link.get_text())
            href = link.get('href', '')
            if _looks_like_school_name(text) and len(text) > 5:
                full_url = urljoin(url, href)
                school_links.append((text, full_url))

        if school_links:
            logger.info(f"[{assoc_code}] Found {len(school_links)} school links to follow")
            for school_name, school_url in school_links[:100]:  # Cap at 100
                head_name = _scrape_school_detail_for_head(session, school_url, assoc_code)
                results.append({
                    'school_name': school_name,
                    'head_name': head_name,
                    'head_title': 'Head of School' if head_name else None,
                    'url': school_url,
                    'location': None,
                })

    logger.info(f"[{assoc_code}] Extracted {len(results)} schools from {url}")
    return results


def _parse_school_card(card: Tag, base_url: str) -> Optional[Dict[str, str]]:
    """Parse a school card element for school name, head, location."""
    # Try to find school name (usually in a heading or strong tag)
    school_name = None
    for tag in card.find_all(['h2', 'h3', 'h4', 'h5', 'strong', 'a']):
        text = clean_text(tag.get_text())
        if _looks_like_school_name(text) or (len(text) > 5 and not _looks_like_person_name(text)):
            school_name = text
            break

    if not school_name:
        # Use first link text as school name
        link = card.find('a')
        if link:
            school_name = clean_text(link.get_text())

    if not school_name:
        return None

    # Look for head of school
    head_name = None
    card_text = card.get_text()
    head_name = _extract_head_from_text(card_text)

    # Look for location
    location = None
    for tag in card.find_all(['span', 'p', 'div']):
        text = clean_text(tag.get_text())
        # Look for city, STATE pattern
        if re.search(r',\s*[A-Z]{2}\b', text) and len(text) < 100:
            location = text
            break

    return {
        'school_name': school_name,
        'head_name': head_name,
        'head_title': 'Head of School' if head_name else None,
        'url': base_url,
        'location': location,
    }


def _scrape_school_detail_for_head(
    session: RateLimitedSession,
    url: str,
    assoc_code: str,
) -> Optional[str]:
    """Visit a school detail page and try to extract head of school name."""
    soup = session.get_soup(url)
    if not soup:
        return None

    text = soup.get_text()
    return _extract_head_from_text(text)


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape_association(
    assoc_code: str,
    session: Optional[RateLimitedSession] = None,
) -> Dict[str, int]:
    """
    Scrape a single association's member directory.
    Returns stats dict.
    """
    if assoc_code not in ASSOCIATION_REGISTRY:
        logger.error(f"Unknown association code: {assoc_code}")
        return {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    assoc = ASSOCIATION_REGISTRY[assoc_code]
    stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    own_session = session is None
    if own_session:
        session = RateLimitedSession(min_delay=assoc.get('rate_limit', 3.0))

    logger.info(f"[{assoc_code}] Starting scrape of {assoc['name']}")

    all_schools = []
    for dir_url in assoc['directory_urls']:
        try:
            schools = scrape_member_list_page(session, dir_url, assoc_code)
            all_schools.extend(schools)
            if schools:
                break  # Found working URL, stop trying alternates
        except Exception as e:
            logger.error(f"[{assoc_code}] Error scraping {dir_url}: {e}")
            continue

    logger.info(f"[{assoc_code}] Found {len(all_schools)} schools total")

    for school_data in all_schools:
        stats['records_processed'] += 1
        try:
            school_name = school_data['school_name']
            head_name = school_data.get('head_name')

            if not head_name:
                continue  # No leadership data to import

            # Try to match to existing school
            school_record = find_school_by_name(school_name)
            school_id = str(school_record['id']) if school_record else None

            # Upsert person
            tags = [
                f'assoc:{assoc_code}',
                'school_leader',
            ]
            person_id, created = upsert_person(
                full_name=head_name,
                data_source=f'association_{assoc_code}',
                title=school_data.get('head_title', 'Head of School'),
                organization=school_name,
                school_id=school_id,
                tags=tags,
            )

            if created:
                stats['records_created'] += 1
            else:
                stats['records_updated'] += 1

            # Record provenance
            record_provenance(
                entity_type='person',
                entity_id=person_id,
                field_name='current_organization',
                field_value=school_name,
                source=f'association_{assoc_code}',
                source_url=school_data.get('url'),
                confidence=0.85,
            )

        except Exception as e:
            stats['records_errored'] += 1
            logger.error(f"[{assoc_code}] Error processing {school_data.get('school_name', '?')}: {e}")

    if own_session:
        session.close()

    logger.info(f"[{assoc_code}] Completed: {stats}")
    return stats


def scrape_all_associations() -> Dict[str, int]:
    """Scrape all configured associations. Returns combined stats."""
    log_id = create_sync_log('state_associations', 'full')
    total_stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    session = RateLimitedSession(min_delay=3.0)

    for assoc_code in ASSOCIATION_REGISTRY:
        try:
            stats = scrape_association(assoc_code, session)
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception as e:
            logger.error(f"Failed to scrape association {assoc_code}: {e}")
            total_stats['records_errored'] += 1

    session.close()

    status = 'completed' if total_stats['records_errored'] == 0 else 'partial'
    complete_sync_log(log_id, total_stats, status=status)

    logger.info(f"All associations completed: {total_stats}")
    return total_stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )

    import sys
    if len(sys.argv) > 1:
        code = sys.argv[1]
        if code == 'all':
            scrape_all_associations()
        elif code in ASSOCIATION_REGISTRY:
            stats = scrape_association(code)
            print(f"Results: {stats}")
        else:
            print(f"Unknown association: {code}")
            print(f"Available: {', '.join(ASSOCIATION_REGISTRY.keys())}, all")
    else:
        print("Usage: python state_associations.py <assoc_code|all>")
        print(f"Available: {', '.join(ASSOCIATION_REGISTRY.keys())}, all")
