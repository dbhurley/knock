#!/usr/bin/env python3
"""
enrich-contacts-v2.py — Smarter contact enrichment

Replaces enrich-contacts.py. Uses requests + BeautifulSoup to find:
  - mailto: links (most reliable email source)
  - Structured data (JSON-LD, microdata)
  - Phone numbers in tel: links and visible text

Strategy:
  1. Pick people who are linked to a school with a website
  2. Visit the school website
  3. Look for the person's name on /faculty/, /staff/, /directory/, /about pages
  4. Extract mailto: and tel: links near the name
  5. Update the database

Run via cron — gentle, ~10 records per run, polite delays.
"""

import os
import sys
import json
import re
import time
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta

try:
    import psycopg2
    import psycopg2.extras
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install psycopg2-binary requests beautifulsoup4")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
DB_URL          = os.getenv("DATABASE_URL", "postgresql://knock_admin:knock@localhost:5432/knock")
BATCH_SIZE      = int(os.getenv("ENRICH_BATCH_SIZE", "10"))
DELAY_BETWEEN   = float(os.getenv("ENRICH_DELAY_SEC", "5"))
STALE_DAYS      = int(os.getenv("ENRICH_STALE_DAYS", "30"))
LOG_FILE        = "/opt/knock/logs/enrich-contacts-v2.log"
LOCK_FILE       = "/tmp/knock-enrich-v2.lock"
USER_AGENT      = "Mozilla/5.0 (Knock Recruitment Research Bot; +https://askknock.com)"
TIMEOUT         = 15

# Keywords that indicate a leadership/staff page (used to filter homepage links)
LEADERSHIP_KEYWORDS = [
    "leadership", "head of school", "headmaster", "headmistress",
    "head-of-school", "administration", "faculty", "staff", "directory",
    "our team", "our-team", "about us", "about-us", "about/leadership",
    "meet our", "meet-our", "people", "contact",
]

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
            os.kill(pid, 0)  # Check if process exists
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


def fetch_pending_people(conn, limit):
    """Get people linked to schools with websites who need enrichment.

    Targets people who:
      - Have a linked school with a website
      - Have first+last names (so we can match them on the page)
      - Are missing a phone OR have only an inferred (unverified) email
      - Were not attempted in the last STALE_DAYS days
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
                p.id, p.first_name, p.last_name, p.full_name,
                p.email_primary, p.phone_primary,
                p.current_title, p.current_organization,
                s.id AS school_id, s.name AS school_name, s.website AS school_website
            FROM people p
            JOIN schools s ON p.current_school_id = s.id
            WHERE s.website IS NOT NULL
              AND s.website != ''
              AND p.first_name IS NOT NULL
              AND p.last_name IS NOT NULL
              AND (
                  p.last_enriched_at IS NULL
                  OR p.last_enriched_at < NOW() - INTERVAL '%s days'
              )
              AND (
                  -- Missing phone
                  p.phone_primary IS NULL OR p.phone_primary = ''
                  -- Or has only an unverified inferred email
                  OR p.email_primary IN (
                      SELECT email_address FROM inferred_emails
                      WHERE verification_status IS NULL
                         OR verification_status NOT IN ('valid', 'catch_all')
                  )
              )
            ORDER BY
                -- Heads of school first
                CASE WHEN p.primary_role = 'head_of_school' THEN 0 ELSE 1 END,
                -- Larger schools have better websites
                s.enrollment_total DESC NULLS LAST,
                p.data_completeness_score DESC NULLS LAST
            LIMIT %s
        """, (STALE_DAYS, limit))
        return cur.fetchall()


def update_person(conn, person_id, fields):
    """Update a person record with enriched fields."""
    if not fields:
        return
    set_clauses = []
    values = []
    for k, v in fields.items():
        set_clauses.append(f"{k} = %s")
        values.append(v)
    set_clauses.append("last_enriched_at = NOW()")
    values.append(person_id)
    sql = f"UPDATE people SET {', '.join(set_clauses)} WHERE id = %s"
    with conn.cursor() as cur:
        cur.execute(sql, values)
    conn.commit()


