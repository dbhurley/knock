"""
University Ed Leadership Program Alumni Importer

Creates import templates for Ed Leadership program data and processes CSV imports:
- Klingenstein Center at Columbia
- Harvard GSE Ed.L.D. program
- Penn GSE mid-career doctoral program
- Vanderbilt Peabody College
- Stanford GSE
- University of Pennsylvania GEL program
- Bank Street College

Accepts CSV imports of alumni lists.
Auto-categorizes by graduation year and current role.
Flags recent graduates (last 5 years) as "emerging" career_stage.
Flags mid-career graduates as pipeline candidates.
"""

import csv
import io
import logging
import os
from typing import Dict, List, Optional, Any
from datetime import datetime

import chardet

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import UNIVERSITY_PROGRAMS
from utils import (
    upsert_person,
    find_school_by_name,
    clean_text,
    create_sync_log,
    complete_sync_log,
    execute,
    fetch_one,
    fetch_all,
)

logger = logging.getLogger('knock.people_sources.university_programs')

CURRENT_YEAR = datetime.now().year

# ---------------------------------------------------------------------------
# Program setup
# ---------------------------------------------------------------------------

def ensure_programs_in_db() -> Dict[str, str]:
    """Ensure all configured programs exist in leadership_programs table.
    Returns {program_key: program_id} mapping."""
    program_ids = {}

    for key, prog in UNIVERSITY_PROGRAMS.items():
        existing = fetch_one(
            """SELECT id FROM leadership_programs
               WHERE institution = %s AND program_name = %s
               LIMIT 1""",
            (prog['institution'], prog['program_name']),
        )

        if existing:
            program_ids[key] = str(existing['id'])
        else:
            row = fetch_one(
                """INSERT INTO leadership_programs
                       (institution, program_name, degree_type, specialization,
                        program_url, avg_cohort_size, typical_duration,
                        program_format, ranking_tier)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    prog['institution'], prog['program_name'],
                    prog['degree_type'], prog['specialization'],
                    prog.get('program_url'), prog.get('avg_cohort_size'),
                    prog.get('typical_duration'), prog.get('program_format'),
                    prog.get('ranking_tier'),
                ),
            )
            program_ids[key] = str(row['id'])
            logger.info(f"Created program record: {prog['institution']} - {prog['program_name']}")

    return program_ids


# ---------------------------------------------------------------------------
# Career stage classification
# ---------------------------------------------------------------------------

def classify_career_stage(
    graduation_year: Optional[int] = None,
    current_title: Optional[str] = None,
) -> str:
    """Classify career stage based on graduation year and current title."""
    if graduation_year:
        years_since = CURRENT_YEAR - graduation_year
        if years_since <= 5:
            return 'emerging'
        elif years_since <= 15:
            return 'mid_career'
        elif years_since <= 25:
            return 'senior'
        else:
            return 'veteran'

    if current_title:
        lower = current_title.lower()
        if any(kw in lower for kw in ['head of school', 'president', 'superintendent']):
            return 'senior'
        if any(kw in lower for kw in ['assistant', 'associate', 'division head']):
            return 'mid_career'
        if any(kw in lower for kw in ['teacher', 'coordinator', 'fellow']):
            return 'emerging'

    return 'mid_career'  # Default


# ---------------------------------------------------------------------------
# CSV Template Generation
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS = [
    'full_name',             # Required
    'email',                 # Optional
    'graduation_year',       # Required
    'degree',                # Optional (M.A., Ed.D., etc.)
    'current_title',         # Optional
    'current_organization',  # Optional
    'city',                  # Optional
    'state',                 # Optional
    'dissertation_topic',    # Optional
    'cohort_name',           # Optional
    'linkedin_url',          # Optional
    'notes',                 # Optional
]


def generate_csv_template(program_key: str) -> str:
    """Generate a CSV template for a specific program."""
    if program_key not in UNIVERSITY_PROGRAMS:
        raise ValueError(f"Unknown program: {program_key}")

    prog = UNIVERSITY_PROGRAMS[program_key]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXPECTED_COLUMNS)

    # Write a sample row
    writer.writerow([
        'Jane Smith',                              # full_name
        'jane.smith@email.com',                    # email
        '2020',                                    # graduation_year
        prog['degree_type'].upper().replace('_', '.'),  # degree
        'Head of School',                          # current_title
        'Sample Academy',                          # current_organization
        'New York',                                # city
        'NY',                                      # state
        'Leadership in Independent Schools',       # dissertation_topic
        f'Cohort {CURRENT_YEAR - 3}',             # cohort_name
        'https://linkedin.com/in/janesmith',       # linkedin_url
        '',                                        # notes
    ])

    return output.getvalue()


def save_csv_template(program_key: str, output_dir: str = '.') -> str:
    """Save a CSV template file for a program. Returns the file path."""
    content = generate_csv_template(program_key)
    prog = UNIVERSITY_PROGRAMS[program_key]
    filename = f"template_{program_key}_alumni.csv"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w', newline='') as f:
        f.write(content)

    logger.info(f"Template saved: {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# CSV Import
# ---------------------------------------------------------------------------

def _detect_encoding(filepath: str) -> str:
    """Detect file encoding."""
    with open(filepath, 'rb') as f:
        raw = f.read(10000)
    detected = chardet.detect(raw)
    return detected.get('encoding', 'utf-8') or 'utf-8'


def import_alumni_csv(
    program_key: str,
    csv_path: str,
) -> Dict[str, int]:
    """
    Import alumni from a CSV file for a specific program.
    Returns stats dict.
    """
    if program_key not in UNIVERSITY_PROGRAMS:
        raise ValueError(f"Unknown program: {program_key}")

    stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}
    program_ids = ensure_programs_in_db()
    program_id = program_ids[program_key]
    prog = UNIVERSITY_PROGRAMS[program_key]

    # Read CSV
    encoding = _detect_encoding(csv_path)
    logger.info(f"Importing {csv_path} (encoding: {encoding}) for program {program_key}")

    with open(csv_path, 'r', encoding=encoding) as f:
        reader = csv.DictReader(f)

        # Validate columns
        if not reader.fieldnames:
            logger.error("CSV has no headers")
            return stats

        missing = {'full_name'} - set(reader.fieldnames)
        if missing:
            logger.error(f"CSV missing required columns: {missing}")
            return stats

        for row in reader:
            stats['records_processed'] += 1
            try:
                full_name = clean_text(row.get('full_name', ''))
                if not full_name:
                    continue

                # Parse graduation year
                grad_year = None
                try:
                    grad_year = int(row.get('graduation_year', '').strip())
                except (ValueError, TypeError):
                    pass

                # Classify career stage
                current_title = clean_text(row.get('current_title', ''))
                career_stage = classify_career_stage(grad_year, current_title)

                # Build tags
                tags = [
                    f'program:{program_key}',
                    f'program_grad',
                    f'career_stage:{career_stage}',
                ]
                if career_stage == 'emerging':
                    tags.append('pipeline_candidate')
                if prog.get('ranking_tier') == 'top_10':
                    tags.append('top_program_graduate')

                # Find school
                current_org = clean_text(row.get('current_organization', ''))
                school_id = None
                if current_org:
                    school = find_school_by_name(current_org)
                    if school:
                        school_id = str(school['id'])

                # Upsert person
                extra_fields = {}
                person_id, created = upsert_person(
                    full_name=full_name,
                    data_source=f'university_{program_key}',
                    title=current_title or None,
                    organization=current_org or None,
                    school_id=school_id,
                    tags=tags,
                )

                if created:
                    stats['records_created'] += 1

                    # Set career stage and additional fields on new records
                    updates = ["career_stage = %s"]
                    params = [career_stage]

                    email = clean_text(row.get('email', ''))
                    if email:
                        updates.append("email_primary = %s")
                        params.append(email)

                    city = clean_text(row.get('city', ''))
                    if city:
                        updates.append("city = %s")
                        params.append(city)

                    state = clean_text(row.get('state', ''))
                    if state:
                        updates.append("state = %s")
                        params.append(state)

                    linkedin = clean_text(row.get('linkedin_url', ''))
                    if linkedin:
                        updates.append("linkedin_url = %s")
                        params.append(linkedin)

                    params.append(person_id)
                    execute(
                        f"UPDATE people SET {', '.join(updates)} WHERE id = %s",
                        tuple(params),
                    )
                else:
                    stats['records_updated'] += 1

                # Add education record
                degree = clean_text(row.get('degree', '')) or prog['degree_type']
                existing_ed = fetch_one(
                    """SELECT id FROM person_education
                       WHERE person_id = %s AND institution = %s
                       LIMIT 1""",
                    (person_id, prog['institution']),
                )
                if not existing_ed:
                    execute(
                        """INSERT INTO person_education
                               (person_id, institution, degree, field_of_study,
                                graduation_year, is_education_leadership)
                           VALUES (%s, %s, %s, %s, %s, TRUE)""",
                        (
                            person_id, prog['institution'],
                            degree, prog['specialization'],
                            grad_year,
                        ),
                    )

                # Add program graduate record
                existing_grad = fetch_one(
                    """SELECT id FROM program_graduates
                       WHERE program_id = %s AND person_id = %s
                       LIMIT 1""",
                    (program_id, person_id),
                )
                if not existing_grad:
                    dissertation = clean_text(row.get('dissertation_topic', ''))
                    cohort = clean_text(row.get('cohort_name', ''))
                    execute(
                        """INSERT INTO program_graduates
                               (program_id, person_id, graduation_year,
                                dissertation_topic, cohort_name, current_status)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (
                            program_id, person_id, grad_year,
                            dissertation or None,
                            cohort or None,
                            'placed' if current_title else 'unknown',
                        ),
                    )

            except Exception as e:
                stats['records_errored'] += 1
                logger.error(f"Error importing row for '{row.get('full_name', '?')}': {e}")

    logger.info(f"[{program_key}] Import completed: {stats}")
    return stats


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------

