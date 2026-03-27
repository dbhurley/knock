"""
Prizmah (Center for Jewish Day Schools) scraper.
Scrapes the Jewish day school directory at prizmah.org.
~300 member schools across the US.
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

logger = logging.getLogger('knock.scrapers.jewish')
CONF = ASSOCIATIONS['jewish']


def _scrape_directory(session: ScraperSession, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scrape the Prizmah school directory."""
    schools = []

    # Prizmah directory page
    try:
        soup = session.get_soup(CONF['search_url'])

        # Look for school listings on the directory page
        school_els = soup.select(
            '.school-listing, .directory-entry, .school-card, '
            '.member-school, article.school, .views-row, .node--school'
        )

        if not school_els:
            # Try broader selectors
            school_els = soup.select('.view-content .views-row, .directory-list li, .school-item')

        for el in school_els:
            if limit and len(schools) >= limit:
                break
            school = _parse_school_element(el)
            if school and school.get('name'):
                schools.append(school)

        # Check for pagination / load more
        page = 1
        while True:
            next_link = soup.select_one('li.pager-next a, a.next, .pagination .next a')
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
                    '.school-listing, .directory-entry, .school-card, '
                    '.member-school, .views-row, .node--school, '
                    '.directory-list li, .school-item'
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
        logger.warning(f"Error scraping Prizmah directory: {e}")

    # Also try alternative directory format
    if not schools:
        try:
            alt_url = CONF.get('directory_url', CONF['search_url'])
            if alt_url != CONF['search_url']:
                soup = session.get_soup(alt_url)
                school_els = soup.select(
                    '.school-listing, .directory-entry, .school-card, '
                    'table tr, .list-item, article'
                )
                for el in school_els:
                    if limit and len(schools) >= limit:
                        break
                    school = _parse_school_element(el)
                    if school and school.get('name'):
                        schools.append(school)
        except Exception as e:
            logger.debug(f"Alt directory also failed: {e}")

    return schools


def _parse_school_element(el: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """Parse a school element from the Prizmah directory."""
    try:
        name_el = el.select_one('h2, h3, h4, .school-name, .title, a.school-link, strong')
        if not name_el:
            return None

        name = clean_text(name_el.get_text())
        if not name or len(name) < 3:
            return None

        # Location
        city = ''
        state = ''
        zip_code = ''
        address = ''

        loc_el = el.select_one('.location, .address, .city-state, .field--address')
        if loc_el:
            loc_text = clean_text(loc_el.get_text())
            loc_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', loc_text)
            if loc_match:
                city = loc_match.group(1).strip()
                state = loc_match.group(2)
                zip_code = loc_match.group(3) or ''
            # Look for full address
            addr_match = re.match(r'(\d+.+?),\s*(.+?),\s*([A-Z]{2})\s*(\d{5})?', loc_text)
            if addr_match:
                address = addr_match.group(1).strip()
                city = addr_match.group(2).strip()
                state = addr_match.group(3)
                zip_code = addr_match.group(4) or ''

        # Contact info
        phone = ''
        phone_el = el.select_one('[href^="tel:"], .phone, .telephone')
        if phone_el:
            phone = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        website = ''
        for a in el.select('a[href^="http"]'):
            href = a.get('href', '')
            if 'prizmah.org' not in href and href:
                website = href
                break

        email = ''
        email_el = el.select_one('[href^="mailto:"], .email')
        if email_el:
            email = extract_email(email_el.get('href', '') or email_el.get_text()) or ''

        # Grades
        grades_text = ''
        grades_el = el.select_one('.grades, .grade-range, .field--grades')
        if grades_el:
            grades_text = grades_el.get_text()
        grade_low, grade_high = parse_grades(grades_text)

        # Enrollment
        enrollment = None
        enroll_el = el.select_one('.enrollment, .students, .field--enrollment')
        if enroll_el:
            enrollment = parse_enrollment(enroll_el.get_text())

        # Head of school
        leader_name = ''
        leader_title = ''
        leader_el = el.select_one('.head-of-school, .principal, .leader, .field--leader')
        if leader_el:
            leader_text = clean_text(leader_el.get_text())
            if ':' in leader_text:
                parts = leader_text.split(':', 1)
                leader_title = parts[0].strip()
                leader_name = parts[1].strip()
            else:
                leader_name = leader_text
                leader_title = 'Head of School'

        # Denomination/movement
        movement = ''
        movement_el = el.select_one('.denomination, .movement, .affiliation-detail, .field--denomination')
        if movement_el:
            movement = clean_text(movement_el.get_text())

        tags = list(CONF['tags'])
        if movement:
            tags.append(movement.lower())

        # Detail URL
        detail_url = ''
        link = el.select_one('a[href]')
        if link:
            href = link.get('href', '')
            if href and not href.startswith('http'):
                href = CONF['base_url'] + href
            detail_url = href

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
            'affiliation': f"Jewish - {movement}" if movement else 'Jewish',
            'accreditation': 'Prizmah',
            'school_type': 'private',
            'data_source': 'association_scrape',
            'tags': tags,
            'leader_name': leader_name,
            'leader_title': leader_title,
            'detail_url': detail_url,
        }

    except Exception as e:
        logger.debug(f"Error parsing Prizmah school element: {e}")
        return None


