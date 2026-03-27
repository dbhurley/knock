"""
NAIS Conference Speaker / Presenter Scraper

Scrapes publicly published speaker bios and session info from:
- NAIS Annual Conference
- NAIS People of Color Conference (PoCC)
- NAIS Institute for New Heads

Extracts names, titles, schools, session topics.
Flags speakers with conference_speaker=TRUE and high career_trajectory_score.
"""

import logging
import re
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import NAIS_CONFERENCE_SOURCES
from utils import (
    RateLimitedSession,
    upsert_person,
    find_school_by_name,
    clean_text,
    create_sync_log,
    complete_sync_log,
    record_provenance,
    execute,
    fetch_one,
    fetch_all,
    safe_date,
)

logger = logging.getLogger('knock.people_sources.nais_conferences')

# ---------------------------------------------------------------------------
# Speaker extraction helpers
# ---------------------------------------------------------------------------

# Pattern: "Name, Title, School" or "Name\nTitle\nSchool"
TITLE_KEYWORDS = [
    'head of school', 'director', 'principal', 'dean', 'president',
    'chief', 'founder', 'teacher', 'coordinator', 'vice president',
    'associate head', 'assistant head', 'division head', 'chair',
    'superintendent', 'cfo', 'coo', 'trustee',
]


def _extract_title_and_org(bio_text: str) -> Dict[str, Optional[str]]:
    """
    From a speaker bio or tagline, extract title and organization.
    Common formats:
    - "Head of School, Phillips Academy"
    - "Director of Diversity, Equity & Inclusion at Sidwell Friends School"
    """
    result = {'title': None, 'organization': None}

    if not bio_text:
        return result

    text = clean_text(bio_text)

    # Try "Title, Organization" pattern
    for kw in TITLE_KEYWORDS:
        pattern = re.compile(
            rf'({re.escape(kw)}[^,]*?),\s*(.+?)(?:\.|$)',
            re.I,
        )
        match = pattern.search(text)
        if match:
            result['title'] = clean_text(match.group(1))
            result['organization'] = clean_text(match.group(2))
            return result

    # Try "Title at Organization" pattern
    for kw in TITLE_KEYWORDS:
        pattern = re.compile(
            rf'({re.escape(kw)}[^,]*?)\s+at\s+(.+?)(?:\.|,|$)',
            re.I,
        )
        match = pattern.search(text)
        if match:
            result['title'] = clean_text(match.group(1))
            result['organization'] = clean_text(match.group(2))
            return result

    return result


def _parse_speaker_card(card, base_url: str) -> Optional[Dict[str, Any]]:
    """Parse a speaker card/element into structured data."""
    # Try to find the name
    name = None
    for tag in card.find_all(['h2', 'h3', 'h4', 'h5', 'strong', '.speaker-name', '.name']):
        candidate = clean_text(tag.get_text())
        if candidate and len(candidate.split()) >= 2 and len(candidate) < 80:
            name = candidate
            break

    if not name:
        # Try first strong or bold element
        strong = card.find('strong') or card.find('b')
        if strong:
            candidate = clean_text(strong.get_text())
            if len(candidate.split()) >= 2 and len(candidate) < 80:
                name = candidate

    if not name:
        return None

    # Get bio/description text
    bio_text = ''
    for tag in card.find_all(['p', 'div', 'span']):
        text = clean_text(tag.get_text())
        if text and text != name and len(text) > 10:
            bio_text = text
            break

    # Extract title and org from bio
    parsed = _extract_title_and_org(bio_text)

    # Look for session/topic info
    session_title = None
    for tag in card.find_all(['em', 'i', '.session-title', '.topic']):
        text = clean_text(tag.get_text())
        if text and len(text) > 5:
            session_title = text
            break

    return {
        'name': name,
        'title': parsed['title'],
        'organization': parsed['organization'],
        'bio_text': bio_text[:500] if bio_text else None,
        'session_title': session_title,
        'url': base_url,
    }


# ---------------------------------------------------------------------------
# Conference scraper
# ---------------------------------------------------------------------------

