"""
IBO (International Baccalaureate Organization) school scraper.
Uses PrepScholar's complete IB school list as primary data source.
~950+ IB DP schools in the US organized by state.
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

logger = logging.getLogger('knock.scrapers.ib_schools')
CONF = ASSOCIATIONS['ib_schools']

# PrepScholar has the most complete, scrapeable list of US IB schools
PREPSCHOLAR_URL = 'https://blog.prepscholar.com/international-baccalaureate-schools-in-us-complete-list'

# US state name -> abbreviation
STATE_NAME_TO_ABBR = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE',
    'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID',
    'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS',
    'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN',
    'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE',
    'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ',
    'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC',
    'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR',
    'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
    'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT',
    'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA',
    'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY',
    'district of columbia': 'DC',
}


def _scrape_prepscholar(session: ScraperSession, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Scrape the PrepScholar complete list of US IB Diploma Programme schools.

    Page structure:
      <h3>State Name</h3>     (inside a <span> wrapper)
      ... possibly <p> or <img> ...
      <table>
        <tr><td><a href="https://ibo.org/school/XXXX/">School Name</a></td>
            <td>City</td></tr>
        ...
      </table>
      <h3>Next State</h3>
      ...
    """
    schools = []
    logger.info("IB: Fetching PrepScholar IB school list...")

    try:
        soup = session.get_soup(PREPSCHOLAR_URL)
    except Exception as e:
        logger.error(f"IB: Failed to fetch PrepScholar page: {e}")
        return schools

    # Find all h3 state headers
    all_h3s = soup.find_all('h3')

    for h3 in all_h3s:
        state_name = clean_text(h3.get_text()).strip()
        if not state_name:
            continue
        state_abbr = STATE_NAME_TO_ABBR.get(state_name.lower(), '')
        if not state_abbr:
            continue

        # Find the next table after this h3 (may be separated by p/img elements)
        table = h3.find_next('table')
        if not table:
            continue

        # Make sure this table comes before the next h3
        next_h3 = h3.find_next('h3')
        if next_h3 and table.sourceline and next_h3.sourceline:
            # If table is after next h3, skip
            if table.sourceline > next_h3.sourceline:
                continue

        # Parse school rows from the table
        tds = table.find_all('td')
        i = 0
        while i < len(tds):
            if limit and len(schools) >= limit:
                break

            td = tds[i]
            link = td.find('a')

            if link and 'ibo.org' in (link.get('href', '') or ''):
                school_name = clean_text(link.get_text()).strip()
                if not school_name or len(school_name) < 3:
                    i += 1
                    continue

                # Extract IBO school number from URL
                ibo_url = link.get('href', '')
                ibo_id = ''
                id_match = re.search(r'/school/(\d+)', ibo_url)
                if id_match:
                    ibo_id = id_match.group(1)

                # Next td should be the city
                city = ''
                if i + 1 < len(tds):
                    city_td = tds[i + 1]
                    if not city_td.find('a'):
                        city = clean_text(city_td.get_text()).strip()
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1

                schools.append({
                    'name': school_name,
                    'city': city,
                    'state': state_abbr,
                    'address': '',
                    'zip_code': '',
                    'phone': '',
                    'website': '',
                    'email': '',
                    'enrollment': None,
                    'grade_low': '',
                    'grade_high': '',
                    'affiliation': 'IB',
                    'accreditation': 'IBO',
                    'school_type': 'private',
                    'data_source': 'association_scrape',
                    'tags': list(CONF['tags']),
                    'leader_name': '',
                    'leader_title': '',
                    'detail_url': ibo_url,
                    'ibo_school_id': ibo_id,
                })
            else:
                i += 1

        if limit and len(schools) >= limit:
            break

    logger.info(f"IB: Scraped {len(schools)} schools from PrepScholar")
    return schools


def scrape_ib_schools(db_conn=None, limit: Optional[int] = None) -> Dict[str, int]:
    """
    Main IBO scraper entry point.
    Scrapes PrepScholar's complete IB school list.
    Returns stats dict.
    """
    logger.info("Starting IB Schools scraper (PrepScholar source)...")
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
        schools_data = _scrape_prepscholar(session, limit=limit)
        logger.info(f"IB: Found {len(schools_data)} schools total")

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
