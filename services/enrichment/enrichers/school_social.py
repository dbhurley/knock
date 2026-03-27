"""
School Social Media Profile Enricher

Discovers social media profile links from school websites. Stores LinkedIn,
Twitter/X, Facebook, Instagram, and YouTube URLs. This helps identify schools
that are active/marketing-savvy versus those that maintain a quiet posture --
useful signal for search engagement strategy.

This enricher:
  1. Finds schools with a website URL
  2. Loads the homepage (and optionally /about or /contact pages)
  3. Extracts social media profile links
  4. Stores them in the school's tags array as structured social profile entries
  5. Records provenance for auditability

Uses polite crawling: 3-second delays between requests.
"""

import logging
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..db import (
    fetch_all, fetch_one, execute,
    create_sync_log, complete_sync_log, record_provenance,
)
from ..utils import RateLimitedSession, clean_html_text

logger = logging.getLogger('knock.enrichment.school_social')

# ---------------------------------------------------------------------------
# Social media platform patterns
# ---------------------------------------------------------------------------

SOCIAL_PLATFORMS = {
    'linkedin': {
        'patterns': [
            re.compile(r'https?://(?:www\.)?linkedin\.com/(?:company|school|in)/[a-zA-Z0-9_-]+', re.I),
        ],
        'domains': ['linkedin.com'],
    },
    'twitter': {
        'patterns': [
            re.compile(r'https?://(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9_]+', re.I),
        ],
        'domains': ['twitter.com', 'x.com'],
    },
    'facebook': {
        'patterns': [
            re.compile(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9._-]+', re.I),
        ],
        'domains': ['facebook.com'],
    },
    'instagram': {
        'patterns': [
            re.compile(r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9._]+', re.I),
        ],
        'domains': ['instagram.com'],
    },
    'youtube': {
        'patterns': [
            re.compile(r'https?://(?:www\.)?youtube\.com/(?:channel|c|user|@)[/a-zA-Z0-9_-]+', re.I),
        ],
        'domains': ['youtube.com'],
    },
}

# Pages to check for social links (in addition to homepage)
PAGES_TO_CHECK = [
    '/',
    '/about',
    '/about-us',
    '/contact',
    '/contact-us',
]


