"""
NAIS / HeadSearch Directory Enricher

Framework for importing data from school association directories:
  - NAIS member directory (National Association of Independent Schools)
  - HeadSearch.org (head of school transitions and openings)
  - State association directories
  - Other CSV/JSON data exports from association databases

Since these directories often require membership access or manual exports,
this enricher provides flexible import scripts that accept CSV and JSON
files, map fields to our schema, and perform fuzzy matching against
existing records.
"""

import csv
import json
import logging
import os
import io
from datetime import datetime
from typing import Optional, Dict, Any, List

import chardet

from ..db import (
    fetch_all, fetch_one, execute,
    create_sync_log, complete_sync_log, record_provenance,
)
from ..utils import (
    normalize_name, fuzzy_name_match, fuzzy_org_match,
    name_similarity, org_similarity, parse_name_parts,
)

logger = logging.getLogger('knock.enrichment.nais_directory')


# ---------------------------------------------------------------------------
# Field mapping configurations for known directory formats
# ---------------------------------------------------------------------------

# NAIS member directory CSV export (typical column names)
NAIS_FIELD_MAP = {
    'school_name': ['School Name', 'Institution', 'School', 'Name'],
    'head_name': ['Head of School', 'Head Name', 'Head', 'School Head', 'Leader Name'],
    'head_title': ['Head Title', 'Title', 'Position'],
    'head_email': ['Head Email', 'Email', 'Head of School Email'],
    'head_phone': ['Head Phone', 'Phone', 'Head of School Phone'],
    'city': ['City'],
    'state': ['State', 'ST'],
    'enrollment': ['Enrollment', 'Total Enrollment', 'Students'],
    'grades': ['Grades', 'Grade Range', 'Grades Served'],
    'boarding': ['Boarding', 'Boarding Status', 'Day/Boarding'],
    'nais_member': ['NAIS Member', 'Member'],
    'website': ['Website', 'URL', 'Web'],
    'head_start_year': ['Head Start Year', 'Start Year', 'Year Appointed'],
}

# HeadSearch.org transition data
HEADSEARCH_FIELD_MAP = {
    'school_name': ['School', 'School Name', 'Institution'],
    'departing_head': ['Departing Head', 'Current Head', 'Outgoing'],
    'incoming_head': ['Incoming Head', 'New Head', 'Appointed'],
    'transition_type': ['Type', 'Transition Type', 'Status'],
    'effective_date': ['Effective Date', 'Start Date', 'Date'],
    'search_firm': ['Search Firm', 'Firm', 'Consultant'],
    'city': ['City', 'Location'],
    'state': ['State', 'ST'],
    'notes': ['Notes', 'Comments', 'Details'],
}

# Generic directory format
GENERIC_FIELD_MAP = {
    'name': ['Name', 'Full Name', 'Person Name'],
    'first_name': ['First Name', 'First'],
    'last_name': ['Last Name', 'Last', 'Surname'],
    'title': ['Title', 'Position', 'Role', 'Job Title'],
    'organization': ['Organization', 'School', 'Institution', 'Company'],
    'email': ['Email', 'Email Address', 'E-mail'],
    'phone': ['Phone', 'Phone Number', 'Telephone'],
    'city': ['City'],
    'state': ['State', 'ST'],
    'linkedin': ['LinkedIn', 'LinkedIn URL', 'LinkedIn Profile'],
}