def mark_attempted(conn, person_id):
    """Update last_enriched_at even on failure to avoid retry storms."""
    with conn.cursor() as cur:
        cur.execute("UPDATE people SET last_enriched_at = NOW() WHERE id = %s", (person_id,))
    conn.commit()


# ── Web fetch ─────────────────────────────────────────────────────────────────
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
    except Exception as e:
        log.debug(f"  fetch failed for {url}: {e}")
    return None


def normalize_url(base, path):
    """Combine base school URL with a faculty path."""
    base = base.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    return base + path


# ── Extraction ────────────────────────────────────────────────────────────────
def find_person_section(soup, first_name, last_name):
    """Find HTML elements that mention this person, return surrounding text+links."""
    full = f"{first_name} {last_name}".lower()
    last = last_name.lower()
    candidates = []

    # Look for any element containing the full name
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "li", "td", "section", "article"]):
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        if full in text.lower():
            # Climb up to find a containing block
            container = tag
            for _ in range(4):
                if container.parent:
                    container = container.parent
            candidates.append(container)

    return candidates


def extract_emails_from_section(section, first_name, last_name):
    """Extract mailto: links from a section, prioritizing ones near the person."""
    emails = []
    fn = first_name.lower()
    ln = last_name.lower()

    # mailto: links are gold
    for link in section.find_all("a", href=True):
        href = link["href"]
        if href.lower().startswith("mailto:"):
            # Strip mailto: prefix and any URL params
            email = href.split(":", 1)[1].split("?")[0].strip()
            # Strip any leading/trailing junk
            email = email.strip("<>\"' \t\r\n")
            if "@" in email and "." in email:
                emails.append(email)

    # Also look for plaintext emails matching the person's name pattern
    text = section.get_text(" ", strip=True)
    plaintext = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    for email in plaintext:
        local = email.split("@")[0].lower()
        if fn in local or ln in local:
            emails.append(email)

    # Filter out generic / role-based addresses
    skip_locals = {
        "info", "admin", "webmaster", "noreply", "no-reply", "contact",
        "office", "inquiry", "inquiries", "hello", "support", "help",
        "general", "secretary", "marketing", "communications", "alumni",
        "development", "advancement", "press", "media", "news", "events",
        "registrar", "billing", "finance", "accounting", "sales",
    }

    # Filter and de-duplicate while preserving order
    seen = set()
    filtered = []
    for e in emails:
        local = e.split("@")[0].lower()
        if local in skip_locals:
            continue
        if e in seen:
            continue
        seen.add(e)
        filtered.append(e)

    # Prioritize emails containing the person's name
    name_match = [e for e in filtered if fn in e.split("@")[0].lower() or ln in e.split("@")[0].lower()]
    other = [e for e in filtered if e not in name_match]
    return name_match + other


def extract_phones_from_section(section, first_name, last_name):
    """Extract phone numbers from a section."""
    phones = []
    # tel: links are most reliable
    for link in section.find_all("a", href=True):
        href = link["href"]
        if href.lower().startswith("tel:"):
            phone = re.sub(r"[^\d+]", "", href[4:])
            if len(phone) >= 10:
                phones.append(phone)

    # Also look for visible phone patterns
    text = section.get_text(" ", strip=True)
    visible = re.findall(r"\(?\b\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b", text)
    for phone in visible:
        cleaned = re.sub(r"\D", "", phone)
        if len(cleaned) == 10:
            phones.append(cleaned)

    return phones


