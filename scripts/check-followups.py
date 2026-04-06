#!/usr/bin/env python3
"""
Knock Follow-Up Reminder System
Checks for overdue follow-ups and stalled search activities.
Designed to run every 6 hours via cron.
"""

import os
import sys
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def section(title):
    return f"\n{'=' * 45}\n  {title}\n{'=' * 45}\n"


def get_overdue_person_followups(cur):
    """Person interactions with overdue follow-up dates."""
    cur.execute("""
        SELECT pi.follow_up_date, pi.follow_up_notes, pi.interaction_type,
               pi.subject, pi.direction, pi.conducted_by, pi.created_at,
               p.full_name, p.current_title, p.current_organization,
               p.email_primary, p.phone_primary,
               (CURRENT_DATE - pi.follow_up_date) AS days_overdue
        FROM person_interactions pi
        JOIN people p ON pi.person_id = p.id
        WHERE pi.follow_up_date IS NOT NULL
          AND pi.follow_up_date <= CURRENT_DATE
          AND pi.outcome IS NULL
        ORDER BY pi.follow_up_date ASC
    """)
    return cur.fetchall()


def get_stalled_search_activities(cur):
    """Active searches where last activity is more than 7 days old."""
    cur.execute("""
        WITH last_activity AS (
            SELECT search_id, MAX(created_at) AS last_act
            FROM search_activities
            GROUP BY search_id
        )
        SELECT s.search_number, s.position_title, s.status,
               sc.name AS school_name, sc.state,
               s.client_contact_name, s.client_contact_email,
               la.last_act,
               EXTRACT(DAY FROM NOW() - COALESCE(la.last_act, s.created_at)) AS days_since_activity
        FROM searches s
        LEFT JOIN schools sc ON s.school_id = sc.id
        LEFT JOIN last_activity la ON la.search_id = s.id
        WHERE s.status NOT IN ('closed', 'cancelled', 'completed')
          AND COALESCE(la.last_act, s.created_at) < NOW() - INTERVAL '7 days'
        ORDER BY days_since_activity DESC
    """)
    return cur.fetchall()


def get_upcoming_followups(cur):
    """Follow-ups due in the next 3 days (not yet overdue)."""
    three_days = datetime.now().date() + timedelta(days=3)
    cur.execute("""
        SELECT pi.follow_up_date, pi.follow_up_notes, pi.interaction_type,
               pi.subject, pi.conducted_by,
               p.full_name, p.current_title, p.current_organization
        FROM person_interactions pi
        JOIN people p ON pi.person_id = p.id
        WHERE pi.follow_up_date > CURRENT_DATE
          AND pi.follow_up_date <= %s
          AND pi.outcome IS NULL
        ORDER BY pi.follow_up_date ASC
    """, (three_days,))
    return cur.fetchall()


def get_searches_needing_update(cur):
    """Searches with upcoming target start dates that may need attention."""
    thirty_days = datetime.now().date() + timedelta(days=30)
    cur.execute("""
        SELECT s.search_number, s.position_title, s.status, s.target_start_date,
               sc.name AS school_name, sc.state,
               s.candidates_identified, s.candidates_presented, s.finalists,
               (s.target_start_date - CURRENT_DATE) AS days_until_start
        FROM searches s
        LEFT JOIN schools sc ON s.school_id = sc.id
        WHERE s.status NOT IN ('closed', 'cancelled', 'completed')
          AND s.target_start_date IS NOT NULL
          AND s.target_start_date <= %s
        ORDER BY s.target_start_date ASC
    """, (thirty_days,))
    return cur.fetchall()


def format_priority(days_overdue):
    if days_overdue is None:
        return "LOW"
    if days_overdue >= 14:
        return "CRITICAL"
    elif days_overdue >= 7:
        return "HIGH"
    elif days_overdue >= 3:
        return "MEDIUM"
    return "LOW"


