"""
Podcast Guest Tracker

Tracks guests from education leadership podcasts by:
1. Attempting to fetch RSS feeds directly
2. Using iTunes Search API to discover RSS feed URLs
3. Parsing episode titles and descriptions for guest names and schools

Podcast sources:
- Heads Together
- The Enrollment Management Podcast
- Independent School Leadership
- The School Leadership Series
- Dreaming in Color (BIPOC school leaders)
"""

import logging
import re
import json
from typing import Dict, List, Optional, Any
from datetime import datetime

import feedparser
import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import PODCAST_SOURCES, ITUNES_SEARCH_API
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
    safe_date,
)

logger = logging.getLogger('knock.people_sources.podcast_guests')

# ---------------------------------------------------------------------------
# Guest name extraction from episode descriptions
# ---------------------------------------------------------------------------

# Patterns to find guest names in episode descriptions
GUEST_INTRO_PATTERNS = [
    # "In this episode, we talk with Dr. Jane Smith, Head of School at..."
    re.compile(r'(?:talk|speak|chat|sit down|interview)\s+(?:with|to)\s+(.+?)(?:,\s+(?:who|the|a|head|director|dean|president))', re.I),
    # "This week's guest is Jane Smith"
    re.compile(r"(?:this\s+week'?s?\s+)?guest\s+is\s+(.+?)(?:,|\.|who)", re.I),
    # "Featuring Dr. John Doe"
    re.compile(r'featuring\s+(.+?)(?:,|\.|who|from)', re.I),
    # "Join us with Jane Smith from Phillips Academy"
    re.compile(r'join\s+(?:us|me)\s+(?:with|as we (?:talk|speak) (?:with|to))\s+(.+?)(?:,|\.|from|who)', re.I),
    # "Guest: Jane Smith" or "Guest - Jane Smith"
    re.compile(r'guest[:\-\s]+(.+?)(?:,|\.|$)', re.I),
    # "with special guest Jane Smith"
    re.compile(r'(?:special\s+)?guest\s+(.+?)(?:,|\.|who|from|$)', re.I),
]

# Pattern: "Name, Title at Organization" or "Name from Organization"
GUEST_ORG_PATTERNS = [
    re.compile(r'(.+?),\s+(.+?)\s+(?:at|of)\s+(.+?)(?:\.|,|$)', re.I),
    re.compile(r'(.+?)\s+from\s+(.+?)(?:\.|,|$)', re.I),
]


def _extract_guest_from_title(title: str) -> Optional[Dict[str, Optional[str]]]:
    """
    Try to extract guest name from episode title.
    Common formats:
    - "Episode 42: Dr. Jane Smith on Leadership"
    - "Jane Smith - Leading Through Change"
    - "Conversation with John Doe"
    """
    if not title:
        return None

    # Pattern: "Something with/featuring Name"
    for pattern in [
        re.compile(r'(?:with|featuring)\s+(.+?)(?:\s+[-\|:]|\s+on\s+|\s*$)', re.I),
        re.compile(r'[-\|:]\s+(.+?)(?:\s+[-\|:]|\s+on\s+|\s*$)', re.I),
    ]:
        match = pattern.search(title)
        if match:
            candidate = clean_text(match.group(1))
            # Verify it looks like a name (2-5 words, starts uppercase)
            words = candidate.split()
            if 2 <= len(words) <= 5 and candidate[0].isupper():
                return {'name': candidate, 'title': None, 'organization': None}

    return None


def _extract_guest_from_description(description: str) -> Optional[Dict[str, Optional[str]]]:
    """Extract guest name, title, organization from episode description."""
    if not description:
        return None

    # Strip HTML tags
    text = re.sub(r'<[^>]+>', ' ', description)
    text = clean_text(text)

    for pattern in GUEST_INTRO_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_name = clean_text(match.group(1))

            # Now try to split "Name, Title at Org"
            for org_pat in GUEST_ORG_PATTERNS:
                org_match = org_pat.match(raw_name)
                if org_match:
                    groups = org_match.groups()
                    if len(groups) == 3:
                        return {
                            'name': clean_text(groups[0]),
                            'title': clean_text(groups[1]),
                            'organization': clean_text(groups[2]),
                        }
                    elif len(groups) == 2:
                        return {
                            'name': clean_text(groups[0]),
                            'title': None,
                            'organization': clean_text(groups[1]),
                        }

            # Just the name
            words = raw_name.split()
            if 2 <= len(words) <= 6 and raw_name[0].isupper():
                return {'name': raw_name, 'title': None, 'organization': None}

    return None


# ---------------------------------------------------------------------------
# RSS feed discovery and parsing
# ---------------------------------------------------------------------------