def discover_leadership_urls(homepage_url, max_urls=8):
    """Fetch the homepage and find candidate leadership/staff page URLs."""
    html = fetch_url(homepage_url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    seen = set()

    base_parsed = urllib.parse.urlparse(homepage_url)
    base_host = base_parsed.netloc

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(" ", strip=True).lower()

        # Resolve relative URLs
        full_url = urllib.parse.urljoin(homepage_url, href)
        parsed = urllib.parse.urlparse(full_url)

        # Same-domain only
        if parsed.netloc and parsed.netloc != base_host:
            continue

        # Skip anchors, mailto, tel, etc.
        if parsed.scheme not in ("http", "https"):
            continue

        # Score based on keyword matches in the URL or link text
        path_lower = parsed.path.lower()
        score = 0
        for kw in LEADERSHIP_KEYWORDS:
            kw_norm = kw.replace(" ", "")
            if kw in path_lower or kw_norm in path_lower:
                score += 2
            if kw in text:
                score += 1

        if score > 0 and full_url not in seen:
            seen.add(full_url)
            candidates.append((score, full_url))

    # Sort by score (highest first) and return top N
    candidates.sort(key=lambda x: -x[0])
    return [url for _, url in candidates[:max_urls]]


def enrich_from_school_site(person):
    """Crawl the school website to find this person's contact info."""
    website = person["school_website"]
    if not website:
        return {}

    first = person["first_name"]
    last = person["last_name"]
    if not first or not last:
        return {}

    # Normalize the homepage URL
    homepage = website if website.startswith("http") else "https://" + website
    homepage = homepage.rstrip("/")

    # Discover leadership/staff page URLs from the homepage navigation
    log.info(f"    Discovering pages on {homepage}")
    candidate_urls = discover_leadership_urls(homepage)

    if not candidate_urls:
        log.info(f"    No leadership URLs found on homepage")
        return {}

    log.info(f"    Found {len(candidate_urls)} candidate pages")

    found_emails = []
    found_phones = []

    # Always check the homepage too — sometimes contact info is right there
    pages_to_check = [homepage] + candidate_urls

    for url in pages_to_check:
        log.info(f"    Checking: {url}")
        html = fetch_url(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        # Strip script/style tags
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        sections = find_person_section(soup, first, last)
        if not sections:
            continue

        log.info(f"    ✓ Found {len(sections)} sections mentioning {first} {last}")
        for section in sections:
            emails = extract_emails_from_section(section, first, last)
            phones = extract_phones_from_section(section, first, last)
            found_emails.extend(emails)
            found_phones.extend(phones)

        if found_emails or found_phones:
            log.info(f"    ✓ Extracted emails={len(found_emails)} phones={len(found_phones)}")
            break  # Stop after first successful extraction

        time.sleep(1)  # Delay between page attempts

    result = {}
    if found_emails:
        # Pick the first email (prefer ones with the person's name in the local part)
        for email in found_emails:
            local = email.split("@")[0].lower()
            if last.lower() in local:
                result["email_primary"] = email
                break
        if "email_primary" not in result:
            result["email_primary"] = found_emails[0]

    if found_phones:
        result["phone_primary"] = found_phones[0]

    return result


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not acquire_lock():
        log.info("Another instance is running, exiting")
        return

    try:
        conn = get_conn()
        people = fetch_pending_people(conn, BATCH_SIZE)
        log.info(f"Processing {len(people)} people...")

        enriched = 0
        for i, person in enumerate(people, 1):
            log.info(f"  [{i}/{len(people)}] {person['full_name']} @ {person['school_name']}")
            try:
                fields = enrich_from_school_site(person)
                if fields:
                    update_person(conn, person["id"], fields)
                    enriched += 1
                    log.info(f"    ✓ Enriched: {list(fields.keys())}")
                else:
                    mark_attempted(conn, person["id"])
                    log.info(f"    - No data found")
            except Exception as e:
                log.error(f"    ✗ Error: {e}")
                mark_attempted(conn, person["id"])

            if i < len(people):
                time.sleep(DELAY_BETWEEN)

        log.info(f"Run complete: {enriched} enriched, {len(people) - enriched} skipped")
        conn.close()
    finally:
        release_lock()


if __name__ == "__main__":
    main()
