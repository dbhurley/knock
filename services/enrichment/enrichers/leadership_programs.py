"""
Educational Leadership Program Tracker

Maintains a registry of top Ed.D. / Ed Leadership programs and tracks their
alumni as the FUTURE pipeline of independent school leadership candidates.

Key programs tracked:
  - Harvard Graduate School of Education
  - Penn Graduate School of Education
  - Columbia Teachers College
  - Vanderbilt Peabody College
  - Stanford Graduate School of Education
  - Klingenstein Center at Columbia
  - NAIS Fellowship Programs
  - And more...

This enricher:
  1. Seeds/maintains the leadership_programs table with known programs
  2. Imports program graduate/alumni data from CSV/JSON exports
  3. Cross-references graduates against our people table
  4. Creates person records for new graduates (future pipeline)
  5. Links graduates to program_graduates table
"""

import csv
import json
import logging
import os
from typing import Optional, Dict, Any, List

from ..db import (
    fetch_all, fetch_one, execute,
    create_sync_log, complete_sync_log, record_provenance,
)
from ..utils import (
    normalize_name, name_similarity, parse_name_parts,
)

logger = logging.getLogger('knock.enrichment.leadership_programs')


# ---------------------------------------------------------------------------
# Seed data: major educational leadership programs
# ---------------------------------------------------------------------------

