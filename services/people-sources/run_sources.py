#!/usr/bin/env python3
"""
Master Runner for Knock People Sources

CLI to run all or specific source scrapers.
Tracks execution in data_sync_log.
Produces summary reports.
Configurable rate limits per source.

Usage:
    python run_sources.py --all
    python run_sources.py --source state_associations
    python run_sources.py --source nais_conferences --source podcast_guests
    python run_sources.py --list
    python run_sources.py --report
"""

import logging
import sys
import os
import time
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import click

# Ensure the people-sources package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    create_sync_log,
    complete_sync_log,
    fetch_all,
    fetch_one,
    close_conn,
)

# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

SOURCES = {
    'state_associations': {
        'name': 'State Association Directories',
        'description': 'Scrape member school directories from independent school associations',
        'module': 'sources.state_associations',
        'function': 'scrape_all_associations',
        'estimated_records': '500-2000',
        'rate_limit_note': '3s between requests per association',
    },
    'nais_conferences': {
        'name': 'NAIS Conference Speakers',
        'description': 'Scrape speaker bios from NAIS Annual Conference, PoCC, Institute for New Heads',
        'module': 'sources.nais_conferences',
        'function': 'scrape_all_conferences',
        'estimated_records': '200-500',
        'rate_limit_note': '3s between requests',
    },
    'publication_authors': {
        'name': 'Education Publication Authors',
        'description': 'Track authors from NAIS Magazine, Education Week, EdSurge',
        'module': 'sources.publication_authors',
        'function': 'scrape_all_publications',
        'estimated_records': '100-500',
        'rate_limit_note': '3s between requests',
    },
    'podcast_guests': {
        'name': 'Podcast Guest Tracker',
        'description': 'Extract guests from education leadership podcasts via RSS feeds',
        'module': 'sources.podcast_guests',
        'function': 'scrape_all_podcasts',
        'estimated_records': '100-300',
        'rate_limit_note': '1s between requests (API calls)',
    },
    'board_from_990': {
        'name': 'Board Members from 990 Filings',
        'description': 'Extract board members from ProPublica 990 data for schools with EINs',
        'module': 'sources.board_from_990',
        'function': 'import_all_school_boards',
        'estimated_records': '2000-5000',
        'rate_limit_note': '1s between ProPublica API requests',
    },
    'job_boards': {
        'name': 'Job Board Monitor',
        'description': 'Monitor NAIS Career Center, Carney Sandoe, EdSurge for leadership openings',
        'module': 'sources.job_boards',
        'function': 'monitor_all_job_boards',
        'estimated_records': '50-200 signals',
        'rate_limit_note': '3s between requests',
    },
}

logger = logging.getLogger('knock.people_sources.runner')


# ---------------------------------------------------------------------------
# Dynamic module loading
# ---------------------------------------------------------------------------

