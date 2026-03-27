"""
AMCSUS (Association of Military Colleges and Schools) scraper.
Scrapes the military academy directory at amcsus.org.
~30 member schools.
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

logger = logging.getLogger('knock.scrapers.military')
CONF = ASSOCIATIONS['military']


def _scrape_directory(session: ScraperSession, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scrape the AMCSUS member schools directory."""
    schools = []

    try:
        soup = session.get_soup(CONF['search_url'])

        # AMCSUS is a small org, usually all schools on one page
        school_els = soup.select(
            '.member-school, .school-listing, .school-card, '
            '.directory-entry, article, .views-row, '
            '.school-item, .member-item'
        )

        if not school_els:
            school_els = soup.select(
                'table tbody tr, .entry-content li, .content li, '
                '.wp-block-list li, .list-item, .card'
            )

        if not school_els:
            # Try parsing WordPress page content
            content = soup.select_one('.entry-content, .page-content, main, #content')
            if content:
                # AMCSUS may use divs, sections, or grid items for each school
                blocks = content.select(
                    'div.school, .et_pb_module, .wp-block-column, '
                    '.elementor-widget-container, section, .school-block'
                )

                if not blocks:
                    # Try to find school entries as headings with following content
                    headings = content.select('h2, h3, h4')
                    for heading in headings:
                        name = clean_text(heading.get_text())
                        if name and len(name) > 5 and _looks_like_school_name(name):
                            school = _build_school_from_heading(heading, name)
                            if school:
                                schools.append(school)
                                if limit and len(schools) >= limit:
                                    break

                for block in blocks:
                    school = _parse_content_block(block)
                    if school and school.get('name'):
                        if not any(s['name'] == school['name'] for s in schools):
                            schools.append(school)
                    if limit and len(schools) >= limit:
                        break

                # Also check for linked school pages
                for link in content.select('a[href]'):
                    if limit and len(schools) >= limit:
                        break
                    text = clean_text(link.get_text())
                    if text and _looks_like_school_name(text):
                        href = link.get('href', '')
                        if href and 'amcsus.org' in href:
                            # This might be a detail page
                            school = {
                                'name': text,
                                'detail_url': href if href.startswith('http') else CONF['base_url'] + href,
                                'city': '', 'state': '', 'address': '', 'zip_code': '',
                                'phone': '', 'website': '', 'email': '',
                                'enrollment': None,
                                'grade_low': '', 'grade_high': '',
                                'affiliation': 'Military',
                                'accreditation': 'AMCSUS',
                                'school_type': 'private',
                                'data_source': 'association_scrape',
                                'tags': list(CONF['tags']),
                                'leader_name': '', 'leader_title': '',
                            }
                            if not any(s['name'] == school['name'] for s in schools):
                                schools.append(school)

        for el in school_els:
            if limit and len(schools) >= limit:
                break
            school = _parse_school_element(el)
            if school and school.get('name'):
                if not any(s['name'] == school['name'] for s in schools):
                    schools.append(school)

    except Exception as e:
        logger.warning(f"Error scraping AMCSUS directory: {e}")

    return schools


def _looks_like_school_name(text: str) -> bool:
    """Heuristic check if text looks like a school/academy name."""
    keywords = ['academy', 'school', 'institute', 'college', 'military', 'preparatory', 'prep']
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def _build_school_from_heading(heading: BeautifulSoup, name: str) -> Optional[Dict[str, Any]]:
    """Build a school dict from a heading and its siblings."""
    try:
        city = ''
        state = ''
        phone = ''
        website = ''
        email = ''

        sibling = heading.find_next_sibling()
        checked = 0
        while sibling and checked < 8:
            text = clean_text(sibling.get_text())

            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', text)
            if loc_match and not city:
                city = loc_match.group(1).strip()
                state = loc_match.group(2)

            if not phone:
                phone = extract_phone(text) or ''

            for a in sibling.select('a[href^="http"]') if hasattr(sibling, 'select') else []:
                href = a.get('href', '')
                if 'amcsus.org' not in href and not website:
                    website = href

            email_el = sibling.select_one('[href^="mailto:"]') if hasattr(sibling, 'select_one') else None
            if email_el and not email:
                email = extract_email(email_el.get('href', '')) or ''

            # Check if we've hit the next school heading
            if sibling.name in ('h2', 'h3', 'h4'):
                break

            sibling = sibling.find_next_sibling()
            checked += 1

        return {
            'name': name, 'city': city, 'state': state,
            'address': '', 'zip_code': '',
            'phone': phone, 'website': website, 'email': email,
            'enrollment': None,
            'grade_low': '', 'grade_high': '',
            'affiliation': 'Military',
            'accreditation': 'AMCSUS',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': '', 'leader_title': '',
            'detail_url': '',
        }
    except Exception:
        return None