PROGRAMS_SEED = [
    {
        'institution': 'Harvard University',
        'program_name': 'Doctor of Education Leadership (Ed.L.D.)',
        'degree_type': 'ed_d',
        'specialization': 'Education Leadership',
        'program_url': 'https://www.gse.harvard.edu/doctoral/doctor-education-leadership',
        'avg_cohort_size': 25,
        'typical_duration': '3 years',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
    },
    {
        'institution': 'Harvard University',
        'program_name': 'Ed.M. in School Leadership',
        'degree_type': 'masters',
        'specialization': 'School Leadership',
        'program_url': 'https://www.gse.harvard.edu/masters/school-leadership',
        'avg_cohort_size': 50,
        'typical_duration': '1 year',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
    },
    {
        'institution': 'University of Pennsylvania',
        'program_name': 'Ed.D. in Educational Leadership',
        'degree_type': 'ed_d',
        'specialization': 'Educational Leadership',
        'program_url': 'https://www.gse.upenn.edu/academics/programs/educational-leadership-edd',
        'avg_cohort_size': 30,
        'typical_duration': '3 years',
        'program_format': 'executive',
        'ranking_tier': 'top_10',
    },
    {
        'institution': 'University of Pennsylvania',
        'program_name': 'Mid-Career Doctoral in Education (Penn Chief Learning Officers)',
        'degree_type': 'ed_d',
        'specialization': 'Education Entrepreneurship',
        'program_url': 'https://www.gse.upenn.edu/academics/programs',
        'avg_cohort_size': 20,
        'typical_duration': '3 years',
        'program_format': 'executive',
        'ranking_tier': 'top_10',
    },
    {
        'institution': 'Columbia University',
        'program_name': 'Ed.D. in Education Leadership',
        'degree_type': 'ed_d',
        'specialization': 'Education Leadership',
        'program_url': 'https://www.tc.columbia.edu/organization-and-leadership/',
        'avg_cohort_size': 35,
        'typical_duration': '3-5 years',
        'program_format': 'part_time',
        'ranking_tier': 'top_10',
    },
    {
        'institution': 'Columbia University - Klingenstein Center',
        'program_name': 'Klingenstein Heads of Schools Program',
        'degree_type': 'certificate',
        'specialization': 'Independent School Leadership',
        'program_url': 'https://www.tc.columbia.edu/klingenstein/',
        'avg_cohort_size': 20,
        'typical_duration': '2 weeks',
        'program_format': 'executive',
        'ranking_tier': 'top_10',
        'notes': 'Premier program for sitting and aspiring independent school heads',
    },
    {
        'institution': 'Columbia University - Klingenstein Center',
        'program_name': 'Klingenstein Summer Institute for Early Career Teachers',
        'degree_type': 'certificate',
        'specialization': 'Independent School Teaching',
        'program_url': 'https://www.tc.columbia.edu/klingenstein/',
        'avg_cohort_size': 60,
        'typical_duration': '2 weeks',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
        'notes': 'Pipeline program - participants often become future school leaders',
    },
    {
        'institution': 'Vanderbilt University',
        'program_name': 'Ed.D. in Leadership and Policy',
        'degree_type': 'ed_d',
        'specialization': 'Leadership and Policy',
        'program_url': 'https://peabody.vanderbilt.edu/departments/lpo/',
        'avg_cohort_size': 25,
        'typical_duration': '3 years',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
    },
    {
        'institution': 'Stanford University',
        'program_name': 'Ph.D. in Education (Policy, Organization, and Leadership Studies)',
        'degree_type': 'ph_d',
        'specialization': 'Education Policy and Leadership',
        'program_url': 'https://ed.stanford.edu/academics/doctoral/phd',
        'avg_cohort_size': 15,
        'typical_duration': '5 years',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
    },
    {
        'institution': 'Stanford University',
        'program_name': 'STEP (Stanford Teacher Education Program)',
        'degree_type': 'masters',
        'specialization': 'Teacher Education',
        'program_url': 'https://ed.stanford.edu/step',
        'avg_cohort_size': 80,
        'typical_duration': '1 year',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
        'notes': 'Pipeline program - many grads enter independent schools',
    },
    {
        'institution': 'Johns Hopkins University',
        'program_name': 'Ed.D. in Education',
        'degree_type': 'ed_d',
        'specialization': 'Education Leadership',
        'program_url': 'https://education.jhu.edu/academics/edd/',
        'avg_cohort_size': 30,
        'typical_duration': '3 years',
        'program_format': 'part_time',
        'ranking_tier': 'top_25',
    },
    {
        'institution': 'Teachers College, Columbia University',
        'program_name': 'Ed.D. in Organization and Leadership',
        'degree_type': 'ed_d',
        'specialization': 'Organization and Leadership',
        'program_url': 'https://www.tc.columbia.edu/organization-and-leadership/',
        'avg_cohort_size': 25,
        'typical_duration': '3-5 years',
        'program_format': 'part_time',
        'ranking_tier': 'top_10',
    },
    {
        'institution': 'University of Virginia',
        'program_name': 'Ed.D. in Education Leadership',
        'degree_type': 'ed_d',
        'specialization': 'Administration and Supervision',
        'program_url': 'https://education.virginia.edu/',
        'avg_cohort_size': 20,
        'typical_duration': '3 years',
        'program_format': 'executive',
        'ranking_tier': 'top_25',
    },
    {
        'institution': 'University of Michigan',
        'program_name': 'Ed.D. in Educational Leadership and Policy',
        'degree_type': 'ed_d',
        'specialization': 'Educational Leadership',
        'program_url': 'https://marsal.umich.edu/',
        'avg_cohort_size': 20,
        'typical_duration': '3 years',
        'program_format': 'executive',
        'ranking_tier': 'top_25',
    },
    {
        'institution': 'NAIS',
        'program_name': 'NAIS Fellowship for Aspiring School Heads',
        'degree_type': 'certificate',
        'specialization': 'Independent School Leadership',
        'program_url': 'https://www.nais.org/learn/professional-development/',
        'avg_cohort_size': 30,
        'typical_duration': '1 year',
        'program_format': 'hybrid',
        'ranking_tier': 'top_10',
        'notes': 'Premier NAIS program for aspiring heads; strong placement rate',
    },
    {
        'institution': 'NAIS',
        'program_name': 'NAIS Institute for New Heads',
        'degree_type': 'certificate',
        'specialization': 'New Head Support',
        'program_url': 'https://www.nais.org/learn/professional-development/',
        'avg_cohort_size': 50,
        'typical_duration': '1 year',
        'program_format': 'hybrid',
        'ranking_tier': 'top_10',
        'notes': 'Support program for newly appointed heads of school',
    },
]


