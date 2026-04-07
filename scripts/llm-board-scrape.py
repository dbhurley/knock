#!/usr/bin/env python3
"""
llm-board-scrape.py — Extract school board members using Claude.

Board members hire heads of school. They are Knock's actual buyers — the
people we need to know to get search engagements. This script:

  1. Picks schools with websites that don't have board members yet
  2. Crawls the school site looking for board/trustees pages
  3. Sends the page text to Claude to extract structured board info
  4. Inserts records into school_board_members
  5. Creates person records for board members where appropriate

Cost: ~$0.02-0.05 per school (varies by board size).

Usage:
  python3 llm-board-scrape.py                  # process default batch
  python3 llm-board-scrape.py --limit 25       # specific batch size
  python3 llm-board-scrape.py --school-id <id> # one specific school
  python3 llm-board-scrape.py --dry-run        # preview only
"""

import os
import sys
import json
import re
import time
import logging
import argparse
import urllib.parse
from datetime import datetime

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
LOG_FILE        = "/opt/knock/logs/llm-board-scrape.log"
USER_AGENT      = "Mozilla/5.0 (Knock Recruitment Research Bot; +https://askknock.com)"
TIMEOUT         = 15
MAX_TOKENS      = 4000  # Boards can be 20+ people
LOCK_FILE       = "/tmp/knock-llm-board.lock"

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


def fetch_schools_needing_board(conn, limit, school_id=None):
    """Get schools with websites that don't have current board members yet."""
    where_extra = "AND s.id = %s" if school_id else ""
    sql = f"""
        SELECT
            s.id, s.name, s.website, s.city, s.state,
            s.enrollment_total, s.school_type, s.religious_affiliation
        FROM schools s
        WHERE s.website IS NOT NULL
          AND s.website != ''
          AND s.is_active = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM school_board_members sbm
              WHERE sbm.school_id = s.id
                AND sbm.is_current = TRUE
          )
          {where_extra}
        ORDER BY s.enrollment_total DESC NULLS LAST
        LIMIT %s
    """
    params = (school_id, limit) if school_id else (limit,)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def insert_board_members(conn, school_id, members, dry_run=False):
    """Insert board members and create person records where possible."""
    if dry_run:
        log.info(f"  [DRY RUN] Would insert {len(members)} board members:")
        for m in members:
            log.info(f"    - {m.get('name', '?'):<35} | {m.get('role', '?')}")
        return len(members)

    inserted = 0
    with conn.cursor() as cur:
        for m in members:
            name = m.get("name", "").strip()
            if not name or len(name) < 3:
                continue

            role = (m.get("role") or "member").strip().lower()
            # Normalize role
            role_map = {
                "chair": "chair",
                "chairperson": "chair",
                "president": "chair",
                "vice chair": "vice_chair",
                "vice-chair": "vice_chair",
                "vice president": "vice_chair",
                "treasurer": "treasurer",
                "secretary": "secretary",
                "trustee": "member",
                "board member": "member",
                "director": "member",
            }
            normalized_role = role_map.get(role, role[:50])

            # Try to find or create a person record
            person_id = None
            parts = name.split()
            if len(parts) >= 2:
                first = parts[0]
                last = parts[-1]
                # Look for existing person by name
                cur.execute("""
                    SELECT id FROM people
                    WHERE LOWER(first_name) = LOWER(%s)
                      AND LOWER(last_name) = LOWER(%s)
                    LIMIT 1
                """, (first, last))
                row = cur.fetchone()
                if row:
                    person_id = row[0]
                else:
                    # Create new person record marked as a board member contact
                    cur.execute("""
                        INSERT INTO people (
                            first_name, last_name, full_name, name_normalized,
                            current_title, current_organization, current_school_id,
                            primary_role, candidate_status, data_source,
                            tags, notes
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s
                        )
                        RETURNING id
                    """, (
                        first[:100],
                        last[:100],
                        name[:300],
                        re.sub(r"[^a-z0-9 ]", "", name.lower())[:300],
                        f"Board {normalized_role.replace('_', ' ').title()}",
                        None,  # We don't know their day job
                        school_id,
                        "board_member",
                        "passive",
                        "board_scrape",
                        ["board_member"],
                        f"Discovered as {normalized_role} on board scrape",
                    ))
                    person_id = cur.fetchone()[0]

            # Insert the board member record
            cur.execute("""
                INSERT INTO school_board_members (
                    school_id, person_id, name, role, is_current
                ) VALUES (
                    %s, %s, %s, %s, TRUE
                )
                ON CONFLICT DO NOTHING
            """, (school_id, person_id, name[:300], normalized_role))
            inserted += 1

    conn.commit()
    return inserted


def mark_school_attempted(conn, school_id):
    """Insert a placeholder record to avoid retrying schools with no board page."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE schools SET last_verified_at = NOW() WHERE id = %s
        """, (school_id,))
    conn.commit()


