"""
NAPSEC + Learning Differences schools scraper.
Scrapes directories for schools serving students with learning differences.
~400 schools across the US.
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

logger = logging.getLogger('knock.scrapers.learning_diff')
CONF = ASSOCIATIONS['learning_diff']

DIRECTORY_SOURCES = [
    {
        'name': 'NAPSEC',
        'url': 'https://www.napsec.org/members',
        'alt_url': 'https://www.napsec.org/member-directory',
    },
    {
        'name': 'SmartKids',
        'url': 'https://www.smart-kids.org/school-directory',
    },
]


def _scrape_napsec(session: ScraperSession, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scrape the NAPSEC member directory."""
    schools = []

    for source in DIRECTORY_SOURCES:
        if limit and len(schools) >= limit:
            break

        for url in [source['url'], source.get('alt_url', '')]:
            if not url:
                continue
            if limit and len(schools) >= limit:
                break

            try:
                soup = session.get_soup(url)

                school_els = soup.select(
                    '.member-listing, .school-listing, .directory-entry, '
                    '.school-card, article, .views-row, '
                    '.member-item, .school-item, .directory-item'
                )

                if not school_els:
                    school_els = soup.select(
                        'table tbody tr, .entry-content li, .content li, '
                        '.wp-block-list li, .list-item'
                    )

                if not school_els:
                    # Try parsing from page content
                    content = soup.select_one('.entry-content, .page-content, main, #content')
                    if content:
                        # Look for school entries as blocks or divs
                        blocks = content.select('div.member, .et_pb_text_inner, .school-block, section')
                        for block in blocks:
                            school = _parse_content_block(block, source['name'])
                            if school and school.get('name'):
                                schools.append(school)
                                if limit and len(schools) >= limit:
                                    break

                for el in school_els:
                    if limit and len(schools) >= limit:
                        break
                    school = _parse_school_element(el, source['name'])
                    if school and school.get('name'):
                        # Avoid duplicates
                        if not any(s['name'] == school['name'] for s in schools):
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
                        base = url.rsplit('/', 1)[0]
                        next_url = base + '/' + next_url.lstrip('/')
                    try:
                        soup = session.get_soup(next_url)
                        page_els = soup.select(
                            '.member-listing, .school-listing, .directory-entry, '
                            '.school-card, article, .member-item, '
                            'table tbody tr, .list-item'
                        )
                        if not page_els:
                            break
                        for el in page_els:
                            if limit and len(schools) >= limit:
                                break
                            school = _parse_school_element(el, source['name'])
                            if school and school.get('name'):
                                if not any(s['name'] == school['name'] for s in schools):
                                    schools.append(school)
                        page += 1
                        if page > 20:
                            break
                    except Exception:
                        break

                if schools:
                    break  # Got results from this source, skip alt_url

            except Exception as e:
                logger.warning(f"Error scraping {source['name']} at {url}: {e}")

    return schools


def _parse_content_block(block: BeautifulSoup, source_name: str) -> Optional[Dict[str, Any]]:
    """Parse a school from a content block."""
    try:
        heading = block.select_one('h2, h3, h4, strong')
        if not heading:
            return None
        name = clean_text(heading.get_text())
        if not name or len(name) < 3:
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
            if 'napsec.org' not in href and 'smart-kids.org' not in href:
                website = href
                break

        email = ''
        email_el = block.select_one('[href^="mailto:"]')
        if email_el:
            email = extract_email(email_el.get('href', '')) or ''

        # Look for specializations
        tags = list(CONF['tags'])
        specializations = ['dyslexia', 'adhd', 'autism', 'learning disabilities',
                          'emotional', 'behavioral', 'speech', 'language']
        text_lower = text.lower()
        for spec in specializations:
            if spec in text_lower:
                tags.append(spec)

        return {
            'name': name, 'city': city, 'state': state,
            'address': '', 'zip_code': '',
            'phone': phone, 'website': website, 'email': email,
            'enrollment': None,
            'grade_low': '', 'grade_high': '',
            'affiliation': 'Special Education',
            'accreditation': source_name,
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': tags,
            'leader_name': '', 'leader_title': '',
            'detail_url': '',
        }
    except Exception:
        return None


def _parse_school_element(el: BeautifulSoup, source_name: str) -> Optional[Dict[str, Any]]:
    """Parse a school element from the directory."""
    try:
        name_el = el.select_one('h2, h3, h4, .school-name, a.title, strong, td:first-child')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None
        if name.lower() in ('school name', 'name', 'school', 'member', 'members'):
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
            if 'napsec.org' not in href and 'smart-kids.org' not in href:
                website = href
                break

        email = ''
        email_el = el.select_one('[href^="mailto:"]')
        if email_el:
            email = extract_email(email_el.get('href', '')) or ''

        grades_text = ''
        grades_el = el.select_one('.grades, .grade-range, .ages')
        if grades_el:
            grades_text = grades_el.get_text()
        grade_low, grade_high = parse_grades(grades_text)

        # Specializations
        tags = list(CONF['tags'])
        spec_el = el.select_one('.specializations, .services, .programs-served')
        if spec_el:
            spec_text = spec_el.get_text().lower()
            for spec in ['dyslexia', 'adhd', 'autism', 'learning disabilities', 'emotional', 'behavioral']:
                if spec in spec_text:
                    tags.append(spec)

        # Boarding option
        if 'boarding' in clean_text(el.get_text()).lower():
            tags.append('boarding')

        leader_name = ''
        leader_title = ''
        leader_el = el.select_one('.director, .principal, .head')
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
            'address': '', 'zip_code': zip_code,
            'phone': phone, 'website': website, 'email': email,
            'enrollment': None,
            'grade_low': grade_low, 'grade_high': grade_high,
            'affiliation': 'Special Education',
            'accreditation': source_name,
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': tags,
            'leader_name': leader_name, 'leader_title': leader_title,
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing learning diff school element: {e}")
        return None


def scrape_learning_diff(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """Main NAPSEC/Learning Differences scraper entry point."""
    logger.info("Starting Learning Differences scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('learning_diff_napsec', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])

    try:
        schools_data = _scrape_napsec(session, limit=limit)
        logger.info(f"Learning Diff: Found {len(schools_data)} schools total")

        for school_data in schools_data:
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

            except Exception as e:
                stats['errored'] += 1
                logger.error(f"Error processing LD school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"Learning Diff scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"Learning Diff scraper complete: {stats}")
    return stats