def generate_all_templates(output_dir: str = '.') -> List[str]:
    """Generate CSV templates for all programs."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for key in UNIVERSITY_PROGRAMS:
        path = save_csv_template(key, output_dir)
        paths.append(path)
    return paths


def import_all_from_directory(csv_dir: str) -> Dict[str, int]:
    """
    Import all CSV files from a directory.
    Expects files named like: klingenstein_alumni.csv, harvard_eld_alumni.csv, etc.
    """
    log_id = create_sync_log('university_programs', 'full')
    total_stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}

    for filename in os.listdir(csv_dir):
        if not filename.endswith('.csv'):
            continue

        # Try to match filename to a program key
        matched_key = None
        for key in UNIVERSITY_PROGRAMS:
            if key in filename.lower():
                matched_key = key
                break

        if not matched_key:
            logger.warning(f"Could not match file '{filename}' to any program. Skipping.")
            continue

        csv_path = os.path.join(csv_dir, filename)
        try:
            stats = import_alumni_csv(matched_key, csv_path)
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception as e:
            logger.error(f"Error importing {filename}: {e}")
            total_stats['records_errored'] += 1

    status = 'completed' if total_stats['records_errored'] == 0 else 'partial'
    complete_sync_log(log_id, total_stats, status=status)

    logger.info(f"All university imports completed: {total_stats}")
    return total_stats


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python university_programs.py templates [output_dir]")
        print("  python university_programs.py import <program_key> <csv_path>")
        print("  python university_programs.py import_dir <csv_directory>")
        print("  python university_programs.py setup  (ensure programs in DB)")
        print(f"\nAvailable programs: {', '.join(UNIVERSITY_PROGRAMS.keys())}")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'templates':
        output_dir = sys.argv[2] if len(sys.argv) > 2 else '.'
        paths = generate_all_templates(output_dir)
        print(f"Generated {len(paths)} templates:")
        for p in paths:
            print(f"  {p}")

    elif cmd == 'import' and len(sys.argv) >= 4:
        program_key = sys.argv[2]
        csv_path = sys.argv[3]
        stats = import_alumni_csv(program_key, csv_path)
        print(f"Results: {stats}")

    elif cmd == 'import_dir' and len(sys.argv) >= 3:
        csv_dir = sys.argv[2]
        stats = import_all_from_directory(csv_dir)
        print(f"Results: {stats}")

    elif cmd == 'setup':
        program_ids = ensure_programs_in_db()
        print(f"Programs in DB: {len(program_ids)}")
        for key, pid in program_ids.items():
            print(f"  {key}: {pid}")

    else:
        print(f"Unknown command: {cmd}")
