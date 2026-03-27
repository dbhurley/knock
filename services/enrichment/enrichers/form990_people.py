"""
Form 990 Executive Compensation Enricher

Uses the ProPublica Nonprofit Explorer API to extract executive compensation
data from IRS Form 990 filings for schools in our database.

This enricher:
  1. For each school, searches ProPublica for their 990 filing
  2. Fetches the filing detail which includes officer compensation
  3. Cross-references executives against our people table (fuzzy name + org match)
  4. INSERTs new people discovered from 990s who aren't in our DB
  5. UPDATEs existing people with compensation data
  6. Stores results in the person_compensation table

ProPublica API docs: https://projects.propublica.org/nonprofits/api/v2/
"""

import logging
import os
from typing import Optional, Dict, Any, List

from ..db import (
    fetch_all, fetch_one, execute, get_cursor,
    create_sync_log, complete_sync_log, record_provenance,
)
from ..utils import (
    RateLimitedSession, normalize_name, fuzzy_name_match,
    fuzzy_org_match, parse_name_parts,
)

logger = logging.getLogger('knock.enrichment.form990')

PROPUBLICA_BASE = os.getenv(
    'PROPUBLICA_BASE_URL',
    'https://projects.propublica.org/nonprofits/api/v2',
)


class Form990PeopleEnricher:
    """Enriches people data from IRS Form 990 filings via ProPublica."""

    def __init__(self, max_schools: int = 100, fiscal_year: Optional[int] = None):
        self.max_schools = max_schools
        self.fiscal_year = fiscal_year
        self.http = RateLimitedSession(min_delay=1.0, user_agent='Knock Enrichment (askknock.com)')
        self.stats = {
            'records_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'records_errored': 0,
        }

    def run(self, school_ids: Optional[List[str]] = None) -> Dict[str, int]:
        """
        Run the Form 990 people enrichment.

        Args:
            school_ids: Optional list of specific school IDs to process.
                        If None, processes schools missing recent 990 data.

        Returns:
            Dictionary of processing statistics.
        """
        sync_log_id = create_sync_log('form_990_people', 'incremental' if school_ids else 'full')
        logger.info("Starting Form 990 people enrichment")

        try:
            schools = self._get_schools(school_ids)
            logger.info(f"Processing {len(schools)} schools for 990 compensation data")

            for i, school in enumerate(schools):
                self.stats['records_processed'] += 1
                try:
                    self._process_school(school)
                except Exception as e:
                    self.stats['records_errored'] += 1
                    logger.error(f"Error processing {school['name']}: {e}", exc_info=True)

                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i+1}/{len(schools)} schools processed")

            status = 'partial' if self.stats['records_errored'] > 0 else 'completed'
            complete_sync_log(sync_log_id, self.stats, status)
            logger.info(f"Form 990 enrichment complete: {self.stats}")

        except Exception as e:
            complete_sync_log(sync_log_id, self.stats, 'failed', str(e))
            logger.error(f"Form 990 enrichment failed: {e}", exc_info=True)
            raise

        finally:
            self.http.close()

        return self.stats

    def _get_schools(self, school_ids: Optional[List[str]] = None) -> List[Dict]:
        """Get the list of schools to process."""
        if school_ids:
            return fetch_all(
                """SELECT id, name, city, state, nces_id, website
                   FROM schools
                   WHERE id = ANY(%s) AND is_active = true
                   ORDER BY name""",
                (school_ids,),
            )

        # Schools that haven't had 990 compensation data extracted recently
        from datetime import datetime
        target_year = self.fiscal_year or (datetime.now().year - 1)

        return fetch_all(
            """SELECT s.id, s.name, s.city, s.state, s.nces_id, s.website
               FROM schools s
               WHERE s.is_active = true
                 AND s.is_private = true
                 AND NOT EXISTS (
                     SELECT 1 FROM person_compensation pc
                     WHERE pc.school_id = s.id
                       AND pc.fiscal_year >= %s
                 )
               ORDER BY s.enrollment_total DESC NULLS LAST
               LIMIT %s""",
            (target_year, self.max_schools),
        )

    def _process_school(self, school: Dict) -> None:
        """Search ProPublica for a school's 990 and extract executive compensation."""
        search_term = school['name']
        state = school.get('state', '')

        # Search ProPublica for the organization
        params = {
            'q': search_term,
            'ntee[id]': '2',  # Education NTEE code
        }
        if state:
            params['state[id]'] = state

        url = f"{PROPUBLICA_BASE}/search.json"
        try:
            resp = self.http.get(url, params=params)
            data = resp.json()
        except Exception as e:
            logger.warning(f"ProPublica search failed for {school['name']}: {e}")
            return

        orgs = data.get('organizations', [])
        if not orgs:
            logger.debug(f"No 990 results for: {school['name']}")
            return

        # Find the best matching org
        best_org = self._find_best_org_match(school, orgs)
        if not best_org:
            logger.debug(f"No confident org match for: {school['name']}")
            return

        ein = best_org['ein']
        logger.info(f"Matched {school['name']} -> EIN {ein} ({best_org['name']})")

        # Fetch org detail with filings
        detail_url = f"{PROPUBLICA_BASE}/organizations/{ein}.json"
        try:
            resp = self.http.get(detail_url)
            detail = resp.json()
        except Exception as e:
            logger.warning(f"ProPublica detail fetch failed for EIN {ein}: {e}")
            return

        filings = detail.get('filings_with_data', [])
        if not filings:
            logger.debug(f"No filing data for EIN {ein}")
            return

        # Process each filing for executive compensation
        for filing in filings[:5]:  # Last 5 years max
            self._process_filing_officers(school, ein, filing)

    def _find_best_org_match(self, school: Dict, orgs: List[Dict]) -> Optional[Dict]:
        """Find the best matching ProPublica organization for a school."""
        school_name = school['name']
        school_state = school.get('state', '')

        best_match = None
        best_score = 0.0

        for org in orgs[:10]:  # Only check top 10 results
            name_score = fuzzy_org_match(school_name, org.get('name', ''))
            if not name_score:
                # Use direct score comparison
                from ..utils import org_similarity
                score = org_similarity(school_name, org.get('name', ''))
            else:
                score = 100.0  # fuzzy_org_match returns bool, so it's above threshold

            # Boost score if state matches
            if school_state and org.get('state', '').upper() == school_state.upper():
                score = min(score + 10, 100)

            if score > best_score:
                best_score = score
                best_match = org

        # Require at least 75% confidence
        if best_score >= 75:
            return best_match
        return None

    def _process_filing_officers(self, school: Dict, ein: int, filing: Dict) -> None:
        """
        Extract officer/executive compensation from a 990 filing.

        The ProPublica API includes officer data at the filing level when available.
        We need to fetch the full filing details to get individual compensation.
        """
        fiscal_year = filing.get('tax_prd_yr')
        if not fiscal_year:
            return

        # Fetch the detailed filing data (includes officer compensation)
        filing_url = f"{PROPUBLICA_BASE}/organizations/{ein}/{fiscal_year}.json"
        try:
            resp = self.http.get(filing_url)
            filing_detail = resp.json()
        except Exception as e:
            logger.warning(f"Filing detail fetch failed for EIN {ein}/{fiscal_year}: {e}")
            return

        # Extract officer/key employee compensation
        # ProPublica may include this in different structures depending on the filing
        officers = []

        # Check for officers in the filing data
        filing_data = filing_detail.get('filing', {})

        # Part VII Section A - Officers, Directors, Trustees, Key Employees
        # ProPublica normalizes this data when available
        if 'officers' in filing_detail:
            officers = filing_detail['officers']
        elif 'compensated_officers' in filing_data:
            officers = filing_data['compensated_officers']

        # Also check if the filing data has compensation info in a different format
        if not officers and 'pdf_url' in filing:
            # We can note the PDF is available but can't parse it automatically
            logger.debug(f"No structured officer data for EIN {ein}/{fiscal_year}, PDF available")
            return

        # If ProPublica returns top-level compensation amounts, create a summary entry
        top_comp = filing.get('pct_compnsatncurrofcrs')
        if top_comp and not officers:
            # Only aggregate data available - still useful
            logger.debug(f"Only aggregate compensation data for EIN {ein}/{fiscal_year}")

        for officer in officers:
            try:
                self._upsert_officer(school, ein, fiscal_year, officer)
            except Exception as e:
                logger.warning(f"Error processing officer from EIN {ein}/{fiscal_year}: {e}")

    def _upsert_officer(
        self,
        school: Dict,
        ein: int,
        fiscal_year: int,
        officer: Dict,
    ) -> None:
        """Match or create a person record and upsert their compensation."""
        officer_name = officer.get('name', '').strip()
        officer_title = officer.get('title', '').strip()

        if not officer_name:
            return

        # Parse compensation fields
        base_comp = self._parse_int(officer.get('compensation', officer.get('reportable_compensation')))
        other_comp = self._parse_int(officer.get('other_compensation', officer.get('other')))
        bonus = self._parse_int(officer.get('bonus'))
        deferred = self._parse_int(officer.get('deferred_compensation'))
        nontaxable = self._parse_int(officer.get('nontaxable_benefits'))
        hours = self._parse_float(officer.get('hours', officer.get('average_hours')))

        total_comp = sum(x for x in [base_comp, bonus, other_comp, deferred, nontaxable] if x)

        # Skip entries with zero or negligible compensation (likely board members)
        if total_comp < 10000:
            return

        # Try to match against existing people
        person_id = self._find_matching_person(officer_name, school)

        if not person_id:
            # Create a new person record
            person_id = self._create_person_from_990(officer_name, officer_title, school)
            if person_id:
                self.stats['records_created'] += 1
        else:
            self.stats['records_updated'] += 1

        if not person_id:
            return

        # Upsert compensation record
        execute(
            """INSERT INTO person_compensation
                   (person_id, school_id, ein, fiscal_year,
                    base_compensation, bonus, other_compensation,
                    deferred_compensation, nontaxable_benefits,
                    total_compensation, hours_per_week,
                    position_title, source)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'form_990')
               ON CONFLICT (person_id, school_id, fiscal_year)
               DO UPDATE SET
                   base_compensation = COALESCE(EXCLUDED.base_compensation, person_compensation.base_compensation),
                   bonus = COALESCE(EXCLUDED.bonus, person_compensation.bonus),
                   other_compensation = COALESCE(EXCLUDED.other_compensation, person_compensation.other_compensation),
                   deferred_compensation = COALESCE(EXCLUDED.deferred_compensation, person_compensation.deferred_compensation),
                   nontaxable_benefits = COALESCE(EXCLUDED.nontaxable_benefits, person_compensation.nontaxable_benefits),
                   total_compensation = COALESCE(EXCLUDED.total_compensation, person_compensation.total_compensation),
                   hours_per_week = COALESCE(EXCLUDED.hours_per_week, person_compensation.hours_per_week),
                   position_title = COALESCE(EXCLUDED.position_title, person_compensation.position_title),
                   ein = COALESCE(EXCLUDED.ein, person_compensation.ein),
                   updated_at = NOW()""",
            (
                person_id, school['id'], str(ein), fiscal_year,
                base_comp, bonus, other_comp,
                deferred, nontaxable,
                total_comp, hours,
                officer_title,
            ),
        )

        # Track provenance
        record_provenance(
            'person', person_id, 'compensation',
            str(total_comp), 'form_990',
            source_url=f"https://projects.propublica.org/nonprofits/organizations/{ein}",
            confidence=0.95,
        )

        # Update the person's current_compensation if this is the most recent year
        execute(
            """UPDATE people
               SET current_compensation = %s,
                   updated_at = NOW()
               WHERE id = %s
                 AND (current_compensation IS NULL OR current_compensation < %s)""",
            (total_comp, person_id, total_comp),
        )

    def _find_matching_person(self, name: str, school: Dict) -> Optional[str]:
        """
        Try to find an existing person in the database matching this 990 officer.
        Uses fuzzy name matching combined with organization matching.
        """
        # First, try exact name + school match
        candidates = fetch_all(
            """SELECT id, full_name, current_organization, current_school_id
               FROM people
               WHERE (current_school_id = %s
                  OR similarity(name_normalized, %s) > 0.4)
               LIMIT 50""",
            (school['id'], normalize_name(name)),
        )

        if not candidates:
            # Broader search by name similarity
            candidates = fetch_all(
                """SELECT id, full_name, current_organization, current_school_id
                   FROM people
                   WHERE name_normalized %% %s
                   LIMIT 20""",
                (normalize_name(name),),
            )

        best_match_id = None
        best_score = 0.0

        for candidate in candidates:
            name_score = 0.0
            from ..utils import name_similarity as ns
            name_score = ns(name, candidate['full_name'])

            # Boost if same school
            org_score = 0.0
            if candidate.get('current_school_id') and str(candidate['current_school_id']) == str(school['id']):
                org_score = 100.0
            elif candidate.get('current_organization'):
                from ..utils import org_similarity
                org_score = org_similarity(school['name'], candidate['current_organization'])

            # Combined score: name is primary, org is secondary
            combined = name_score * 0.6 + org_score * 0.4

            if combined > best_score and name_score >= 75:
                best_score = combined
                best_match_id = str(candidate['id'])

        if best_score >= 70:
            logger.debug(f"Matched 990 officer '{name}' -> person {best_match_id} (score={best_score:.0f})")
            return best_match_id

        return None

    def _create_person_from_990(
        self,
        name: str,
        title: str,
        school: Dict,
    ) -> Optional[str]:
        """Create a new person record from 990 data."""
        parts = parse_name_parts(name)

        row = fetch_one(
            """INSERT INTO people
                   (full_name, first_name, last_name, prefix, suffix,
                    name_normalized, current_title, current_organization,
                    current_school_id, primary_role, data_source, candidate_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'form_990', 'passive')
               RETURNING id""",
            (
                name,
                parts['first_name'],
                parts['last_name'],
                parts['prefix'] or None,
                parts['suffix'] or None,
                normalize_name(name),
                title or None,
                school['name'],
                school['id'],
                self._classify_role(title),
            ),
        )

        if row:
            person_id = str(row['id'])
            logger.info(f"Created new person from 990: {name} ({title}) at {school['name']}")
            record_provenance(
                'person', person_id, 'full_name',
                name, 'form_990', confidence=0.9,
            )
            return person_id

        return None

    @staticmethod
    def _classify_role(title: str) -> Optional[str]:
        """Map a 990 title to our primary_role taxonomy."""
        if not title:
            return None
        t = title.lower()
        if any(x in t for x in ['head of school', 'headmaster', 'headmistress', 'president', 'rector']):
            return 'head_of_school'
        if 'chief financial' in t or 'cfo' in t or 'business officer' in t:
            return 'cfo'
        if 'chief operating' in t or 'coo' in t:
            return 'coo'
        if any(x in t for x in ['academic dean', 'dean of faculty', 'chief academic']):
            return 'academic_dean'
        if 'division head' in t or 'principal' in t:
            return 'division_head'
        if 'director of admission' in t:
            return 'admissions_director'
        if 'director of advancement' in t or 'development' in t:
            return 'advancement_director'
        return None

    @staticmethod
    def _parse_int(value) -> Optional[int]:
        """Safely parse an integer from various formats."""
        if value is None:
            return None
        try:
            return int(float(str(value).replace(',', '').replace('$', '')))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_float(value) -> Optional[float]:
        """Safely parse a float."""
        if value is None:
            return None
        try:
            return float(str(value).replace(',', ''))
        except (ValueError, TypeError):
            return None


def run(max_schools: int = 100, school_ids: Optional[List[str]] = None, **kwargs) -> Dict[str, int]:
    """Entry point for the enrichment runner."""
    enricher = Form990PeopleEnricher(max_schools=max_schools)
    return enricher.run(school_ids=school_ids)
