"""
Education Publication Author Tracker

Monitors and scrapes author bylines from education publications:
- NAIS Independent School Magazine
- Education Week (leadership section)
- EdSurge (independent school articles)

Extracts author name, title, school, article title, date, URL.
Inserts into person_publications and cross-references with people table.
Published authors get published_author=TRUE flag.
"""

import logging
import re
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin
from datetime import datetime

from bs4 import BeautifulSoup
import feedparser

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import PUBLICATION_SOURCES
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

logger = logging.getLogger('knock.people_sources.publication_authors')

# ---------------------------------------------------------------------------
# Article extraction helpers
# ---------------------------------------------------------------------------

def _extract_author_from_byline(byline: str) -> Dict[str, Optional[str]]:
    """
    Parse a byline string like:
    - "By John Smith"
    - "By Dr. Jane Doe, Head of School at Phillips Academy"
    - "John Smith is the director of..."
    Returns {name, title, organization}
    """
    result = {'name': None, 'title': None, 'organization': None}
    if not byline:
        return result

    text = clean_text(byline)

    # Strip "By " prefix
    text = re.sub(r'^By\s+', '', text, flags=re.I)

    # Pattern: "Name, Title at Organization"
    match = re.match(
        r'^(.+?),\s+(.+?)\s+at\s+(.+?)(?:\.|$)',
        text,
    )
    if match:
        result['name'] = clean_text(match.group(1))
        result['title'] = clean_text(match.group(2))
        result['organization'] = clean_text(match.group(3))
        return result

    # Pattern: "Name, Title, Organization"
    match = re.match(r'^(.+?),\s+(.+?),\s+(.+?)(?:\.|$)', text)
    if match:
        result['name'] = clean_text(match.group(1))
        result['title'] = clean_text(match.group(2))
        result['organization'] = clean_text(match.group(3))
        return result

    # Pattern: "Name is the title of/at organization"
    match = re.match(
        r'^(.+?)\s+is\s+(?:the\s+)?(.+?)\s+(?:of|at)\s+(.+?)(?:\.|$)',
        text,
        re.I,
    )
    if match:
        result['name'] = clean_text(match.group(1))
        result['title'] = clean_text(match.group(2))
        result['organization'] = clean_text(match.group(3))
        return result

    # Just a name: "John Smith" (no comma or "is")
    if ',' not in text and ' is ' not in text.lower() and len(text.split()) <= 5:
        result['name'] = text
        return result

    # Take the part before the first comma as name
    parts = text.split(',', 1)
    result['name'] = clean_text(parts[0])
    return result


# ---------------------------------------------------------------------------
# RSS-based scraping
# ---------------------------------------------------------------------------

def _scrape_via_rss(
    source_key: str,
    session: RateLimitedSession,
) -> List[Dict[str, Any]]:
    """Scrape articles from an RSS feed."""
    source = PUBLICATION_SOURCES[source_key]
    articles = []

    rss_url = source.get('rss_url')
    if not rss_url:
        return articles

    logger.info(f"[{source_key}] Fetching RSS feed: {rss_url}")

    try:
        feed = feedparser.parse(rss_url)
    except Exception as e:
        logger.error(f"[{source_key}] RSS parse error: {e}")
        return articles

    if not feed.entries:
        logger.warning(f"[{source_key}] No entries in RSS feed")
        return articles

    logger.info(f"[{source_key}] Found {len(feed.entries)} RSS entries")

    for entry in feed.entries[:50]:  # Cap at 50 recent articles
        title = clean_text(entry.get('title', ''))
        link = entry.get('link', '')
        published = entry.get('published', entry.get('updated', ''))

        # Get author from feed entry
        author_name = entry.get('author', '')

        # If no author in feed metadata, try to scrape the article page
        if not author_name and link:
            author_data = _scrape_article_page_for_author(session, link, source_key)
            if author_data:
                articles.append({
                    'title': title,
                    'url': link,
                    'date': safe_date(published),
                    'publisher': source['name'],
                    **author_data,
                })
                continue

        if author_name:
            parsed = _extract_author_from_byline(author_name)
            articles.append({
                'title': title,
                'url': link,
                'date': safe_date(published),
                'publisher': source['name'],
                'author_name': parsed['name'] or author_name,
                'author_title': parsed['title'],
                'author_organization': parsed['organization'],
            })

    return articles


def _scrape_article_page_for_author(
    session: RateLimitedSession,
    url: str,
    source_key: str,
) -> Optional[Dict[str, Any]]:
    """Visit an article page to extract author byline."""
    soup = session.get_soup(url)
    if not soup:
        return None

    # Look for author elements
    for selector in [
        '.author-name', '.byline', '[class*="author"]', '[class*="byline"]',
        'meta[name="author"]', '[rel="author"]', '.contributor',
    ]:
        el = soup.select_one(selector)
        if el:
            if el.name == 'meta':
                text = el.get('content', '')
            else:
                text = clean_text(el.get_text())

            if text and len(text) < 200:
                parsed = _extract_author_from_byline(text)
                if parsed['name']:
                    return {
                        'author_name': parsed['name'],
                        'author_title': parsed['title'],
                        'author_organization': parsed['organization'],
                    }

    return None


# ---------------------------------------------------------------------------
# HTML page scraping
# ---------------------------------------------------------------------------

