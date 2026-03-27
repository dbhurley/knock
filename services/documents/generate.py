#!/usr/bin/env python3
"""
Knock Document Generator CLI

Usage:
  python generate.py candidate-profile --person-id UUID [--search-id UUID] [-o FILE]
  python generate.py search-status    --search-id UUID [-o FILE]
  python generate.py opportunity-profile --search-id UUID [-o FILE]
  python generate.py committee-briefing  --search-id UUID [-o FILE]
"""

import sys
import os

# Ensure the parent directory is on sys.path so relative imports work
# when running as `python generate.py` from the documents/ directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Also support running from the services/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click


@click.group()
def cli():
    """Knock Document Generator — produce professional PDFs for executive searches."""
    pass


@cli.command("candidate-profile")
@click.option("--person-id", required=True, help="UUID of the candidate")
@click.option("--search-id", default=None, help="UUID of the search (optional, for match context)")
@click.option("-o", "--output", default=None, help="Output PDF path")
def candidate_profile(person_id, search_id, output):
    """Generate a professional candidate profile PDF."""
    from documents.candidate_profile import generate
    generate(person_id, search_id, output)


@cli.command("search-status")
@click.option("--search-id", required=True, help="UUID of the search")
@click.option("-o", "--output", default=None, help="Output PDF path")
def search_status(search_id, output):
    """Generate a search status report PDF."""
    from documents.search_status_report import generate
    generate(search_id, output)


@cli.command("opportunity-profile")
@click.option("--search-id", required=True, help="UUID of the search")
@click.option("-o", "--output", default=None, help="Output PDF path")
def opportunity_profile(search_id, output):
    """Generate an opportunity profile (OP) document PDF."""
    from documents.opportunity_profile import generate
    generate(search_id, output)


@cli.command("committee-briefing")
@click.option("--search-id", required=True, help="UUID of the search")
@click.option("-o", "--output", default=None, help="Output PDF path")
def committee_briefing(search_id, output):
    """Generate a committee briefing packet PDF."""
    from documents.committee_briefing import generate
    generate(search_id, output)


if __name__ == "__main__":
    cli()
