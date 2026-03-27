"""
Friends Council on Education (Quaker schools) scraper.
Scrapes the Quaker/Friends school directory at friendscouncil.org.
~80 member schools.
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

logger = logging.getLogger('knock.scrapers.quaker')
CONF = ASSOCIATIONS['quaker']


def _scrape_directory(session: ScraperSession, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scrape the Friends Council school directory."""
    schools = []

    try:
        soup = session.get_soup(CONF['search_url'])

        # FCE lists member schools on a single page or paginated list
        school_els = soup.select(
            '.school-listing, .member-school, .directory-entry, '
            '.school-card, article.school, .views-row, '
            '.school-item, .member-item'
        )

        if not school_els:
            # Try WordPress/generic selectors
            school_els = soup.select(
                '.entry-content li, .wp-block-list li, '
                'table tbody tr, .elementor-widget-container li'
            )

        if not school_els:
            # Try to find school data in the page content
            content = soup.select_one('.entry-content, .page-content, main, #content')
            if content:
                # Look for school names as links or strong text
                links = content.select('a[href]')
                for link in links:
                    text = clean_text(link.get_text())
                    if text and len(text) > 5 and 'school' in text.lower() or 'friends' in text.lower() or 'academy' in text.lower():
                        school = {
                            'name': text,
                            'city': '', 'state': '', 'address': '', 'zip_code': '',
                            'phone': '', 'website': link.get('href', ''), 'email': '',
                            'enrollment': None,
                            'grade_low': '', 'grade_high': '',
                            'affiliation': 'Quaker',
                            'accreditation': 'FCE',
                            'school_type': 'private',
                            'data_source': 'association_scrape',
                            'tags': list(CONF['tags']),
                            'leader_name': '', 'leader_title': '',
                            'detail_url': link.get('href', ''),
                        }
                        # Try to extract location from surrounding text
                        parent = link.parent
                        if parent:
                            parent_text = clean_text(parent.get_text())
                            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})', parent_text)
                            if loc_match:
                                school['city'] = loc_match.group(1).strip()
                                school['state'] = loc_match.group(2)
                        if school['name']:
                            schools.append(school)

        for el in school_els:
            if limit and len(schools) >= limit:
                break
            school = _parse_school_element(el)
            if school and school.get('name'):
                schools.append(school)

    except Exception as e:
        logger.warning(f"Error scraping FCE directory: {e}")

    return schools


def _parse_school_element(el: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """Parse a school element from the FCE directory."""
    try:
        name_el = el.select_one('h2, h3, h4, .school-name, a, strong, td:first-child')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None

        city = ''
        state = ''
        zip_code = ''

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
            if 'friendscouncil.org' not in href and href:
                website = href
                break

        email = ''
        email_el = el.select_one('[href^="mailto:"]')
        if email_el:
            email = extract_email(email_el.get('href', '')) or ''

        grades_text = ''
        grades_el = el.select_one('.grades, .grade-range')
        if grades_el:
            grades_text = grades_el.get_text()
        else:
            grade_match = re.search(r'(?:grades?|PK|K)\s*[-\u2013]\s*\d{1,2}', full_text, re.IGNORECASE)
            if grade_match:
                grades_text = grade_match.group(0)
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
            'phone': phone, 'website': website, 'email': email,
            'enrollment': None,
            'grade_low': grade_low, 'grade_high': grade_high,
            'affiliation': 'Quaker',
            'accreditation': 'FCE',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': '', 'leader_title': '',
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing FCE school element: {e}")
        return None


def _scrape_detail_page(session: ScraperSession, url: str, school: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich school data from its detail/school website page."""
    if not url:
        return school
    try:
        soup = session.get_soup(url)

        if not school.get('phone'):
            phone_el = soup.select_one('[href^="tel:"], .phone, .phone-number')
            if phone_el:
                school['phone'] = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        if not school.get('email'):
            email_el = soup.select_one('[href^="mailto:"]')
            if email_el:
                school['email'] = extract_email(email_el.get('href', '')) or ''

        if not school.get('city') or not school.get('state'):
            addr_el = soup.select_one('.address, [itemprop="address"], .contact-address')
            if addr_el:
                addr_text = clean_text(addr_el.get_text())
                loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', addr_text)
                if loc_match:
                    school['city'] = loc_match.group(1).strip()
                    school['state'] = loc_match.group(2)
                    school['zip_code'] = loc_match.group(3) or school.get('zip_code', '')

        if not school.get('leader_name'):
            for label in ['head of school', 'principal', 'director', 'clerk']:
                for el in soup.select('dt, strong, th, .label, h3, h4'):
                    if label in el.get_text().lower():
                        val_el = el.find_next_sibling() or el.parent
                        if val_el:
                            text = clean_text(val_el.get_text())
                            if text and text.lower() != label:
                                school['leader_name'] = text
                                school['leader_title'] = label.title()
                                break
                if school.get('leader_name'):
                    break

        if not school.get('enrollment'):
            page_text = soup.get_text()
            enroll_match = re.search(r'(\d{2,4})\s*students', page_text, re.IGNORECASE)
            if enroll_match:
                school['enrollment'] = parse_enrollment(enroll_match.group(0))

    except Exception as e:
        logger.debug(f"Error on FCE detail page {url}: {e}")

    return school


def scrape_quaker(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """Main FCE/Quaker scraper entry point."""
    logger.info("Starting Quaker/FCE scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('quaker_fce', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])

    try:
        schools_data = _scrape_directory(session, limit=limit)
        logger.info(f"Quaker: Found {len(schools_data)} schools total")

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
                logger.error(f"Error processing Quaker school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"Quaker scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"Quaker scraper complete: {stats}")
    return stats
