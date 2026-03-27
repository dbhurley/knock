"""
AMS (American Montessori Society) scraper.
Scrapes NCES Private School Universe Survey data for AMS member schools.
NCES PSS Association code 23 = AMS. ~945 member schools.
Also scrapes Association Montessori International (AMI) with code 24.
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

logger = logging.getLogger('knock.scrapers.montessori')
CONF = ASSOCIATIONS['montessori']

# NCES Private School Universe Survey search endpoint
NCES_BASE = 'https://nces.ed.gov/surveys/pss/privateschoolsearch'
NCES_LIST_URL = f'{NCES_BASE}/school_list.asp'
AMS_ASSOCIATION_CODE = '23'   # American Montessori Society
AMI_ASSOCIATION_CODE = '24'   # Association Montessori International


def _build_search_params(association_code: str, page: int = 1) -> Dict[str, str]:
    """Build NCES search query parameters."""
    return {
        'Search': '1',
        'Association': association_code,
        'NumOfStudentsRange': 'more',
        'IncGrade': '-1',
        'LoGrade': '-1',
        'HiGrade': '-1',
        'SchoolPageNum': str(page),
    }


def _parse_nces_results_page(soup: BeautifulSoup, accreditation: str = 'AMS') -> List[Dict[str, Any]]:
    """
    Parse a NCES search results page into school dicts.

    Each result row has this HTML structure:
    <div class='resultRow'>
      <div>1.</div>
      <div><a href="...&ID=XXXX">school name</a><br/><span>address</span></div>
      <div>phone</div>
      <div>county</div>
      <div>enrollment</div>
      <div>grades</div>
    </div>
    """
    schools = []
    rows = soup.select('.resultRow')

    for row in rows:
        try:
            divs = row.find_all('div', recursive=False)
            if len(divs) < 6:
                continue

            name_div = divs[1]
            link = name_div.find('a')
            if not link:
                continue

            name = clean_text(link.get_text())
            if not name or len(name) < 3:
                continue
            name = re.sub(r'^[\s\-]+|[\s\-]+$', '', name).strip().title()

            # Extract NCES ID
            href = link.get('href', '')
            nces_id = ''
            id_match = re.search(r'ID=([A-Za-z0-9]+)', href)
            if id_match:
                nces_id = id_match.group(1)

            # Parse address
            addr_span = name_div.find('span')
            address = ''
            city = ''
            state = ''
            zip_code = ''
            if addr_span:
                addr_text = addr_span.get_text().replace('\xa0', ' ').strip()
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

            phone = extract_phone(clean_text(divs[2].get_text())) or '' if len(divs) > 2 else ''
            county = clean_text(divs[3].get_text()) if len(divs) > 3 else ''
            enrollment = parse_enrollment(clean_text(divs[4].get_text())) if len(divs) > 4 else None
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
                'affiliation': 'Montessori',
                'accreditation': accreditation,
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
    for span in soup.find_all('span'):
        text = span.get_text()
        match = re.search(r'(\d+)\s*of\s*(\d+)', text.replace('\xa0', ' '))
        if match:
            return int(match.group(2))
    return 1


def _scrape_nces_association(session: ScraperSession, assoc_code: str,
                              accreditation: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scrape all pages of NCES results for a given association code."""
    all_schools = []

    params = _build_search_params(assoc_code, page=1)
    url = NCES_LIST_URL + '?' + '&'.join(f'{k}={v}' for k, v in params.items())
    logger.info(f"Montessori: Fetching NCES {accreditation} page 1...")
    soup = session.get_soup(url)

    total_pages = _get_total_pages(soup)

    results_span = soup.find('span', string=re.compile(r'Search Results:\s*\d+'))
    if results_span:
        count_match = re.search(r'(\d+)', results_span.get_text())
        if count_match:
            logger.info(f"Montessori: Total {accreditation} schools in NCES: {count_match.group(1)}")

    page_schools = _parse_nces_results_page(soup, accreditation=accreditation)
    all_schools.extend(page_schools)
    logger.info(f"Montessori: {accreditation} page 1 yielded {len(page_schools)} schools")

    if limit and len(all_schools) >= limit:
        return all_schools[:limit]

    for page_num in range(2, total_pages + 1):
        if limit and len(all_schools) >= limit:
            break

        params = _build_search_params(assoc_code, page=page_num)
        url = NCES_LIST_URL + '?' + '&'.join(f'{k}={v}' for k, v in params.items())

        try:
            logger.info(f"Montessori: Fetching {accreditation} page {page_num}/{total_pages}...")
            soup = session.get_soup(url)
            page_schools = _parse_nces_results_page(soup, accreditation=accreditation)
            if not page_schools:
                logger.warning(f"Montessori: No schools on page {page_num}, stopping.")
                break
            all_schools.extend(page_schools)
        except Exception as e:
            logger.warning(f"Montessori: Error fetching page {page_num}: {e}")
            continue

    if limit:
        return all_schools[:limit]
    return all_schools


def scrape_montessori(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """
    Main Montessori scraper entry point.
    Scrapes NCES PSS for AMS (code 23) and AMI (code 24) member schools.
    Deduplicates since some schools belong to both AMS and AMI.
    Returns stats dict.
    """
    logger.info("Starting Montessori/AMS scraper (NCES PSS source)...")
    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0,
             'schools_created': 0, 'schools_updated': 0,
             'people_created': 0, 'people_updated': 0}

    sync_log_id = None
    try:
        sync_log_id = create_sync_log('montessori_ams', 'association_scrape', conn=db_conn)
    except Exception as e:
        logger.warning(f"Could not create sync log: {e}")

    session = ScraperSession(min_delay=CONF['request_delay'])
    seen_nces_ids = set()

    try:
        # Scrape AMS schools (primary)
        ams_limit = limit
        ams_schools = _scrape_nces_association(session, AMS_ASSOCIATION_CODE, 'AMS', limit=ams_limit)
        logger.info(f"Montessori: Scraped {len(ams_schools)} AMS schools from NCES")

        # Scrape AMI schools (secondary, may overlap)
        remaining = (limit - len(ams_schools)) if limit else None
        if remaining is None or remaining > 0:
            ami_schools = _scrape_nces_association(session, AMI_ASSOCIATION_CODE, 'AMI', limit=remaining)
            logger.info(f"Montessori: Scraped {len(ami_schools)} AMI schools from NCES")
        else:
            ami_schools = []

        # Combine, deduplicating by NCES ID
        all_schools = []
        for school in ams_schools:
            nid = school.get('nces_id', '')
            if nid:
                seen_nces_ids.add(nid)
            all_schools.append(school)

        for school in ami_schools:
            nid = school.get('nces_id', '')
            if nid and nid in seen_nces_ids:
                continue
            if nid:
                seen_nces_ids.add(nid)
            # Tag AMI schools differently
            school['accreditation'] = 'AMS/AMI'
            if 'ami' not in school['tags']:
                school['tags'].append('ami')
            all_schools.append(school)

        if limit:
            all_schools = all_schools[:limit]

        logger.info(f"Montessori: {len(all_schools)} unique schools after dedup")

        for school_data in all_schools:
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
