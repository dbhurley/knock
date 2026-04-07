#!/usr/bin/env python3
"""
import-accs.py — Import schools from the ACCS (Association of Classical Christian Schools).

Two-phase strategy:
  1. Bulk fetch the AJAX endpoint at classicalchristian.org?school-finder=ajax
     This returns ~435 schools with name, address, email, phone, enrollment,
     accreditation status, year founded, church affiliation
  2. For each school, optionally Plasmate-fetch the individual /schools/{slug}/
     page to extract the headmaster name (the AJAX feed has these fields blank)

Usage:
  python3 import-accs.py                    # Bulk import only
  python3 import-accs.py --with-headmasters # Also fetch individual pages for HOS
  python3 import-accs.py --dry-run          # Preview without writing
"""

import os
import sys
import json
import re
import time
import argparse
import logging
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Install: pip install psycopg2-binary")
    sys.exit(1)

DB_URL          = os.getenv("DATABASE_URL", "postgresql://knock_admin:knock@localhost:5432/knock")
ACCS_FEED       = "https://classicalchristian.org?school-finder=ajax"
ACCS_BASE       = "https://classicalchristian.org"
LOG_FILE        = "/opt/knock/logs/import-accs.log"
PLASMATE_BIN    = "/usr/local/bin/plasmate"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger()
log.addHandler(logging.StreamHandler(sys.stdout))


def get_conn():
    return psycopg2.connect(DB_URL)


