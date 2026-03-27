"""
NCEA (National Catholic Educational Association) scraper.
Scrapes Catholic school directories.
~5,900 Catholic schools across the US.
"""

import logging
import re
import time
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
    create_sync_log, complete_sync_log, fetch_all,
)

logger = logging.getLogger('knock.scrapers.catholic')
CONF = ASSOCIATIONS['catholic']

# Catholic diocese directories often organize by state/diocese
DIRECTORY_URLS = [
    "https://www.privateschoolreview.com/catholic",
    "https://www.catholicschoolsguide.org/find-a-school/",
    "https://www.ncea.org/NCEA/Proclaim/Catholic_School_Data/NCEA/Proclaim/Catholic_School_Data/Catholic_School_Data.aspx",
]

US_STATES_LIST = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
]


def _search_state_directory(session: ScraperSession, state: str) -> List[Dict[str, Any]]:
    """Search for Catholic schools in a given state via directory sites."""
    schools = []

    # Try the private school review Catholic directory by state
    url = f"https://www.privateschoolreview.com/catholic/{state.lower()}"
    try:
        soup = session.get_soup(url)

        # Parse school listings
        rows = soup.select('table.schools tr, .school-row, .listing-row')
        if not rows:
            rows = soup.select('.school-list li, .school-listing, article')

        for row in rows:
            school = _parse_listing_row(row, state)
            if school and school.get('name'):
                schools.append(school)

        # Paginate
        page = 2
        while True:
            next_link = soup.select_one('a.next, a[rel="next"], .pagination a:last-child')
            if not next_link:
                break
            next_url = next_link.get('href', '')
            if not next_url or 'javascript' in next_url:
                break
            if not next_url.startswith('http'):
                next_url = f"https://www.privateschoolreview.com{next_url}"
            try:
                soup = session.get_soup(next_url)
                rows = soup.select('table.schools tr, .school-row, .listing-row, .school-list li')
                if not rows:
                    break
                for row in rows:
                    school = _parse_listing_row(row, state)
                    if school and school.get('name'):
                        schools.append(school)
                page += 1
                if page > 20:
                    break
            except Exception:
                break

    except Exception as e:
        logger.warning(f"Error searching Catholic schools in {state}: {e}")

    return schools


