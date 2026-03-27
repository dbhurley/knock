"""
Search Status Report Generator
Produces a search progress report PDF for client updates.
"""

from __future__ import annotations
import sys
from .utils import (
    get_connection,
    render_template,
    html_to_pdf,
    fetch_search,
    fetch_school,
    fetch_search_candidates,
    fetch_search_activities,
)

# Canonical pipeline stages and their display labels
PIPELINE_STAGES = [
    ("identified", "Identified"),
    ("contacted", "Contacted"),
    ("screening", "Screening"),
    ("presented", "Presented"),
    ("interviewing", "Interviewing"),
    ("finalist", "Finalist"),
    ("offer", "Offer"),
    ("placed", "Placed"),
    ("declined", "Declined / Withdrawn"),
]


def _build_pipeline(candidates: list[dict]) -> tuple[list[dict], int]:
    """Summarise candidates into pipeline stage counts."""
    counts: dict[str, int] = {}
    for c in candidates:
        status = (c.get("status") or "identified").lower()
        counts[status] = counts.get(status, 0) + 1

    total = len(candidates)
    pipeline = []
    for key, label in PIPELINE_STAGES:
        cnt = counts.pop(key, 0)
        if cnt or key in ("identified", "presented", "interviewing", "finalist"):
            pipeline.append({
                "label": label,
                "count": cnt,
                "pct": round(cnt / total * 100) if total else 0,
            })
    # Catch any unexpected statuses
    for key, cnt in counts.items():
        pipeline.append({
            "label": key.replace("_", " ").title(),
            "count": cnt,
            "pct": round(cnt / total * 100) if total else 0,
        })
    return pipeline, total


def generate(search_id: str, output: str | None = None) -> str:
    """Generate a search status report PDF."""
    conn = get_connection()
    try:
        search = fetch_search(conn, search_id)
        school = {}
        if search.get("school_id"):
            school = fetch_school(conn, str(search["school_id"]))

        candidates = fetch_search_candidates(conn, search_id)
        activities = fetch_search_activities(conn, search_id)
        pipeline, total = _build_pipeline(candidates)

        html = render_template(
            "search_status.html",
            title="Search Status Report",
            search=search,
            school=school,
            candidates=candidates,
            pipeline=pipeline,
            total_candidates=total,
            activities=activities,
        )

        if output is None:
            snum = search.get("search_number") or search_id[:8]
            output = f"output/search_status_{snum}.pdf"

        path = html_to_pdf(html, output)
        print(f"Generated search status report: {path}")
        return path
    finally:
        conn.close()


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    if not sid:
        print("Usage: python -m documents.search_status_report <search_id>")
        sys.exit(1)
    generate(sid)
