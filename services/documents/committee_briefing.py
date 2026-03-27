"""
Committee Briefing Packet Generator
Produces a comprehensive briefing document for the search committee,
including all candidate profiles, a comparison matrix, suggested
interview questions, and a rating worksheet.
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
    fetch_person_education,
    fetch_person_experience,
    fetch_match_score,
)

# Default rating criteria for the worksheet
RATING_CRITERIA = [
    "Leadership Vision & Strategic Thinking",
    "Educational Philosophy & Curriculum Knowledge",
    "Fundraising & Advancement Experience",
    "Community & Relationship Building",
    "Financial Acumen & Operations Management",
    "Diversity, Equity & Inclusion Commitment",
    "Communication & Presence",
    "Cultural Fit with School Community",
    "Track Record of Results",
    "Overall Impression",
]


def _generate_interview_questions(candidate: dict, search: dict) -> list[str]:
    """Generate tailored interview questions for a candidate based on their profile."""
    questions = []
    position = search.get("position_title", "this role")

    # Always ask these core questions
    questions.append(
        f"What draws you to the {position} position at {search.get('client_contact_name', 'this school')},"
        f" and how does it align with your career trajectory?"
    )
    questions.append(
        "Describe your leadership philosophy and how it has evolved over your career."
    )

    # Tailor based on candidate strengths / gaps
    if candidate.get("strengths"):
        strength = candidate["strengths"][0] if candidate["strengths"] else "leadership"
        questions.append(
            f"You have noted strength in '{strength}.' Can you share a specific example of how"
            f" this has driven measurable outcomes at your current institution?"
        )

    if candidate.get("leadership_style"):
        questions.append(
            "How would your direct reports describe your leadership style, and how do you"
            " adapt it to different situations?"
        )

    questions.append(
        "Describe a significant challenge you faced as a school leader and how you navigated it."
    )
    questions.append(
        "How have you approached fundraising and advancement in your current or past roles?"
    )
    questions.append(
        "What strategies have you used to build an inclusive and equitable school community?"
    )
    questions.append(
        "How do you engage with a Board of Trustees to advance institutional goals?"
    )

    return questions[:8]  # cap at 8


def generate(search_id: str, output: str | None = None) -> str:
    """Generate a committee briefing packet PDF."""
    conn = get_connection()
    try:
        search = fetch_search(conn, search_id)
        school = {}
        if search.get("school_id"):
            school = fetch_school(conn, str(search["school_id"]))

        raw_candidates = fetch_search_candidates(conn, search_id)

        # Enrich each candidate with education, experience, and match data
        candidates = []
        for c in raw_candidates:
            pid = str(c["person_id"])
            c["education"] = fetch_person_education(conn, pid)
            c["experience"] = fetch_person_experience(conn, pid)
            c["match_data"] = fetch_match_score(conn, pid, search_id)
            c["interview_questions"] = _generate_interview_questions(c, search)
            candidates.append(c)

        html = render_template(
            "committee_briefing.html",
            title="Committee Briefing Packet",
            search=search,
            school=school,
            candidates=candidates,
            rating_criteria=RATING_CRITERIA,
        )

        if output is None:
            snum = search.get("search_number") or search_id[:8]
            output = f"output/committee_briefing_{snum}.pdf"

        path = html_to_pdf(html, output)
        print(f"Generated committee briefing packet: {path}")
        return path
    finally:
        conn.close()


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    if not sid:
        print("Usage: python -m documents.committee_briefing <search_id>")
        sys.exit(1)
    generate(sid)
