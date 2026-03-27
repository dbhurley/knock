"""
ACSI (Association of Christian Schools International) scraper.
Scrapes the ACSI school search directory at acsi.org.
~2,400 member schools across the US.
"""

import logging
import time
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
    create_sync_log, complete_sync_log, fetch_all,
)

logger = logging.getLogger('knock.scrapers.acsi')
CONF = ASSOCIATIONS['acsi']


def _get_state_list() -> List[str]:
    """Return list of US state abbreviations to iterate."""
    return [
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
    ]


def _search_schools_by_state(session: ScraperSession, state: str) -> List[Dict[str, Any]]:
    """
    Search ACSI directory for schools in a given state.
    ACSI uses a search form that posts to their API endpoint.
    Falls back to HTML scraping if API is unavailable.
    """
    schools = []

    # Try the search page with state parameter
    search_url = f"{CONF['base_url']}/school-search?state={state}&country=US"
    try:
        soup = session.get_soup(search_url)

        # ACSI renders school cards in the search results
        school_cards = soup.select('.school-card, .school-result, .search-result-item, .school-listing')

        if not school_cards:
            # Try alternative selectors
            school_cards = soup.select('[data-school], .result-item, article.school')

        if not school_cards:
            # Fall back to looking for any structured listing
            school_cards = soup.select('.card, .listing-item, .directory-item')

        for card in school_cards:
            school = _parse_school_card(card, state)
            if school and school.get('name'):
                schools.append(school)

        # Check for pagination
        page = 2
        while len(school_cards) >= 20:
            next_url = f"{search_url}&page={page}"
            try:
                soup = session.get_soup(next_url)
                school_cards = soup.select('.school-card, .school-result, .search-result-item, .school-listing, .card, .listing-item')
                for card in school_cards:
                    school = _parse_school_card(card, state)
                    if school and school.get('name'):
                        schools.append(school)
                page += 1
            except Exception:
                break

    except Exception as e:
        logger.warning(f"Error searching ACSI for state {state}: {e}")

    # Also try the API endpoint if available
    if not schools:
        try:
            api_url = CONF.get('api_url', f"{CONF['base_url']}/api/school-search")
            resp = session.post(api_url, json={
                'state': state,
                'country': 'US',
                'pageSize': 100,
                'page': 1,
            })
            if resp.status_code == 200:
                data = resp.json()
                results = data.get('results', data.get('schools', data.get('data', [])))
                for item in results:
                    school = _parse_api_result(item, state)
                    if school and school.get('name'):
                        schools.append(school)
        except Exception as e:
            logger.debug(f"ACSI API not available for {state}: {e}")

    return schools


def _parse_school_card(card: BeautifulSoup, default_state: str) -> Optional[Dict[str, Any]]:
    """Parse a school card HTML element into a school dict."""
    try:
        # Extract school name - try various selectors
        name_el = (
            card.select_one('h3, h2, h4, .school-name, .name, [data-name]') or
            card.select_one('a[href*="school"]') or
            card.select_one('strong, b')
        )
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None

        # Extract location info
        location_el = card.select_one('.location, .address, .city-state, .school-location')
        city = ''
        state = default_state
        address = ''
        zip_code = ''

        if location_el:
            loc_text = clean_text(location_el.get_text())
            # Parse "City, ST ZIP" pattern
            import re
            loc_match = re.match(r'(.+?),\s*([A-Z]{2})\s*(\d{5})?', loc_text)
            if loc_match:
                city = loc_match.group(1).strip()
                state = loc_match.group(2)
                zip_code = loc_match.group(3) or ''
            else:
                city = loc_text.split(',')[0].strip() if ',' in loc_text else loc_text

        # Extract additional details
        phone = ''
        phone_el = card.select_one('.phone, [href^="tel:"], .contact-phone')
        if phone_el:
            phone_text = phone_el.get('href', '') or phone_el.get_text()
            phone = extract_phone(phone_text) or ''

        website = ''
        web_el = card.select_one('a[href*="http"]:not([href*="acsi.org"])')
        if web_el:
            website = web_el.get('href', '')

        email = ''
        email_el = card.select_one('a[href^="mailto:"], .email')
        if email_el:
            email = extract_email(email_el.get('href', '') or email_el.get_text()) or ''

        enrollment = None
        enroll_el = card.select_one('.enrollment, .students, .student-count')
        if enroll_el:
            enrollment = parse_enrollment(enroll_el.get_text())

        grades_text = ''
        grades_el = card.select_one('.grades, .grade-range, .grade-levels')
        if grades_el:
            grades_text = grades_el.get_text()
        grade_low, grade_high = parse_grades(grades_text)

        # Extract head of school / leadership
        leader_name = ''
        leader_title = ''
        leader_el = card.select_one('.head-of-school, .principal, .leader, .administrator')
        if leader_el:
            leader_text = clean_text(leader_el.get_text())
            # Often formatted as "Title: Name" or "Name, Title"
            if ':' in leader_text:
                parts = leader_text.split(':', 1)
                leader_title = parts[0].strip()
                leader_name = parts[1].strip()
            elif ',' in leader_text:
                parts = leader_text.split(',', 1)
                leader_name = parts[0].strip()
                leader_title = parts[1].strip()
            else:
                leader_name = leader_text

        # Detail page link
        detail_link = ''
        link_el = card.select_one('a[href*="school"]')
        if link_el:
            href = link_el.get('href', '')
            if href and not href.startswith('http'):
                href = CONF['base_url'] + href
            detail_link = href

        return {
            'name': name,
            'city': city,
            'state': state,
            'address': address,
            'zip_code': zip_code,
            'phone': phone,
            'website': website,
            'email': email,
            'enrollment': enrollment,
            'grade_low': grade_low,
            'grade_high': grade_high,
            'affiliation': 'Christian',
            'accreditation': 'ACSI',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': CONF['tags'],
            'leader_name': leader_name,
            'leader_title': leader_title,
            'detail_url': detail_link,
        }

    except Exception as e:
        logger.debug(f"Error parsing ACSI school card: {e}")
        return None


