"""
ACSI (Association of Christian Schools International) scraper.
Scrapes NCES Private School Universe Survey data for ACSI member schools.
NCES PSS Association code 5 = ACSI. ~1,600 member schools across the US.
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

logger = logging.getLogger('knock.scrapers.acsi')
CONF = ASSOCIATIONS['acsi']

# NCES Private School Universe Survey search endpoint
NCES_BASE = 'https://nces.ed.gov/surveys/pss/privateschoolsearch'
NCES_LIST_URL = f'{NCES_BASE}/school_list.asp'
NCES_DETAIL_URL = f'{NCES_BASE}/school_detail.asp'
ACSI_ASSOCIATION_CODE = '5'  # NCES association code for ACSI


def _build_search_params(page: int = 1) -> Dict[str, str]:
    """Build NCES search query parameters for ACSI schools."""
    return {
        'Search': '1',
        'Association': ACSI_ASSOCIATION_CODE,
        'NumOfStudentsRange': 'more',
        'IncGrade': '-1',
        'LoGrade': '-1',
        'HiGrade': '-1',
        'SchoolPageNum': str(page),
    }


def _parse_nces_results_page(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Parse a NCES search results page into school dicts.

    Each result row has this HTML structure:
    <div class='resultRow'>
      <div>1.</div>
      <div>
        <a href="school_detail.asp?...&ID=XXXX">school name</a><br/>
        <span>123 Main St,&nbsp;City,&nbsp;ST&nbsp;ZIP</span>
      </div>
      <div>(555) 123-4567</div>
      <div>County Name</div>
      <div>500</div>
      <div>PK-12</div>
    </div>
    """
    schools = []
    rows = soup.select('.resultRow')

    for row in rows:
        try:
            divs = row.find_all('div', recursive=False)
            if len(divs) < 6:
                continue

            # div[0] = row number (e.g. "1.")
            # div[1] = name link + address span
            # div[2] = phone
            # div[3] = county
            # div[4] = students
            # div[5] = grades

            name_div = divs[1]
            link = name_div.find('a')
            if not link:
                continue

            name = clean_text(link.get_text())
            if not name or len(name) < 3:
                continue
            # NCES lowercases names with text-transform; title-case them
            # Also strip leading/trailing dashes and spaces
            name = re.sub(r'^[\s\-]+|[\s\-]+$', '', name).strip().title()

            # Extract NCES ID from link href
            href = link.get('href', '')
            nces_id = ''
            id_match = re.search(r'ID=([A-Za-z0-9]+)', href)
            if id_match:
                nces_id = id_match.group(1)

            # Parse address from span
            addr_span = name_div.find('span')
            address = ''
            city = ''
            state = ''
            zip_code = ''
            if addr_span:
                # Replace &nbsp; with spaces for parsing
                addr_text = addr_span.get_text().replace('\xa0', ' ').strip()
                # Pattern: "123 Main St, City, ST ZIP" or "123 Main St, City, ST ZIP-XXXX"
                addr_match = re.match(
                    r'(.+?),\s*([A-Za-z\s.]+?),\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)?$',
                    addr_text
                )
                if addr_match:
                    address = addr_match.group(1).strip()
                    city = addr_match.group(2).strip()
                    state = addr_match.group(3).strip()
                    zip_code = (addr_match.group(4) or '').strip()
                else:
                    # Fallback: try splitting by comma
                    parts = [p.strip() for p in addr_text.split(',')]
                    if len(parts) >= 2:
                        address = parts[0]
                        last_part = parts[-1].strip()
                        st_match = re.search(r'([A-Z]{2})\s*(\d{5})?', last_part)
                        if st_match:
                            state = st_match.group(1)
                            zip_code = st_match.group(2) or ''
                        if len(parts) >= 3:
                            city = parts[1].strip()
                        elif len(parts) == 2:
                            city = last_part.split()[0] if last_part else ''

            # Phone
            phone_text = clean_text(divs[2].get_text()) if len(divs) > 2 else ''
            phone = extract_phone(phone_text) or ''

            # County
            county = clean_text(divs[3].get_text()) if len(divs) > 3 else ''

            # Students (enrollment)
            enrollment_text = clean_text(divs[4].get_text()) if len(divs) > 4 else ''
            enrollment = parse_enrollment(enrollment_text)

            # Grades
            grades_text = clean_text(divs[5].get_text()) if len(divs) > 5 else ''
            grade_low, grade_high = parse_grades(grades_text)

            schools.append({
                'name': name,
                'city': city,
                'state': state,
                'address': address,
                'zip_code': zip_code,
                'phone': phone,
                'county': county,
                'website': '',
                'email': '',
                'enrollment': enrollment,
                'grade_low': grade_low,
                'grade_high': grade_high,
                'affiliation': 'Christian',
                'accreditation': 'ACSI',
                'school_type': 'private',
                'data_source': 'association_scrape',
                'tags': list(CONF['tags']),
                'leader_name': '',
                'leader_title': '',
                'detail_url': f'{NCES_BASE}/{href}' if href else '',
                'nces_id': nces_id,
            })

        except Exception as e:
            logger.debug(f"Error parsing NCES row: {e}")
            continue

    return schools


