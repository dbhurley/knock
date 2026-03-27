"""
Board Member Extractor from IRS Form 990 Filings

Uses ProPublica's Nonprofit Explorer API to extract board member names from
Part VII, Section A (Officers, Directors, Trustees, Key Employees) of 990 filings.

For each school with a known EIN:
1. Pull board member names from 990 filings
2. Insert into school_board_members table
3. Create people records — board members at private schools are often:
   - Former heads of school
   - Parents with business connections
   - Community leaders who influence hiring decisions
4. Flag with board_experience tags
"""

import logging
import re
import time
from typing import Dict, List, Optional, Any

import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import PROPUBLICA_990_API
from utils import (
    RateLimitedSession,
    upsert_person,
    find_school_by_name,
    clean_text,
    parse_name_parts,
    create_sync_log,
    complete_sync_log,
    record_provenance,
    execute,
    fetch_one,
    fetch_all,
)

logger = logging.getLogger('knock.people_sources.board_from_990')

# ---------------------------------------------------------------------------
# ProPublica API helpers
# ---------------------------------------------------------------------------

def _api_url(template: str, **kwargs) -> str:
    """Build a ProPublica API URL."""
    base = PROPUBLICA_990_API['base_url']
    path = template.format(**kwargs)
    return base + path


def _fetch_org(session: RateLimitedSession, ein: str) -> Optional[Dict[str, Any]]:
    """Fetch organization data from ProPublica by EIN."""
    url = _api_url(PROPUBLICA_990_API['org_endpoint'], ein=ein)
    return session.get_json(url)


def _fetch_filing(session: RateLimitedSession, ein: str, tax_period: str) -> Optional[Dict[str, Any]]:
    """Fetch a specific filing from ProPublica."""
    url = _api_url(PROPUBLICA_990_API['filing_endpoint'], ein=ein, tax_period=tax_period)
    return session.get_json(url)


def _search_org(session: RateLimitedSession, query: str, page: int = 0) -> Optional[Dict[str, Any]]:
    """Search for organizations in ProPublica."""
    url = _api_url(PROPUBLICA_990_API['search_endpoint'], query=query, page=page)
    return session.get_json(url)


# ---------------------------------------------------------------------------
# Board member extraction
# ---------------------------------------------------------------------------

# Title patterns that indicate board roles
BOARD_ROLE_PATTERNS = {
    'chair': re.compile(r'\b(?:chair|chairman|chairwoman|chairperson)\b', re.I),
    'vice_chair': re.compile(r'\bvice\s*chair', re.I),
    'treasurer': re.compile(r'\btreasurer\b', re.I),
    'secretary': re.compile(r'\bsecretary\b', re.I),
    'member': re.compile(r'\b(?:trustee|director|member|board)\b', re.I),
    'head_of_school': re.compile(r'\b(?:head\s+of\s+school|headmaster|headmistress|principal|president|superintendent|director)\b', re.I),
}


def _classify_board_role(title: str) -> str:
    """Classify a 990 title into a board role."""
    if not title:
        return 'member'
    for role, pattern in BOARD_ROLE_PATTERNS.items():
        if pattern.search(title):
            return role
    return 'member'


def _is_likely_school_leader(title: str) -> bool:
    """Check if this person is likely the head of school (not just a board member)."""
    if not title:
        return False
    return bool(BOARD_ROLE_PATTERNS['head_of_school'].search(title))


