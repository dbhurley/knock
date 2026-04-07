#!/usr/bin/env bash
# Wrapper for llm-board-scrape.py - runs every 8 hours
set -e
cd /opt/knock
source services/association-scrapers/venv/bin/activate
export DATABASE_URL=$(cat services/association-scrapers/.db_url)
export ANTHROPIC_API_KEY=$(systemctl cat openclaw 2>/dev/null | grep -oP "ANTHROPIC_API_KEY=\K[^\s]+" | head -1)
exec python3 scripts/llm-board-scrape.py --limit 10
