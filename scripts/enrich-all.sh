#!/usr/bin/env bash
# enrich-all.sh — Run the full enrichment pipeline
# Usage: ./scripts/enrich-all.sh
#
# Prerequisites: Docker containers must be running (docker compose up -d)

set -euo pipefail

CONTAINER="knock-postgres-1"
DB_USER="knock_admin"
DB_NAME="knock"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           Knock Data Enrichment Pipeline                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check Docker is running
if ! docker ps --format '{{.Names}}' | grep -q "$CONTAINER"; then
  echo "ERROR: Container $CONTAINER is not running."
  echo "Start it with: docker compose up -d"
  exit 1
fi

run_sql() {
  local script="$1"
  local name="$2"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "▶ Running: $name"
  echo "  Script:  $script"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" < "$script" 2>&1
  echo ""
}

# Step 0: Run migration (idempotent — uses IF NOT EXISTS)
echo "▶ Step 0: Applying migration 012 (data quality columns)..."
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" < "$SCRIPT_DIR/../db/migrations/012_add_data_quality.sql" 2>&1
echo ""

# Step 0.5: Clean up trial searches (if they still exist)
if docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
  "SELECT COUNT(*) FROM searches WHERE search_number IN ('KNK-2026-001', 'KNK-2026-002')" | grep -q '[1-9]'; then
  echo "▶ Step 0.5: Removing trial searches..."
  docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" < "$SCRIPT_DIR/cleanup-trial-searches.sql" 2>&1
  echo ""
fi

# Step 1: School linkage repair
run_sql "$SCRIPT_DIR/enrich-01-school-linkage.sql" "School Linkage Repair"

# Step 2: Dedup + data quality scoring
run_sql "$SCRIPT_DIR/enrich-02-dedup-quality.sql" "Deduplication & Quality Scoring"

# Step 3: Education + specialization inference
run_sql "$SCRIPT_DIR/enrich-03-infer-education-specializations.sql" "Education & Specialization Inference"

# Step 4: Re-run quality scoring (since steps 1 & 3 added data)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "▶ Step 4: Re-scoring data quality (post-enrichment)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
run_sql "$SCRIPT_DIR/enrich-02-dedup-quality.sql" "Final Quality Re-score"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  Enrichment Complete!                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Review duplicate groups:  SELECT * FROM people WHERE duplicate_group_id IS NOT NULL ORDER BY duplicate_group_id;"
echo "  2. Check quality distribution: SELECT data_completeness_score, COUNT(*) FROM people GROUP BY data_completeness_score ORDER BY 1;"
echo "  3. Review unlinked people:   SELECT full_name, current_organization FROM people WHERE current_school_id IS NULL AND primary_role = 'head_of_school';"
