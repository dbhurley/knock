"""
Shared utilities for Knock document generation.
Handles database queries, template rendering, and PDF conversion.
"""

import os
import pathlib
from datetime import datetime, date

import jinja2
import psycopg2
import psycopg2.extras
from weasyprint import HTML

# ---------------------------------------------------------------------------
# Branding constants
# ---------------------------------------------------------------------------
BRAND = {
    "primary": "#b8860b",
    "text": "#1a1a1a",
    "background": "#fafaf8",
    "light_gold": "#f5e6b8",
    "medium_gold": "#d4a825",
    "border": "#e0d5b5",
    "muted": "#6b6b6b",
    "font_stack": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    "company_name": "Knock",
    "tagline": "Executive Search for Independent Schools",
}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knock_admin:l8locd6zKTed4qo89f2Sihj%2BdeVX8CImvN8v%2BfUmsCg%3D@127.0.0.1:5432/knock",
)


def get_connection():
    """Return a psycopg2 connection using RealDictCursor."""
    return psycopg2.connect(_DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------
TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html"]),
)


def _format_date(value, fmt="%B %Y"):
    """Jinja2 filter: format a date or datetime object."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    return str(value)


def _format_currency(value):
    """Jinja2 filter: format an integer as currency."""
    if value is None:
        return ""
    try:
        return f"${int(value):,}"
    except (ValueError, TypeError):
        return str(value)


def _default_if_none(value, default=""):
    """Jinja2 filter: return default when value is None."""
    return value if value is not None else default


_jinja_env.filters["format_date"] = _format_date
_jinja_env.filters["format_currency"] = _format_currency
_jinja_env.filters["d"] = _default_if_none


def render_template(template_name: str, **ctx) -> str:
    """Render a Jinja2 template with brand context injected."""
    ctx.setdefault("brand", BRAND)
    ctx.setdefault("generated_at", datetime.now().strftime("%B %d, %Y"))
    tpl = _jinja_env.get_template(template_name)
    return tpl.render(**ctx)


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def html_to_pdf(html_string: str, output_path: str) -> str:
    """Convert an HTML string to a PDF file using WeasyPrint."""
    outpath = pathlib.Path(output_path)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_string, base_url=str(TEMPLATE_DIR)).write_pdf(str(outpath))
    return str(outpath)


# ---------------------------------------------------------------------------
# Common data-fetching helpers
# ---------------------------------------------------------------------------

def fetch_person(conn, person_id: str) -> dict:
    """Fetch a person record by UUID."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM people WHERE id = %s", (person_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Person not found: {person_id}")
    return dict(row)


def fetch_person_education(conn, person_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM person_education WHERE person_id = %s ORDER BY graduation_year DESC NULLS LAST",
        (person_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def fetch_person_experience(conn, person_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM person_experience WHERE person_id = %s ORDER BY is_current DESC, start_date DESC NULLS LAST",
        (person_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def fetch_person_references(conn, person_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM person_references WHERE person_id = %s ORDER BY created_at",
        (person_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def fetch_person_skills(conn, person_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM person_skills WHERE person_id = %s ORDER BY endorsed_count DESC NULLS LAST",
        (person_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def fetch_search(conn, search_id: str) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT * FROM searches WHERE id = %s", (search_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Search not found: {search_id}")
    return dict(row)


def fetch_school(conn, school_id: str) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT * FROM schools WHERE id = %s", (school_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"School not found: {school_id}")
    return dict(row)


def fetch_search_candidates(conn, search_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT sc.*, p.full_name, p.current_title, p.current_organization,
                  p.linkedin_profile_photo_url, p.leadership_style, p.strengths
           FROM search_candidates sc
           JOIN people p ON p.id = sc.person_id
           WHERE sc.search_id = %s
           ORDER BY sc.match_score DESC NULLS LAST""",
        (search_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def fetch_search_activities(conn, search_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM search_activities WHERE search_id = %s ORDER BY created_at DESC",
        (search_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def fetch_match_score(conn, person_id: str, search_id: str) -> dict | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM match_scores_log WHERE candidate_id = %s AND search_id = %s ORDER BY computed_at DESC LIMIT 1",
        (person_id, search_id),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def fetch_pricing_band(conn, band_code: str) -> dict | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM pricing_bands WHERE band_code = %s AND is_active = true",
        (band_code,),
    )
    row = cur.fetchone()
    return dict(row) if row else None