class DirectoryImporter:
    """Import and map data from association directory exports."""

    def __init__(self, source_name: str = 'nais_directory'):
        self.source_name = source_name
        self.stats = {
            'records_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'records_errored': 0,
        }

    def import_nais_directory(self, file_path: str) -> Dict[str, int]:
        """
        Import NAIS member directory CSV.
        Updates school records and creates/updates head of school people records.
        """
        sync_log_id = create_sync_log('nais_directory', 'manual')
        logger.info(f"Importing NAIS directory from {file_path}")

        try:
            rows = self._read_csv(file_path)
            field_map = self._resolve_field_map(rows[0] if rows else {}, NAIS_FIELD_MAP)

            for row in rows:
                self.stats['records_processed'] += 1
                try:
                    self._process_nais_row(row, field_map)
                except Exception as e:
                    self.stats['records_errored'] += 1
                    logger.error(f"Error processing NAIS row: {e}", exc_info=True)

            status = 'partial' if self.stats['records_errored'] > 0 else 'completed'
            complete_sync_log(sync_log_id, self.stats, status)
            logger.info(f"NAIS import complete: {self.stats}")

        except Exception as e:
            complete_sync_log(sync_log_id, self.stats, 'failed', str(e))
            raise

        return self.stats

    def import_headsearch_transitions(self, file_path: str) -> Dict[str, int]:
        """
        Import HeadSearch.org transition data.
        Creates industry_signals for head transitions and updates people/school records.
        """
        sync_log_id = create_sync_log('headsearch', 'manual')
        logger.info(f"Importing HeadSearch transitions from {file_path}")

        try:
            rows = self._read_file(file_path)
            field_map = self._resolve_field_map(rows[0] if rows else {}, HEADSEARCH_FIELD_MAP)

            for row in rows:
                self.stats['records_processed'] += 1
                try:
                    self._process_headsearch_row(row, field_map)
                except Exception as e:
                    self.stats['records_errored'] += 1
                    logger.error(f"Error processing HeadSearch row: {e}", exc_info=True)

            status = 'partial' if self.stats['records_errored'] > 0 else 'completed'
            complete_sync_log(sync_log_id, self.stats, status)
            logger.info(f"HeadSearch import complete: {self.stats}")

        except Exception as e:
            complete_sync_log(sync_log_id, self.stats, 'failed', str(e))
            raise

        return self.stats

    def import_generic_directory(self, file_path: str, source: str = 'directory') -> Dict[str, int]:
        """
        Import a generic directory CSV/JSON file.
        Creates/updates people records based on the available fields.
        """
        sync_log_id = create_sync_log(source, 'manual')
        logger.info(f"Importing generic directory from {file_path}")

        try:
            rows = self._read_file(file_path)
            field_map = self._resolve_field_map(rows[0] if rows else {}, GENERIC_FIELD_MAP)

            for row in rows:
                self.stats['records_processed'] += 1
                try:
                    self._process_generic_row(row, field_map, source)
                except Exception as e:
                    self.stats['records_errored'] += 1
                    logger.error(f"Error processing row: {e}", exc_info=True)

            status = 'partial' if self.stats['records_errored'] > 0 else 'completed'
            complete_sync_log(sync_log_id, self.stats, status)
            logger.info(f"Directory import complete: {self.stats}")

        except Exception as e:
            complete_sync_log(sync_log_id, self.stats, 'failed', str(e))
            raise

        return self.stats

    # -----------------------------------------------------------------------
    # Row processors
    # -----------------------------------------------------------------------

    def _process_nais_row(self, row: Dict, field_map: Dict) -> None:
        """Process a single NAIS directory row."""
        school_name = self._get_field(row, field_map, 'school_name')
        head_name = self._get_field(row, field_map, 'head_name')

        if not school_name:
            return

        # Match to existing school
        school = self._find_school(school_name, self._get_field(row, field_map, 'state'))

        if school:
            # Update school with NAIS data
            updates = {}
            enrollment = self._get_field(row, field_map, 'enrollment')
            if enrollment:
                try:
                    updates['enrollment_total'] = int(enrollment.replace(',', ''))
                except ValueError:
                    pass

            website = self._get_field(row, field_map, 'website')
            if website:
                updates['website'] = website

            if updates:
                set_clause = ', '.join(f"{k} = COALESCE({k}, %s)" for k in updates)
                execute(
                    f"UPDATE schools SET {set_clause}, nais_member = true, updated_at = NOW() WHERE id = %s",
                    tuple(updates.values()) + (school['id'],),
                )
        else:
            logger.debug(f"No school match for NAIS entry: {school_name}")

        # Process head of school
        if head_name and school:
            self._upsert_person_from_directory(
                name=head_name,
                title=self._get_field(row, field_map, 'head_title') or 'Head of School',
                email=self._get_field(row, field_map, 'head_email'),
                phone=self._get_field(row, field_map, 'head_phone'),
                school=school,
                source='nais_directory',
            )

    def _process_headsearch_row(self, row: Dict, field_map: Dict) -> None:
        """Process a HeadSearch transition row."""
        school_name = self._get_field(row, field_map, 'school_name')
        if not school_name:
            return

        school = self._find_school(school_name, self._get_field(row, field_map, 'state'))
        school_id = school['id'] if school else None

        departing_head = self._get_field(row, field_map, 'departing_head')
        incoming_head = self._get_field(row, field_map, 'incoming_head')
        transition_type = self._get_field(row, field_map, 'transition_type')
        effective_date = self._get_field(row, field_map, 'effective_date')

        # Create industry signal for the transition
        if departing_head:
            departing_person_id = None
            if school:
                person = self._find_person(departing_head, school)
                if person:
                    departing_person_id = person['id']

            execute(
                """INSERT INTO industry_signals
                       (signal_type, school_id, person_id, headline, description,
                        source_name, signal_date, confidence)
                   VALUES ('head_departure', %s, %s, %s, %s, 'headsearch', %s, 'confirmed')""",
                (
                    school_id,
                    departing_person_id,
                    f"{departing_head} departing {school_name}",
                    self._get_field(row, field_map, 'notes'),
                    effective_date,
                ),
            )
            self.stats['records_created'] += 1

        if incoming_head:
            incoming_person_id = None
            if school:
                # Create or find the incoming head
                incoming_person_id = self._upsert_person_from_directory(
                    name=incoming_head,
                    title='Head of School',
                    school=school,
                    source='headsearch',
                )

            execute(
                """INSERT INTO industry_signals
                       (signal_type, school_id, person_id, headline, description,
                        source_name, signal_date, confidence)
                   VALUES ('head_appointment', %s, %s, %s, %s, 'headsearch', %s, 'confirmed')""",
                (
                    school_id,
                    incoming_person_id,
                    f"{incoming_head} appointed at {school_name}",
                    self._get_field(row, field_map, 'notes'),
                    effective_date,
                ),
            )
            self.stats['records_created'] += 1

        # Update school leadership history
        if school and departing_head:
            execute(
                """UPDATE school_leadership_history
                   SET is_current = false,
                       end_date = COALESCE(end_date, %s),
                       departure_reason = COALESCE(departure_reason, %s)
                   WHERE school_id = %s AND is_current = true""",
                (effective_date, transition_type, school_id),
            )

        if school and incoming_head:
            incoming_person = self._find_person(incoming_head, school)
            execute(
                """INSERT INTO school_leadership_history
                       (school_id, person_id, position_title, start_date, is_current)
                   VALUES (%s, %s, 'Head of School', %s, true)""",
                (school_id, incoming_person['id'] if incoming_person else None, effective_date),
            )

    def _process_generic_row(self, row: Dict, field_map: Dict, source: str) -> None:
        """Process a generic directory row."""
        name = self._get_field(row, field_map, 'name')
        if not name:
            first = self._get_field(row, field_map, 'first_name') or ''
            last = self._get_field(row, field_map, 'last_name') or ''
            name = f"{first} {last}".strip()

        if not name:
            return

        org_name = self._get_field(row, field_map, 'organization')
        school = self._find_school(org_name, self._get_field(row, field_map, 'state')) if org_name else None

        self._upsert_person_from_directory(
            name=name,
            title=self._get_field(row, field_map, 'title'),
            email=self._get_field(row, field_map, 'email'),
            phone=self._get_field(row, field_map, 'phone'),
            school=school,
            source=source,
            linkedin_url=self._get_field(row, field_map, 'linkedin'),
        )

    # -----------------------------------------------------------------------
    # Shared helpers
    # -----------------------------------------------------------------------

    def _find_school(self, name: str, state: Optional[str] = None) -> Optional[Dict]:
        """Find a school by fuzzy name match, optionally filtered by state."""
        if not name:
            return None

        if state:
            candidates = fetch_all(
                """SELECT id, name, city, state, website
                   FROM schools
                   WHERE state = %s AND name_normalized %% %s
                   ORDER BY similarity(name_normalized, %s) DESC
                   LIMIT 5""",
                (state.upper(), normalize_name(name), normalize_name(name)),
            )
        else:
            candidates = fetch_all(
                """SELECT id, name, city, state, website
                   FROM schools
                   WHERE name_normalized %% %s
                   ORDER BY similarity(name_normalized, %s) DESC
                   LIMIT 5""",
                (normalize_name(name), normalize_name(name)),
            )

        for c in candidates:
            if org_similarity(name, c['name']) >= 75:
                return c

        return None

    def _find_person(self, name: str, school: Optional[Dict] = None) -> Optional[Dict]:
        """Find a person by fuzzy name match, optionally within a school context."""
        if not name:
            return None

        if school:
            candidates = fetch_all(
                """SELECT id, full_name, current_school_id
                   FROM people
                   WHERE current_school_id = %s OR name_normalized %% %s
                   LIMIT 20""",
                (school['id'], normalize_name(name)),
            )
        else:
            candidates = fetch_all(
                """SELECT id, full_name, current_school_id
                   FROM people
                   WHERE name_normalized %% %s
                   LIMIT 10""",
                (normalize_name(name),),
            )

        for c in candidates:
            score = name_similarity(name, c['full_name'])
            if school and str(c.get('current_school_id', '')) == str(school['id']):
                score = min(score + 15, 100)
            if score >= 80:
                return c

        return None

    def _upsert_person_from_directory(
        self,
        name: str,
        title: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        school: Optional[Dict] = None,
        source: str = 'directory',
        linkedin_url: Optional[str] = None,
    ) -> Optional[str]:
        """Create or update a person record from directory data. Returns person_id."""
        if not name:
            return None

        # Try to find existing
        person = self._find_person(name, school)

        if person:
            # Update with new data
            updates = []
            params = []

            if email:
                updates.append("email_primary = COALESCE(email_primary, %s)")
                params.append(email)
            if phone:
                updates.append("phone_primary = COALESCE(phone_primary, %s)")
                params.append(phone)
            if title:
                updates.append("current_title = COALESCE(current_title, %s)")
                params.append(title)
            if linkedin_url:
                updates.append("linkedin_url = COALESCE(linkedin_url, %s)")
                params.append(linkedin_url)

            if updates:
                updates.append("updated_at = NOW()")
                params.append(person['id'])
                execute(
                    f"UPDATE people SET {', '.join(updates)} WHERE id = %s",
                    tuple(params),
                )
                self.stats['records_updated'] += 1

            record_provenance('person', str(person['id']), 'directory_match',
                            name, source, confidence=0.85)
            return str(person['id'])

        else:
            # Create new person
            parts = parse_name_parts(name)
            row = fetch_one(
                """INSERT INTO people
                       (full_name, first_name, last_name, prefix, suffix,
                        name_normalized, current_title, current_organization,
                        current_school_id, email_primary, phone_primary,
                        linkedin_url, data_source, candidate_status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'passive')
                   RETURNING id""",
                (
                    name,
                    parts['first_name'],
                    parts['last_name'],
                    parts['prefix'] or None,
                    parts['suffix'] or None,
                    normalize_name(name),
                    title,
                    school['name'] if school else None,
                    school['id'] if school else None,
                    email,
                    phone,
                    linkedin_url,
                    source,
                ),
            )

            if row:
                person_id = str(row['id'])
                self.stats['records_created'] += 1
                logger.info(f"Created person from {source}: {name}")
                record_provenance('person', person_id, 'full_name', name, source)
                return person_id

        return None

    # -----------------------------------------------------------------------
    # File reading helpers
    # -----------------------------------------------------------------------

    def _read_file(self, file_path: str) -> List[Dict]:
        """Read a CSV or JSON file, auto-detecting format."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.json':
            return self._read_json(file_path)
        else:
            return self._read_csv(file_path)

    def _read_csv(self, file_path: str) -> List[Dict]:
        """Read a CSV file with auto-detected encoding."""
        # Detect encoding
        with open(file_path, 'rb') as f:
            raw = f.read()
            detected = chardet.detect(raw)
            encoding = detected.get('encoding', 'utf-8')

        with open(file_path, 'r', encoding=encoding, errors='replace') as f:
            reader = csv.DictReader(f)
            return list(reader)

    def _read_json(self, file_path: str) -> List[Dict]:
        """Read a JSON file (expects array of objects or object with a data array)."""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Try common wrapper keys
            for key in ['data', 'results', 'records', 'items', 'members', 'schools']:
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data]
        return []

    @staticmethod
    def _resolve_field_map(sample_row: Dict, known_map: Dict) -> Dict[str, Optional[str]]:
        """
        Resolve a field map by finding which actual column names match our known aliases.
        Returns a dict mapping our field names to actual column names.
        """
        result = {}
        available_cols = set(sample_row.keys()) if sample_row else set()

        for our_field, aliases in known_map.items():
            matched = None
            for alias in aliases:
                if alias in available_cols:
                    matched = alias
                    break
                # Case-insensitive match
                for col in available_cols:
                    if col.lower().strip() == alias.lower().strip():
                        matched = col
                        break
                if matched:
                    break
            result[our_field] = matched

        return result

    @staticmethod
    def _get_field(row: Dict, field_map: Dict, field_name: str) -> Optional[str]:
        """Get a field value using the resolved field map."""
        col_name = field_map.get(field_name)
        if not col_name:
            return None
        value = row.get(col_name, '')
        if isinstance(value, str):
            value = value.strip()
        return value or None


def run(file_path: Optional[str] = None, format: str = 'nais', **kwargs) -> Dict[str, int]:
    """
    Entry point for the enrichment runner.

    Args:
        file_path: Path to the CSV/JSON file to import
        format: One of 'nais', 'headsearch', 'generic'
    """
    if not file_path:
        logger.warning("No file_path provided to NAIS directory importer. "
                       "This enricher requires a manual data export file. "
                       "Use: python enrich.py nais --file /path/to/export.csv")
        return {'records_processed': 0, 'records_created': 0,
                'records_updated': 0, 'records_errored': 0}

    importer = DirectoryImporter(source_name=format)

    if format == 'nais':
        return importer.import_nais_directory(file_path)
    elif format == 'headsearch':
        return importer.import_headsearch_transitions(file_path)
    else:
        return importer.import_generic_directory(file_path, source=format)