def _scrape_detail_page(session: ScraperSession, url: str, school: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich school data from its detail page."""
    if not url or 'prizmah.org' not in url:
        return school

    try:
        soup = session.get_soup(url)

        if not school.get('phone'):
            phone_el = soup.select_one('[href^="tel:"], .phone, .field--phone')
            if phone_el:
                school['phone'] = extract_phone(phone_el.get('href', '') or phone_el.get_text()) or ''

        if not school.get('website'):
            for a in soup.select('a[href^="http"]'):
                href = a.get('href', '')
                if 'prizmah.org' not in href:
                    school['website'] = href
                    break

        if not school.get('email'):
            email_el = soup.select_one('[href^="mailto:"]')
            if email_el:
                school['email'] = extract_email(email_el.get('href', '')) or ''

        if not school.get('enrollment'):
            for el in soup.select('.field-label, dt, strong, th'):
                if 'enrollment' in el.get_text().lower():
                    val_el = el.find_next_sibling() or el.parent
                    if val_el:
                        school['enrollment'] = parse_enrollment(val_el.get_text())
                    break

        if not school.get('leader_name'):
            for label in ['head of school', 'principal', 'director', 'rosh']:
                for el in soup.select('.field-label, dt, strong, th'):
                    if label in el.get_text().lower():
                        val_el = el.find_next_sibling() or el.parent
                        if val_el:
                            school['leader_name'] = clean_text(val_el.get_text())
                            school['leader_title'] = label.title()
                            break
                if school.get('leader_name'):
                    break

    except Exception as e:
        logger.debug(f"Error on Prizmah detail page {url}: {e}")

    return school


def scrape_jewish(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """Main Prizmah/Jewish scraper entry point."""
    logger.info("Starting Jewish/Prizmah scraper...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('jewish_prizmah', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])

    try:
        schools_data = _scrape_directory(session, limit=limit)
        logger.info(f"Jewish: Found {len(schools_data)} schools total")

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
                logger.error(f"Error processing Jewish school {school_data.get('name', '?')}: {e}")

    except Exception as e:
        logger.error(f"Jewish scraper fatal error: {e}")
        if sync_log_id:
            complete_sync_log(sync_log_id, stats, status='failed', error_details=str(e), conn=db_conn)
        raise
    finally:
        session.close()

    if sync_log_id:
        complete_sync_log(sync_log_id, stats, conn=db_conn)

    logger.info(f"Jewish scraper complete: {stats}")
    return stats