def fetch_accs_feed():
    """Fetch the bulk school directory feed."""
    log.info(f"Fetching {ACCS_FEED}")
    req = urllib.request.Request(
        ACCS_FEED,
        headers={"User-Agent": "Knock-Recruitment-Bot/1.0 (https://askknock.com)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    schools = data.get("schools", [])
    log.info(f"Retrieved {len(schools)} schools from ACCS feed")
    return schools


def normalize_school(raw):
    """Convert ACCS school record to our schema."""
    name = (raw.get("title_formatted") or raw.get("title") or "").strip()
    # Strip trailing state in parens like "Abiding Savior Academy (SD)"
    name = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", name)
    if not name:
        return None

    return {
        "name": name,
        "name_normalized": re.sub(r"[^a-z0-9 ]", "", name.lower()),
        "street_address": (raw.get("address") or raw.get("facility_address") or "").strip(),
        "city": (raw.get("city") or "").strip(),
        "state": (raw.get("state") or "").strip()[:2].upper(),
        "zip": (raw.get("zip") or "").strip()[:10],
        "phone": (raw.get("phone") or "").strip()[:20],
        "email": (raw.get("email") or "").strip().lower()[:300],
        "website": (raw.get("url") or raw.get("link") or "").strip()[:500],
        "enrollment_total": parse_int(raw.get("number_students")),
        "total_teachers": parse_int(raw.get("number_teachers")),
        "founding_year": parse_int(raw.get("year_founded")),
        "lat": raw.get("lat"),
        "lng": raw.get("lng"),
        "country": (raw.get("country") or "United States").strip()[:2] if (raw.get("country") or "") in ("United States", "USA") else "US",
        "accs_status": (raw.get("status") or "").strip(),
        "accs_accredited": (raw.get("accredited") or "").strip().lower() == "yes",
        "church_affiliation": (raw.get("church_type") or "").strip(),
        "classroom_format": (raw.get("classroom_format") or "").strip(),
        "is_international": bool(raw.get("is_international")),
        "slug": raw.get("slug") or "",
    }


def parse_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return None


def determine_segment(church_type, name):
    """Map ACCS church_type to our school_segment values."""
    ct = (church_type or "").lower()
    n = (name or "").lower()

    if "catholic" in ct or "catholic" in n:
        return "catholic"
    if "lutheran" in ct or "lutheran" in n:
        return "lutheran"
    if "baptist" in ct or "baptist" in n:
        return "baptist"
    if "presbyterian" in ct or "presbyterian" in n or "reformed" in ct:
        return "presbyterian"
    if "methodist" in ct or "wesleyan" in ct:
        return "methodist"
    if "episcopal" in ct or "anglican" in ct:
        return "episcopal"
    if "pentecostal" in ct or "assembly" in ct:
        return "pentecostal"
    if ct or "christian" in n or "academy" in n:
        return "evangelical_christian"
    return "evangelical_christian"


def find_existing_school(conn, school):
    """Try to find an existing school by NCES ID, name+state, or fuzzy match."""
    with conn.cursor() as cur:
        # Exact name + state match
        cur.execute("""
            SELECT id FROM schools
            WHERE LOWER(name) = LOWER(%s) AND state = %s
            LIMIT 1
        """, (school["name"], school["state"]))
        row = cur.fetchone()
        if row:
            return row[0]

        # Trigram fuzzy on normalized name + city
        if school["city"]:
            cur.execute("""
                SELECT id FROM schools
                WHERE state = %s AND city ILIKE %s
                  AND similarity(LOWER(name), LOWER(%s)) > 0.7
                ORDER BY similarity(LOWER(name), LOWER(%s)) DESC
                LIMIT 1
            """, (school["state"], school["city"], school["name"], school["name"]))
            row = cur.fetchone()
            if row:
                return row[0]
    return None


def upsert_school(conn, school, dry_run=False):
    """Insert or update a school record. Returns (school_id, was_new)."""
    existing_id = find_existing_school(conn, school)
    segment = determine_segment(school["church_affiliation"], school["name"])

    if dry_run:
        return existing_id or "DRY", existing_id is None

    with conn.cursor() as cur:
        if existing_id:
            # Update with non-NULL values, prefer ACCS data for missing fields
            cur.execute("""
                UPDATE schools SET
                    street_address = COALESCE(NULLIF(%s,''), street_address),
                    city           = COALESCE(NULLIF(%s,''), city),
                    state          = COALESCE(NULLIF(%s,''), state),
                    zip            = COALESCE(NULLIF(%s,''), zip),
                    phone          = COALESCE(NULLIF(%s,''), phone),
                    email          = COALESCE(NULLIF(%s,''), email),
                    website        = COALESCE(NULLIF(%s,''), website),
                    enrollment_total = COALESCE(%s, enrollment_total),
                    total_teachers   = COALESCE(%s, total_teachers),
                    founding_year    = COALESCE(%s, founding_year),
                    school_segment   = %s,
                    pedagogy         = COALESCE(pedagogy, 'classical'),
                    is_active        = TRUE,
                    last_verified_at = NOW(),
                    tags             = ARRAY(SELECT DISTINCT unnest(COALESCE(tags, ARRAY[]::text[]) || ARRAY['accs','classical_christian']))
                WHERE id = %s
            """, (
                school["street_address"], school["city"], school["state"], school["zip"],
                school["phone"], school["email"], school["website"],
                school["enrollment_total"], school["total_teachers"], school["founding_year"],
                segment, existing_id,
            ))
            conn.commit()
            return existing_id, False
        else:
            cur.execute("""
                INSERT INTO schools (
                    name, name_normalized, street_address, city, state, zip,
                    phone, email, website,
                    enrollment_total, total_teachers, founding_year,
                    school_segment, pedagogy,
                    is_private, is_active, data_source,
                    school_culture_tags, tags,
                    created_at, updated_at, last_verified_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    TRUE, TRUE, 'accs_import',
                    %s, %s,
                    NOW(), NOW(), NOW()
                )
                RETURNING id
            """, (
                school["name"][:500],
                school["name_normalized"][:500],
                school["street_address"][:500],
                school["city"][:200],
                school["state"],
                school["zip"],
                school["phone"],
                school["email"],
                school["website"],
                school["enrollment_total"],
                school["total_teachers"],
                school["founding_year"],
                segment,
                "classical",
                ["classical", "faith-based"],
                ["accs", "classical_christian"],
            ))
            new_id = cur.fetchone()[0]
            conn.commit()
            return new_id, True


# ── Plasmate-based headmaster extraction ──────────────────────────────────────
def fetch_headmaster_via_plasmate(slug):
    """Use Plasmate to render an individual school page and extract the headmaster."""
    url = f"{ACCS_BASE}/schools/{slug}/"
    try:
        result = subprocess.run(
            [PLASMATE_BIN, "fetch", url],
            capture_output=True, text=True, timeout=30
        )
        out = result.stdout
        # Find a JSON object in the output
        for start in (i for i in range(len(out) - 1, -1, -1) if out[i] == "{"):
            try:
                candidate = out[start:]
                depth, end = 0, -1
                for j, ch in enumerate(candidate):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = j + 1
                            break
                if end > 0:
                    som = json.loads(candidate[:end])
                    return extract_headmaster_from_som(som)
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception as e:
        log.debug(f"Plasmate error for {slug}: {e}")
    return None


def extract_headmaster_from_som(som):
    """Extract headmaster name from a Plasmate SOM."""
    text_blocks = []
    for region in som.get("regions", []):
        for el in region.get("elements", []):
            txt = el.get("text", "")
            if txt:
                text_blocks.append(txt)
    full_text = " ".join(text_blocks)

    # Patterns for headmaster identification
    patterns = [
        r"(?:Head\s*(?:master|mistress|of\s*School)|Principal|Director)\s*:?\s*([A-Z][a-zA-Z\.]+(?:\s+[A-Z][a-zA-Z\.]+){1,3})",
        r"([A-Z][a-zA-Z\.]+(?:\s+[A-Z][a-zA-Z\.]+){1,3})\s*[-,]?\s*(?:Head\s*(?:master|mistress|of\s*School)|Principal|Director)",
    ]
    for pat in patterns:
        m = re.search(pat, full_text)
        if m:
            name = m.group(1).strip()
            if 5 <= len(name) <= 60:
                return name
    return None


def create_or_link_person(conn, school_id, name, role="head_of_school"):
    """Create a person record for the headmaster and link to school."""
    if not name or len(name.split()) < 2:
        return None

    parts = name.split()
    first = parts[0]
    last = parts[-1]

    with conn.cursor() as cur:
        # Check if exists
        cur.execute("""
            SELECT id FROM people
            WHERE LOWER(first_name) = LOWER(%s) AND LOWER(last_name) = LOWER(%s)
              AND current_school_id = %s
            LIMIT 1
        """, (first, last, school_id))
        row = cur.fetchone()
        if row:
            return row[0]

        cur.execute("""
            INSERT INTO people (
                first_name, last_name, full_name, name_normalized,
                current_title, current_school_id, primary_role,
                candidate_status, data_source, tags
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                'passive', 'accs_import', ARRAY['accs','classical_christian']
            )
            RETURNING id
        """, (
            first[:100], last[:100], name[:300],
            re.sub(r"[^a-z0-9 ]", "", name.lower())[:300],
            "Head of School", school_id, role,
        ))
        return cur.fetchone()[0]


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="ACCS school directory importer")
    parser.add_argument("--with-headmasters", action="store_true",
                        help="Also fetch individual pages via Plasmate to get HOS names")
    parser.add_argument("--limit", type=int, help="Limit number of schools (for testing)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    schools = fetch_accs_feed()

    if args.limit:
        schools = schools[: args.limit]

    conn = get_conn()
    new_count = 0
    updated_count = 0
    hos_count = 0
    error_count = 0

    try:
        for i, raw in enumerate(schools, 1):
            try:
                normalized = normalize_school(raw)
                if not normalized:
                    continue

                # Skip international for now
                if raw.get("is_international"):
                    continue

                if i % 50 == 0:
                    log.info(f"  Progress: {i}/{len(schools)} ({new_count} new, {updated_count} updated)")

                school_id, was_new = upsert_school(conn, normalized, dry_run=args.dry_run)
                if was_new:
                    new_count += 1
                else:
                    updated_count += 1

                if args.with_headmasters and not args.dry_run and school_id and school_id != "DRY":
                    slug = normalized.get("slug")
                    if slug:
                        hos_name = fetch_headmaster_via_plasmate(slug)
                        if hos_name:
                            person_id = create_or_link_person(conn, school_id, hos_name)
                            if person_id:
                                hos_count += 1
                                log.info(f"    + HOS: {hos_name}")
                                conn.commit()
                        time.sleep(1)  # Be polite

            except Exception as e:
                error_count += 1
                log.error(f"  Error on {raw.get('title','?')}: {e}")
                conn.rollback()

        log.info(f"\n=== ACCS Import Complete ===")
        log.info(f"  New schools:     {new_count}")
        log.info(f"  Updated schools: {updated_count}")
        log.info(f"  HOS extracted:   {hos_count}")
        log.info(f"  Errors:          {error_count}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