class LeadershipProgramTracker:
    """Tracks educational leadership programs and their graduates."""

    def __init__(self):
        self.stats = {
            'records_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'records_errored': 0,
        }

    def run(self, file_path: Optional[str] = None, **kwargs) -> Dict[str, int]:
        """
        Run the leadership program tracker.

        If no file_path is provided, seeds/updates the program registry.
        If a file_path is provided, imports graduate data.
        """
        sync_log_id = create_sync_log('leadership_programs', 'manual' if file_path else 'full')
        logger.info("Starting leadership program tracker")

        try:
            # Always seed/update programs
            self._seed_programs()

            # Import graduate data if file provided
            if file_path:
                self._import_graduates(file_path)

            status = 'partial' if self.stats['records_errored'] > 0 else 'completed'
            complete_sync_log(sync_log_id, self.stats, status)
            logger.info(f"Leadership program tracker complete: {self.stats}")

        except Exception as e:
            complete_sync_log(sync_log_id, self.stats, 'failed', str(e))
            logger.error(f"Leadership program tracker failed: {e}", exc_info=True)
            raise

        return self.stats

    def _seed_programs(self) -> None:
        """Seed the leadership_programs table with known programs."""
        logger.info(f"Seeding {len(PROGRAMS_SEED)} leadership programs")

        for prog in PROGRAMS_SEED:
            self.stats['records_processed'] += 1
            try:
                existing = fetch_one(
                    """SELECT id FROM leadership_programs
                       WHERE institution = %s AND program_name = %s""",
                    (prog['institution'], prog['program_name']),
                )

                if existing:
                    # Update existing
                    execute(
                        """UPDATE leadership_programs SET
                               degree_type = %s,
                               specialization = %s,
                               program_url = %s,
                               avg_cohort_size = %s,
                               typical_duration = %s,
                               program_format = %s,
                               ranking_tier = %s,
                               notes = COALESCE(%s, notes)
                           WHERE id = %s""",
                        (
                            prog['degree_type'],
                            prog.get('specialization'),
                            prog.get('program_url'),
                            prog.get('avg_cohort_size'),
                            prog.get('typical_duration'),
                            prog.get('program_format'),
                            prog.get('ranking_tier'),
                            prog.get('notes'),
                            existing['id'],
                        ),
                    )
                    self.stats['records_updated'] += 1
                else:
                    # Insert new
                    execute(
                        """INSERT INTO leadership_programs
                               (institution, program_name, degree_type, specialization,
                                program_url, avg_cohort_size, typical_duration,
                                program_format, ranking_tier, notes)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            prog['institution'],
                            prog['program_name'],
                            prog['degree_type'],
                            prog.get('specialization'),
                            prog.get('program_url'),
                            prog.get('avg_cohort_size'),
                            prog.get('typical_duration'),
                            prog.get('program_format'),
                            prog.get('ranking_tier'),
                            prog.get('notes'),
                        ),
                    )
                    self.stats['records_created'] += 1

            except Exception as e:
                self.stats['records_errored'] += 1
                logger.error(f"Error seeding program {prog['program_name']}: {e}")

    def _import_graduates(self, file_path: str) -> None:
        """Import graduate data from a CSV or JSON file."""
        logger.info(f"Importing graduates from {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.json':
            with open(file_path, 'r') as f:
                data = json.load(f)
                rows = data if isinstance(data, list) else data.get('graduates', data.get('data', [data]))
        else:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))

        for row in rows:
            self.stats['records_processed'] += 1
            try:
                self._process_graduate_row(row)
            except Exception as e:
                self.stats['records_errored'] += 1
                logger.error(f"Error processing graduate: {e}", exc_info=True)

    def _process_graduate_row(self, row: Dict) -> None:
        """Process a single graduate record."""
        # Extract fields (flexible field naming)
        name = (
            row.get('name') or row.get('full_name') or row.get('Name')
            or f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
        )
        if not name:
            return

        institution = row.get('institution') or row.get('school') or row.get('program')
        program_name = row.get('program_name') or row.get('program') or row.get('degree')
        grad_year = row.get('graduation_year') or row.get('year') or row.get('grad_year')
        dissertation = row.get('dissertation') or row.get('dissertation_topic')
        cohort = row.get('cohort') or row.get('cohort_name')

        # Find the program
        program_id = None
        if institution:
            prog = fetch_one(
                """SELECT id FROM leadership_programs
                   WHERE institution ILIKE %s
                   ORDER BY CASE WHEN program_name ILIKE %s THEN 0 ELSE 1 END
                   LIMIT 1""",
                (f"%{institution}%", f"%{program_name or ''}%"),
            )
            if prog:
                program_id = prog['id']

        # Find or create the person
        person_id = self._find_or_create_person(name, row)

        if not person_id:
            return

        # Parse graduation year
        year = None
        if grad_year:
            try:
                year = int(str(grad_year).strip())
            except ValueError:
                pass

        # Upsert into program_graduates
        existing = fetch_one(
            """SELECT id FROM program_graduates
               WHERE person_id = %s AND program_id = %s""",
            (person_id, program_id),
        )

        if existing:
            execute(
                """UPDATE program_graduates SET
                       graduation_year = COALESCE(%s, graduation_year),
                       dissertation_topic = COALESCE(%s, dissertation_topic),
                       cohort_name = COALESCE(%s, cohort_name)
                   WHERE id = %s""",
                (year, dissertation, cohort, existing['id']),
            )
            self.stats['records_updated'] += 1
        else:
            execute(
                """INSERT INTO program_graduates
                       (program_id, person_id, graduation_year,
                        dissertation_topic, cohort_name, current_status)
                   VALUES (%s, %s, %s, %s, %s, 'unknown')""",
                (program_id, person_id, year, dissertation, cohort),
            )
            self.stats['records_created'] += 1

        # Also add to person_education
        if institution:
            degree = row.get('degree_type') or row.get('degree') or 'Ed.D.'
            existing_ed = fetch_one(
                """SELECT id FROM person_education
                   WHERE person_id = %s AND institution ILIKE %s""",
                (person_id, f"%{institution}%"),
            )
            if not existing_ed:
                execute(
                    """INSERT INTO person_education
                           (person_id, institution, degree, field_of_study,
                            graduation_year, is_education_leadership)
                       VALUES (%s, %s, %s, %s, %s, true)""",
                    (person_id, institution, degree,
                     row.get('specialization') or 'Education Leadership', year),
                )

    def _find_or_create_person(self, name: str, row: Dict) -> Optional[str]:
        """Find an existing person or create a new one."""
        # Try to find by name
        candidates = fetch_all(
            """SELECT id, full_name FROM people
               WHERE name_normalized %% %s
               LIMIT 10""",
            (normalize_name(name),),
        )

        for c in candidates:
            if name_similarity(name, c['full_name']) >= 85:
                return str(c['id'])

        # Create new person
        parts = parse_name_parts(name)
        title = row.get('current_title') or row.get('title')
        org = row.get('current_organization') or row.get('organization') or row.get('current_school')

        result = fetch_one(
            """INSERT INTO people
                   (full_name, first_name, last_name, name_normalized,
                    current_title, current_organization,
                    email_primary, linkedin_url,
                    data_source, candidate_status, career_stage)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                       'leadership_program', 'passive', 'emerging')
               RETURNING id""",
            (
                name,
                parts['first_name'],
                parts['last_name'],
                normalize_name(name),
                title,
                org,
                row.get('email') or row.get('email_address'),
                row.get('linkedin') or row.get('linkedin_url'),
            ),
        )

        if result:
            person_id = str(result['id'])
            logger.info(f"Created person from leadership program: {name}")
            record_provenance('person', person_id, 'full_name', name,
                            'leadership_program', confidence=0.9)
            return person_id

        return None


def run(file_path: Optional[str] = None, **kwargs) -> Dict[str, int]:
    """Entry point for the enrichment runner."""
    tracker = LeadershipProgramTracker()
    return tracker.run(file_path=file_path)