def _parse_api_result(item: Dict[str, Any], default_state: str) -> Optional[Dict[str, Any]]:
    """Parse an API JSON result into a school dict."""
    try:
        name = item.get('name', item.get('schoolName', item.get('Name', '')))
        if not name:
            return None

        return {
            'name': clean_text(name),
            'city': item.get('city', item.get('City', '')),
            'state': item.get('state', item.get('State', default_state)),
            'address': item.get('address', item.get('Address', '')),
            'zip_code': str(item.get('zip', item.get('zipCode', item.get('Zip', '')))),
            'phone': extract_phone(str(item.get('phone', item.get('Phone', '')))) or '',
            'website': item.get('website', item.get('Website', '')),
            'email': item.get('email', item.get('Email', '')),
            'enrollment': item.get('enrollment', item.get('Enrollment')),
            'grade_low': item.get('gradeLow', item.get('GradeLow', '')),
            'grade_high': item.get('gradeHigh', item.get('GradeHigh', '')),
            'affiliation': 'Christian',
            'accreditation': 'ACSI',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': CONF['tags'],
            'leader_name': item.get('headOfSchool', item.get('principal', '')),
            'leader_title': item.get('headTitle', 'Head of School'),
            'detail_url': '',
        }
    except Exception as e:
        logger.debug(f"Error parsing ACSI API result: {e}")
        return None


def _scrape_detail_page(session: ScraperSession, url: str, school: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape additional details from a school's detail page."""
    if not url:
        return school

    try:
        soup = session.get_soup(url)

        # Look for additional data on the detail page
        if not school.get('phone'):
            phone_el = soup.select_one('[href^="tel:"], .phone-number, .contact-phone')
            if phone_el:
                school['phone'] = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        if not school.get('email'):
            email_el = soup.select_one('[href^="mailto:"], .email-address')
            if email_el:
                school['email'] = extract_email(email_el.get('href', '') or email_el.get_text()) or ''

        if not school.get('website'):
            web_el = soup.select_one('a[href*="http"]:not([href*="acsi.org"])')
            if web_el:
                school['website'] = web_el.get('href', '')

        if not school.get('enrollment'):
            for el in soup.select('.detail-item, .info-item, dt, .stat'):
                text = el.get_text().lower()
                if 'enrollment' in text or 'students' in text:
                    val_el = el.find_next_sibling() or el.parent
                    if val_el:
                        school['enrollment'] = parse_enrollment(val_el.get_text())
                    break

        # Programs and extra tags
        program_els = soup.select('.program, .accreditation-badge, .feature-tag')
        for pel in program_els:
            tag = clean_text(pel.get_text()).lower()
            if tag and tag not in school['tags']:
                school['tags'].append(tag)

        # Leadership info
        if not school.get('leader_name'):
            leader_section = soup.select_one('.leadership, .administration, .staff-leadership')
            if leader_section:
                name_el = leader_section.select_one('h3, h4, .name, strong')
                title_el = leader_section.select_one('.title, .position, em')
                if name_el:
                    school['leader_name'] = clean_text(name_el.get_text())
                if title_el:
                    school['leader_title'] = clean_text(title_el.get_text())

    except Exception as e:
        logger.debug(f"Error scraping ACSI detail page {url}: {e}")

    return school


def scrape_acsi(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """
    Main ACSI scraper entry point.
    Iterates US states, scrapes school listings, deduplicates against DB.
    Returns stats dict with processed/created/updated/errored counts.
    """
    logger.info("Starting ACSI scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('acsi', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])
    states = _get_state_list()
    total_scraped = 0

    try:
        for state in states:
            if limit and total_scraped >= limit:
                break

            logger.info(f"ACSI: Searching state {state}...")
            schools = _search_schools_by_state(session, state)
            logger.info(f"ACSI: Found {len(schools)} schools in {state}")

            for school_data in schools:
                if limit and total_scraped >= limit:
                    break

                try:
                    stats['processed'] += 1

                    # Scrape detail page for more info
                    if school_data.get('detail_url'):
                        school_data = _scrape_detail_page(session, school_data['detail_url'], school_data)

                    # Check for existing school
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
                        logger.debug(f"Updated school: {school_data['name']} ({school_id})")
                    else:
                        school_id = insert_school(school_data, conn=db_conn)
                        stats['created'] += 1
                        stats['schools_created'] += 1
                        logger.debug(f"Created school: {school_data['name']} ({school_id})")

                    # Process leadership/people data
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
                            'title': school_data.get('leader_title', 'Head of School'),
                            'organization': school_data['name'],
                            'school_id': school_id,
                            'email': school_data.get('email', ''),
                            'phone': school_data.get('phone', ''),
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
                    logger.error(f"Error processing ACSI school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"ACSI scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"ACSI scraper complete: {stats}")
    return stats
