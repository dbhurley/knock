#!/usr/bin/env python3
"""
Knock Enrichment Service - Master Runner

CLI tool to run all enrichment modules or specific ones.
Tracks progress in data_sync_log table, rate limits external requests,
handles errors gracefully, and reports summary statistics.

Usage:
    python enrich.py all                       # Run all enrichers
    python enrich.py form990                   # Run Form 990 compensation enricher
    python enrich.py websites                  # Run school website scraper
    python enrich.py nais --file export.csv    # Import NAIS directory
    python enrich.py headsearch --file data.csv # Import HeadSearch transitions
    python enrich.py news                      # Run news monitor
    python enrich.py programs                  # Seed leadership programs
    python enrich.py programs --file grads.csv # Import program graduates

Options:
    --max-schools N   Max schools to process (default: 100)
    --school-ids ID   Comma-separated school UUIDs to target
    --file PATH       Input file for directory/program imports
    --format FMT      Format for directory imports (nais, headsearch, generic)
    --dry-run         Preview what would be done without making changes
    --verbose         Enable debug logging
"""

import os
import sys
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

import click

# Ensure the package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichment.db import close_conn, create_sync_log, complete_sync_log

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the enrichment runner."""
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)

    # File handler
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"enrich_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Root logger
    root = logging.getLogger('knock.enrichment')
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Also capture warnings
    logging.captureWarnings(True)


logger = logging.getLogger('knock.enrichment.runner')


# ---------------------------------------------------------------------------
# Enricher registry
# ---------------------------------------------------------------------------

ENRICHERS = {
    'form990': {
        'module': 'enrichment.enrichers.form990_people',
        'description': 'Form 990 Executive Compensation Enricher',
        'requires_file': False,
    },
    'websites': {
        'module': 'enrichment.enrichers.school_websites',
        'description': 'School Website Leadership Scraper',
        'requires_file': False,
    },
    'nais': {
        'module': 'enrichment.enrichers.nais_directory',
        'description': 'NAIS / HeadSearch Directory Enricher',
        'requires_file': True,
    },
    'headsearch': {
        'module': 'enrichment.enrichers.nais_directory',
        'description': 'HeadSearch Transition Importer',
        'requires_file': True,
    },
    'news': {
        'module': 'enrichment.enrichers.news_monitor',
        'description': 'News & Transition Monitor',
        'requires_file': False,
    },
    'programs': {
        'module': 'enrichment.enrichers.leadership_programs',
        'description': 'Educational Leadership Program Tracker',
        'requires_file': False,  # Optional file for graduate imports
    },
    'mission': {
        'module': 'enrichment.enrichers.school_mission',
        'description': 'School Mission & Culture Scraper',
        'requires_file': False,
    },
    'social': {
        'module': 'enrichment.enrichers.school_social',
        'description': 'School Social Media Profile Scraper',
        'requires_file': False,
    },
}


def load_enricher(name: str):
    """Dynamically load an enricher module and return its run function."""
    config = ENRICHERS.get(name)
    if not config:
        raise ValueError(f"Unknown enricher: {name}")

    import importlib
    module = importlib.import_module(config['module'])
    return module.run


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument('enricher', type=click.Choice(list(ENRICHERS.keys()) + ['all']))
@click.option('--max-schools', default=100, help='Max schools to process')
@click.option('--school-ids', default=None, help='Comma-separated school UUIDs')
@click.option('--file', 'file_path', default=None, help='Input file for imports')
@click.option('--format', 'fmt', default=None, help='Import format (nais, headsearch, generic)')
@click.option('--verbose', is_flag=True, help='Enable debug logging')
def main(enricher: str, max_schools: int, school_ids: Optional[str],
         file_path: Optional[str], fmt: Optional[str], verbose: bool):
    """
    Knock Data Enrichment Runner

    Enriches the people and schools database from public sources.
    """
    setup_logging(verbose)
    logger.info("=" * 70)
    logger.info("Knock Enrichment Service")
    logger.info("=" * 70)

    # Parse school_ids
    parsed_school_ids = None
    if school_ids:
        parsed_school_ids = [s.strip() for s in school_ids.split(',') if s.strip()]

    # Determine which enrichers to run
    if enricher == 'all':
        enrichers_to_run = [name for name, cfg in ENRICHERS.items() if not cfg['requires_file']]
    else:
        enrichers_to_run = [enricher]

    # Validate file requirement
    for name in enrichers_to_run:
        cfg = ENRICHERS[name]
        if cfg['requires_file'] and not file_path:
            logger.error(f"Enricher '{name}' requires --file argument")
            sys.exit(1)

    # Run enrichers
    all_stats: Dict[str, Dict[str, int]] = {}
    total_start = time.time()

    for name in enrichers_to_run:
        logger.info("-" * 50)
        logger.info(f"Running: {ENRICHERS[name]['description']}")
        logger.info("-" * 50)

        start = time.time()
        try:
            run_fn = load_enricher(name)

            # Build kwargs based on the enricher
            kwargs = {
                'max_schools': max_schools,
                'school_ids': parsed_school_ids,
            }
            if file_path:
                kwargs['file_path'] = file_path
            if fmt:
                kwargs['format'] = fmt
            elif name == 'headsearch':
                kwargs['format'] = 'headsearch'

            stats = run_fn(**kwargs)
            all_stats[name] = stats

            elapsed = time.time() - start
            logger.info(f"Completed {name} in {elapsed:.1f}s: {stats}")

        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"FAILED {name} after {elapsed:.1f}s: {e}", exc_info=True)
            all_stats[name] = {
                'records_processed': 0, 'records_created': 0,
                'records_updated': 0, 'records_errored': 1,
            }

    # Print summary
    total_elapsed = time.time() - total_start
    print_summary(all_stats, total_elapsed)

    # Cleanup
    close_conn()


def print_summary(all_stats: Dict[str, Dict[str, int]], elapsed: float) -> None:
    """Print a formatted summary of all enrichment runs."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("ENRICHMENT SUMMARY")
    logger.info("=" * 70)

    totals = {'processed': 0, 'created': 0, 'updated': 0, 'errored': 0}

    for name, stats in all_stats.items():
        desc = ENRICHERS.get(name, {}).get('description', name)
        p = stats.get('records_processed', 0)
        c = stats.get('records_created', 0)
        u = stats.get('records_updated', 0)
        e = stats.get('records_errored', 0)

        status_icon = 'OK' if e == 0 else f'WARN ({e} errors)'
        logger.info(f"  {desc}")
        logger.info(f"    Processed: {p:,}  Created: {c:,}  Updated: {u:,}  [{status_icon}]")

        totals['processed'] += p
        totals['created'] += c
        totals['updated'] += u
        totals['errored'] += e

    logger.info("-" * 70)
    logger.info(f"  TOTAL: {totals['processed']:,} processed, "
                f"{totals['created']:,} created, "
                f"{totals['updated']:,} updated, "
                f"{totals['errored']:,} errors")
    logger.info(f"  Time: {elapsed:.1f}s ({elapsed/60:.1f}m)")
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
