"""
School Mission & Culture Scraper

Scrapes school websites for mission statements, core values, educational
philosophy, and strategic priorities. Auto-tags schools with culture descriptors
to support cultural-fit matching for executive search.

This enricher:
  1. Finds schools with a website URL but no school_culture_tags
  2. Visits the school's website, checking /about, /mission, /values, etc.
  3. Extracts mission statement text, core values, educational philosophy
  4. Uses keyword analysis to auto-tag culture attributes
  5. Updates school_culture_tags and strategic_priorities columns
  6. Tracks provenance for all enriched fields

Uses polite crawling: 3-second delays between requests, respects timeouts.
"""

import logging
import re
from typing import Optional, Dict, Any, List, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..db import (
    fetch_all, execute,
    create_sync_log, complete_sync_log, record_provenance,
)
from ..utils import RateLimitedSession, clean_html_text

logger = logging.getLogger('knock.enrichment.school_mission')

# ---------------------------------------------------------------------------
# URL patterns to check for mission/values/philosophy content
# ---------------------------------------------------------------------------

MISSION_URL_PATTERNS = [
    '/about',
    '/about-us',
    '/mission',
    '/our-mission',
    '/about/mission',
    '/about/mission-vision',
    '/about/mission-and-vision',
    '/about/mission-values',
    '/about-us/mission',
    '/about-us/mission-and-vision',
    '/about/our-mission',
    '/about/philosophy',
    '/about/our-philosophy',
    '/philosophy',
    '/values',
    '/about/values',
    '/about/core-values',
    '/about/our-values',
    '/about/vision',
    '/about/history-mission',
    '/about/who-we-are',
    '/about/what-we-believe',
    '/about/our-story',
    '/about/strategic-plan',
    '/strategic-plan',
    '/about/strategic-vision',
    '/about/diversity',
    '/about/diversity-equity-inclusion',
    '/about/dei',
    '/about/community',
]

# ---------------------------------------------------------------------------
# Culture tag keyword mappings
# ---------------------------------------------------------------------------

# Maps culture tags to keywords/phrases that indicate them.
# A tag is assigned if enough matching keywords appear in the text.
CULTURE_TAG_KEYWORDS: Dict[str, List[str]] = {
    'progressive': [
        'progressive', 'student-centered', 'student centered',
        'inquiry-based', 'inquiry based', 'constructivist',
        'whole child', 'social-emotional', 'social emotional',
        'experiential learning', 'discovery-based',
    ],
    'traditional': [
        'traditional', 'classical education', 'time-honored',
        'rigorous academics', 'structured curriculum',
        'discipline', 'western canon', 'liberal arts tradition',
    ],
    'classical': [
        'classical', 'trivium', 'quadrivium', 'socratic',
        'great books', 'classical liberal arts', 'latin',
        'rhetoric', 'logic and rhetoric',
    ],
    'montessori': [
        'montessori', 'prepared environment', 'self-directed',
        'hands-on learning', 'multi-age', 'mixed-age',
    ],
    'waldorf': [
        'waldorf', 'steiner', 'eurythmy', 'handwork',
        'main lesson', 'artistic curriculum',
    ],
    'faith-based': [
        'faith-based', 'faith based', 'christian', 'catholic',
        'episcopal', 'jewish', 'islamic', 'quaker',
        'friends school', 'lutheran', 'baptist', 'methodist',
        'presbyterian', 'adventist', 'ministry', 'spiritual formation',
        'chapel', 'bible', 'scripture', 'god', 'christ',
        'religious', 'parish', 'diocese',
    ],
    'college-prep': [
        'college prep', 'college-prep', 'college preparatory',
        'college placement', 'ivy league', 'selective college',
        'college counseling', 'ap courses', 'advanced placement',
        'sat prep', 'college readiness',
    ],
    'arts-focused': [
        'arts-focused', 'arts focused', 'performing arts',
        'visual arts', 'conservatory', 'arts integration',
        'creative expression', 'fine arts', 'theater program',
        'music program', 'dance program', 'arts immersion',
    ],
    'stem-focused': [
        'stem', 'steam', 'science and technology',
        'engineering program', 'robotics', 'coding',
        'computer science', 'innovation lab', 'maker space',
        'makerspace', 'technology-rich', 'computational thinking',
    ],
    'boarding': [
        'boarding school', 'boarding program', 'residential life',
        'dormitory', 'dorm life', 'residential community',
        'boarding experience', 'day and boarding',
    ],
    'military': [
        'military academy', 'military school', 'cadet',
        'corps of cadets', 'jrotc', 'military tradition',
        'military discipline', 'regiment',
    ],
    'special-needs': [
        'learning differences', 'learning disabilities',
        'special needs', 'dyslexia', 'adhd', 'autism spectrum',
        'individualized learning', 'remedial', 'orton-gillingham',
        'wilson reading', 'therapeutic', 'specialized instruction',
    ],
    'gifted': [
        'gifted', 'talented', 'gifted and talented',
        'accelerated', 'advanced learners', 'enrichment',
        'honors program', 'intellectually curious',
        'academically advanced',
    ],
    'experiential': [
        'experiential', 'hands-on', 'outdoor education',
        'field studies', 'place-based', 'adventure',
        'wilderness', 'service learning', 'real-world',
        'project-based learning',
    ],
    'project-based': [
        'project-based', 'project based', 'pbl',
        'design thinking', 'interdisciplinary projects',
        'collaborative projects', 'capstone',
    ],
    'diverse': [
        'diverse', 'diversity', 'multicultural',
        'global perspective', 'international students',
        'cultural competence', 'global citizens',
        'cross-cultural', 'world cultures',
    ],
    'inclusive': [
        'inclusive', 'inclusion', 'equity',
        'belonging', 'accessibility', 'anti-racist',
        'social justice', 'equitable', 'affirming',
        'dei', 'diversity equity and inclusion',
    ],
}

