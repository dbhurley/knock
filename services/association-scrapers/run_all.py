#!/usr/bin/env python3
"""
CLI runner for Knock association scrapers.

Usage:
    python run_all.py all              # Run all scrapers
    python run_all.py acsi             # Run specific scraper
    python run_all.py acsi catholic    # Run multiple scrapers
    python run_all.py --list           # List available scrapers
    python run_all.py all --limit 10   # Limit records per scraper
"""

import sys
import os
import time
import logging
from datetime import datetime

import click

# Ensure the package root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import ASSOCIATIONS, SCRAPER_MODULES
from utils import get_db_conn, close_db_conn

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('knock.scrapers.cli')

# Available scrapers -- lazy imports to avoid circular deps
SCRAPER_REGISTRY = {
    'acsi': ('scrapers.acsi', 'scrape_acsi'),
    'catholic': ('scrapers.catholic', 'scrape_catholic'),
    'jewish': ('scrapers.jewish', 'scrape_jewish'),
    'episcopal': ('scrapers.episcopal', 'scrape_episcopal'),
    'quaker': ('scrapers.quaker', 'scrape_quaker'),
    'montessori': ('scrapers.montessori', 'scrape_montessori'),
    'waldorf': ('scrapers.waldorf', 'scrape_waldorf'),
    'classical': ('scrapers.classical', 'scrape_classical'),
    'ib_schools': ('scrapers.ib_schools', 'scrape_ib_schools'),
    'naeyc': ('scrapers.naeyc', 'scrape_naeyc'),
    'learning_diff': ('scrapers.learning_diff', 'scrape_learning_diff'),
    'military': ('scrapers.military', 'scrape_military'),
}


def _import_scraper(name: str):
    """Dynamically import a scraper function."""
    module_path, func_name = SCRAPER_REGISTRY[name]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def _print_summary(all_stats: dict, elapsed: float) -> None:
    """Print a formatted summary table."""
    click.echo("")
    click.echo("=" * 72)
    click.echo(f"{'SCRAPER SUMMARY':^72}")
    click.echo("=" * 72)
    click.echo(
        f"{'Scraper':<16} {'Status':<10} {'Processed':>10} {'Created':>10} "
        f"{'Updated':>10} {'Errors':>8}"
    )
    click.echo("-" * 72)

    totals = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0}

    for name, result in all_stats.items():
        if isinstance(result, dict):
            status = 'OK'
            processed = result.get('processed', 0)
            created = result.get('created', 0)
            updated = result.get('updated', 0)
            errored = result.get('errored', 0)
        else:
            status = 'FAILED'
            processed = created = updated = errored = 0

        totals['processed'] += processed
        totals['created'] += created
        totals['updated'] += updated
        totals['errored'] += errored

        click.echo(
            f"{name:<16} {status:<10} {processed:>10} {created:>10} "
            f"{updated:>10} {errored:>8}"
        )

    click.echo("-" * 72)
    click.echo(
        f"{'TOTAL':<16} {'':10} {totals['processed']:>10} {totals['created']:>10} "
        f"{totals['updated']:>10} {totals['errored']:>8}"
    )
    click.echo("=" * 72)
    click.echo(f"Elapsed time: {elapsed:.1f}s")
    click.echo("")


@click.command()
@click.argument('scrapers', nargs=-1)
@click.option('--list', 'list_scrapers', is_flag=True, help='List available scrapers')
@click.option('--limit', type=int, default=None, help='Limit records per scraper (for testing)')
@click.option('--dry-run', is_flag=True, help='Run without database writes (not yet implemented)')
@click.option('--verbose', '-v', is_flag=True, help='Enable debug logging')
def main(scrapers, list_scrapers, limit, dry_run, verbose):
    """Run Knock association scrapers.

    Pass 'all' to run all scrapers, or specific scraper names.
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if list_scrapers:
        click.echo("")
        click.echo("Available scrapers:")
        click.echo("-" * 60)
        for name, conf in sorted(ASSOCIATIONS.items()):
            est = conf.get('estimated_schools', '?')
            click.echo(f"  {name:<16} {conf['short_name']:<8} ~{est} schools")
        click.echo("-" * 60)
        click.echo(f"\n  Total: {len(ASSOCIATIONS)} scrapers")
        click.echo(f"\n  Usage: python run_all.py <scraper_name> [--limit N]")
        click.echo(f"         python run_all.py all")
        click.echo("")
        return

    if not scrapers:
        click.echo("Error: specify scraper name(s) or 'all'. Use --list to see options.")
        sys.exit(1)

    # Determine which scrapers to run
    to_run = []
    if 'all' in scrapers:
        to_run = list(SCRAPER_REGISTRY.keys())
    else:
        for name in scrapers:
            if name not in SCRAPER_REGISTRY:
                click.echo(f"Error: unknown scraper '{name}'. Use --list to see options.")
                sys.exit(1)
            to_run.append(name)

    click.echo(f"\nKnock Association Scrapers")
    click.echo(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo(f"Scrapers to run: {', '.join(to_run)}")
    if limit:
        click.echo(f"Record limit per scraper: {limit}")
    click.echo("")

    # Get database connection
    db_conn = None
    try:
        db_conn = get_db_conn()
        click.echo("Database connection established.")
    except Exception as e:
        click.echo(f"Warning: Could not connect to database: {e}")
        click.echo("Running without database (results will not be saved).")

    all_stats = {}
    start_time = time.time()

    for name in to_run:
        click.echo(f"\n{'='*40}")
        click.echo(f"Running: {name} ({ASSOCIATIONS[name]['short_name']})")
        click.echo(f"{'='*40}")

        scraper_start = time.time()
        try:
            scrape_func = _import_scraper(name)
            stats = scrape_func(db_conn=db_conn, limit=limit)
            all_stats[name] = stats
            elapsed = time.time() - scraper_start
            click.echo(
                f"  Done in {elapsed:.1f}s: "
                f"processed={stats.get('processed', 0)}, "
                f"created={stats.get('created', 0)}, "
                f"updated={stats.get('updated', 0)}, "
                f"errors={stats.get('errored', 0)}"
            )
        except Exception as e:
            elapsed = time.time() - scraper_start
            all_stats[name] = str(e)
            click.echo(f"  FAILED after {elapsed:.1f}s: {e}")
            logger.exception(f"Scraper {name} failed")

    total_elapsed = time.time() - start_time
    _print_summary(all_stats, total_elapsed)

    # Cleanup
    if db_conn:
        try:
            close_db_conn()
        except Exception:
            pass


if __name__ == '__main__':
    main()
