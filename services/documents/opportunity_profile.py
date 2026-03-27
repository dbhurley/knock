"""
Opportunity Profile Generator
Produces the "OP" marketing document sent to prospective candidates
describing the school, the position, and the application process.
"""

from __future__ import annotations
import sys
from .utils import (
    get_connection,
    render_template,
    html_to_pdf,
    fetch_search,
    fetch_school,
)


def generate(search_id: str, output: str | None = None) -> str:
    """Generate an opportunity profile PDF."""
    conn = get_connection()
    try:
        search = fetch_search(conn, search_id)
        school = {}
        if search.get("school_id"):
            school = fetch_school(conn, str(search["school_id"]))

        html = render_template(
            "opportunity_profile.html",
            title="Opportunity Profile",
            search=search,
            school=school,
        )

        if output is None:
            school_name = (school.get("name") or "school").replace(" ", "_")
            output = f"output/opportunity_profile_{school_name}.pdf"

        path = html_to_pdf(html, output)
        print(f"Generated opportunity profile: {path}")
        return path
    finally:
        conn.close()


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    if not sid:
        print("Usage: python -m documents.opportunity_profile <search_id>")
        sys.exit(1)
    generate(sid)
