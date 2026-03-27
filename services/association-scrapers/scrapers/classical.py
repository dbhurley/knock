"""
ACCS (Association of Classical Christian Schools) scraper.
Scrapes the Classical Christian school directory at classicalchristian.org.
~500 member schools.
"""

import logging
import re
from typing import Dict, Any, Optional, List

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import ASSOCIATIONS
from utils import (
    ScraperSession, find_matching_school, find_matching_person,
    insert_school, update_school, insert_person, update_person,
    parse_name_parts, extract_email, extract_phone, clean_text,
    parse_enrollment, parse_grades, normalize_state,
    create_sync_log, complete_sync_log,
)

logger = logging.getLogger('knock.scrapers.classical')
CONF = ASSOCIATIONS['classical']


def _scrape_directory(session: ScraperSession, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scrape the ACCS school directory."""
    schools = []

    try:
        # ACCS Find-a-School page
        soup = session.get_soup(CONF['search_url'])

        school_els = soup.select(
            '.school-listing, .school-card, .directory-entry, '
            '.member-school, article.school, .school-item, '
            '.views-row, .directory-item'
        )

        if not school_els:
            school_els = soup.select(
                'table tbody tr, .entry-content li, .content li, '
                '.wp-block-list li, .school-directory li'
            )

        if not school_els:
            # Try alternative page structure -- ACCS uses WP
            content = soup.select_one('.entry-content, .page-content, main')
            if content:
                # Look for structured school data in divs or sections
                sections = content.select('div.school, section, .et_pb_text_inner')
                for section in sections:
                    school = _parse_section(section)
                    if school and school.get('name'):
                        schools.append(school)
                        if limit and len(schools) >= limit:
                            break

        for el in school_els:
            if limit and len(schools) >= limit:
                break
            school = _parse_school_element(el)
            if school and school.get('name'):
                schools.append(school)

        # Check for state-by-state pages
        state_links = soup.select('a[href*="state"], a[href*="find-a-school"]')
        visited = {CONF['search_url']}
        for link in state_links:
            if limit and len(schools) >= limit:
                break
            href = link.get('href', '')
            if not href or href in visited:
                continue
            if not href.startswith('http'):
                href = CONF['base_url'] + href
            if href in visited:
                continue
            visited.add(href)
            try:
                state_soup = session.get_soup(href)
                state_els = state_soup.select(
                    '.school-listing, .school-card, article, '
                    '.school-item, table tbody tr, .directory-item, li'
                )
                for el in state_els:
                    if limit and len(schools) >= limit:
                        break
                    school = _parse_school_element(el)
                    if school and school.get('name'):
                        if not any(s['name'] == school['name'] for s in schools):
                            schools.append(school)
            except Exception:
                continue

        # Pagination
        page = 2
        while True:
            next_link = soup.select_one('a.next, a[rel="next"], .pagination .next a')
            if not next_link:
                break
            next_url = next_link.get('href', '')
            if not next_url or next_url in visited:
                break
            if not next_url.startswith('http'):
                next_url = CONF['base_url'] + next_url
            visited.add(next_url)
            try:
                soup = session.get_soup(next_url)
                page_els = soup.select(
                    '.school-listing, .school-card, .directory-entry, '
                    '.school-item, table tbody tr'
                )
                if not page_els:
                    break
                for el in page_els:
                    if limit and len(schools) >= limit:
                        break
                    school = _parse_school_element(el)
                    if school and school.get('name'):
                        schools.append(school)
                page += 1
                if page > 30:
                    break
            except Exception:
                break

    except Exception as e:
        logger.warning(f"Error scraping ACCS directory: {e}")

    return schools


def _parse_section(section: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """Parse a school from a content section on the ACCS directory."""
    try:
        heading = section.select_one('h2, h3, h4, strong')
        if not heading:
            return None
        name = clean_text(heading.get_text())
        if not name or len(name) < 3:
            return None

        text = clean_text(section.get_text())

        city = ''
        state = ''
        loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', text)
        if loc_match:
            potential_city = loc_match.group(1).strip()
            if potential_city.lower() != name.lower():
                city = potential_city
                state = loc_match.group(2)

        phone = extract_phone(text) or ''

        website = ''
        for a in section.select('a[href^="http"]'):
            href = a.get('href', '')
            if 'classicalchristian.org' not in href and 'accsedu.org' not in href:
                website = href
                break

        email = ''
        email_el = section.select_one('[href^="mailto:"]')
        if email_el:
            email = extract_email(email_el.get('href', '')) or ''

        return {
            'name': name, 'city': city, 'state': state,
            'address': '', 'zip_code': '',
            'phone': phone, 'website': website, 'email': email,
            'enrollment': None,
            'grade_low': '', 'grade_high': '',
            'affiliation': 'Classical Christian',
            'accreditation': 'ACCS',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': '', 'leader_title': '',
            'detail_url': '',
        }
    except Exception:
        return None


def _parse_school_element(el: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """Parse a school element from the ACCS directory."""
    try:
        name_el = el.select_one('h2, h3, h4, .school-name, a.title, strong, td:first-child')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None
        if name.lower() in ('school name', 'name', 'school', 'member schools', 'find a school'):
            return None

        city = ''
        state = ''
        zip_code = ''

        loc_el = el.select_one('.location, .address, .city-state, td:nth-child(2)')
        if loc_el:
            loc_text = clean_text(loc_el.get_text())
            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', loc_text)
            if loc_match:
                city = loc_match.group(1).strip()
                state = loc_match.group(2)
                zip_code = loc_match.group(3) or ''
        else:
            full_text = clean_text(el.get_text())
            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', full_text)
            if loc_match:
                potential_city = loc_match.group(1).strip()
                if potential_city.lower() != name.lower():
                    city = potential_city
                    state = loc_match.group(2)
                    zip_code = loc_match.group(3) or ''

        phone = ''
        phone_el = el.select_one('[href^="tel:"], .phone')
        if phone_el:
            phone = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        website = ''
        for a in el.select('a[href^="http"]'):
            href = a.get('href', '')
            if 'classicalchristian.org' not in href and 'accsedu.org' not in href:
                website = href
                break

        grades_text = ''
        grades_el = el.select_one('.grades, .grade-range')
        if grades_el:
            grades_text = grades_el.get_text()
        grade_low, grade_high = parse_grades(grades_text)

        enrollment = None
        enroll_el = el.select_one('.enrollment, .students')
        if enroll_el:
            enrollment = parse_enrollment(enroll_el.get_text())

        detail_url = ''
        link = name_el if name_el.name == 'a' else el.select_one('a[href]')
        if link and link.name == 'a':
            href = link.get('href', '')
            if href and not href.startswith('http'):
                href = CONF['base_url'] + href
            detail_url = href

        return {
            'name': name, 'city': city, 'state': state,
            'address': '', 'zip_code': zip_code,
            'phone': phone, 'website': website, 'email': '',
            'enrollment': enrollment,
            'grade_low': grade_low, 'grade_high': grade_high,
            'affiliation': 'Classical Christian',
            'accreditation': 'ACCS',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': '', 'leader_title': '',
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing ACCS school element: {e}")
        return None


def _scrape_detail_page(session: ScraperSession, url: str, school: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich from detail page."""
    if not url:
        return school
    try:
        soup = session.get_soup(url)

        if not school.get('phone'):
            phone_el = soup.select_one('[href^="tel:"], .phone')
            if phone_el:
                school['phone'] = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        if not school.get('email'):
            email_el = soup.select_one('[href^="mailto:"]')
            if email_el:
                school['email'] = extract_email(email_el.get('href', '')) or ''

        if not school.get('website'):
            for a in soup.select('a[href^="http"]'):
                href = a.get('href', '')
                if 'classicalchristian.org' not in href and 'accsedu.org' not in href:
                    school['website'] = href
                    break

        if not school.get('leader_name'):
            for label in ['headmaster', 'head of school', 'principal', 'director']:
                for el in soup.select('dt, strong, th, .label, h4'):
                    if label in el.get_text().lower():
                        val_el = el.find_next_sibling()
                        if val_el:
                            school['leader_name'] = clean_text(val_el.get_text())
                            school['leader_title'] = label.title()
                            break
                if school.get('leader_name'):
                    break

        if not school.get('enrollment'):
            page_text = soup.get_text()
            match = re.search(r'(\d{2,4})\s*students', page_text, re.IGNORECASE)
            if match:
                school['enrollment'] = parse_enrollment(match.group(0))

    except Exception as e:
        logger.debug(f"Error on ACCS detail page {url}: {e}")

    return school


def scrape_classical(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """Main ACCS/Classical scraper entry point."""
    logger.info("Starting Classical/ACCS scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('classical_accs', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])

    try:
        schools_data = _scrape_directory(session, limit=limit)
        logger.info(f"Classical: Found {len(schools_data)} schools total")

        for school_data in schools_data:
            try:
                stats['processed'] += 1

                if school_data.get('detail_url'):
                    school_data = _scrape_detail_page(session, school_data['detail_url'], school_data)

                existing = find_matching_school(
                    school_data['name'], school_data['city'], school_data['state'], conn=db_conn,
                )

                school_id = None
                if existing:
                    school_id = str(existing['id'])
                    update_school(school_id, school_data, conn=db_conn)
                    stats['updated'] += 1
                    stats['schools_updated'] += 1
                else:
                    school_id = insert_school(school_data, conn=db_conn)
                    stats['created'] += 1
                    stats['schools_created'] += 1

                if school_data.get('leader_name') and school_id:
                    name_parts = parse_name_parts(school_data['leader_name'])
                    existing_person = find_matching_person(
                        name_parts['first_name'], name_parts['last_name'],
                        school_data['name'], conn=db_conn,
                    )
                    person_data = {
                        'first_name': name_parts['first_name'],
                        'last_name': name_parts['last_name'],
                        'title': school_data.get('leader_title', 'Headmaster'),
                        'organization': school_data['name'],
                        'school_id': school_id,
                        'data_source': 'association_directory',
                    }
                    if existing_person:
                        update_person(str(existing_person['id']), person_data, conn=db_conn)
                        stats['people_updated'] += 1
                    else:
                        insert_person(person_data, conn=db_conn)
                        stats['people_created'] += 1

            except Exception as e:
                stats['errored'] += 1
                logger.error(f"Error processing Classical school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"Classical scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"Classical scraper complete: {stats}")
    return stats
