#!/usr/bin/env python3
"""
Knock Weekly Pipeline Report
Comprehensive weekly summary of all search activity and data quality.
Designed to run Monday 9 AM ET via cron.
"""

import os
import sys
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from collections import defaultdict

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def section(title):
    return f"\n{'=' * 50}\n  {title}\n{'=' * 50}\n"


def get_searches_by_stage(cur):
    """All active searches grouped by status."""
    cur.execute("""
        SELECT s.search_number, s.position_title, s.status, s.salary_band,
               s.fee_amount, s.fee_status, s.deposit_paid,
               sc.name AS school_name, sc.state,
               s.candidates_identified, s.candidates_presented,
               s.candidates_interviewed, s.finalists,
               s.status_changed_at, s.created_at, s.target_start_date,
               s.lead_consultant
        FROM searches s
        LEFT JOIN schools sc ON s.school_id = sc.id
        WHERE s.status NOT IN ('cancelled')
        ORDER BY
            CASE s.status
                WHEN 'intake' THEN 1
                WHEN 'sourcing' THEN 2
                WHEN 'screening' THEN 3
                WHEN 'presenting' THEN 4
                WHEN 'interviewing' THEN 5
                WHEN 'finalist' THEN 6
                WHEN 'offer' THEN 7
                WHEN 'completed' THEN 8
                WHEN 'closed' THEN 9
                ELSE 10
            END,
            s.created_at DESC
    """)
    return cur.fetchall()


def get_search_candidates_by_search(cur, search_id):
    """Candidates in a specific search pipeline."""
    cur.execute("""
        SELECT sc.status, p.full_name, p.current_title, p.current_organization,
               sc.match_score, sc.created_at, sc.updated_at
        FROM search_candidates sc
        JOIN people p ON sc.person_id = p.id
        WHERE sc.search_id = %s
        ORDER BY sc.match_score DESC NULLS LAST
    """, (search_id,))
    return cur.fetchall()


def get_stalled_searches(cur):
    """Searches with no activity in 7+ days."""
    seven_days_ago = datetime.now() - timedelta(days=7)
    cur.execute("""
        SELECT s.search_number, s.position_title, s.status,
               sc.name AS school_name, sc.state,
               s.status_changed_at,
               (SELECT MAX(sa.created_at) FROM search_activities sa WHERE sa.search_id = s.id) AS last_activity
        FROM searches s
        LEFT JOIN schools sc ON s.school_id = sc.id
        WHERE s.status NOT IN ('closed', 'cancelled', 'completed')
        ORDER BY last_activity ASC NULLS FIRST
    """)
    results = []
    for row in cur.fetchall():
        last_act = row["last_activity"] or row["status_changed_at"] or row["status_changed_at"]
        if last_act is None or last_act < seven_days_ago:
            row["days_stalled"] = (datetime.now() - last_act).days if last_act else None
            results.append(row)
    return results


def get_new_records_this_week(cur):
    """New people and schools added this week."""
    week_ago = datetime.now() - timedelta(days=7)
    stats = {}
    cur.execute("SELECT COUNT(*) FROM people WHERE created_at >= %s", (week_ago,))
    stats["new_people"] = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM schools WHERE created_at >= %s", (week_ago,))
    stats["new_schools"] = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM industry_signals WHERE created_at >= %s", (week_ago,))
    stats["new_signals"] = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM person_interactions WHERE created_at >= %s", (week_ago,))
    stats["new_interactions"] = cur.fetchone()["count"]
    cur.execute("""
        SELECT full_name, current_title, current_organization, state, created_at
        FROM people WHERE created_at >= %s
        ORDER BY created_at DESC LIMIT 15
    """, (week_ago,))
    stats["recent_people"] = cur.fetchall()
    return stats


