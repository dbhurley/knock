#!/usr/bin/env bash
# Wrapper for llm-enrich.py - runs every 6 hours via cron
# Processes the highest-priority unenriched HOS candidates
set -e
cd /opt/knock
source services/association-scrapers/venv/bin/activate
export DATABASE_URL=$(cat services/association-scrapers/.db_url)
export ANTHROPIC_API_KEY=$(systemctl cat openclaw 2>/dev/null | grep -oP "ANTHROPIC_API_KEY=\K[^\s]+" | head -1)
export ENRICH_BATCH_SIZE=5
exec python3 scripts/llm-enrich.py --limit 5