# ---------------------------------------------------------------------------
# Strategic priority keyword mappings
# ---------------------------------------------------------------------------

STRATEGIC_PRIORITY_KEYWORDS: Dict[str, List[str]] = {
    'stem-expansion': [
        'stem expansion', 'new science', 'innovation center',
        'technology initiative', 'stem investment', 'robotics program',
        'coding curriculum', 'engineering lab',
    ],
    'dei-initiatives': [
        'diversity initiative', 'equity initiative', 'inclusion initiative',
        'dei strategic', 'anti-bias', 'cultural competency training',
        'diverse hiring', 'financial aid expansion', 'access and affordability',
    ],
    'campus-development': [
        'campus master plan', 'new building', 'renovation',
        'construction', 'facility upgrade', 'capital campaign',
        'new campus', 'expansion project', 'campus improvement',
    ],
    'enrollment-growth': [
        'enrollment growth', 'enrollment increase', 'new families',
        'recruitment', 'marketing strategy', 'admission growth',
        'expand enrollment',
    ],
    'sustainability': [
        'sustainability', 'green campus', 'carbon neutral',
        'environmental stewardship', 'solar', 'leed',
        'climate action', 'eco-friendly',
    ],
    'global-education': [
        'global education', 'international program', 'study abroad',
        'exchange program', 'global competence', 'world languages',
        'international baccalaureate', 'ib program',
    ],
    'wellness-focus': [
        'wellness', 'mental health', 'social-emotional learning',
        'mindfulness', 'counseling expansion', 'student well-being',
        'health and wellness',
    ],
    'technology-integration': [
        'technology integration', '1:1 device', 'digital literacy',
        'ed tech', 'learning management', 'hybrid learning',
        'online learning', 'digital transformation',
    ],
    'endowment-growth': [
        'endowment growth', 'endowment campaign', 'planned giving',
        'major gifts', 'comprehensive campaign', 'fundraising goal',
    ],
    'faculty-development': [
        'faculty development', 'teacher training', 'professional development',
        'teacher retention', 'faculty compensation', 'faculty recruitment',
    ],
}