def format_report():
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M ET")

    lines = []
    lines.append(f"KNOCK FOLLOW-UP CHECK - {now}")
    lines.append("=" * 50)

    # Overdue person follow-ups
    overdue = get_overdue_person_followups(cur)
    lines.append(section("OVERDUE FOLLOW-UPS"))
    if overdue:
        lines.append(f"  {len(overdue)} overdue follow-up(s) found:\n")
        for item in overdue:
            priority = format_priority(item["days_overdue"])
            days = item["days_overdue"] if item["days_overdue"] is not None else "?"
            org = item["current_organization"] or "N/A"
            lines.append(f"  [{priority}] {item['full_name']} - {days} days overdue")
            lines.append(f"    Role: {item['current_title'] or 'N/A'} at {org}")
            lines.append(f"    Due: {item['follow_up_date']} | Type: {item['interaction_type'] or 'N/A'}")
            if item["follow_up_notes"]:
                notes = item["follow_up_notes"][:100]
                lines.append(f"    Notes: {notes}{'...' if len(item['follow_up_notes']) > 100 else ''}")
            contact = []
            if item["email_primary"]:
                contact.append(item["email_primary"])
            if item["phone_primary"]:
                contact.append(item["phone_primary"])
            if contact:
                lines.append(f"    Contact: {' | '.join(contact)}")
            lines.append("")
    else:
        lines.append("  No overdue follow-ups. All clear!")

    # Upcoming follow-ups (next 3 days)
    upcoming = get_upcoming_followups(cur)
    lines.append(section("UPCOMING FOLLOW-UPS (Next 3 Days)"))
    if upcoming:
        for item in upcoming:
            lines.append(f"  {item['follow_up_date']}: {item['full_name']}")
            lines.append(f"    {item['current_title'] or 'N/A'} at {item['current_organization'] or 'N/A'}")
            if item["follow_up_notes"]:
                lines.append(f"    Notes: {item['follow_up_notes'][:80]}")
    else:
        lines.append("  No follow-ups scheduled in the next 3 days.")

    # Stalled searches
    stalled = get_stalled_search_activities(cur)
    lines.append(section("STALLED SEARCHES (7+ Days Inactive)"))
    if stalled:
        for s in stalled:
            days = int(s["days_since_activity"]) if s["days_since_activity"] else "?"
            school = s["school_name"] or "TBD"
            lines.append(f"  {s['search_number'] or 'N/A'}: {s['position_title']}")
            lines.append(f"    {school}, {s['state'] or ''} | Status: {s['status']} | Inactive: {days} days")
            if s["client_contact_name"]:
                lines.append(f"    Client: {s['client_contact_name']} ({s['client_contact_email'] or 'no email'})")
    else:
        lines.append("  All searches have recent activity.")

    # Searches approaching deadlines
    deadline_searches = get_searches_needing_update(cur)
    lines.append(section("SEARCHES APPROACHING START DATE"))
    if deadline_searches:
        for s in deadline_searches:
            days_left = s["days_until_start"]
            urgency = "OVERDUE" if days_left and days_left < 0 else f"{days_left} days"
            school = s["school_name"] or "TBD"
            lines.append(f"  {s['search_number'] or 'N/A'}: {s['position_title']} at {school}")
            lines.append(f"    Target: {s['target_start_date']} ({urgency}) | Status: {s['status']}")
            lines.append(f"    Pipeline: {s['candidates_identified'] or 0} ID / {s['candidates_presented'] or 0} PR / {s['finalists'] or 0} FN")
    else:
        lines.append("  No searches approaching their start dates.")

    # Summary counts
    total_actions = len(overdue) + len(stalled) + len(deadline_searches)
    lines.append(f"\n{'=' * 50}")
    lines.append(f"  TOTAL ACTION ITEMS: {total_actions}")
    lines.append(f"    Overdue follow-ups: {len(overdue)}")
    lines.append(f"    Stalled searches:   {len(stalled)}")
    lines.append(f"    Deadline alerts:    {len(deadline_searches)}")
    lines.append(f"    Upcoming (3 days):  {len(upcoming)}")
    lines.append(f"{'=' * 50}")

    cur.close()
    conn.close()
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        report = format_report()
        print(report)
    except Exception as e:
        print(f"ERROR generating follow-up check: {e}", file=sys.stderr)
        sys.exit(1)
