"""
School Website Leadership Scraper

Scrapes school websites for leadership/administration pages to discover
and enrich person records (names, titles, emails, bios, photos).

This enricher:
  1. For schools with a website URL in our DB
  2. Tries common leadership page URL patterns
  3. Extracts name, title, email, phone, bio, photo URL
  4. Cross-references against people table
  5. Creates new records for unknown leaders
  6. Updates existing records with bio, email, phone

Uses polite crawling: 2-second delays between requests, respects robots.txt.
"""

import logging
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ..db import (
    fetch_all, fetch_one, execute,
    create_sync_log, complete_sync_log, record_provenance,
)
from ..utils import (
    RateLimitedSession, normalize_name, fuzzy_name_match,
    name_similarity, parse_name_parts,
    extract_email_from_text, extract_phone_from_text, clean_html_text,
)

logger = logging.getLogger('knock.enrichment.school_websites')

# Common URL patterns for school leadership/administration pages
LEADERSHIP_URL_PATTERNS = [
    '/about/leadership',
    '/about/administration',
    '/about/head-of-school',
    '/about-us/leadership',
    '/about-us/administration',
    '/about-us/head-of-school',
    '/about/our-leadership',
    '/about/our-team',
    '/about/senior-leadership',
    '/our-team',
    '/leadership-team',
    '/leadership',
    '/administration',
    '/about/board-of-trustees',
    '/about/board',
    '/about/administrative-team',
    '/about/heads-message',
    '/about/meet-our-team',
    '/about/faculty-staff/administration',
    '/about/people/leadership',
    '/community/leadership',
]

# Titles that indicate school leadership
LEADERSHIP_TITLES = {
    'head_of_school': [
        'head of school', 'headmaster', 'headmistress', 'president',
        'rector', 'executive director', 'school director',
    ],
    'assistant_head': [
        'assistant head', 'associate head', 'deputy head',
    ],
    'division_head': [
        'division head', 'head of upper school', 'head of middle school',
        'head of lower school', 'upper school director', 'middle school director',
        'lower school director', 'principal',
    ],
    'academic_dean': [
        'academic dean', 'dean of faculty', 'dean of academics',
        'chief academic officer', 'dean of curriculum',
    ],
    'cfo': [
        'chief financial officer', 'cfo', 'director of finance',
        'business manager', 'chief business officer',
    ],
    'admissions_director': [
        'director of admission', 'director of admissions',
        'dean of admission', 'dean of enrollment',
    ],
    'advancement_director': [
        'director of advancement', 'director of development',
        'chief advancement officer', 'vp of advancement',
    ],
    'dean_of_students': [
        'dean of students', 'dean of student life',
        'director of student affairs',
    ],
}