def _parse_content_block(block: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """Parse a school from a content block."""
    try:
        heading = block.select_one('h2, h3, h4, strong')
        if not heading:
            return None
        name = clean_text(heading.get_text())
        if not name or len(name) < 3:
            return None
        if not _looks_like_school_name(name) and len(name) < 20:
            return None

        text = clean_text(block.get_text())
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
        for a in block.select('a[href^="http"]'):
            href = a.get('href', '')
            if 'amcsus.org' not in href:
                website = href
                break

        email = ''
        email_el = block.select_one('[href^="mailto:"]')
        if email_el:
            email = extract_email(email_el.get('href', '')) or ''

        # Military-specific tags
        tags = list(CONF['tags'])
        text_lower = text.lower()
        if 'boarding' in text_lower:
            tags.append('boarding')
        if 'jrotc' in text_lower:
            tags.append('jrotc')
        if 'coed' in text_lower or 'co-ed' in text_lower:
            tags.append('coed')
        elif 'boys' in text_lower or 'young men' in text_lower:
            tags.append('boys')

        grades_match = re.search(r'(?:grades?)\s*([\dPK]+)\s*[-\u2013]\s*(\d+)', text, re.IGNORECASE)
        grade_low, grade_high = '', ''
        if grades_match:
            grade_low = grades_match.group(1)
            grade_high = grades_match.group(2)

        return {
            'name': name, 'city': city, 'state': state,
            'address': '', 'zip_code': '',
            'phone': phone, 'website': website, 'email': email,
            'enrollment': None,
            'grade_low': grade_low, 'grade_high': grade_high,
            'affiliation': 'Military',
            'accreditation': 'AMCSUS',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': tags,
            'leader_name': '', 'leader_title': '',
            'detail_url': '',
        }
    except Exception:
        return None


def _parse_school_element(el: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """Parse a school element."""
    try:
        name_el = el.select_one('h2, h3, h4, .school-name, a.title, strong, td:first-child')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None
        if name.lower() in ('school name', 'name', 'member schools'):
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
            if 'amcsus.org' not in href:
                website = href
                break

        grades_el = el.select_one('.grades, .grade-range')
        grade_low, grade_high = '', ''
        if grades_el:
            grade_low, grade_high = parse_grades(grades_el.get_text())

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
            'affiliation': 'Military',
            'accreditation': 'AMCSUS',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': list(CONF['tags']),
            'leader_name': '', 'leader_title': '',
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing AMCSUS school element: {e}")
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
                if 'amcsus.org' not in href:
                    school['website'] = href
                    break

        if not school.get('city') or not school.get('state'):
            page_text = soup.get_text()
            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', page_text)
            if loc_match:
                school['city'] = loc_match.group(1).strip()
                school['state'] = loc_match.group(2)

        if not school.get('leader_name'):
            for label in ['commandant', 'superintendent', 'president', 'headmaster', 'director']:
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
            match = re.search(r'(\d{2,4})\s*(?:students|cadets)', page_text, re.IGNORECASE)
            if match:
                school['enrollment'] = parse_enrollment(match.group(0))

        # Grades
        if not school.get('grade_low'):
            page_text = soup.get_text()
            grades_match = re.search(r'(?:grades?)\s*([\dPK]+)\s*[-\u2013]\s*(\d+)', page_text, re.IGNORECASE)
            if grades_match:
                school['grade_low'] = grades_match.group(1)
                school['grade_high'] = grades_match.group(2)

    except Exception as e:
        logger.debug(f"Error on AMCSUS detail page {url}: {e}")

    return school


def scrape_military(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """Main AMCSUS/Military scraper entry point."""
    logger.info("Starting Military/AMCSUS scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('military_amcsus', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])

    try:
        schools_data = _scrape_directory(session, limit=limit)
        logger.info(f"Military: Found {len(schools_data)} schools total")

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
                        'title': school_data.get('leader_title', 'Superintendent'),
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
                logger.error(f"Error processing military school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"Military scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"Military scraper complete: {stats}")
    return stats
