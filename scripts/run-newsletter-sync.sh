#!/usr/bin/env bash
set -e
cd /opt/knock
source services/association-scrapers/venv/bin/activate
export DATABASE_URL=$(cat services/association-scrapers/.db_url)
exec python3 scripts/newsletter.py sync
