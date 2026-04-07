#!/usr/bin/env python3
"""
newsletter.py — Knock newsletter management.

Two newsletter lists:
  - heads-of-school: Industry insights for current HOS
  - school-board-members: Board briefings for trustees

Commands:
  python3 newsletter.py sync                              # Refresh subscriber lists from people table
  python3 newsletter.py lists                             # Show all lists with counts
  python3 newsletter.py campaigns                         # Show recent campaigns
  python3 newsletter.py draft <list-slug> --subject "..."  --body-file body.html
  python3 newsletter.py send <campaign-id> [--test EMAIL] # Send a campaign
  python3 newsletter.py preview <campaign-id>             # Preview the email
"""

import os
import sys
import json
import re
import argparse
import smtplib
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, formatdate

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Install: pip install psycopg2-binary")
    sys.exit(1)

DB_URL       = os.getenv("DATABASE_URL", "postgresql://knock_admin:knock@localhost:5432/knock")
SMTP_HOST    = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "25"))
FROM_EMAIL   = os.getenv("FROM_EMAIL", "janet@askknock.com")
FROM_NAME    = os.getenv("FROM_NAME", "Janet at Knock")
UNSUB_BASE   = "https://askknock.com/unsubscribe"


def get_conn():
    return psycopg2.connect(DB_URL)


# ── Sync subscribers from audience query ─────────────────────────────────────
def sync_lists(conn, dry_run=False):
    """Refresh subscriptions from each list's audience_query."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, slug, name, audience_query FROM newsletter_lists WHERE is_active = TRUE")
        lists = cur.fetchall()

    for lst in lists:
        print(f"\n=== {lst['name']} ({lst['slug']}) ===")
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            try:
                cur.execute(lst["audience_query"])
                candidates = cur.fetchall()
            except Exception as e:
                print(f"  Query error: {e}")
                continue

        added = 0
        already = 0
        for row in candidates:
            person_id = row.get("id")
            email = (row.get("email_primary") or "").lower().strip()
            if not email or "@" not in email:
                continue

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO newsletter_subscriptions (list_id, person_id, email_address, status)
                    VALUES (%s, %s, %s, 'active')
                    ON CONFLICT (list_id, email_address) DO NOTHING
                    RETURNING id
                """, (lst["id"], person_id, email))
                if cur.fetchone():
                    added += 1
                else:
                    already += 1

        # Update count
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE newsletter_lists SET subscriber_count = (
                    SELECT COUNT(*) FROM newsletter_subscriptions
                    WHERE list_id = %s AND status = 'active'
                ), updated_at = NOW() WHERE id = %s
            """, (lst["id"], lst["id"]))

        if not dry_run:
            conn.commit()

        print(f"  Added {added} new subscribers ({already} already on list)")
        print(f"  Total active: {get_active_count(conn, lst['id'])}")


def get_active_count(conn, list_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM newsletter_subscriptions
            WHERE list_id = %s AND status = 'active'
        """, (list_id,))
        return cur.fetchone()[0]


