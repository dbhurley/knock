"""
AWSNA (Association of Waldorf Schools of North America) scraper.
Scrapes the Waldorf/Steiner school directory at waldorfeducation.org.
~160 member schools.
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

logger = logging.getLogger('knock.scrapers.waldorf')
CONF = ASSOCIATIONS['waldorf']


def _scrape_directory(session: ScraperSession, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scrape the AWSNA Find-a-School directory."""
    schools = []

    try:
        soup = session.get_soup(CONF['search_url'])

        # AWSNA typically lists all schools on a single page or by region
        school_els = soup.select(
            '.school-listing, .school-card, .directory-entry, '
            '.member-school, article, .views-row, '
            '.school-item, .wp-block-group'
        )

        if not school_els:
            # Try table rows or list items
            school_els = soup.select('table tbody tr, .entry-content li, .school-list li')

        if not school_els:
            # Try to parse from a map or list format
            content = soup.select_one('.entry-content, .page-content, main, #content')
            if content:
                # Look for headings that might be school names
                headings = content.select('h3, h4, h5')
                for heading in headings:
                    name = clean_text(heading.get_text())
                    if name and len(name) > 5:
                        school = _build_school_from_heading(heading, name)
                        if school:
                            schools.append(school)
                            if limit and len(schools) >= limit:
                                break

        for el in school_els:
            if limit and len(schools) >= limit:
                break
            school = _parse_school_element(el)
            if school and school.get('name'):
                schools.append(school)

        # Check for additional pages by region
        region_links = soup.select('a[href*="region"], a[href*="state"], .region-link')
        for link in region_links:
            if limit and len(schools) >= limit:
                break
            href = link.get('href', '')
            if not href:
                continue
            if not href.startswith('http'):
                href = CONF['base_url'] + href
            try:
                region_soup = session.get_soup(href)
                region_els = region_soup.select(
                    '.school-listing, .school-card, article, '
                    '.school-item, table tbody tr, li'
                )
                for el in region_els:
                    if limit and len(schools) >= limit:
                        break
                    school = _parse_school_element(el)
                    if school and school.get('name'):
                        # Avoid duplicates
                        if not any(s['name'] == school['name'] for s in schools):
                            schools.append(school)
            except Exception:
                continue

    except Exception as e:
        logger.warning(f"Error scraping AWSNA directory: {e}")

    return schools


def _build_school_from_heading(heading: BeautifulSoup, name: str) -> Optional[Dict[str, Any]]:
    """Build a school dict from a heading element and its siblings."""
    try:
        city = ''
        state = ''
        phone = ''
        website = ''

        # Look at next siblings for location/contact info
        sibling = heading.find_next_sibling()
        checked = 0
        while sibling and checked < 5:
            text = clean_text(sibling.get_text())

            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})', text)
            if loc_match and not city:
                city = loc_match.group(1).strip()
                state = loc_match.group(2)

            if not phone:
                phone = extract_phone(text) or ''

            link = sibling.select_one('a[href^="http"]')
            if link and not website:
                href = link.get('href', '')
                if 'waldorfeducation.org' not in href:
                    website = href

            sibling = sibling.find_next_sibling()
            checked += 1

        return {
            'name': name, 'city': city, 'state': state,
            'address': '', 'zip_code': '',
            'phone': phone, 'website': website, 'email': '',
            'enrollment': None,
            'grade_low': '', 'grade_high': '',
            'affiliation': 'Waldorf',
            'accreditation': 'AWSNA',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': '', 'leader_title': '',
            'detail_url': '',
        }
    except Exception:
        return None


def _parse_school_element(el: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """Parse a school element from the AWSNA directory."""
    try:
        name_el = el.select_one('h2, h3, h4, .school-name, a.title, strong, td:first-child')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None
        if name.lower() in ('school', 'name', 'school name', 'member schools'):
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
            if 'waldorfeducation.org' not in href and href:
                website = href
                break

        grades_text = ''
        grades_el = el.select_one('.grades, .grade-range')
        if grades_el:
            grades_text = grades_el.get_text()
        grade_low, grade_high = parse_grades(grades_text)

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
            'enrollment': None,
            'grade_low': grade_low, 'grade_high': grade_high,
            'affiliation': 'Waldorf',
            'accreditation': 'AWSNA',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': '', 'leader_title': '',
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing AWSNA school element: {e}")
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
                if 'waldorfeducation.org' not in href:
                    school['website'] = href
                    break

        if not school.get('leader_name'):
            for label in ['faculty chair', 'administrator', 'lead teacher', 'director', 'head']:
                for el in soup.select('dt, strong, th, .label'):
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
        logger.debug(f"Error on Waldorf detail page {url}: {e}")

    return school


def scrape_waldorf(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """Main AWSNA/Waldorf scraper entry point."""
    logger.info("Starting Waldorf/AWSNA scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('waldorf_awsna', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])

    try:
        schools_data = _scrape_directory(session, limit=limit)
        logger.info(f"Waldorf: Found {len(schools_data)} schools total")

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
                        'title': school_data.get('leader_title', 'Faculty Chair'),
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
                logger.error(f"Error processing Waldorf school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"Waldorf scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"Waldorf scraper complete: {stats}")
    return stats