def scrape_conference_speakers(
    conf_key: str,
    session: Optional[RateLimitedSession] = None,
) -> List[Dict[str, Any]]:
    """Scrape speakers from a single conference source."""
    if conf_key not in NAIS_CONFERENCE_SOURCES:
        logger.error(f"Unknown conference key: {conf_key}")
        return []

    conf = NAIS_CONFERENCE_SOURCES[conf_key]
    own_session = session is None
    if own_session:
        session = RateLimitedSession(min_delay=3.0)

    speakers = []
    logger.info(f"[{conf_key}] Starting scrape of {conf['name']}")

    # Try speaker pages
    for url in conf.get('speaker_urls', []):
        soup = session.get_soup(url)
        if not soup:
            continue

        # Try various speaker card selectors
        cards = []
        for selector in [
            '.speaker-card', '.speaker-item', '.speaker',
            '.presenter-card', '.presenter', '.bio-card',
            '.faculty-member', '.person-card',
            'div[class*="speaker"]', 'div[class*="presenter"]',
            'article', '.views-row',
        ]:
            found = soup.select(selector)
            if len(found) >= 2:
                cards = found
                logger.info(f"[{conf_key}] Found {len(found)} speaker cards with '{selector}' at {url}")
                break

        if not cards:
            # Fallback: look for repeated heading + paragraph patterns
            for heading in soup.find_all(['h3', 'h4']):
                text = clean_text(heading.get_text())
                if text and len(text.split()) >= 2 and len(text) < 80:
                    bio_el = heading.find_next_sibling('p')
                    bio_text = clean_text(bio_el.get_text()) if bio_el else ''
                    parsed = _extract_title_and_org(bio_text)
                    speakers.append({
                        'name': text,
                        'title': parsed['title'],
                        'organization': parsed['organization'],
                        'bio_text': bio_text[:500],
                        'session_title': None,
                        'url': url,
                    })

        for card in cards:
            parsed = _parse_speaker_card(card, url)
            if parsed:
                speakers.append(parsed)

        if speakers:
            break  # Found working URL

    # Also try schedule pages for additional session/speaker data
    for url in conf.get('schedule_urls', []):
        soup = session.get_soup(url)
        if not soup:
            continue

        for selector in [
            '.session', '.schedule-item', '.session-card',
            'div[class*="session"]', '.event-item',
        ]:
            items = soup.select(selector)
            if len(items) >= 2:
                for item in items:
                    # Look for presenter names within session items
                    for tag in item.find_all(['span', 'p', 'div']):
                        cls = ' '.join(tag.get('class', []))
                        if any(kw in cls.lower() for kw in ['speaker', 'presenter', 'faculty']):
                            name = clean_text(tag.get_text())
                            if name and len(name.split()) >= 2 and len(name) < 80:
                                # Get session title
                                session_title = None
                                heading = item.find(['h3', 'h4', 'h5'])
                                if heading:
                                    session_title = clean_text(heading.get_text())

                                speakers.append({
                                    'name': name,
                                    'title': None,
                                    'organization': None,
                                    'bio_text': None,
                                    'session_title': session_title,
                                    'url': url,
                                })
                break

    if own_session:
        session.close()

    # Deduplicate by name
    seen_names = set()
    unique_speakers = []
    for s in speakers:
        normalized = s['name'].lower().strip()
        if normalized not in seen_names:
            seen_names.add(normalized)
            unique_speakers.append(s)

    logger.info(f"[{conf_key}] Found {len(unique_speakers)} unique speakers")
    return unique_speakers


# ---------------------------------------------------------------------------
# Database import
# ---------------------------------------------------------------------------

def _ensure_event_record(conf_key: str) -> str:
    """Find or create an industry_events record for this conference. Returns event_id."""
    conf = NAIS_CONFERENCE_SOURCES[conf_key]
    existing = fetch_one(
        """SELECT id FROM industry_events
           WHERE event_name = %s AND organization = 'NAIS'
           ORDER BY created_at DESC LIMIT 1""",
        (conf['name'],),
    )
    if existing:
        return str(existing['id'])

    row = fetch_one(
        """INSERT INTO industry_events (event_name, organization, event_type, url)
           VALUES (%s, 'NAIS', %s, %s)
           RETURNING id""",
        (conf['name'], conf['event_type'], conf['base_url']),
    )
    return str(row['id'])


def import_conference_speakers(conf_key: str) -> Dict[str, int]:
    """Scrape and import speakers from a conference into the database."""
    stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    speakers = scrape_conference_speakers(conf_key)
    if not speakers:
        logger.info(f"[{conf_key}] No speakers found")
        return stats

    event_id = _ensure_event_record(conf_key)

    for speaker in speakers:
        stats['records_processed'] += 1
        try:
            school_id = None
            if speaker.get('organization'):
                school = find_school_by_name(speaker['organization'])
                if school:
                    school_id = str(school['id'])

            tags = ['conference_speaker', f'nais_{conf_key}', 'high_visibility']
            person_id, created = upsert_person(
                full_name=speaker['name'],
                data_source=f'nais_{conf_key}',
                title=speaker.get('title'),
                organization=speaker.get('organization'),
                school_id=school_id,
                tags=tags,
            )

            if created:
                stats['records_created'] += 1
            else:
                stats['records_updated'] += 1

            # Add as event attendee (speaker role)
            existing_attendee = fetch_one(
                """SELECT id FROM event_attendees
                   WHERE event_id = %s AND person_id = %s""",
                (event_id, person_id),
            )
            if not existing_attendee:
                execute(
                    """INSERT INTO event_attendees (event_id, person_id, role, notes)
                       VALUES (%s, %s, 'speaker', %s)""",
                    (event_id, person_id, speaker.get('session_title')),
                )

            # Record provenance
            record_provenance(
                entity_type='person',
                entity_id=person_id,
                field_name='conference_speaker',
                field_value='true',
                source=f'nais_{conf_key}',
                source_url=speaker.get('url'),
                confidence=0.95,
            )

        except Exception as e:
            stats['records_errored'] += 1
            logger.error(f"[{conf_key}] Error importing speaker {speaker.get('name', '?')}: {e}")

    return stats


def scrape_all_conferences() -> Dict[str, int]:
    """Scrape all NAIS conferences and import speakers."""
    log_id = create_sync_log('nais_conferences', 'full')
    total_stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    for conf_key in NAIS_CONFERENCE_SOURCES:
        try:
            stats = import_conference_speakers(conf_key)
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception as e:
            logger.error(f"Failed to scrape conference {conf_key}: {e}")
            total_stats['records_errored'] += 1

    status = 'completed' if total_stats['records_errored'] == 0 else 'partial'
    complete_sync_log(log_id, total_stats, status=status)

    logger.info(f"All conferences completed: {total_stats}")
    return total_stats


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in NAIS_CONFERENCE_SOURCES:
        stats = import_conference_speakers(sys.argv[1])
        print(f"Results: {stats}")
    else:
        scrape_all_conferences()
