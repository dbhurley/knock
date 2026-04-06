#!/usr/bin/env python3
"""
Knock Daily Digest
Generates a morning briefing for Janet with key business metrics and alerts.
Designed to run daily at 8 AM ET via cron.
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
    return f"\n{'=' * 40}\n  {title}\n{'=' * 40}\n"


def get_new_signals(cur, since):
    """Industry signals from the last 24 hours."""
    cur.execute("""
        SELECT s.signal_type, s.headline, s.confidence, s.impact,
               sc.name AS school_name, s.signal_date
        FROM industry_signals s
        LEFT JOIN schools sc ON s.school_id = sc.id
        WHERE s.created_at >= %s
        ORDER BY s.created_at DESC
    """, (since,))
    return cur.fetchall()


def get_active_searches(cur):
    """All currently active searches with status summary."""
    cur.execute("""
        SELECT s.search_number, s.position_title, s.status,
               sc.name AS school_name, sc.state,
               s.candidates_identified, s.candidates_presented,
               s.candidates_interviewed, s.finalists,
               s.status_changed_at, s.created_at
        FROM searches s
        LEFT JOIN schools sc ON s.school_id = sc.id
        WHERE s.status NOT IN ('closed', 'cancelled', 'completed')
        ORDER BY s.created_at DESC
    """)
    return cur.fetchall()


def get_recently_changed_people(cur, since):
    """People records that were updated in the last 24 hours."""
    cur.execute("""
        SELECT full_name, current_title, current_organization,
               candidate_status, updated_at
        FROM people
        WHERE updated_at >= %s
        ORDER BY updated_at DESC
        LIMIT 20
    """, (since,))
    return cur.fetchall()


def get_upcoming_transitions(cur):
    """Schools with predicted leadership transitions in the next 6 months."""
    six_months = datetime.now().date() + timedelta(days=180)
    cur.execute("""
        SELECT name, state, current_hos_name, hos_tenure_years,
               transition_prediction_score, predicted_transition_date,
               predicted_transition_window, enrollment_total
        FROM schools
        WHERE predicted_transition_date IS NOT NULL
          AND predicted_transition_date <= %s
          AND predicted_transition_date >= CURRENT_DATE
          AND is_active = true
        ORDER BY predicted_transition_date ASC
        LIMIT 15
    """, (six_months,))
    return cur.fetchall()


def get_high_transition_scores(cur):
    """Schools with high transition prediction scores (no specific date needed)."""
    cur.execute("""
        SELECT name, state, current_hos_name, hos_tenure_years,
               transition_prediction_score, enrollment_total
        FROM schools
        WHERE transition_prediction_score >= 70
          AND is_active = true
        ORDER BY transition_prediction_score DESC
        LIMIT 10
    """)
    return cur.fetchall()


def get_quick_stats(cur):
    """Database summary stats."""
    stats = {}
    cur.execute("SELECT COUNT(*) FROM people")
    stats["total_people"] = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM people WHERE candidate_status = 'active'")
    stats["active_candidates"] = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM schools WHERE is_active = true")
    stats["active_schools"] = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM searches WHERE status NOT IN ('closed', 'cancelled', 'completed')")
    stats["active_searches"] = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM searches WHERE status IN ('completed')")
    stats["completed_searches"] = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM industry_signals WHERE created_at >= NOW() - INTERVAL '24 hours'")
    stats["signals_24h"] = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM person_interactions WHERE follow_up_date IS NOT NULL AND follow_up_date <= CURRENT_DATE AND outcome IS NULL")
    stats["overdue_followups"] = cur.fetchone()["count"]
    return stats


def format_report():
    conn = get_connection()
    cur = conn.cursor()
    since = datetime.now() - timedelta(hours=24)
    today = datetime.now().strftime("%A, %B %d, %Y")

    lines = []
    lines.append(f"KNOCK DAILY DIGEST - {today}")
    lines.append("=" * 50)

    # Quick stats
    stats = get_quick_stats(cur)
    lines.append(section("DASHBOARD"))
    lines.append(f"  Active Searches:     {stats['active_searches']}")
    lines.append(f"  Completed Searches:  {stats['completed_searches']}")
    lines.append(f"  People in Database:  {stats['total_people']:,}")
    lines.append(f"  Active Candidates:   {stats['active_candidates']}")
    lines.append(f"  Active Schools:      {stats['active_schools']:,}")
    lines.append(f"  Signals (24h):       {stats['signals_24h']}")
    lines.append(f"  Overdue Follow-ups:  {stats['overdue_followups']}")

    # New industry signals
    signals = get_new_signals(cur, since)
    lines.append(section("NEW INDUSTRY SIGNALS (24h)"))
    if signals:
        for s in signals:
            school = s["school_name"] or "General"
            lines.append(f"  [{s['signal_type']}] {s['headline']}")
            lines.append(f"    School: {school} | Confidence: {s['confidence']} | Impact: {s['impact']}")
    else:
        lines.append("  No new signals in the last 24 hours.")

    # Active searches
    searches = get_active_searches(cur)
    lines.append(section("ACTIVE SEARCHES"))
    if searches:
        for s in searches:
            school = s["school_name"] or "TBD"
            state = s["state"] or ""
            loc = f"{school}, {state}" if state else school
            pipeline = (
                f"ID:{s['candidates_identified'] or 0} / "
                f"PR:{s['candidates_presented'] or 0} / "
                f"IV:{s['candidates_interviewed'] or 0} / "
                f"FN:{s['finalists'] or 0}"
            )
            lines.append(f"  {s['search_number'] or 'N/A'}: {s['position_title']}")
            lines.append(f"    {loc} | Status: {s['status']} | Pipeline: {pipeline}")
    else:
        lines.append("  No active searches.")

    # Recently changed people
    people = get_recently_changed_people(cur, since)
    lines.append(section("PEOPLE UPDATED (24h)"))
    if people:
        for p in people:
            org = p["current_organization"] or "N/A"
            title = p["current_title"] or "N/A"
            lines.append(f"  {p['full_name']} - {title} at {org}")
            lines.append(f"    Status: {p['candidate_status']} | Updated: {p['updated_at'].strftime('%Y-%m-%d %H:%M') if p['updated_at'] else 'N/A'}")
    else:
        lines.append("  No people records changed in the last 24 hours.")

    # Upcoming transitions
    transitions = get_upcoming_transitions(cur)
    lines.append(section("PREDICTED TRANSITIONS (Next 6 Months)"))
    if transitions:
        for t in transitions:
            hos = t["current_hos_name"] or "Unknown"
            score = t["transition_prediction_score"] or 0
            pred_date = t["predicted_transition_date"].strftime("%Y-%m") if t["predicted_transition_date"] else "N/A"
            enrollment = t["enrollment_total"] or 0
            lines.append(f"  {t['name']} ({t['state']})")
            lines.append(f"    HoS: {hos} ({t['hos_tenure_years'] or '?'} yrs) | Score: {score:.0f} | Date: {pred_date} | Enroll: {enrollment}")
    else:
        # Fall back to high-score transitions
        high_scores = get_high_transition_scores(cur)
        if high_scores:
            lines.append("  No date-specific predictions, but high-score schools:")
            for t in high_scores:
                hos = t["current_hos_name"] or "Unknown"
                score = t["transition_prediction_score"] or 0
                lines.append(f"  {t['name']} ({t['state']})")
                lines.append(f"    HoS: {hos} ({t['hos_tenure_years'] or '?'} yrs) | Score: {score:.0f} | Enroll: {t['enrollment_total'] or 0}")
        else:
            lines.append("  No transition predictions available.")

    lines.append("\n" + "=" * 50)
    lines.append(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
    lines.append("=" * 50)

    cur.close()
    conn.close()
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        report = format_report()
        print(report)
    except Exception as e:
        print(f"ERROR generating daily digest: {e}", file=sys.stderr)
        sys.exit(1)
