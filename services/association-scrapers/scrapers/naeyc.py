"""
NAEYC (National Association for the Education of Young Children) scraper.
Scrapes the NAEYC accredited programs directory.
~6,500 accredited early childhood programs.
"""

import logging
import re
import json
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

logger = logging.getLogger('knock.scrapers.naeyc')
CONF = ASSOCIATIONS['naeyc']

US_STATES_LIST = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
]


def _search_by_state(session: ScraperSession, state: str) -> List[Dict[str, Any]]:
    """Search NAEYC accredited programs by state."""
    schools = []

    # Try the NAEYC accreditation search
    search_url = f"{CONF['search_url']}?state={state}"
    try:
        soup = session.get_soup(search_url)

        school_els = soup.select(
            '.program-result, .search-result, .accredited-program, '
            '.school-listing, .result-item, article, .views-row'
        )

        if not school_els:
            school_els = soup.select('table tbody tr, .list-item, .card')

        for el in school_els:
            school = _parse_program_element(el, state)
            if school and school.get('name'):
                schools.append(school)

        # Pagination
        page = 2
        while True:
            next_link = soup.select_one('a.next, a[rel="next"], .pager-next a')
            if not next_link:
                break
            next_url = next_link.get('href', '')
            if not next_url:
                break
            if not next_url.startswith('http'):
                next_url = CONF['base_url'] + next_url
            try:
                soup = session.get_soup(next_url)
                page_els = soup.select(
                    '.program-result, .search-result, .accredited-program, '
                    '.result-item, table tbody tr, .card'
                )
                if not page_els:
                    break
                for el in page_els:
                    school = _parse_program_element(el, state)
                    if school and school.get('name'):
                        schools.append(school)
                page += 1
                if page > 50:
                    break
            except Exception:
                break

    except Exception as e:
        logger.warning(f"Error searching NAEYC for state {state}: {e}")

    # Try API
    if not schools:
        try:
            api_url = CONF.get('api_url', f"{CONF['base_url']}/api/accreditation/search")
            resp = session.get(f"{api_url}?state={state}&pageSize=100")
            if resp.status_code == 200:
                data = resp.json()
                results = data.get('results', data.get('programs', []))
                for item in results:
                    school = _parse_api_result(item, state)
                    if school and school.get('name'):
                        schools.append(school)
        except Exception as e:
            logger.debug(f"NAEYC API not available: {e}")

    return schools


def _parse_program_element(el: BeautifulSoup, default_state: str) -> Optional[Dict[str, Any]]:
    """Parse a program element from the NAEYC directory."""
    try:
        name_el = el.select_one('h2, h3, h4, .program-name, .school-name, a.title, strong, td:first-child')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None
        if name.lower() in ('program name', 'name', 'program'):
            return None

        city = ''
        state = default_state
        zip_code = ''
        address = ''

        loc_el = el.select_one('.location, .address, .city-state, td:nth-child(2)')
        if loc_el:
            loc_text = clean_text(loc_el.get_text())
            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', loc_text)
            if loc_match:
                city = loc_match.group(1).strip()
                state = loc_match.group(2)
                zip_code = loc_match.group(3) or ''
            addr_match = re.match(r'(\d+.+?),\s*(.+?),\s*([A-Z]{2})', loc_text)
            if addr_match:
                address = addr_match.group(1)
                city = addr_match.group(2).strip()
                state = addr_match.group(3)

        phone = ''
        phone_el = el.select_one('[href^="tel:"], .phone')
        if phone_el:
            phone = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        website = ''
        for a in el.select('a[href^="http"]'):
            href = a.get('href', '')
            if 'naeyc.org' not in href and href:
                website = href
                break

        # Program type (center, school, family child care)
        program_type = ''
        type_el = el.select_one('.program-type, .type, .category')
        if type_el:
            program_type = clean_text(type_el.get_text())

        tags = list(CONF['tags'])
        if program_type:
            tags.append(program_type.lower())

        # Capacity/enrollment
        enrollment = None
        cap_el = el.select_one('.capacity, .enrollment, .children-served')
        if cap_el:
            enrollment = parse_enrollment(cap_el.get_text())

        # Ages served
        ages_el = el.select_one('.ages, .age-range, .ages-served')
        grade_low, grade_high = 'PK', 'PK'
        if ages_el:
            age_text = ages_el.get_text()
            if re.search(r'infant|birth|0', age_text, re.IGNORECASE):
                grade_low = 'PK'
            if re.search(r'kindergarten|5|6', age_text, re.IGNORECASE):
                grade_high = 'K'

        # Director
        leader_name = ''
        leader_title = ''
        leader_el = el.select_one('.director, .principal, .contact-name')
        if leader_el:
            leader_name = clean_text(leader_el.get_text())
            leader_title = 'Director'

        detail_url = ''
        link = name_el if name_el.name == 'a' else el.select_one('a[href]')
        if link and link.name == 'a':
            href = link.get('href', '')
            if href and not href.startswith('http'):
                href = CONF['base_url'] + href
            detail_url = href

        return {
            'name': name, 'city': city, 'state': state,
            'address': address, 'zip_code': zip_code,
            'phone': phone, 'website': website, 'email': '',
            'enrollment': enrollment,
            'grade_low': grade_low, 'grade_high': grade_high,
            'affiliation': 'Early Childhood',
            'accreditation': 'NAEYC',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': tags,
            'leader_name': leader_name, 'leader_title': leader_title,
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing NAEYC program element: {e}")
        return None


def _parse_api_result(item: Dict[str, Any], default_state: str) -> Optional[Dict[str, Any]]:
    """Parse a NAEYC API result."""
    try:
        name = item.get('name', item.get('programName', ''))
        if not name:
            return None
        return {
            'name': clean_text(name),
            'city': item.get('city', ''),
            'state': item.get('state', default_state),
            'address': item.get('address', ''),
            'zip_code': str(item.get('zip', '')),
            'phone': extract_phone(str(item.get('phone', ''))) or '',
            'website': item.get('website', ''),
            'email': item.get('email', ''),
            'enrollment': item.get('capacity', item.get('enrollment')),
            'grade_low': 'PK', 'grade_high': 'PK',
            'affiliation': 'Early Childhood',
            'accreditation': 'NAEYC',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': item.get('director', item.get('contactName', '')),
            'leader_title': 'Director',
            'detail_url': '',
        }
    except Exception:
        return None


def scrape_naeyc(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """Main NAEYC scraper entry point."""
    logger.info("Starting NAEYC scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('naeyc', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])
    total_scraped = 0

    try:
        for state in US_STATES_LIST:
            if limit and total_scraped >= limit:
                break

            logger.info(f"NAEYC: Searching state {state}...")
            programs = _search_by_state(session, state)
            logger.info(f"NAEYC: Found {len(programs)} programs in {state}")

            for school_data in programs:
                if limit and total_scraped >= limit:
                    break

                try:
                    stats['processed'] += 1

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
                            'title': school_data.get('leader_title', 'Director'),
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
                    logger.error(f"Error processing NAEYC program {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"NAEYC scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"NAEYC scraper complete: {stats}")
    return stats