# ── List operations ───────────────────────────────────────────────────────────
def list_lists(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT slug, name, description, subscriber_count FROM newsletter_lists ORDER BY name")
        for r in cur.fetchall():
            print(f"\n[{r['slug']}] {r['name']}")
            print(f"   {r['description']}")
            print(f"   {r['subscriber_count']} active subscribers")


def list_campaigns(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT c.id, c.subject, c.status, c.sent_count, c.created_at, l.name AS list_name
            FROM newsletter_campaigns c
            JOIN newsletter_lists l ON c.list_id = l.id
            ORDER BY c.created_at DESC LIMIT 20
        """)
        for r in cur.fetchall():
            print(f"\n{r['id']} | {r['status']:<10} | {r['list_name']}")
            print(f"   {r['subject']}")
            print(f"   Sent: {r['sent_count']} | Created: {r['created_at']}")


# ── Draft a campaign ──────────────────────────────────────────────────────────
def draft_campaign(conn, list_slug, subject, body_path):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, name FROM newsletter_lists WHERE slug = %s", (list_slug,))
        lst = cur.fetchone()
    if not lst:
        print(f"List '{list_slug}' not found")
        return

    if not os.path.exists(body_path):
        print(f"Body file not found: {body_path}")
        return

    with open(body_path, "r") as f:
        body_html = f.read()

    body_text = re.sub(r"<[^>]+>", "", body_html)
    body_text = re.sub(r"\s+", " ", body_text).strip()

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO newsletter_campaigns (list_id, subject, body_html, body_text, status)
            VALUES (%s, %s, %s, %s, 'draft')
            RETURNING id
        """, (lst["id"], subject, body_html, body_text))
        campaign_id = cur.fetchone()[0]
    conn.commit()

    print(f"✓ Draft created: {campaign_id}")
    print(f"  List: {lst['name']}")
    print(f"  Subject: {subject}")
    print(f"\nNext: python3 newsletter.py preview {campaign_id}")
    print(f"Then: python3 newsletter.py send {campaign_id} --test you@example.com")


# ── Preview ───────────────────────────────────────────────────────────────────
def preview_campaign(conn, campaign_id):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT c.*, l.name AS list_name, l.subscriber_count
            FROM newsletter_campaigns c JOIN newsletter_lists l ON c.list_id = l.id
            WHERE c.id = %s
        """, (campaign_id,))
        c = cur.fetchone()
    if not c:
        print("Campaign not found")
        return

    print(f"\n══════════════════════════════════════════════════════════════")
    print(f"Campaign: {c['id']}")
    print(f"List:     {c['list_name']} ({c['subscriber_count']} subscribers)")
    print(f"Subject:  {c['subject']}")
    print(f"Status:   {c['status']}")
    print(f"══════════════════════════════════════════════════════════════")
    print(f"\n--- HTML BODY ---\n{c['body_html'][:1500]}")
    print(f"\n--- TEXT BODY ---\n{c['body_text'][:800]}")


# ── Send a campaign ───────────────────────────────────────────────────────────
def send_campaign(conn, campaign_id, test_email=None):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT c.*, l.name AS list_name, l.from_email, l.from_name, l.id AS list_id
            FROM newsletter_campaigns c JOIN newsletter_lists l ON c.list_id = l.id
            WHERE c.id = %s
        """, (campaign_id,))
        c = cur.fetchone()
    if not c:
        print("Campaign not found")
        return

    if test_email:
        recipients = [{"email_address": test_email, "id": None, "person_id": None}]
        print(f"TEST MODE: sending only to {test_email}")
    else:
        if c["status"] == "sent":
            print("Campaign already sent")
            return
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, person_id, email_address FROM newsletter_subscriptions
                WHERE list_id = %s AND status = 'active'
            """, (c["list_id"],))
            recipients = cur.fetchall()
        print(f"Sending to {len(recipients)} subscribers...")
        with conn.cursor() as cur:
            cur.execute("UPDATE newsletter_campaigns SET status = 'sending' WHERE id = %s", (campaign_id,))
        conn.commit()

    sent = 0
    failed = 0
    smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT)

    for r in recipients:
        try:
            email = r["email_address"]
            msg = MIMEMultipart("alternative")
            msg["Subject"] = c["subject"]
            msg["From"] = f'{c.get("from_name", FROM_NAME)} <{c.get("from_email", FROM_EMAIL)}>'
            msg["To"] = email
            msg["Message-ID"] = make_msgid(domain="askknock.com")
            msg["Date"] = formatdate(localtime=True)
            msg["List-Unsubscribe"] = f"<mailto:janet@askknock.com?subject=unsubscribe>, <{UNSUB_BASE}?email={email}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

            html = c["body_html"]
            html = html.replace("{{email}}", email)
            html += f'\n<p style="font-size:11px;color:#999;margin-top:3em;border-top:1px solid #eee;padding-top:1em;">You are receiving this from Knock Executive Search. <a href="{UNSUB_BASE}?email={email}">Unsubscribe</a></p>'

            msg.attach(MIMEText(c["body_text"] + f"\n\n---\nUnsubscribe: {UNSUB_BASE}?email={email}", "plain"))
            msg.attach(MIMEText(html, "html"))

            smtp.sendmail(c.get("from_email", FROM_EMAIL), [email], msg.as_string())
            sent += 1

            if not test_email and r.get("id"):
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO newsletter_sends (campaign_id, subscription_id, email_address, status, sent_at)
                        VALUES (%s, %s, %s, 'sent', NOW())
                        ON CONFLICT (campaign_id, subscription_id) DO UPDATE SET status = 'sent', sent_at = NOW()
                    """, (campaign_id, r["id"], email))
                    cur.execute("""
                        UPDATE newsletter_subscriptions SET last_sent_at = NOW() WHERE id = %s
                    """, (r["id"],))
                conn.commit()

            if sent % 50 == 0:
                print(f"  ... {sent}/{len(recipients)} sent")
            time.sleep(0.1)  # Polite throttle
        except Exception as e:
            failed += 1
            print(f"  ✗ {r.get('email_address', '?')}: {e}")

    smtp.quit()

    if not test_email:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE newsletter_campaigns
                SET status = 'sent', sent_at = NOW(), sent_count = %s
                WHERE id = %s
            """, (sent, campaign_id))
        conn.commit()

    print(f"\n✓ Sent: {sent} | ✗ Failed: {failed}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Knock newsletter management")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync", help="Refresh subscriber lists from audience queries")
    sub.add_parser("lists", help="Show all newsletter lists")
    sub.add_parser("campaigns", help="Show recent campaigns")

    p_draft = sub.add_parser("draft", help="Create a campaign draft")
    p_draft.add_argument("list_slug")
    p_draft.add_argument("--subject", required=True)
    p_draft.add_argument("--body-file", required=True)

    p_preview = sub.add_parser("preview", help="Preview a campaign")
    p_preview.add_argument("campaign_id")

    p_send = sub.add_parser("send", help="Send a campaign")
    p_send.add_argument("campaign_id")
    p_send.add_argument("--test", help="Send only to test email")

    args = parser.parse_args()
    conn = get_conn()

    try:
        if args.cmd == "sync":
            sync_lists(conn)
        elif args.cmd == "lists":
            list_lists(conn)
        elif args.cmd == "campaigns":
            list_campaigns(conn)
        elif args.cmd == "draft":
            draft_campaign(conn, args.list_slug, args.subject, args.body_file)
        elif args.cmd == "preview":
            preview_campaign(conn, args.campaign_id)
        elif args.cmd == "send":
            send_campaign(conn, args.campaign_id, args.test)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