class SchoolWebsiteScraper:
    """Scrapes school websites for leadership information."""

    def __init__(self, max_schools: int = 50):
        self.max_schools = max_schools
        self.http = RateLimitedSession(
            min_delay=2.0,  # Polite 2-second delay
            user_agent='Knock Research Bot (askknock.com; contact: hello@askknock.com)',
        )
        self.stats = {
            'records_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'records_errored': 0,
        }

    def run(self, school_ids: Optional[List[str]] = None) -> Dict[str, int]:
        """Run the school website scraper."""
        sync_log_id = create_sync_log('school_website', 'incremental' if school_ids else 'full')
        logger.info("Starting school website leadership scraper")

        try:
            schools = self._get_schools(school_ids)
            logger.info(f"Processing {len(schools)} schools with websites")

            for i, school in enumerate(schools):
                self.stats['records_processed'] += 1
                try:
                    self._process_school(school)
                except Exception as e:
                    self.stats['records_errored'] += 1
                    logger.error(f"Error scraping {school['name']}: {e}", exc_info=True)

                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i+1}/{len(schools)} schools")

            status = 'partial' if self.stats['records_errored'] > 0 else 'completed'
            complete_sync_log(sync_log_id, self.stats, status)
            logger.info(f"School website scraping complete: {self.stats}")

        except Exception as e:
            complete_sync_log(sync_log_id, self.stats, 'failed', str(e))
            logger.error(f"School website scraping failed: {e}", exc_info=True)
            raise

        finally:
            self.http.close()

        return self.stats

    def _get_schools(self, school_ids: Optional[List[str]] = None) -> List[Dict]:
        """Get schools with websites to scrape."""
        if school_ids:
            return fetch_all(
                """SELECT id, name, city, state, website
                   FROM schools
                   WHERE id = ANY(%s) AND website IS NOT NULL AND website != ''
                   ORDER BY name""",
                (school_ids,),
            )

        return fetch_all(
            """SELECT s.id, s.name, s.city, s.state, s.website
               FROM schools s
               WHERE s.is_active = true
                 AND s.website IS NOT NULL
                 AND s.website != ''
                 AND NOT EXISTS (
                     SELECT 1 FROM enrichment_provenance ep
                     WHERE ep.entity_type = 'school'
                       AND ep.entity_id = s.id
                       AND ep.source = 'school_website'
                       AND ep.enriched_at > NOW() - INTERVAL '90 days'
                 )
               ORDER BY s.tier ASC NULLS LAST, s.enrollment_total DESC NULLS LAST
               LIMIT %s""",
            (self.max_schools,),
        )

    def _process_school(self, school: Dict) -> None:
        """Scrape a school's website for leadership info."""
        base_url = school['website']
        if not base_url:
            return

        # Ensure URL has a scheme
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url

        # Try each leadership URL pattern until we find one that works
        leaders_found = []
        for pattern in LEADERSHIP_URL_PATTERNS:
            url = urljoin(base_url.rstrip('/') + '/', pattern.lstrip('/'))
            try:
                resp = self.http.get_html(url)
                if resp.status_code == 200 and len(resp.text) > 1000:
                    leaders = self._extract_leaders_from_page(resp.text, url)
                    if leaders:
                        leaders_found.extend(leaders)
                        logger.info(f"Found {len(leaders)} leaders at {url}")
                        # Don't break - check additional pages for more leaders
                        if len(leaders_found) >= 20:
                            break
            except Exception as e:
                logger.debug(f"Failed to fetch {url}: {e}")
                continue

        if not leaders_found:
            logger.debug(f"No leadership data found for {school['name']}")
            return

        # Deduplicate leaders by name
        seen_names = set()
        unique_leaders = []
        for leader in leaders_found:
            normalized = normalize_name(leader.get('name', ''))
            if normalized and normalized not in seen_names:
                seen_names.add(normalized)
                unique_leaders.append(leader)

        # Process each discovered leader
        for leader in unique_leaders:
            try:
                self._upsert_leader(school, leader)
            except Exception as e:
                logger.warning(f"Error upserting leader {leader.get('name')}: {e}")

        # Mark school as scraped
        record_provenance(
            'school', str(school['id']), 'leadership_page_scraped',
            str(len(unique_leaders)), 'school_website',
            source_url=base_url,
        )

    def _extract_leaders_from_page(self, html: str, url: str) -> List[Dict]:
        """Extract leadership info from an HTML page."""
        soup = BeautifulSoup(html, 'lxml')
        leaders = []

        # Strategy 1: Look for structured person cards/profiles
        # Common patterns: div.team-member, div.staff-member, div.person-card, etc.
        person_selectors = [
            'div.team-member', 'div.staff-member', 'div.person-card',
            'div.leadership-member', 'div.admin-member', 'div.profile-card',
            'div.bio-card', 'div.person', 'article.team-member',
            'li.team-member', 'div.faculty-member', 'div.personnel',
            'div[class*="leader"]', 'div[class*="staff"]', 'div[class*="team"]',
            'div[class*="person"]', 'div[class*="profile"]', 'div[class*="bio"]',
        ]

        for selector in person_selectors:
            cards = soup.select(selector)
            if cards:
                for card in cards:
                    leader = self._parse_person_card(card, url)
                    if leader:
                        leaders.append(leader)
                if leaders:
                    return leaders

        # Strategy 2: Look for heading + description patterns
        # e.g., <h3>John Smith</h3><p>Head of School</p>
        for heading_tag in ['h2', 'h3', 'h4']:
            headings = soup.find_all(heading_tag)
            for heading in headings:
                leader = self._parse_heading_pattern(heading, url)
                if leader:
                    leaders.append(leader)
            if leaders:
                return leaders

        # Strategy 3: Look for tables with staff info
        tables = soup.find_all('table')
        for table in tables:
            table_leaders = self._parse_staff_table(table, url)
            leaders.extend(table_leaders)

        return leaders

    def _parse_person_card(self, card: Tag, page_url: str) -> Optional[Dict]:
        """Extract person info from a structured card element."""
        result = {'source_url': page_url}

        # Find name - usually in a heading or strong tag
        name_el = (
            card.find(['h2', 'h3', 'h4', 'h5'])
            or card.find('strong')
            or card.find(class_=re.compile(r'name|title', re.I))
        )
        if name_el:
            result['name'] = clean_html_text(name_el.get_text())

        # Find title - usually in a paragraph or span after the name
        title_el = card.find(class_=re.compile(r'position|role|title|job', re.I))
        if not title_el and name_el:
            # Look for the next sibling paragraph or span
            next_el = name_el.find_next_sibling(['p', 'span', 'div'])
            if next_el:
                title_el = next_el

        if title_el:
            title_text = clean_html_text(title_el.get_text())
            # Don't use the name as the title
            if title_text and title_text != result.get('name'):
                result['title'] = title_text

        # Find email
        email_link = card.find('a', href=re.compile(r'^mailto:'))
        if email_link:
            result['email'] = email_link['href'].replace('mailto:', '').split('?')[0].lower()

        # Find phone
        phone_link = card.find('a', href=re.compile(r'^tel:'))
        if phone_link:
            result['phone'] = extract_phone_from_text(phone_link['href'])

        # Find photo
        img = card.find('img')
        if img:
            src = img.get('src') or img.get('data-src')
            if src:
                result['photo_url'] = urljoin(page_url, src)

        # Find bio text
        bio_el = card.find(class_=re.compile(r'bio|description|about|summary', re.I))
        if not bio_el:
            # Look for longer paragraph text
            paragraphs = card.find_all('p')
            for p in paragraphs:
                text = clean_html_text(p.get_text())
                if len(text) > 100:  # Bio text is usually substantial
                    bio_el = p
                    break
        if bio_el:
            result['bio'] = clean_html_text(bio_el.get_text())[:5000]

        # Also extract email/phone from card text
        card_text = card.get_text()
        if 'email' not in result:
            email = extract_email_from_text(card_text)
            if email:
                result['email'] = email
        if 'phone' not in result:
            phone = extract_phone_from_text(card_text)
            if phone:
                result['phone'] = phone

        # Validate: must have at least a name
        if not result.get('name') or len(result['name']) < 3:
            return None

        # Filter out obvious non-person entries
        name_lower = result['name'].lower()
        if any(skip in name_lower for skip in ['contact us', 'read more', 'learn more', 'view all']):
            return None

        return result

    def _parse_heading_pattern(self, heading: Tag, page_url: str) -> Optional[Dict]:
        """Extract person info from a heading + following content pattern."""
        name = clean_html_text(heading.get_text())
        if not name or len(name) < 3 or len(name) > 100:
            return None

        # Check if this looks like a person name (not a section heading)
        name_lower = name.lower()
        skip_words = ['about', 'our', 'the', 'welcome', 'history', 'mission', 'leadership team',
                       'administration', 'faculty', 'contact', 'board of', 'quick links']
        if any(w in name_lower for w in skip_words):
            return None

        result = {'name': name, 'source_url': page_url}

        # Look at the next sibling for title/bio
        next_el = heading.find_next_sibling(['p', 'span', 'div'])
        if next_el:
            text = clean_html_text(next_el.get_text())
            if text and len(text) < 200:
                result['title'] = text
            elif text:
                result['bio'] = text[:5000]

        return result

    def _parse_staff_table(self, table: Tag, page_url: str) -> List[Dict]:
        """Extract staff info from an HTML table."""
        leaders = []
        rows = table.find_all('tr')

        for row in rows[1:]:  # Skip header row
            cells = row.find_all(['td', 'th'])
            if len(cells) >= 2:
                name = clean_html_text(cells[0].get_text())
                title = clean_html_text(cells[1].get_text())
                if name and len(name) > 2 and title:
                    leader = {'name': name, 'title': title, 'source_url': page_url}
                    if len(cells) >= 3:
                        text = cells[2].get_text()
                        email = extract_email_from_text(text)
                        if email:
                            leader['email'] = email
                        phone = extract_phone_from_text(text)
                        if phone:
                            leader['phone'] = phone
                    leaders.append(leader)

        return leaders

    def _upsert_leader(self, school: Dict, leader: Dict) -> None:
        """Match or create a person record and update with scraped data."""
        leader_name = leader.get('name', '').strip()
        if not leader_name:
            return

        # Try to find an existing person match
        person_id = self._find_matching_person(leader_name, school)

        if person_id:
            # Update existing person with new data
            self._update_person(person_id, leader, school)
            self.stats['records_updated'] += 1
        else:
            # Create new person
            person_id = self._create_person(leader, school)
            if person_id:
                self.stats['records_created'] += 1

    def _find_matching_person(self, name: str, school: Dict) -> Optional[str]:
        """Try to find an existing person matching this leader."""
        # Search by name similarity within the school context
        candidates = fetch_all(
            """SELECT id, full_name, current_school_id, current_organization
               FROM people
               WHERE current_school_id = %s
                  OR name_normalized %% %s
               LIMIT 30""",
            (school['id'], normalize_name(name)),
        )

        best_id = None
        best_score = 0.0

        for c in candidates:
            score = name_similarity(name, c['full_name'])

            # Boost if same school
            if c.get('current_school_id') and str(c['current_school_id']) == str(school['id']):
                score = min(score + 15, 100)

            if score > best_score and score >= 80:
                best_score = score
                best_id = str(c['id'])

        return best_id

    def _update_person(self, person_id: str, leader: Dict, school: Dict) -> None:
        """Update an existing person with scraped leadership data."""
        updates = []
        params = []

        if leader.get('email'):
            updates.append("email_primary = COALESCE(email_primary, %s)")
            params.append(leader['email'])
            record_provenance('person', person_id, 'email_primary', leader['email'],
                            'school_website', source_url=leader.get('source_url'))

        if leader.get('phone'):
            updates.append("phone_primary = COALESCE(phone_primary, %s)")
            params.append(leader['phone'])
            record_provenance('person', person_id, 'phone_primary', leader['phone'],
                            'school_website', source_url=leader.get('source_url'))

        if leader.get('title'):
            updates.append("current_title = COALESCE(current_title, %s)")
            params.append(leader['title'])

        if leader.get('photo_url'):
            updates.append("linkedin_profile_photo_url = COALESCE(linkedin_profile_photo_url, %s)")
            params.append(leader['photo_url'])

        if leader.get('bio'):
            updates.append("linkedin_summary = COALESCE(linkedin_summary, %s)")
            params.append(leader['bio'][:5000])

        if updates:
            updates.append("updated_at = NOW()")
            params.append(person_id)
            sql = f"UPDATE people SET {', '.join(updates)} WHERE id = %s"
            execute(sql, tuple(params))

    def _create_person(self, leader: Dict, school: Dict) -> Optional[str]:
        """Create a new person record from scraped website data."""
        name = leader.get('name', '')
        parts = parse_name_parts(name)
        title = leader.get('title', '')

        row = fetch_one(
            """INSERT INTO people
                   (full_name, first_name, last_name, prefix, suffix,
                    name_normalized, current_title, current_organization,
                    current_school_id, primary_role,
                    email_primary, phone_primary,
                    linkedin_profile_photo_url, linkedin_summary,
                    data_source, candidate_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       'web_scrape', 'passive')
               RETURNING id""",
            (
                name,
                parts['first_name'],
                parts['last_name'],
                parts['prefix'] or None,
                parts['suffix'] or None,
                normalize_name(name),
                title or None,
                school['name'],
                school['id'],
                self._classify_title(title),
                leader.get('email'),
                leader.get('phone'),
                leader.get('photo_url'),
                leader.get('bio', '')[:5000] or None,
            ),
        )

        if row:
            person_id = str(row['id'])
            logger.info(f"Created person from website: {name} ({title}) at {school['name']}")
            record_provenance('person', person_id, 'full_name', name,
                            'school_website', source_url=leader.get('source_url'))
            return person_id
        return None

    @staticmethod
    def _classify_title(title: str) -> Optional[str]:
        """Map a scraped title to our primary_role taxonomy."""
        if not title:
            return None
        t = title.lower()
        for role, keywords in LEADERSHIP_TITLES.items():
            if any(kw in t for kw in keywords):
                return role
        return None


def run(max_schools: int = 50, school_ids: Optional[List[str]] = None, **kwargs) -> Dict[str, int]:
    """Entry point for the enrichment runner."""
    scraper = SchoolWebsiteScraper(max_schools=max_schools)
    return scraper.run(school_ids=school_ids)
