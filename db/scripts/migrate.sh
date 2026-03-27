#!/usr/bin/env bash
set -euo pipefail

# migrate.sh - Run all SQL migrations in order against PostgreSQL
# Usage: DATABASE_URL=postgres://user:pass@host:5432/knock ./migrate.sh

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL environment variable is not set."
    echo "Usage: DATABASE_URL=postgres://user:pass@host:5432/knock $0"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="$SCRIPT_DIR/../migrations"

if [ ! -d "$MIGRATIONS_DIR" ]; then
    echo "ERROR: Migrations directory not found at $MIGRATIONS_DIR"
    exit 1
fi

echo "=== Knock Database Migration ==="
echo "Running migrations from: $MIGRATIONS_DIR"
echo ""

for migration in "$MIGRATIONS_DIR"/*.sql; do
    filename="$(basename "$migration")"
    echo "Running: $filename ..."
    psql "$DATABASE_URL" -f "$migration" -v ON_ERROR_STOP=1
    echo "  Done: $filename"
done

echo ""
echo "=== All migrations completed successfully ==="
