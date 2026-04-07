#!/usr/bin/env bash
# Wrapper for enrich-contacts-v2.py - runs every 4 hours via cron
set -e
cd /opt/knock
source services/association-scrapers/venv/bin/activate
export DATABASE_URL=$(cat services/association-scrapers/.db_url)
export ENRICH_BATCH_SIZE=15
export ENRICH_DELAY_SEC=4
exec python3 scripts/enrich-contacts-v2.py