class SchoolMissionScraper:
    """Scrapes school websites for mission, values, and culture data."""

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
        """Run the mission/culture scraper."""
        sync_log_id = create_sync_log('school_mission', 'incremental')
        logger.info("Starting school mission & culture scraper")

        try:
            schools = self._get_schools()
            logger.info(f"Processing {len(schools)} schools for mission/culture data")

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
            logger.info(f"School mission scraping complete: {self.stats}")

        except Exception as e:
            complete_sync_log(sync_log_id, self.stats, 'failed', str(e))
            logger.error(f"School mission scraping failed: {e}", exc_info=True)
            raise

        finally:
            self.http.close()

        return self.stats

    def _get_schools(self) -> List[Dict]:
        """Get schools with websites but no culture tags."""
        return fetch_all(
            """SELECT id, name, city, state, website, school_type,
                      religious_affiliation, boarding_status
               FROM schools
               WHERE is_active = true
                 AND website IS NOT NULL
                 AND website != ''
                 AND (school_culture_tags IS NULL OR school_culture_tags = '{}')
               ORDER BY tier ASC NULLS LAST,
                        enrollment_total DESC NULLS LAST
               LIMIT %s""",
            (self.max_schools,),
        )

    def _process_school(self, school: Dict) -> bool:
        """Scrape a school's website for mission/culture info. Returns True if updated."""
        base_url = school['website']
        if not base_url:
            return False

        if not base_url.startswith('http'):
            base_url = 'https://' + base_url

        # Collect all text from mission/about pages
        all_text_parts: List[str] = []
        mission_text = ''
        source_urls: List[str] = []

        for pattern in MISSION_URL_PATTERNS:
            url = urljoin(base_url.rstrip('/') + '/', pattern.lstrip('/'))
            try:
                resp = self.http.get_html(url)
                if resp.status_code == 200 and len(resp.text) > 500:
                    page_text = self._extract_page_text(resp.text)
                    if page_text and len(page_text) > 50:
                        all_text_parts.append(page_text)
                        source_urls.append(url)

                        # Try to extract a specific mission statement
                        if not mission_text:
                            mission = self._extract_mission_statement(resp.text)
                            if mission:
                                mission_text = mission

                        # Stop after collecting enough text (4 pages max)
                        if len(all_text_parts) >= 4:
                            break
            except Exception as e:
                logger.debug(f"Failed to fetch {url}: {e}")
                continue

        if not all_text_parts:
            logger.debug(f"No mission/culture content found for {school['name']}")
            return False

        # Combine all scraped text for analysis
        combined_text = '\n\n'.join(all_text_parts)
        combined_lower = combined_text.lower()

        # Determine culture tags
        culture_tags = self._detect_culture_tags(combined_lower, school)

        # Determine strategic priorities
        strategic_priorities = self._detect_strategic_priorities(combined_lower)

        if not culture_tags and not strategic_priorities:
            logger.debug(f"No culture signals detected for {school['name']}")
            return False

        # Update the school record
        self._update_school(school, culture_tags, strategic_priorities,
                           mission_text, source_urls)
        return True

    def _extract_page_text(self, html: str) -> str:
        """Extract meaningful text content from an HTML page."""
        soup = BeautifulSoup(html, 'lxml')

        # Remove script, style, nav, footer, header elements
        for tag in soup.find_all(['script', 'style', 'nav', 'footer',
                                   'header', 'noscript', 'iframe']):
            tag.decompose()

        # Try to find the main content area
        main_content = (
            soup.find('main')
            or soup.find('article')
            or soup.find(id=re.compile(r'content|main', re.I))
            or soup.find(class_=re.compile(r'content|main|entry|post', re.I))
        )

        target = main_content if main_content else soup.body
        if not target:
            return ''

        text = clean_html_text(target.get_text(separator=' '))

        # Truncate very long pages to avoid processing noise
        if len(text) > 10000:
            text = text[:10000]

        return text

    def _extract_mission_statement(self, html: str) -> str:
        """Try to extract a specific mission statement from the page."""
        soup = BeautifulSoup(html, 'lxml')

        # Strategy 1: Look for elements explicitly labeled as mission
        mission_patterns = [
            re.compile(r'mission\s*statement', re.I),
            re.compile(r'our\s*mission', re.I),
            re.compile(r'school\s*mission', re.I),
        ]

        for pattern in mission_patterns:
            # Check headings
            for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
                if pattern.search(heading.get_text()):
                    # Get the next paragraph(s) after this heading
                    mission_parts = []
                    for sibling in heading.find_next_siblings():
                        if sibling.name in ['h1', 'h2', 'h3', 'h4']:
                            break
                        text = clean_html_text(sibling.get_text())
                        if text and len(text) > 20:
                            mission_parts.append(text)
                        if len(' '.join(mission_parts)) > 1000:
                            break
                    if mission_parts:
                        return ' '.join(mission_parts)[:2000]

        # Strategy 2: Look for blockquotes or specially styled mission text
        for bq in soup.find_all('blockquote'):
            text = clean_html_text(bq.get_text())
            if len(text) > 50 and any(w in text.lower() for w in
                    ['mission', 'educate', 'inspire', 'develop', 'prepare',
                     'nurture', 'empower', 'community', 'students']):
                return text[:2000]

        return ''

    def _detect_culture_tags(self, text_lower: str, school: Dict) -> List[str]:
        """Detect applicable culture tags from scraped text."""
        detected_tags: List[str] = []

        for tag, keywords in CULTURE_TAG_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            # Require at least 2 keyword matches for a tag
            # (some tags like 'boarding' may appear incidentally)
            threshold = 2
            if matches >= threshold:
                detected_tags.append(tag)

        # Also infer from existing school metadata
        if school.get('religious_affiliation') and school['religious_affiliation'] not in ('None', ''):
            if 'faith-based' not in detected_tags:
                detected_tags.append('faith-based')

        if school.get('boarding_status') and 'boarding' in school['boarding_status'].lower():
            if 'boarding' not in detected_tags:
                detected_tags.append('boarding')

        return sorted(set(detected_tags))

    def _detect_strategic_priorities(self, text_lower: str) -> List[str]:
        """Detect strategic priorities from scraped text."""
        detected: List[str] = []

        for priority, keywords in STRATEGIC_PRIORITY_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            if matches >= 2:
                detected.append(priority)

        return sorted(set(detected))

    def _update_school(
        self,
        school: Dict,
        culture_tags: List[str],
        strategic_priorities: List[str],
        mission_text: str,
        source_urls: List[str],
    ) -> None:
        """Update a school record with culture/mission data."""
        school_id = str(school['id'])
        updates = []
        params = []

        if culture_tags:
            updates.append("school_culture_tags = %s")
            params.append(culture_tags)
            record_provenance(
                'school', school_id, 'school_culture_tags',
                ', '.join(culture_tags), 'school_mission_scraper',
                source_url=source_urls[0] if source_urls else None,
                confidence=0.8,
            )

        if strategic_priorities:
            updates.append("strategic_priorities = %s")
            params.append(strategic_priorities)
            record_provenance(
                'school', school_id, 'strategic_priorities',
                ', '.join(strategic_priorities), 'school_mission_scraper',
                source_url=source_urls[0] if source_urls else None,
                confidence=0.7,
            )

        if mission_text:
            # Store mission statement in the notes field (appending)
            updates.append(
                "notes = CASE WHEN notes IS NULL THEN %s "
                "ELSE notes || E'\\n\\n' || %s END"
            )
            mission_label = f"[Mission Statement - auto-scraped]\n{mission_text}"
            params.extend([mission_label, mission_label])
            record_provenance(
                'school', school_id, 'mission_statement',
                mission_text[:500], 'school_mission_scraper',
                source_url=source_urls[0] if source_urls else None,
                confidence=0.9,
            )

        updates.append("last_enriched_at = NOW()")
        updates.append("updated_at = NOW()")
        params.append(school_id)

        sql = f"UPDATE schools SET {', '.join(updates)} WHERE id = %s"
        execute(sql, tuple(params))

        logger.info(
            f"Updated {school['name']}: "
            f"culture_tags={culture_tags}, "
            f"strategic_priorities={strategic_priorities}"
        )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def scrape_missions(limit: int = 100) -> Dict[str, int]:
    """Convenience function to run the mission scraper with a given limit."""
    scraper = SchoolMissionScraper(max_schools=limit)
    return scraper.run()


def run(max_schools: int = 100, **kwargs) -> Dict[str, int]:
    """Entry point for the enrichment runner."""
    scraper = SchoolMissionScraper(max_schools=max_schools)
    return scraper.run()