def extract_board_from_org_data(org_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract board members from ProPublica org data.
    The API returns filings, and each filing may have officer/director data.
    """
    members = []

    # Get the most recent filing with people data
    filings = org_data.get('filings_with_data', [])
    if not filings:
        filings = org_data.get('filings', [])

    if not filings:
        return members

    # ProPublica embeds officer data in certain filing formats
    # Try to get the most recent filing's officer list
    for filing in filings[:3]:  # Check last 3 filings
        officers = filing.get('officers', [])
        if officers:
            for officer in officers:
                name = clean_text(officer.get('name', ''))
                title = clean_text(officer.get('title', ''))
                compensation = officer.get('compensation', 0)

                if not name or name.upper() == name:  # Skip all-caps org names
                    # Try cleaning up
                    if name:
                        name = name.title()

                members.append({
                    'name': name,
                    'title': title,
                    'role': _classify_board_role(title),
                    'compensation': compensation,
                    'is_school_leader': _is_likely_school_leader(title),
                    'tax_period': filing.get('tax_prd_yr') or filing.get('tax_period'),
                })
            break  # Got data from this filing

    return members


def extract_board_from_filing_xml(filing_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract board members from a parsed 990 filing.
    Part VII Section A lists officers, directors, trustees, key employees.
    """
    members = []

    # Navigate to the right section of the filing
    # Structure varies by form version, try multiple paths
    return_data = filing_data.get('Return', {}).get('ReturnData', {})
    if not return_data:
        return members

    form = return_data.get('IRS990', {})
    if not form:
        form = return_data.get('IRS990EZ', {})

    # Part VII - Compensation of Officers, Directors, Trustees
    part7 = form.get('Form990PartVIISectionAGrp', [])
    if not part7:
        part7 = form.get('OfficerDirectorTrusteeEmplGrp', [])
    if not part7:
        part7 = form.get('CompensationOfHghstPdEmplGrp', [])

    if isinstance(part7, dict):
        part7 = [part7]

    for person in part7:
        # Name can be in various fields
        name = ''
        name_fields = ['PersonNm', 'BusinessName', 'Name']
        for nf in name_fields:
            if nf in person:
                val = person[nf]
                if isinstance(val, dict):
                    name = val.get('BusinessNameLine1Txt', '')
                else:
                    name = str(val)
                break

        title = person.get('TitleTxt', person.get('Title', ''))
        compensation = person.get('ReportableCompFromOrgAmt',
                        person.get('Compensation', 0))

        if name:
            members.append({
                'name': clean_text(name),
                'title': clean_text(title) if title else '',
                'role': _classify_board_role(str(title)),
                'compensation': int(compensation) if compensation else 0,
                'is_school_leader': _is_likely_school_leader(str(title)),
                'tax_period': None,
            })

    return members


# ---------------------------------------------------------------------------
# Database import
# ---------------------------------------------------------------------------

def import_board_for_school(
    school_id: str,
    ein: str,
    session: Optional[RateLimitedSession] = None,
) -> Dict[str, int]:
    """Extract and import board members for a single school."""
    stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    own_session = session is None
    if own_session:
        session = RateLimitedSession(
            min_delay=PROPUBLICA_990_API['rate_limit'],
            user_agent='Knock Research Bot (askknock.com)',
        )

    # Fetch org data from ProPublica
    org_data = _fetch_org(session, ein)
    if not org_data:
        logger.warning(f"No ProPublica data for EIN {ein}")
        if own_session:
            session.close()
        return stats

    org = org_data.get('organization', {})
    org_name = org.get('name', '')

    # Extract board members
    members = extract_board_from_org_data(org_data)

    if not members:
        logger.info(f"No board members found for EIN {ein} ({org_name})")
        if own_session:
            session.close()
        return stats

    logger.info(f"Found {len(members)} board members for {org_name} (EIN {ein})")

    for member in members:
        stats['records_processed'] += 1
        try:
            name = member['name']
            if not name or len(name) < 3:
                continue

            # Determine tags
            tags = ['board_experience', f'board:{ein}']
            if member['is_school_leader']:
                tags.append('school_leader')
            if member['role'] == 'chair':
                tags.append('board_chair')

            # Upsert person
            person_id, created = upsert_person(
                full_name=name,
                data_source='form_990',
                title=member.get('title') if member['is_school_leader'] else f"Board {member['role'].replace('_', ' ').title()}",
                organization=org_name,
                school_id=school_id,
                tags=tags,
            )

            if created:
                stats['records_created'] += 1
            else:
                stats['records_updated'] += 1

            # Insert into school_board_members
            existing = fetch_one(
                """SELECT id FROM school_board_members
                   WHERE school_id = %s AND person_id = %s""",
                (school_id, person_id),
            )
            if not existing:
                execute(
                    """INSERT INTO school_board_members
                           (school_id, person_id, name, role, is_current)
                       VALUES (%s, %s, %s, %s, TRUE)""",
                    (school_id, person_id, name, member['role']),
                )

            # If compensation is available and this is a school leader, record it
            if member.get('compensation') and member.get('compensation') > 0 and member['is_school_leader']:
                tax_year = member.get('tax_period')
                if tax_year:
                    existing_comp = fetch_one(
                        """SELECT id FROM person_compensation
                           WHERE person_id = %s AND school_id = %s AND fiscal_year = %s""",
                        (person_id, school_id, int(tax_year)),
                    )
                    if not existing_comp:
                        execute(
                            """INSERT INTO person_compensation
                                   (person_id, school_id, ein, fiscal_year,
                                    total_compensation, position_title, source)
                               VALUES (%s, %s, %s, %s, %s, %s, 'form_990')""",
                            (person_id, school_id, ein, int(tax_year),
                             member['compensation'], member.get('title')),
                        )

            record_provenance(
                entity_type='person',
                entity_id=person_id,
                field_name='board_experience',
                field_value=f'{org_name} ({member["role"]})',
                source='form_990',
                source_url=f'https://projects.propublica.org/nonprofits/organizations/{ein}',
                confidence=0.95,
            )

        except Exception as e:
            stats['records_errored'] += 1
            logger.error(f"Error importing board member {member.get('name', '?')} for EIN {ein}: {e}")

    if own_session:
        session.close()

    return stats


def import_all_school_boards() -> Dict[str, int]:
    """Import board members for all schools with known EINs."""
    log_id = create_sync_log('board_from_990', 'full')
    total_stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    # Get all schools with EINs
    schools = fetch_all(
        """SELECT id, name, ein FROM schools
           WHERE ein IS NOT NULL AND ein != ''
           ORDER BY name""",
    )

    if not schools:
        logger.warning("No schools with EINs found in database")
        complete_sync_log(log_id, total_stats, status='completed')
        return total_stats

    logger.info(f"Processing 990 filings for {len(schools)} schools with EINs")

    session = RateLimitedSession(
        min_delay=PROPUBLICA_990_API['rate_limit'],
        user_agent='Knock Research Bot (askknock.com)',
    )

    for school in schools:
        try:
            stats = import_board_for_school(
                school_id=str(school['id']),
                ein=school['ein'],
                session=session,
            )
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception as e:
            logger.error(f"Error processing school {school['name']} (EIN {school['ein']}): {e}")
            total_stats['records_errored'] += 1

    session.close()

    status = 'completed' if total_stats['records_errored'] == 0 else 'partial'
    complete_sync_log(log_id, total_stats, status=status)

    logger.info(f"All 990 board imports completed: {total_stats}")
    return total_stats


# ---------------------------------------------------------------------------
# Search for school EINs (utility for filling in missing EINs)
# ---------------------------------------------------------------------------

def search_school_ein(school_name: str) -> Optional[Dict[str, str]]:
    """Search ProPublica for a school's EIN. Returns {ein, name, state} or None."""
    session = RateLimitedSession(
        min_delay=PROPUBLICA_990_API['rate_limit'],
        user_agent='Knock Research Bot (askknock.com)',
    )

    try:
        data = _search_org(session, school_name)
        if not data:
            return None

        orgs = data.get('organizations', [])
        for org in orgs[:5]:
            org_name = org.get('name', '')
            # Look for school-like names
            if any(kw in org_name.lower() for kw in ['school', 'academy', 'prep', 'institute']):
                return {
                    'ein': org.get('ein', ''),
                    'name': org_name,
                    'state': org.get('state', ''),
                }

        # Return first result if nothing school-like
        if orgs:
            return {
                'ein': orgs[0].get('ein', ''),
                'name': orgs[0].get('name', ''),
                'state': orgs[0].get('state', ''),
            }

    except Exception as e:
        logger.error(f"Error searching for EIN of '{school_name}': {e}")
    finally:
        session.close()

    return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == 'all':
            import_all_school_boards()
        elif sys.argv[1] == 'search' and len(sys.argv) > 2:
            name = ' '.join(sys.argv[2:])
            result = search_school_ein(name)
            print(f"Result: {result}")
        else:
            # Assume it's an EIN
            ein = sys.argv[1]
            school_id = sys.argv[2] if len(sys.argv) > 2 else None
            if school_id:
                stats = import_board_for_school(school_id, ein)
                print(f"Results: {stats}")
            else:
                print("Usage: python board_from_990.py <all | search <name> | <ein> <school_id>>")
    else:
        print("Usage: python board_from_990.py <all | search <name> | <ein> <school_id>>")