class SchoolSocialScraper:
    """Discovers and stores school social media profiles."""

    def __init__(self, max_schools: int = 100):
        self.max_schools = max_schools
        self.http = RateLimitedSession(
            min_delay=3.0,  # 3-second delay between requests
            user_agent='Knock Research Bot (askknock.com; contact: hello@askknock.com)',
        )
        self.stats = {
            'records_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'records_errored': 0,
        }

    def run(self) -> Dict[str, int]:
        """Run the social media profile scraper."""
        sync_log_id = create_sync_log('school_social', 'incremental')
        logger.info("Starting school social media profile scraper")

        try:
            schools = self._get_schools()
            logger.info(f"Processing {len(schools)} schools for social profiles")

            for i, school in enumerate(schools):
                self.stats['records_processed'] += 1
                try:
                    updated = self._process_school(school)
                    if updated:
                        self.stats['records_updated'] += 1
                except Exception as e:
                    self.stats['records_errored'] += 1
                    logger.error(f"Error scraping {school['name']}: {e}", exc_info=True)

                if (i + 1) % 10 == 0:
                    logger.info(
                        f"Progress: {i+1}/{len(schools)} schools | "
                        f"Updated: {self.stats['records_updated']} | "
                        f"Errors: {self.stats['records_errored']}"
                    )

            status = 'partial' if self.stats['records_errored'] > 0 else 'completed'
            complete_sync_log(sync_log_id, self.stats, status)
            logger.info(f"Social profile scraping complete: {self.stats}")

        except Exception as e:
            complete_sync_log(sync_log_id, self.stats, 'failed', str(e))
            logger.error(f"Social profile scraping failed: {e}", exc_info=True)
            raise

        finally:
            self.http.close()

        return self.stats

    def _get_schools(self) -> List[Dict]:
        """Get schools with websites that haven't been scraped for social profiles recently."""
        return fetch_all(
            """SELECT s.id, s.name, s.website, s.tags
               FROM schools s
               WHERE s.is_active = true
                 AND s.website IS NOT NULL
                 AND s.website != ''
                 AND NOT EXISTS (
                     SELECT 1 FROM enrichment_provenance ep
                     WHERE ep.entity_type = 'school'
                       AND ep.entity_id = s.id
                       AND ep.source = 'school_social_scraper'
                       AND ep.enriched_at > NOW() - INTERVAL '90 days'
                 )
               ORDER BY s.tier ASC NULLS LAST,
                        s.enrollment_total DESC NULLS LAST
               LIMIT %s""",
            (self.max_schools,),
        )

    def _process_school(self, school: Dict) -> bool:
        """Scrape a school's website for social media links. Returns True if updated."""
        base_url = school['website']
        if not base_url:
            return False

        if not base_url.startswith('http'):
            base_url = 'https://' + base_url

        # Collect social profiles from multiple pages
        all_profiles: Dict[str, str] = {}

        for page_path in PAGES_TO_CHECK:
            url = urljoin(base_url.rstrip('/') + '/', page_path.lstrip('/'))
            try:
                resp = self.http.get_html(url)
                if resp.status_code == 200:
                    profiles = self._extract_social_links(resp.text, url)
                    # First-found URL wins for each platform
                    for platform, profile_url in profiles.items():
                        if platform not in all_profiles:
                            all_profiles[platform] = profile_url

                    # Stop once we have profiles or checked enough pages
                    if len(all_profiles) >= 3:
                        break
            except Exception as e:
                logger.debug(f"Failed to fetch {url}: {e}")
                continue

            # Only check additional pages if homepage didn't yield much
            if all_profiles and page_path == '/':
                break

        if not all_profiles:
            logger.debug(f"No social profiles found for {school['name']}")
            # Still mark as scraped so we don't retry
            record_provenance(
                'school', str(school['id']), 'social_profiles_scraped',
                '0', 'school_social_scraper',
                source_url=base_url,
            )
            return False

        # Update the school record
        self._update_school(school, all_profiles)
        return True

    def _extract_social_links(self, html: str, page_url: str) -> Dict[str, str]:
        """Extract social media profile URLs from an HTML page."""
        soup = BeautifulSoup(html, 'lxml')
        profiles: Dict[str, str] = {}

        # Find all links on the page
        for link in soup.find_all('a', href=True):
            href = link['href'].strip()
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue

            # Resolve relative URLs
            if not href.startswith('http'):
                href = urljoin(page_url, href)

            parsed = urlparse(href)
            domain = parsed.netloc.lower().lstrip('www.')

            for platform, config in SOCIAL_PLATFORMS.items():
                if platform in profiles:
                    continue  # Already found this platform

                # Check if the domain matches
                if any(d in domain for d in config['domains']):
                    # Validate with regex pattern
                    for pattern in config['patterns']:
                        match = pattern.match(href)
                        if match:
                            clean_url = match.group(0)
                            # Skip generic/share URLs
                            if not self._is_share_url(clean_url, platform):
                                profiles[platform] = clean_url
                                break

        return profiles

    @staticmethod
    def _is_share_url(url: str, platform: str) -> bool:
        """Check if a URL is a share/intent link rather than a profile link."""
        url_lower = url.lower()
        share_indicators = [
            '/sharer', '/share', '/intent/', '/dialog/',
            'share.', '/pin/', '/status/',
        ]
        return any(indicator in url_lower for indicator in share_indicators)

    def _update_school(self, school: Dict, profiles: Dict[str, str]) -> None:
        """Update a school record with discovered social profiles."""
        school_id = str(school['id'])

        # Build social profile tags like "social:linkedin:https://..."
        existing_tags = school.get('tags') or []
        # Remove any old social tags
        new_tags = [t for t in existing_tags if not t.startswith('social:')]

        for platform, url in sorted(profiles.items()):
            new_tags.append(f"social:{platform}:{url}")

        # Update tags and record provenance
        execute(
            "UPDATE schools SET tags = %s, updated_at = NOW() WHERE id = %s",
            (new_tags, school_id),
        )

        # Record provenance for each platform
        for platform, url in profiles.items():
            record_provenance(
                'school', school_id, f'social_{platform}',
                url, 'school_social_scraper',
                source_url=school['website'],
                confidence=0.95,
            )

        # Record overall scrape
        record_provenance(
            'school', school_id, 'social_profiles_scraped',
            str(len(profiles)), 'school_social_scraper',
            source_url=school['website'],
        )

        logger.info(
            f"Updated {school['name']}: "
            f"social_profiles={list(profiles.keys())}"
        )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def scrape_social(limit: int = 100) -> Dict[str, int]:
    """Convenience function to run the social scraper with a given limit."""
    scraper = SchoolSocialScraper(max_schools=limit)
    return scraper.run()


def run(max_schools: int = 100, **kwargs) -> Dict[str, int]:
    """Entry point for the enrichment runner."""
    scraper = SchoolSocialScraper(max_schools=max_schools)
    return scraper.run()