def _run_source(source_key: str) -> Dict[str, int]:
    """Dynamically import and run a source module."""
    if source_key not in SOURCES:
        raise ValueError(f"Unknown source: {source_key}")

    src = SOURCES[source_key]
    module_path = src['module']
    function_name = src['function']

    logger.info(f"--- Running: {src['name']} ({source_key}) ---")

    # Dynamic import
    import importlib
    module = importlib.import_module(module_path)
    func = getattr(module, function_name)

    start = time.time()
    stats = func()
    elapsed = time.time() - start

    logger.info(f"--- Completed: {src['name']} in {elapsed:.1f}s ---")
    logger.info(f"    Processed: {stats.get('records_processed', 0)}")
    logger.info(f"    Created:   {stats.get('records_created', 0)}")
    logger.info(f"    Updated:   {stats.get('records_updated', 0)}")
    logger.info(f"    Errors:    {stats.get('records_errored', 0)}")

    stats['elapsed_seconds'] = round(elapsed, 1)
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option('--all', 'run_all', is_flag=True, help='Run all sources')
@click.option('--source', '-s', multiple=True, help='Run specific source(s)')
@click.option('--list', 'list_sources', is_flag=True, help='List available sources')
@click.option('--report', is_flag=True, help='Show recent sync log report')
@click.option('--verbose', '-v', is_flag=True, help='Verbose logging (DEBUG level)')
@click.option('--dry-run', is_flag=True, help='Show what would run without executing')
def main(run_all, source, list_sources, report, verbose, dry_run):
    """Knock People Sources - Master Runner"""

    # Setup logging
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                os.path.join(os.path.dirname(__file__), 'run_sources.log'),
                mode='a',
            ),
        ],
    )

    if list_sources:
        click.echo("\nAvailable People Sources:")
        click.echo("=" * 70)
        for key, src in SOURCES.items():
            click.echo(f"\n  {key}")
            click.echo(f"    {src['name']}")
            click.echo(f"    {src['description']}")
            click.echo(f"    Estimated records: {src['estimated_records']}")
            click.echo(f"    Rate limit: {src['rate_limit_note']}")
        click.echo()
        return

    if report:
        _show_report()
        return

    # Determine which sources to run
    sources_to_run = []
    if run_all:
        sources_to_run = list(SOURCES.keys())
    elif source:
        for s in source:
            if s not in SOURCES:
                click.echo(f"Error: Unknown source '{s}'", err=True)
                click.echo(f"Available: {', '.join(SOURCES.keys())}", err=True)
                sys.exit(1)
            sources_to_run.append(s)
    else:
        click.echo("No sources specified. Use --all, --source <name>, or --list")
        sys.exit(1)

    if dry_run:
        click.echo(f"\nDry run - would execute {len(sources_to_run)} sources:")
        for s in sources_to_run:
            click.echo(f"  - {s}: {SOURCES[s]['name']}")
        return

    # Run sources
    click.echo(f"\n{'='*70}")
    click.echo(f"  Knock People Sources - Running {len(sources_to_run)} source(s)")
    click.echo(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo(f"{'='*70}\n")

    log_id = create_sync_log('people_sources_runner', 'full')
    total_stats = {'records_processed': 0, 'records_created': 0, 'records_updated': 0, 'records_errored': 0}
    source_results = {}
    overall_start = time.time()

    for source_key in sources_to_run:
        try:
            stats = _run_source(source_key)
            source_results[source_key] = stats
            for k in ['records_processed', 'records_created', 'records_updated', 'records_errored']:
                total_stats[k] += stats.get(k, 0)
        except Exception as e:
            logger.error(f"FATAL error running {source_key}: {e}", exc_info=True)
            source_results[source_key] = {
                'error': str(e),
                'records_processed': 0,
                'records_created': 0,
                'records_updated': 0,
                'records_errored': 1,
            }
            total_stats['records_errored'] += 1

    overall_elapsed = time.time() - overall_start

    # Complete sync log
    status = 'completed' if total_stats['records_errored'] == 0 else 'partial'
    complete_sync_log(log_id, total_stats, status=status)

    # Print summary
    click.echo(f"\n{'='*70}")
    click.echo(f"  SUMMARY")
    click.echo(f"{'='*70}")
    click.echo(f"  Total time:      {overall_elapsed:.1f}s")
    click.echo(f"  Total processed: {total_stats['records_processed']}")
    click.echo(f"  Total created:   {total_stats['records_created']}")
    click.echo(f"  Total updated:   {total_stats['records_updated']}")
    click.echo(f"  Total errors:    {total_stats['records_errored']}")
    click.echo()

    for key, result in source_results.items():
        status_icon = 'OK' if result.get('records_errored', 0) == 0 else 'WARN'
        if 'error' in result:
            status_icon = 'FAIL'
        elapsed = result.get('elapsed_seconds', 0)
        click.echo(f"  [{status_icon}] {key}: "
                   f"{result.get('records_created', 0)} created, "
                   f"{result.get('records_updated', 0)} updated, "
                   f"{result.get('records_errored', 0)} errors "
                   f"({elapsed}s)")

    click.echo(f"{'='*70}\n")

    # Cleanup
    close_conn()

    # Exit with error code if there were failures
    if total_stats['records_errored'] > 0:
        sys.exit(1)


def _show_report():
    """Show recent sync log entries."""
    logs = fetch_all(
        """SELECT source, sync_type, started_at, completed_at,
                  records_processed, records_created, records_updated,
                  records_errored, status
           FROM data_sync_log
           WHERE source IN ('state_associations', 'nais_conferences',
                           'publication_authors', 'podcast_guests',
                           'board_from_990', 'job_boards',
                           'university_programs', 'people_sources_runner')
           ORDER BY started_at DESC
           LIMIT 20""",
    )

    if not logs:
        click.echo("No sync logs found for people sources.")
        return

    click.echo(f"\nRecent People Sources Sync Log ({len(logs)} entries):")
    click.echo(f"{'='*90}")
    click.echo(f"  {'Source':<25} {'Status':<10} {'Processed':>10} {'Created':>10} {'Errors':>8} {'When'}")
    click.echo(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*20}")

    for log in logs:
        started = log['started_at'].strftime('%Y-%m-%d %H:%M') if log['started_at'] else '?'
        click.echo(
            f"  {log['source']:<25} {log['status'] or '?':<10} "
            f"{log['records_processed'] or 0:>10} {log['records_created'] or 0:>10} "
            f"{log['records_errored'] or 0:>8} {started}"
        )

    click.echo()

    # Show current people count
    count = fetch_one("SELECT COUNT(*) as cnt FROM people")
    if count:
        click.echo(f"  Total people in database: {count['cnt']}")

    click.echo()
    close_conn()


if __name__ == '__main__':
    main()
