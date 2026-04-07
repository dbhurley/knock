#!/usr/bin/env python3
"""
llm-enrich.py — LLM-powered candidate enrichment using Claude.

For each unenriched candidate:
  1. Fetches their school's leadership/about page
  2. Asks Claude to extract structured information from the bio:
     - Professional summary
     - Education history (institution, degree, year)
     - Career timeline highlights
     - Specializations and expertise areas
     - Leadership style indicators
     - Notable achievements or quotes

Claude's reasoning is dramatically better than regex/keyword matching for
understanding nuanced bios. This is meant to run on the highest-priority
candidates (HOS at large NAIS schools) where data quality matters most.

Usage:
  python3 llm-enrich.py                    # process default batch
  python3 llm-enrich.py --limit 25         # process N candidates
  python3 llm-enrich.py --person-id <uuid> # enrich one specific person
  python3 llm-enrich.py --dry-run          # show what would be extracted

Cost estimate: ~$0.01-0.03 per candidate using claude-sonnet.
"""

import os
import sys
import json
import re
import time
import logging
import argparse
import urllib.parse
from datetime import datetime, timezone

try:
    import psycopg2
    import psycopg2.extras
    import requests
    from bs4 import BeautifulSoup
    import anthropic
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install: pip install psycopg2-binary requests beautifulsoup4 anthropic")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
DB_URL          = os.getenv("DATABASE_URL", "postgresql://knock_admin:knock@localhost:5432/knock")
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY")
MODEL           = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
LOG_FILE        = "/opt/knock/logs/llm-enrich.log"
USER_AGENT      = "Mozilla/5.0 (Knock Recruitment Research Bot; +https://askknock.com)"
TIMEOUT         = 15
MAX_TOKENS      = 1500
LOCK_FILE       = "/tmp/knock-llm-enrich.lock"

if not ANTHROPIC_KEY:
    print("ANTHROPIC_API_KEY environment variable not set")
    sys.exit(1)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger()
log.addHandler(logging.StreamHandler(sys.stdout))


# ── Lock ──────────────────────────────────────────────────────────────────────
def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return False
        except (OSError, ValueError):
            os.unlink(LOCK_FILE)
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        os.unlink(LOCK_FILE)
    except OSError:
        pass


# ── DB ────────────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DB_URL)


def fetch_candidates(conn, limit, person_id=None):
    """Get candidates ranked by impact: HOS at large NAIS-tier schools first."""
    where_extra = "AND p.id = %s" if person_id else ""
    sql = f"""
        SELECT
            p.id, p.first_name, p.last_name, p.full_name,
            p.current_title, p.specializations, p.cultural_fit_tags,
            p.linkedin_summary, p.linkedin_headline,
            s.id AS school_id, s.name AS school_name, s.website,
            s.enrollment_total, s.school_type, s.religious_affiliation
        FROM people p
        JOIN schools s ON p.current_school_id = s.id
        WHERE s.website IS NOT NULL
          AND s.website != ''
          AND p.first_name IS NOT NULL
          AND p.last_name IS NOT NULL
          AND p.primary_role = 'head_of_school'
          AND (
              p.specializations IS NULL
              OR array_length(p.specializations, 1) IS NULL
              OR array_length(p.specializations, 1) < 2
          )
          {where_extra}
        ORDER BY s.enrollment_total DESC NULLS LAST
        LIMIT %s
    """
    params = (person_id, limit) if person_id else (limit,)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def update_person_from_llm(conn, person_id, extracted, dry_run=False):
    """Apply LLM-extracted data to the person record."""
    if dry_run:
        log.info(f"  [DRY RUN] Would update {person_id}: {json.dumps(extracted, indent=2)}")
        return

    sets = []
    values = []

    if extracted.get("specializations"):
        sets.append("specializations = %s")
        values.append(extracted["specializations"])

    if extracted.get("leadership_style"):
        sets.append("leadership_style = %s")
        values.append(extracted["leadership_style"])

    if extracted.get("strengths"):
        sets.append("strengths = %s")
        values.append(extracted["strengths"])

    if extracted.get("alma_mater"):
        sets.append("alma_mater = %s")
        values.append(extracted["alma_mater"])

    if extracted.get("highest_degree"):
        sets.append("highest_degree = %s")
        values.append(extracted["highest_degree"])

    if extracted.get("years_experience"):
        sets.append("years_experience = %s")
        values.append(extracted["years_experience"])

    sets.append("last_enriched_at = NOW()")
    values.append(person_id)

    if len(sets) > 1:  # More than just the timestamp
        sql = f"UPDATE people SET {', '.join(sets)} WHERE id = %s"
        with conn.cursor() as cur:
            cur.execute(sql, values)

    # Insert education records
    for edu in extracted.get("education", []):
        if not edu.get("institution"):
            continue
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO person_education (person_id, institution, degree, field_of_study, graduation_year, is_education_leadership)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                person_id,
                edu["institution"][:300],
                (edu.get("degree") or "")[:100],
                (edu.get("field_of_study") or "")[:300],
                edu.get("year"),
                bool(edu.get("is_education_leadership", False)),
            ))

    conn.commit()