def _scrape_via_html(
    source_key: str,
    session: RateLimitedSession,
) -> List[Dict[str, Any]]:
    """Scrape articles from HTML listing pages."""
    source = PUBLICATION_SOURCES[source_key]
    articles = []

    for list_url in source.get('article_list_urls', []):
        soup = session.get_soup(list_url)
        if not soup:
            continue

        # Look for article cards/items
        for selector in [
            'article', '.article-card', '.post-item', '.article-item',
            '.story-card', '.content-card', 'div[class*="article"]',
            '.views-row', '.magazine-article',
        ]:
            items = soup.select(selector)
            if len(items) >= 2:
                logger.info(f"[{source_key}] Found {len(items)} article items with '{selector}'")
                for item in items[:50]:
                    article = _parse_article_item(item, list_url, source['name'])
                    if article and article.get('author_name'):
                        articles.append(article)
                break

        if articles:
            break

    return articles


def _parse_article_item(item, base_url: str, publisher: str) -> Optional[Dict[str, Any]]:
    """Parse an article list item for title, author, date."""
    # Title
    title = None
    link = None
    for tag in item.find_all(['h2', 'h3', 'h4', 'a']):
        text = clean_text(tag.get_text())
        if text and len(text) > 10 and len(text) < 300:
            title = text
            if tag.name == 'a':
                link = urljoin(base_url, tag.get('href', ''))
            elif tag.find('a'):
                link = urljoin(base_url, tag.find('a').get('href', ''))
            break

    if not title:
        return None

    # Author
    author_name = None
    for tag in item.find_all(['span', 'p', 'div', 'a']):
        cls = ' '.join(tag.get('class', []))
        if any(kw in cls.lower() for kw in ['author', 'byline', 'writer']):
            text = clean_text(tag.get_text())
            parsed = _extract_author_from_byline(text)
            if parsed['name']:
                author_name = parsed['name']
                break

    # Date
    date_str = None
    for tag in item.find_all(['time', 'span', 'p']):
        if tag.name == 'time':
            date_str = tag.get('datetime', tag.get_text())
            break
        cls = ' '.join(tag.get('class', []))
        if 'date' in cls.lower():
            date_str = clean_text(tag.get_text())
            break

    return {
        'title': title,
        'url': link or base_url,
        'date': safe_date(date_str),
        'publisher': publisher,
        'author_name': author_name,
        'author_title': None,
        'author_organization': None,
    }


# ---------------------------------------------------------------------------
# Database import
# ---------------------------------------------------------------------------

def import_articles(source_key: str) -> Dict[str, int]:
    """Scrape and import articles from a publication source."""
    stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    source = PUBLICATION_SOURCES[source_key]
    session = RateLimitedSession(min_delay=source.get('rate_limit', 3.0))

    # Choose scraping strategy
    if source.get('scrape_strategy') == 'rss' and source.get('rss_url'):
        articles = _scrape_via_rss(source_key, session)
    else:
        articles = _scrape_via_html(source_key, session)

    session.close()

    if not articles:
        logger.info(f"[{source_key}] No articles found")
        return stats

    logger.info(f"[{source_key}] Processing {len(articles)} articles")

    for article in articles:
        stats['records_processed'] += 1
        try:
            author_name = article.get('author_name')
            if not author_name:
                continue

            # Check if publication already exists
            existing_pub = fetch_one(
                """SELECT id FROM person_publications
                   WHERE title = %s AND publisher = %s
                   LIMIT 1""",
                (article['title'], article['publisher']),
            )
            if existing_pub:
                stats['records_updated'] += 1
                continue  # Already tracked

            # Find or create person
            school_id = None
            if article.get('author_organization'):
                school = find_school_by_name(article['author_organization'])
                if school:
                    school_id = str(school['id'])

            tags = ['published_author', f'pub:{source_key}']
            person_id, person_created = upsert_person(
                full_name=author_name,
                data_source=f'publication_{source_key}',
                title=article.get('author_title'),
                organization=article.get('author_organization'),
                school_id=school_id,
                tags=tags,
            )

            # Insert publication record
            execute(
                """INSERT INTO person_publications
                       (person_id, publication_type, title, publisher, publication_date, url)
                   VALUES (%s, 'article', %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (person_id, article['title'], article['publisher'],
                 article.get('date'), article.get('url')),
            )

            if person_created:
                stats['records_created'] += 1
            else:
                stats['records_updated'] += 1

            # Record provenance
            record_provenance(
                entity_type='person',
                entity_id=person_id,
                field_name='published_author',
                field_value='true',
                source=f'publication_{source_key}',
                source_url=article.get('url'),
                confidence=0.95,
            )

        except Exception as e:
            stats['records_errored'] += 1
            logger.error(f"[{source_key}] Error importing article by {article.get('author_name', '?')}: {e}")

    return stats


def scrape_all_publications() -> Dict[str, int]:
    """Scrape all configured publication sources."""
    log_id = create_sync_log('publication_authors', 'full')
    total_stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    for source_key in PUBLICATION_SOURCES:
        try:
            stats = import_articles(source_key)
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception as e:
            logger.error(f"Failed to scrape publication {source_key}: {e}")
            total_stats['records_errored'] += 1

    status = 'completed' if total_stats['records_errored'] == 0 else 'partial'
    complete_sync_log(log_id, total_stats, status=status)

    logger.info(f"All publications completed: {total_stats}")
    return total_stats


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in PUBLICATION_SOURCES:
        stats = import_articles(sys.argv[1])
        print(f"Results: {stats}")
    else:
        scrape_all_publications()
