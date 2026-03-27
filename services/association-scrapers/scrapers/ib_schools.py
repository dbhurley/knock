"""
IBO (International Baccalaureate Organization) school scraper.
Scrapes the IB World Schools directory at ibo.org for US private IB schools.
~2,000 US IB schools (filtering for private).
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

logger = logging.getLogger('knock.scrapers.ib_schools')
CONF = ASSOCIATIONS['ib_schools']

US_STATES_LIST = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
]


def _search_ib_directory(session: ScraperSession, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Search the IBO school directory for US private schools."""
    schools = []

    # Try the IBO find-a-school page with US country filter
    try:
        search_url = f"{CONF['search_url']}?country=US"
        soup = session.get_soup(search_url)

        school_els = soup.select(
            '.school-result, .school-card, .search-result, '
            '.school-listing, .result-item, article.school'
        )

        if not school_els:
            school_els = soup.select('table tbody tr, .list-item, .card')

        for el in school_els:
            if limit and len(schools) >= limit:
                break
            school = _parse_school_element(el)
            if school and school.get('name'):
                schools.append(school)

        # Pagination
        page = 2
        while True:
            next_link = soup.select_one('a.next, a[rel="next"], .pagination .next a')
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
                    '.school-result, .school-card, .search-result, '
                    '.result-item, table tbody tr, .card'
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
                if page > 100:
                    break
            except Exception:
                break

    except Exception as e:
        logger.warning(f"Error scraping IBO directory: {e}")

    # Try API endpoint
    if not schools:
        try:
            api_url = CONF.get('api_url', f"{CONF['base_url']}/wp-json/ibo/v1/schools")
            for state in US_STATES_LIST:
                if limit and len(schools) >= limit:
                    break
                try:
                    resp = session.get(f"{api_url}?country=US&state={state}")
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data if isinstance(data, list) else data.get('results', data.get('schools', []))
                        for item in results:
                            school = _parse_api_result(item)
                            if school and school.get('name'):
                                # Filter for private schools
                                school_type = item.get('type', item.get('schoolType', '')).lower()
                                if 'private' in school_type or 'independent' in school_type or not school_type:
                                    schools.append(school)
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"IBO API not available: {e}")

    return schools


def _parse_school_element(el: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """Parse a school element from the IBO search results."""
    try:
        name_el = el.select_one('h2, h3, h4, .school-name, a.title, strong, td:first-child')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None
        if name.lower() in ('school name', 'name'):
            return None

        city = ''
        state = ''
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
        else:
            full_text = clean_text(el.get_text())
            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', full_text)
            if loc_match:
                potential_city = loc_match.group(1).strip()
                if potential_city.lower() != name.lower():
                    city = potential_city
                    state = loc_match.group(2)

        # IB programmes offered
        programmes = []
        prog_el = el.select_one('.programmes, .ib-programmes, .program-list')
        if prog_el:
            prog_text = clean_text(prog_el.get_text())
            for prog in ['PYP', 'MYP', 'DP', 'CP']:
                if prog in prog_text.upper():
                    programmes.append(f"IB {prog}")

        tags = list(CONF['tags']) + programmes

        phone = ''
        phone_el = el.select_one('[href^="tel:"], .phone')
        if phone_el:
            phone = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        website = ''
        for a in el.select('a[href^="http"]'):
            href = a.get('href', '')
            if 'ibo.org' not in href and href:
                website = href
                break

        detail_url = ''
        link = name_el if name_el.name == 'a' else el.select_one('a[href]')
        if link and link.name == 'a':
            href = link.get('href', '')
            if href and not href.startswith('http'):
                href = CONF['base_url'] + href
            detail_url = href

        grades_el = el.select_one('.grades, .grade-range')
        grade_low, grade_high = '', ''
        if grades_el:
            grade_low, grade_high = parse_grades(grades_el.get_text())

        return {
            'name': name, 'city': city, 'state': state,
            'address': address, 'zip_code': zip_code,
            'phone': phone, 'website': website, 'email': '',
            'enrollment': None,
            'grade_low': grade_low, 'grade_high': grade_high,
            'affiliation': 'IB',
            'accreditation': 'IBO',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': tags,
            'leader_name': '', 'leader_title': '',
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing IB school element: {e}")
        return None


def _parse_api_result(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse an IBO API JSON result."""
    try:
        name = item.get('name', item.get('schoolName', ''))
        if not name:
            return None

        programmes = []
        for prog in item.get('programmes', item.get('ibProgrammes', [])):
            if isinstance(prog, str):
                programmes.append(f"IB {prog}")
            elif isinstance(prog, dict):
                programmes.append(f"IB {prog.get('name', prog.get('code', ''))}")

        tags = list(CONF['tags']) + programmes

        return {
            'name': clean_text(name),
            'city': item.get('city', ''),
            'state': item.get('state', item.get('region', '')),
            'address': item.get('address', ''),
            'zip_code': str(item.get('zip', item.get('postalCode', ''))),
            'phone': extract_phone(str(item.get('phone', ''))) or '',
            'website': item.get('website', item.get('url', '')),
            'email': item.get('email', ''),
            'enrollment': item.get('enrollment'),
            'grade_low': '', 'grade_high': '',
            'affiliation': 'IB',
            'accreditation': 'IBO',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': tags,
            'leader_name': item.get('headOfSchool', item.get('principal', '')),
            'leader_title': 'Head of School',
            'detail_url': '',
        }
    except Exception:
        return None


def _scrape_detail_page(session: ScraperSession, url: str, school: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich from IBO school detail page."""
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
                if 'ibo.org' not in href:
                    school['website'] = href
                    break

        # IB programmes detail
        prog_section = soup.select_one('.programme-info, .ib-programmes, .programmes-offered')
        if prog_section:
            for prog in ['PYP', 'MYP', 'DP', 'CP']:
                if prog in prog_section.get_text().upper():
                    tag = f"IB {prog}"
                    if tag not in school['tags']:
                        school['tags'].append(tag)

        if not school.get('leader_name'):
            for label in ['head of school', 'principal', 'coordinator', 'director']:
                for el in soup.select('dt, strong, th, .label'):
                    if label in el.get_text().lower():
                        val_el = el.find_next_sibling()
                        if val_el:
                            school['leader_name'] = clean_text(val_el.get_text())
                            school['leader_title'] = label.title()
                            break
                if school.get('leader_name'):
                    break

    except Exception as e:
        logger.debug(f"Error on IB detail page {url}: {e}")

    return school


def scrape_ib_schools(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """Main IBO scraper entry point."""
    logger.info("Starting IB Schools scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('ib_schools', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])

    try:
        schools_data = _search_ib_directory(session, limit=limit)
        logger.info(f"IB: Found {len(schools_data)} schools total")

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
                        'title': school_data.get('leader_title', 'Head of School'),
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
                logger.error(f"Error processing IB school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"IB scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"IB Schools scraper complete: {stats}")
    return stats