def mark_attempted(conn, person_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE people SET last_enriched_at = NOW() WHERE id = %s", (person_id,))
    conn.commit()


# ── Web fetch with leadership page discovery ─────────────────────────────────
LEADERSHIP_KEYWORDS = [
    "head of school", "headmaster", "headmistress",
    "leadership", "administration", "about-us/head", "about/head",
    "our-team", "our team", "meet our",
]


def fetch_url(url):
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
            return resp.text
    except Exception:
        pass
    return None


def find_bio_page(homepage_url, person_name):
    """Find the page on this school's site that contains the person's bio."""
    homepage = homepage_url if homepage_url.startswith("http") else "https://" + homepage_url
    homepage = homepage.rstrip("/")

    html = fetch_url(homepage)
    if not html:
        return None, None

    soup = BeautifulSoup(html, "html.parser")
    base_host = urllib.parse.urlparse(homepage).netloc

    # Find candidate URLs from homepage navigation
    candidates = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(" ", strip=True).lower()
        full_url = urllib.parse.urljoin(homepage, href)
        parsed = urllib.parse.urlparse(full_url)

        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc and parsed.netloc != base_host:
            continue

        path_lower = parsed.path.lower()
        score = 0
        for kw in LEADERSHIP_KEYWORDS:
            kw_norm = kw.replace(" ", "")
            if kw in path_lower or kw_norm in path_lower:
                score += 3
            if kw in text:
                score += 2

        if score > 0:
            candidates.append((score, full_url))

    candidates.sort(key=lambda x: -x[0])

    # Try each candidate URL, looking for the person's name
    name_parts = person_name.lower().split()
    for _, url in candidates[:6]:
        page_html = fetch_url(url)
        if not page_html:
            continue
        page_lower = page_html.lower()
        if all(part in page_lower for part in name_parts if len(part) > 2):
            return url, page_html
        time.sleep(0.5)

    # Fall back to homepage if it mentions the person
    if all(part in html.lower() for part in name_parts if len(part) > 2):
        return homepage, html

    return None, None


def extract_text_around_name(html, first_name, last_name, context_chars=2500):
    """Extract a focused text block around the person's name from the page."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    full_text = soup.get_text(" ", strip=True)
    full_text = re.sub(r"\s+", " ", full_text)

    full_name = f"{first_name} {last_name}"
    idx = full_text.lower().find(full_name.lower())
    if idx == -1:
        idx = full_text.lower().find(last_name.lower())

    if idx == -1:
        return full_text[:context_chars]

    start = max(0, idx - 200)
    end = min(len(full_text), idx + context_chars)
    return full_text[start:end]


# ── LLM extraction ────────────────────────────────────────────────────────────
EXTRACTION_PROMPT = """You are extracting structured information about a school leader from their bio.

PERSON: {full_name}
ROLE: {current_title}
SCHOOL: {school_name}

BIO TEXT (excerpt from school website):
{bio_text}

Extract the following information IF clearly present in the text. Return ONLY valid JSON.
If a field is not mentioned, omit it from the JSON entirely (do not return null or empty).

Schema:
{{
  "education": [
    {{"institution": "...", "degree": "B.A.|M.A.|M.Ed.|Ph.D.|Ed.D.|MBA|J.D.|...", "field_of_study": "...", "year": 2010, "is_education_leadership": true|false}}
  ],
  "alma_mater": "Most prominent undergraduate or graduate institution",
  "highest_degree": "Doctorate|Masters|Bachelors",
  "years_experience": 25,
  "specializations": ["fundraising", "stem", "dei", "boarding", "college_prep", "arts", "international", "early_childhood", "special_education", "enrollment_management", "strategic_planning", "curriculum_development"],
  "leadership_style": ["collaborative", "visionary", "transformational", "operational", "servant", "data_driven", "entrepreneurial"],
  "strengths": ["3-5 short phrases about their notable strengths or accomplishments"]
}}

Rules:
- Only include "education" entries if you can identify both an institution AND degree from the text
- Only use specializations from the provided list (do not invent new ones)
- Only use leadership_style values from the provided list
- Strengths should be short concrete phrases (e.g., "Led $50M capital campaign", "Grew enrollment 40% in 5 years")
- If the bio is too sparse or doesn't actually describe this person, return: {{}}
- DO NOT speculate or invent facts. If unsure, omit the field.

Return ONLY the JSON object, nothing else."""


def extract_with_llm(client, person, bio_text):
    """Call Claude to extract structured info from a bio."""
    prompt = EXTRACTION_PROMPT.format(
        full_name=person["full_name"],
        current_title=person["current_title"] or "Head of School",
        school_name=person["school_name"],
        bio_text=bio_text[:3000],
    )

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        # Find the JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        log.warning(f"  JSON parse error: {e}")
        return None
    except Exception as e:
        log.error(f"  LLM error: {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="LLM-powered candidate enrichment")
    parser.add_argument("--limit", type=int, default=10, help="Number of candidates to process")
    parser.add_argument("--person-id", type=str, help="Process a specific person by UUID")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args()

    if not acquire_lock():
        log.info("Another instance is running, exiting")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    try:
        conn = get_conn()
        candidates = fetch_candidates(conn, args.limit, args.person_id)
        log.info(f"Processing {len(candidates)} candidates with model={MODEL}")

        enriched = 0
        for i, person in enumerate(candidates, 1):
            log.info(f"[{i}/{len(candidates)}] {person['full_name']} @ {person['school_name']}")

            try:
                # Find their bio page
                url, html = find_bio_page(person["website"], person["full_name"])
                if not html:
                    log.info(f"    - No bio page found")
                    if not args.dry_run:
                        mark_attempted(conn, person["id"])
                    continue

                log.info(f"    Found bio at: {url}")

                # Extract text around their name
                bio_text = extract_text_around_name(
                    html, person["first_name"], person["last_name"]
                )

                if len(bio_text) < 200:
                    log.info(f"    - Bio text too short ({len(bio_text)} chars)")
                    if not args.dry_run:
                        mark_attempted(conn, person["id"])
                    continue

                # Send to Claude
                extracted = extract_with_llm(client, person, bio_text)
                if not extracted or not any(extracted.values()):
                    log.info(f"    - LLM returned no data")
                    if not args.dry_run:
                        mark_attempted(conn, person["id"])
                    continue

                fields = list(extracted.keys())
                log.info(f"    ✓ Extracted: {fields}")
                update_person_from_llm(conn, person["id"], extracted, dry_run=args.dry_run)
                enriched += 1

            except Exception as e:
                log.error(f"    ✗ Error: {e}")
                if not args.dry_run:
                    mark_attempted(conn, person["id"])

            time.sleep(2)  # Polite delay

        log.info(f"Run complete: {enriched}/{len(candidates)} enriched")
        conn.close()
    finally:
        release_lock()


if __name__ == "__main__":
    main()