def _discover_rss_url(podcast_key: str) -> Optional[str]:
    """Try to discover RSS feed URL via iTunes Search API."""
    source = PODCAST_SOURCES[podcast_key]
    search_term = source.get('itunes_search')
    if not search_term:
        return None

    try:
        resp = requests.get(
            ITUNES_SEARCH_API,
            params={
                'term': search_term,
                'media': 'podcast',
                'limit': 5,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        results = data.get('results', [])

        # Find best matching podcast
        search_lower = source['name'].lower()
        for r in results:
            name = r.get('collectionName', '').lower()
            if search_lower in name or name in search_lower:
                feed_url = r.get('feedUrl')
                if feed_url:
                    logger.info(f"[{podcast_key}] Discovered RSS feed via iTunes: {feed_url}")
                    return feed_url

        # Return first result if no exact match
        if results and results[0].get('feedUrl'):
            return results[0]['feedUrl']

    except Exception as e:
        logger.warning(f"[{podcast_key}] iTunes search failed: {e}")

    return None


def _parse_podcast_feed(
    podcast_key: str,
    rss_url: str,
) -> List[Dict[str, Any]]:
    """Parse an RSS feed and extract guest information from episodes."""
    episodes = []

    try:
        feed = feedparser.parse(rss_url)
    except Exception as e:
        logger.error(f"[{podcast_key}] Feed parse error for {rss_url}: {e}")
        return episodes

    if not feed.entries:
        logger.warning(f"[{podcast_key}] No entries in feed: {rss_url}")
        return episodes

    podcast_name = feed.feed.get('title', PODCAST_SOURCES[podcast_key]['name'])
    logger.info(f"[{podcast_key}] Parsing {len(feed.entries)} episodes from '{podcast_name}'")

    for entry in feed.entries[:100]:  # Process up to 100 recent episodes
        title = clean_text(entry.get('title', ''))
        description = entry.get('summary', entry.get('description', ''))
        published = entry.get('published', entry.get('updated', ''))
        link = entry.get('link', '')

        # Try to extract guest from title first, then description
        guest = _extract_guest_from_title(title)
        if not guest:
            guest = _extract_guest_from_description(description)

        if guest and guest.get('name'):
            episodes.append({
                'guest_name': guest['name'],
                'guest_title': guest.get('title'),
                'guest_organization': guest.get('organization'),
                'episode_title': title,
                'episode_url': link,
                'episode_date': safe_date(published),
                'podcast_name': podcast_name,
                'podcast_key': podcast_key,
            })

    return episodes


def scrape_podcast(podcast_key: str) -> List[Dict[str, Any]]:
    """Scrape a single podcast for guest information."""
    if podcast_key not in PODCAST_SOURCES:
        logger.error(f"Unknown podcast key: {podcast_key}")
        return []

    source = PODCAST_SOURCES[podcast_key]
    episodes = []

    # Try configured RSS URLs first
    for rss_url in source.get('rss_urls', []):
        eps = _parse_podcast_feed(podcast_key, rss_url)
        if eps:
            episodes.extend(eps)
            break

    # If no results, try to discover via iTunes
    if not episodes:
        discovered_url = _discover_rss_url(podcast_key)
        if discovered_url:
            episodes = _parse_podcast_feed(podcast_key, discovered_url)

    # Deduplicate by guest name
    seen = set()
    unique = []
    for ep in episodes:
        key = ep['guest_name'].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(ep)

    logger.info(f"[{podcast_key}] Found {len(unique)} unique guests from {len(episodes)} episodes")
    return unique


# ---------------------------------------------------------------------------
# Database import
# ---------------------------------------------------------------------------

def import_podcast_guests(podcast_key: str) -> Dict[str, int]:
    """Scrape and import guests from a podcast."""
    stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    episodes = scrape_podcast(podcast_key)
    if not episodes:
        return stats

    for ep in episodes:
        stats['records_processed'] += 1
        try:
            school_id = None
            if ep.get('guest_organization'):
                school = find_school_by_name(ep['guest_organization'])
                if school:
                    school_id = str(school['id'])

            # Determine tags
            tags = ['podcast_guest', f'podcast:{podcast_key}']
            if podcast_key == 'dreaming_in_color':
                tags.append('bipoc_leader')

            person_id, created = upsert_person(
                full_name=ep['guest_name'],
                data_source=f'podcast_{podcast_key}',
                title=ep.get('guest_title'),
                organization=ep.get('guest_organization'),
                school_id=school_id,
                tags=tags,
            )

            if created:
                stats['records_created'] += 1
            else:
                stats['records_updated'] += 1

            # Insert into person_publications with type='podcast'
            existing = fetch_one(
                """SELECT id FROM person_publications
                   WHERE person_id = %s AND title = %s AND publication_type = 'podcast'
                   LIMIT 1""",
                (person_id, ep['episode_title']),
            )
            if not existing:
                execute(
                    """INSERT INTO person_publications
                           (person_id, publication_type, title, publisher,
                            publication_date, url)
                       VALUES (%s, 'podcast', %s, %s, %s, %s)""",
                    (
                        person_id,
                        ep['episode_title'],
                        ep['podcast_name'],
                        ep.get('episode_date'),
                        ep.get('episode_url'),
                    ),
                )

            record_provenance(
                entity_type='person',
                entity_id=person_id,
                field_name='podcast_guest',
                field_value='true',
                source=f'podcast_{podcast_key}',
                source_url=ep.get('episode_url'),
                confidence=0.90,
            )

        except Exception as e:
            stats['records_errored'] += 1
            logger.error(f"[{podcast_key}] Error importing guest {ep.get('guest_name', '?')}: {e}")

    return stats


def scrape_all_podcasts() -> Dict[str, int]:
    """Scrape all configured podcasts."""
    log_id = create_sync_log('podcast_guests', 'full')
    total_stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    for podcast_key in PODCAST_SOURCES:
        try:
            stats = import_podcast_guests(podcast_key)
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception as e:
            logger.error(f"Failed to scrape podcast {podcast_key}: {e}")
            total_stats['records_errored'] += 1

    status = 'completed' if total_stats['records_errored'] == 0 else 'partial'
    complete_sync_log(log_id, total_stats, status=status)

    logger.info(f"All podcasts completed: {total_stats}")
    return total_stats


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in PODCAST_SOURCES:
        stats = import_podcast_guests(sys.argv[1])
        print(f"Results: {stats}")
    else:
        scrape_all_podcasts()
