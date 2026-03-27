"""
AMS (American Montessori Society) + AMI scraper.
Scrapes Montessori school directories.
~1,300 AMS member schools plus AMI-affiliated programs.
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

logger = logging.getLogger('knock.scrapers.montessori')
CONF = ASSOCIATIONS['montessori']

US_STATES_LIST = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
]


def _search_ams_by_state(session: ScraperSession, state: str) -> List[Dict[str, Any]]:
    """Search AMS Find-a-School directory by state."""
    schools = []

    # Try the AMS search page
    search_url = f"{CONF['search_url']}?state={state}"
    try:
        soup = session.get_soup(search_url)

        school_els = soup.select(
            '.school-result, .school-card, .search-result, '
            '.school-listing, .views-row, article.school'
        )

        if not school_els:
            school_els = soup.select('.result-item, .directory-item, .card')

        for el in school_els:
            school = _parse_ams_element(el, state)
            if school and school.get('name'):
                schools.append(school)

        # Pagination
        page = 2
        while len(school_els) >= 20:
            next_url = f"{search_url}&page={page}"
            try:
                soup = session.get_soup(next_url)
                school_els = soup.select(
                    '.school-result, .school-card, .search-result, '
                    '.school-listing, .views-row, .result-item, .card'
                )
                if not school_els:
                    break
                for el in school_els:
                    school = _parse_ams_element(el, state)
                    if school and school.get('name'):
                        schools.append(school)
                page += 1
            except Exception:
                break

    except Exception as e:
        logger.warning(f"Error searching AMS for state {state}: {e}")

    # Also try the API endpoint
    if not schools:
        try:
            api_url = CONF.get('api_url', f"{CONF['base_url']}/api/schoolSearch")
            resp = session.post(api_url, json={
                'state': state,
                'country': 'US',
                'pageSize': 100,
            })
            if resp.status_code == 200:
                data = resp.json()
                results = data.get('results', data.get('schools', []))
                for item in results:
                    school = _parse_api_result(item, state)
                    if school and school.get('name'):
                        schools.append(school)
        except Exception as e:
            logger.debug(f"AMS API not available: {e}")

    return schools


def _parse_ams_element(el: BeautifulSoup, default_state: str) -> Optional[Dict[str, Any]]:
    """Parse a school element from AMS search results."""
    try:
        name_el = el.select_one('h2, h3, h4, .school-name, .name, a.title, strong')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None

        city = ''
        state = default_state
        zip_code = ''
        address = ''

        loc_el = el.select_one('.location, .address, .city-state')
        if loc_el:
            loc_text = clean_text(loc_el.get_text())
            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', loc_text)
            if loc_match:
                city = loc_match.group(1).strip()
                state = loc_match.group(2)
                zip_code = loc_match.group(3) or ''
            # Address
            addr_match = re.match(r'(\d+.+?),\s*(.+?),\s*([A-Z]{2})', loc_text)
            if addr_match:
                address = addr_match.group(1).strip()
                city = addr_match.group(2).strip()
                state = addr_match.group(3)

        phone = ''
        phone_el = el.select_one('[href^="tel:"], .phone')
        if phone_el:
            phone = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        website = ''
        for a in el.select('a[href^="http"]'):
            href = a.get('href', '')
            if 'amshq.org' not in href and href:
                website = href
                break

        email = ''
        email_el = el.select_one('[href^="mailto:"]')
        if email_el:
            email = extract_email(email_el.get('href', '')) or ''

        grades_text = ''
        grades_el = el.select_one('.grades, .grade-range, .age-range')
        if grades_el:
            grades_text = grades_el.get_text()
        grade_low, grade_high = parse_grades(grades_text)

        # AMS often shows age range instead of grades
        if not grade_low:
            age_el = el.select_one('.ages, .age-range')
            if age_el:
                age_text = age_el.get_text()
                age_match = re.search(r'(\d+)\s*(?:months?|mo)?\s*[-\u2013]\s*(\d+)', age_text)
                if age_match:
                    low_age = int(age_match.group(1))
                    if low_age <= 3:
                        grade_low = 'PK'
                    elif low_age <= 5:
                        grade_low = 'K'

        enrollment = None
        enroll_el = el.select_one('.enrollment, .students')
        if enroll_el:
            enrollment = parse_enrollment(enroll_el.get_text())

        # Accreditation level
        accred_el = el.select_one('.accreditation, .ams-level, .credential')
        accreditation = 'AMS'
        if accred_el:
            accred_text = clean_text(accred_el.get_text())
            if 'ami' in accred_text.lower():
                accreditation = 'AMS/AMI'

        leader_name = ''
        leader_title = ''
        leader_el = el.select_one('.head-of-school, .director, .principal')
        if leader_el:
            leader_text = clean_text(leader_el.get_text())
            if ':' in leader_text:
                parts = leader_text.split(':', 1)
                leader_title = parts[0].strip()
                leader_name = parts[1].strip()
            else:
                leader_name = leader_text
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
            'phone': phone, 'website': website, 'email': email,
            'enrollment': enrollment,
            'grade_low': grade_low, 'grade_high': grade_high,
            'affiliation': 'Montessori',
            'accreditation': accreditation,
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': leader_name, 'leader_title': leader_title,
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing AMS school element: {e}")
        return None


def _parse_api_result(item: Dict[str, Any], default_state: str) -> Optional[Dict[str, Any]]:
    """Parse an AMS API JSON result."""
    try:
        name = item.get('name', item.get('schoolName', ''))
        if not name:
            return None
        return {
            'name': clean_text(name),
            'city': item.get('city', ''),
            'state': item.get('state', default_state),
            'address': item.get('address', ''),
            'zip_code': str(item.get('zip', item.get('zipCode', ''))),
            'phone': extract_phone(str(item.get('phone', ''))) or '',
            'website': item.get('website', ''),
            'email': item.get('email', ''),
            'enrollment': item.get('enrollment'),
            'grade_low': '', 'grade_high': '',
            'affiliation': 'Montessori',
            'accreditation': 'AMS',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': item.get('headOfSchool', item.get('director', '')),
            'leader_title': 'Director',
            'detail_url': '',
        }
    except Exception:
        return None


def _scrape_detail_page(session: ScraperSession, url: str, school: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich school data from detail page."""
    if not url:
        return school
    try:
        soup = session.get_soup(url)

        if not school.get('phone'):
            phone_el = soup.select_one('[href^="tel:"], .phone')
            if phone_el:
                school['phone'] = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        if not school.get('website'):
            for a in soup.select('a[href^="http"]'):
                href = a.get('href', '')
                if 'amshq.org' not in href and 'amiusa.org' not in href:
                    school['website'] = href
                    break

        if not school.get('email'):
            email_el = soup.select_one('[href^="mailto:"]')
            if email_el:
                school['email'] = extract_email(email_el.get('href', '')) or ''

        # Look for Montessori program levels
        for el in soup.select('.program-level, .montessori-level, .credential-level'):
            tag = clean_text(el.get_text()).lower()
            if tag and tag not in school['tags']:
                school['tags'].append(tag)

        if not school.get('leader_name'):
            for label in ['director', 'head of school', 'principal', 'administrator']:
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
        logger.debug(f"Error on Montessori detail page {url}: {e}")

    return school


def scrape_montessori(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """Main AMS/Montessori scraper entry point."""
    logger.info("Starting Montessori/AMS scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('montessori_ams', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])
    total_scraped = 0

    try:
        for state in US_STATES_LIST:
            if limit and total_scraped >= limit:
                break

            logger.info(f"Montessori: Searching state {state}...")
            schools = _search_ams_by_state(session, state)
            logger.info(f"Montessori: Found {len(schools)} schools in {state}")

            for school_data in schools:
                if limit and total_scraped >= limit:
                    break

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
                    logger.error(f"Error processing Montessori school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"Montessori scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"Montessori scraper complete: {stats}")
    return stats