def _get_total_pages(soup: BeautifulSoup) -> int:
    """Extract total number of pages from NCES pagination."""
    # Look for pattern like "1 of 108"
    for span in soup.find_all('span'):
        text = span.get_text()
        match = re.search(r'(\d+)\s*of\s*(\d+)', text.replace('\xa0', ' '))
        if match:
            return int(match.group(2))
    return 1


def _scrape_all_nces_pages(session: ScraperSession, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scrape all pages of NCES ACSI school results."""
    all_schools = []

    # Fetch first page to get total count
    params = _build_search_params(page=1)
    url = NCES_LIST_URL + '?' + '&'.join(f'{k}={v}' for k, v in params.items())
    logger.info(f"ACSI: Fetching NCES search page 1...")
    soup = session.get_soup(url)

    # Get total pages
    total_pages = _get_total_pages(soup)
    logger.info(f"ACSI: Found {total_pages} pages of results")

    # Also extract the total count from "Search Results: XXXX"
    results_span = soup.find('span', string=re.compile(r'Search Results:\s*\d+'))
    if results_span:
        count_match = re.search(r'(\d+)', results_span.get_text())
        if count_match:
            logger.info(f"ACSI: Total schools in NCES: {count_match.group(1)}")

    # Parse first page
    page_schools = _parse_nces_results_page(soup)
    all_schools.extend(page_schools)
    logger.info(f"ACSI: Page 1 yielded {len(page_schools)} schools")

    if limit and len(all_schools) >= limit:
        return all_schools[:limit]

    # Iterate remaining pages
    for page_num in range(2, total_pages + 1):
        if limit and len(all_schools) >= limit:
            break

        params = _build_search_params(page=page_num)
        url = NCES_LIST_URL + '?' + '&'.join(f'{k}={v}' for k, v in params.items())

        try:
            logger.info(f"ACSI: Fetching page {page_num}/{total_pages}...")
            soup = session.get_soup(url)
            page_schools = _parse_nces_results_page(soup)
            if not page_schools:
                logger.warning(f"ACSI: No schools on page {page_num}, stopping.")
                break
            all_schools.extend(page_schools)
            logger.debug(f"ACSI: Page {page_num} yielded {len(page_schools)} schools (total: {len(all_schools)})")
        except Exception as e:
            logger.warning(f"ACSI: Error fetching page {page_num}: {e}")
            continue

    if limit:
        return all_schools[:limit]
    return all_schools


def scrape_acsi(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """
    Main ACSI scraper entry point.
    Scrapes NCES Private School Universe Survey for ACSI member schools.
    Returns stats dict with processed/created/updated/errored counts.
    """
    logger.info("Starting ACSI scraper (NCES PSS source)...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('acsi', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])

    try:
        schools_data = _scrape_all_nces_pages(session, limit=limit)
        logger.info(f"ACSI: Scraped {len(schools_data)} schools from NCES")

        for school_data in schools_data:
            try:
                stats['processed'] += 1

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
