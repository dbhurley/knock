"""
Candidate Profile Generator
Produces a professional 1-2 page PDF profile for a single candidate,
optionally scoped to a specific search for match-score context.
"""

from __future__ import annotations
import sys
from .utils import (
    get_connection,
    render_template,
    html_to_pdf,
    fetch_person,
    fetch_person_education,
    fetch_person_experience,
    fetch_person_references,
    fetch_search,
    fetch_school,
    fetch_match_score,
    fetch_search_candidates,
)


def generate(person_id: str, search_id: str | None = None, output: str | None = None) -> str:
    """Generate a candidate profile PDF and return the output path."""
    conn = get_connection()
    try:
        person = fetch_person(conn, person_id)
        education = fetch_person_education(conn, person_id)
        experience = fetch_person_experience(conn, person_id)
        references = fetch_person_references(conn, person_id)

        search = None
        school = {}
        match_score = None
        search_candidate = None

        if search_id:
            search = fetch_search(conn, search_id)
            if search.get("school_id"):
                school = fetch_school(conn, str(search["school_id"]))
            match_score = fetch_match_score(conn, person_id, search_id)
            # Get the search_candidate record for reasoning text
            for sc in fetch_search_candidates(conn, search_id):
                if str(sc["person_id"]) == str(person_id):
                    search_candidate = sc
                    break

        html = render_template(
            "candidate_profile.html",
            title="Candidate Profile",
            person=person,
            education=education,
            experience=experience,
            references=references,
            search=search or {},
            school=school,
            match_score=match_score,
            search_candidate=search_candidate,
        )

        if output is None:
            safe_name = (person.get("full_name") or "candidate").replace(" ", "_")
            output = f"output/candidate_profile_{safe_name}.pdf"

        path = html_to_pdf(html, output)
        print(f"Generated candidate profile: {path}")
        return path
    finally:
        conn.close()


if __name__ == "__main__":
    # Quick standalone usage
    pid = sys.argv[1] if len(sys.argv) > 1 else None
    sid = sys.argv[2] if len(sys.argv) > 2 else None
    if not pid:
        print("Usage: python -m documents.candidate_profile <person_id> [search_id]")
        sys.exit(1)
    generate(pid, sid)