def get_data_quality_metrics(cur):
    """Data quality: percentage of people with key fields populated."""
    cur.execute("SELECT COUNT(*) FROM people")
    total = cur.fetchone()["count"]
    if total == 0:
        return {"total": 0}

    metrics = {"total": total}
    # Text fields - check for NOT NULL and not empty string
    text_fields = {
        "email_primary": "Has Email",
        "phone_primary": "Has Phone",
        "current_title": "Has Title",
        "current_organization": "Has Organization",
        "city": "Has City",
        "state": "Has State",
        "linkedin_url": "Has LinkedIn",
        "candidate_status": "Has Status",
        "primary_role": "Has Role",
        "career_stage": "Has Career Stage",
    }
    for field, label in text_fields.items():
        cur.execute(f"SELECT COUNT(*) FROM people WHERE {field} IS NOT NULL AND {field} != ''")
        count = cur.fetchone()["count"]
        metrics[label] = {"count": count, "pct": round(count / total * 100, 1)}

    # Numeric fields - just check NOT NULL
    numeric_fields = {
        "knock_rating": "Has Knock Rating",
    }
    for field, label in numeric_fields.items():
        cur.execute(f"SELECT COUNT(*) FROM people WHERE {field} IS NOT NULL")
        count = cur.fetchone()["count"]
        metrics[label] = {"count": count, "pct": round(count / total * 100, 1)}

    # Education records
    cur.execute("SELECT COUNT(DISTINCT person_id) FROM person_education")
    edu_count = cur.fetchone()["count"]
    metrics["Has Education"] = {"count": edu_count, "pct": round(edu_count / total * 100, 1)}

    # Experience records
    cur.execute("SELECT COUNT(DISTINCT person_id) FROM person_experience")
    exp_count = cur.fetchone()["count"]
    metrics["Has Experience"] = {"count": exp_count, "pct": round(exp_count / total * 100, 1)}

    return metrics