# ── Web fetch with board page discovery ─────────────────────────────────────
BOARD_KEYWORDS = [
    "board of trustees", "board-of-trustees",
    "board of directors", "board-of-directors",
    "trustees", "directors",
    "governance", "leadership",
    "our board", "our-board",
    "school board", "school-board",
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


def find_board_page(homepage_url):
    """Find the page on this school's site that lists board members."""
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
        for kw in BOARD_KEYWORDS:
            kw_norm = kw.replace(" ", "")
            if kw in path_lower or kw_norm in path_lower:
                score += 5  # URL match is strong signal
            if kw in text:
                score += 3  # Link text match is also strong

        # Bonus if "board" or "trustees" appears in the URL at all
        if "board" in path_lower or "trustee" in path_lower:
            score += 2

        if score > 0:
            candidates.append((score, full_url, text))

    candidates.sort(key=lambda x: -x[0])

    # Try the top 4 candidates
    for score, url, text in candidates[:4]:
        log.info(f"    Trying ({score}): {url}")
        page_html = fetch_url(url)
        if not page_html:
            continue
        # Quick sanity check: does this page actually mention "board" or "trustees"?
        page_lower = page_html.lower()
        if ("board" in page_lower or "trustee" in page_lower) and (
            "chair" in page_lower or "president" in page_lower or "member" in page_lower
        ):
            return url, page_html
        time.sleep(0.5)

    return None, None


def extract_text_for_llm(html, max_chars=8000):
    """Extract clean text from HTML, optimized for LLM consumption."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text[:max_chars]


# ── LLM extraction ────────────────────────────────────────────────────────────
EXTRACTION_PROMPT = """You are extracting board members from a school's board of trustees / governance page.

SCHOOL: {school_name}
LOCATION: {location}

PAGE TEXT:
{page_text}

Extract every individual board member listed on this page. Return ONLY valid JSON.

Schema:
{{
  "members": [
    {{
      "name": "Full Name (as displayed)",
      "role": "chair|vice_chair|treasurer|secretary|member|president|trustee|director",
      "title": "Optional outside professional title (CEO of Acme Corp, etc.)",
      "notes": "Optional brief context (alumni, parent of '24, etc.)"
    }}
  ]
}}

Rules:
- Include EVERYONE listed on the board, including officers (chair, treasurer, etc.)
- Use lowercase role names from the list above
- If a person is listed as Chairman, Chairperson, or President of the Board, use "chair"
- If listed as Vice Chair / Vice Chairman / Vice President, use "vice_chair"
- If just listed as a board member or trustee, use "member"
- Include their professional title/affiliation if shown (e.g., "CEO of Acme Corp", "Partner at Smith & Jones")
- DO NOT include staff, head of school, or administration — only BOARD members
- DO NOT include emeritus or former members unless the section header explicitly says "current"
- DO NOT invent or speculate. If the page doesn't list board members clearly, return: {{"members": []}}
- Names should be the full name as displayed (preserve middle initials, suffixes)

Return ONLY the JSON object."""


def extract_with_llm(client, school, page_text):
    """Call Claude to extract board member list."""
    prompt = EXTRACTION_PROMPT.format(
        school_name=school["name"],
        location=f"{school.get('city', '')}, {school.get('state', '')}",
        page_text=page_text,
    )

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

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
    parser = argparse.ArgumentParser(description="LLM board member scraper")
    parser.add_argument("--limit", type=int, default=10, help="Number of schools to process")
    parser.add_argument("--school-id", type=str, help="Process a specific school by UUID")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args()

    if not acquire_lock():
        log.info("Another instance is running, exiting")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    try:
        conn = get_conn()
        schools = fetch_schools_needing_board(conn, args.limit, args.school_id)
        log.info(f"Processing {len(schools)} schools with model={MODEL}")

        total_members = 0
        successful_schools = 0

        for i, school in enumerate(schools, 1):
            log.info(f"[{i}/{len(schools)}] {school['name']} ({school.get('enrollment_total', '?')} students)")

            try:
                # Find the board page
                url, html = find_board_page(school["website"])
                if not html:
                    log.info(f"    - No board page found")
                    if not args.dry_run:
                        mark_school_attempted(conn, school["id"])
                    continue

                log.info(f"    Found board page: {url}")

                # Extract text and send to Claude
                page_text = extract_text_for_llm(html)
                if len(page_text) < 200:
                    log.info(f"    - Page text too short")
                    if not args.dry_run:
                        mark_school_attempted(conn, school["id"])
                    continue

                extracted = extract_with_llm(client, school, page_text)
                if not extracted:
                    log.info(f"    - LLM returned no data")
                    if not args.dry_run:
                        mark_school_attempted(conn, school["id"])
                    continue

                members = extracted.get("members", [])
                if not members:
                    log.info(f"    - No board members extracted")
                    if not args.dry_run:
                        mark_school_attempted(conn, school["id"])
                    continue

                inserted = insert_board_members(conn, school["id"], members, dry_run=args.dry_run)
                log.info(f"    ✓ Extracted {len(members)} board members ({inserted} inserted)")
                total_members += inserted
                successful_schools += 1

            except Exception as e:
                log.error(f"    ✗ Error: {e}")
                if not args.dry_run:
                    mark_school_attempted(conn, school["id"])

            time.sleep(2)  # Polite delay

        log.info(f"Run complete: {successful_schools}/{len(schools)} schools | {total_members} board members added")
        conn.close()
    finally:
        release_lock()


if __name__ == "__main__":
    main()