def _parse_listing_row(row: BeautifulSoup, default_state: str) -> Optional[Dict[str, Any]]:
    """Parse a school listing row from the directory."""
    try:
        name_el = row.select_one('a, h3, h4, .school-name, td:first-child')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None
        # Filter out header rows
        if name.lower() in ('school name', 'name', 'school'):
            return None

        # Location parsing
        city = ''
        state = default_state
        zip_code = ''
        address = ''

        location_el = row.select_one('.location, .city, td:nth-child(2)')
        if location_el:
            loc_text = clean_text(location_el.get_text())
            loc_match = re.match(r'(.+?),\s*([A-Z]{2})\s*(\d{5})?', loc_text)
            if loc_match:
                city = loc_match.group(1).strip()
                state = loc_match.group(2)
                zip_code = loc_match.group(3) or ''
            else:
                city = loc_text.split(',')[0].strip() if ',' in loc_text else loc_text

        # Grades
        grades_text = ''
        grades_el = row.select_one('.grades, td:nth-child(3)')
        if grades_el:
            grades_text = grades_el.get_text()
        grade_low, grade_high = parse_grades(grades_text)

        # Enrollment
        enrollment = None
        enroll_el = row.select_one('.enrollment, .students, td:nth-child(4)')
        if enroll_el:
            enrollment = parse_enrollment(enroll_el.get_text())

        # Detail link
        detail_url = ''
        link = row.select_one('a[href]')
        if link:
            href = link.get('href', '')
            if href and not href.startswith('http'):
                href = f"https://www.privateschoolreview.com{href}"
            detail_url = href

        # Phone
        phone = ''
        phone_el = row.select_one('[href^="tel:"], .phone')
        if phone_el:
            phone = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        return {
            'name': name,
            'city': city,
            'state': state,
            'address': address,
            'zip_code': zip_code,
            'phone': phone,
            'website': '',
            'email': '',
            'enrollment': enrollment,
            'grade_low': grade_low,
            'grade_high': grade_high,
            'affiliation': 'Catholic',
            'accreditation': 'NCEA',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': CONF['tags'],
            'leader_name': '',
            'leader_title': '',
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing Catholic school row: {e}")
        return None


def _scrape_detail_page(session: ScraperSession, url: str, school: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich school data from its detail page."""
    if not url:
        return school

    try:
        soup = session.get_soup(url)

        # Phone
        if not school.get('phone'):
            phone_el = soup.select_one('[href^="tel:"], .phone, .phone-number')
            if phone_el:
                school['phone'] = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        # Website
        if not school.get('website'):
            for a in soup.select('a[href^="http"]'):
                href = a.get('href', '')
                if 'privateschoolreview' not in href and 'ncea' not in href:
                    school['website'] = href
                    break

        # Email
        if not school.get('email'):
            email_el = soup.select_one('[href^="mailto:"]')
            if email_el:
                school['email'] = extract_email(email_el.get('href', '')) or ''

        # Enrollment
        if not school.get('enrollment'):
            for el in soup.select('td, .stat, .detail-value, dt + dd'):
                parent_text = ''
                prev = el.find_previous_sibling()
                if prev:
                    parent_text = prev.get_text().lower()
                if 'enrollment' in parent_text or 'student' in parent_text:
                    school['enrollment'] = parse_enrollment(el.get_text())
                    break

        # Principal / Head of School
        if not school.get('leader_name'):
            for label_text in ['principal', 'head of school', 'president', 'director']:
                for el in soup.select('dt, th, .label, strong'):
                    if label_text in el.get_text().lower():
                        value_el = el.find_next_sibling() or el.parent
                        if value_el:
                            leader_text = clean_text(value_el.get_text())
                            if leader_text and leader_text.lower() != label_text:
                                school['leader_name'] = leader_text
                                school['leader_title'] = label_text.title()
                                break
                if school.get('leader_name'):
                    break

        # Address
        if not school.get('address'):
            addr_el = soup.select_one('.address, [itemprop="streetAddress"], .street-address')
            if addr_el:
                school['address'] = clean_text(addr_el.get_text())

    except Exception as e:
        logger.debug(f"Error on Catholic detail page {url}: {e}")

    return school


def scrape_catholic(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """
    Main NCEA/Catholic scraper entry point.
    Iterates US states, scrapes school directories, deduplicates against DB.
    """
    logger.info("Starting Catholic/NCEA scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('catholic_ncea', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])
    total_scraped = 0

    try:
        for state in US_STATES_LIST:
            if limit and total_scraped >= limit:
                break

            logger.info(f"Catholic: Searching state {state}...")
            schools = _search_state_directory(session, state)
            logger.info(f"Catholic: Found {len(schools)} schools in {state}")

            for school_data in schools:
                if limit and total_scraped >= limit:
                    break

                try:
                    stats['processed'] += 1

                    if school_data.get('detail_url'):
                        school_data = _scrape_detail_page(session, school_data['detail_url'], school_data)

                    existing = find_matching_school(
                        school_data['name'],
                        school_data['city'],
                        school_data['state'],
                        conn=db_conn,
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
                            name_parts['first_name'],
                            name_parts['last_name'],
                            school_data['name'],
                            conn=db_conn,
                        )

                        person_data = {
                            'first_name': name_parts['first_name'],
                            'last_name': name_parts['last_name'],
                            'title': school_data.get('leader_title', 'Principal'),
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

                    total_scraped += 1

                except Exception as e:
                    stats['errored'] += 1
                    logger.error(f"Error processing Catholic school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"Catholic scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"Catholic scraper complete: {stats}")
    return stats