def get_revenue_summary(cur):
    """Revenue summary from searches."""
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE status NOT IN ('closed', 'cancelled', 'completed')) AS active_count,
            COALESCE(SUM(fee_amount) FILTER (WHERE status NOT IN ('closed', 'cancelled', 'completed')), 0) AS active_revenue,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
            COALESCE(SUM(fee_amount) FILTER (WHERE status = 'completed'), 0) AS completed_revenue,
            COUNT(*) FILTER (WHERE deposit_paid = true) AS deposits_received,
            COALESCE(SUM(deposit_amount) FILTER (WHERE deposit_paid = true), 0) AS total_deposits
        FROM searches
    """)
    return cur.fetchone()


def format_report():
    conn = get_connection()
    cur = conn.cursor()
    today = datetime.now().strftime("%A, %B %d, %Y")
    week_start = (datetime.now() - timedelta(days=7)).strftime("%B %d")

    lines = []
    lines.append(f"KNOCK WEEKLY PIPELINE REPORT")
    lines.append(f"Week of {week_start} - {datetime.now().strftime('%B %d, %Y')}")
    lines.append("=" * 55)

    # Revenue summary
    rev = get_revenue_summary(cur)
    lines.append(section("REVENUE SNAPSHOT"))
    lines.append(f"  Active Searches:       {rev['active_count']}")
    lines.append(f"  Active Pipeline Value:  ${rev['active_revenue']:,}")
    lines.append(f"  Completed Placements:   {rev['completed_count']}")
    lines.append(f"  Completed Revenue:      ${rev['completed_revenue']:,}")
    lines.append(f"  Deposits Received:      {rev['deposits_received']} (${rev['total_deposits']:,})")

    # Searches by stage
    searches = get_searches_by_stage(cur)
    by_status = defaultdict(list)
    for s in searches:
        by_status[s["status"]].append(s)

    lines.append(section("SEARCHES BY STAGE"))
    stage_order = ["intake", "sourcing", "screening", "presenting", "interviewing",
                   "finalist", "offer", "completed", "closed"]
    for stage in stage_order:
        if stage in by_status:
            lines.append(f"\n  --- {stage.upper()} ({len(by_status[stage])}) ---")
            for s in by_status[stage]:
                school = s["school_name"] or "TBD"
                state = s["state"] or ""
                fee = f"${s['fee_amount']:,}" if s["fee_amount"] else "N/A"
                deposit = "PAID" if s["deposit_paid"] else "UNPAID"
                lines.append(f"  {s['search_number'] or 'N/A'}: {s['position_title']}")
                lines.append(f"    {school}{', ' + state if state else ''} | Fee: {fee} ({deposit})")
                pipeline = (
                    f"    Pipeline: {s['candidates_identified'] or 0} identified / "
                    f"{s['candidates_presented'] or 0} presented / "
                    f"{s['candidates_interviewed'] or 0} interviewed / "
                    f"{s['finalists'] or 0} finalists"
                )
                lines.append(pipeline)

    # Candidate detail for active searches
    active_search_ids = [s for s in searches if s["status"] not in ("closed", "cancelled", "completed")]
    if active_search_ids:
        lines.append(section("CANDIDATE PIPELINES"))
        for s in active_search_ids:
            candidates = get_search_candidates_by_search(cur, s["search_number"] if "id" not in s else None)
            # We need search IDs - let's get them
            cur.execute("SELECT id FROM searches WHERE search_number = %s", (s["search_number"],))
            search_row = cur.fetchone()
            if search_row:
                candidates = get_search_candidates_by_search(cur, search_row["id"])
                if candidates:
                    lines.append(f"\n  {s['search_number']}: {s['position_title']} at {s['school_name'] or 'TBD'}")
                    by_cand_status = defaultdict(list)
                    for c in candidates:
                        by_cand_status[c["status"] or "unknown"].append(c)
                    for cstatus, cands in by_cand_status.items():
                        lines.append(f"    [{cstatus}]")
                        for c in cands[:5]:
                            score = f"({c['match_score']:.0f}%)" if c["match_score"] else ""
                            org = c["current_organization"] or ""
                            lines.append(f"      - {c['full_name']} {score} {c['current_title'] or ''} {('at ' + org) if org else ''}")
                        if len(cands) > 5:
                            lines.append(f"      ... and {len(cands) - 5} more")

    # Stalled searches
    stalled = get_stalled_searches(cur)
    lines.append(section("STALLED SEARCHES (No Activity 7+ Days)"))
    if stalled:
        for s in stalled:
            days = s["days_stalled"]
            days_str = f"{days} days" if days else "Never active"
            lines.append(f"  WARNING: {s['search_number'] or 'N/A'}: {s['position_title']}")
            lines.append(f"    {s['school_name'] or 'TBD'} | Status: {s['status']} | Stalled: {days_str}")
    else:
        lines.append("  All searches have recent activity. Great!")

    # New records this week
    new_records = get_new_records_this_week(cur)
    lines.append(section("NEW THIS WEEK"))
    lines.append(f"  New People:       {new_records['new_people']}")
    lines.append(f"  New Schools:      {new_records['new_schools']}")
    lines.append(f"  New Signals:      {new_records['new_signals']}")
    lines.append(f"  New Interactions:  {new_records['new_interactions']}")
    if new_records["recent_people"]:
        lines.append("\n  Recent People Added:")
        for p in new_records["recent_people"][:10]:
            org = p["current_organization"] or ""
            state = p["state"] or ""
            lines.append(f"    - {p['full_name']} | {p['current_title'] or 'N/A'} {('at ' + org) if org else ''} {('(' + state + ')') if state else ''}")

    # Data quality
    dq = get_data_quality_metrics(cur)
    lines.append(section("DATA QUALITY METRICS"))
    lines.append(f"  Total People Records: {dq['total']:,}\n")
    if dq["total"] > 0:
        for label, data in dq.items():
            if label == "total":
                continue
            bar_len = int(data["pct"] / 5)
            bar = "#" * bar_len + "." * (20 - bar_len)
            lines.append(f"  {label:<20} [{bar}] {data['pct']:5.1f}% ({data['count']:,})")

    lines.append("\n" + "=" * 55)
    lines.append(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
    lines.append("=" * 55)

    cur.close()
    conn.close()
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        report = format_report()
        print(report)
    except Exception as e:
        print(f"ERROR generating weekly report: {e}", file=sys.stderr)
        sys.exit(1)
