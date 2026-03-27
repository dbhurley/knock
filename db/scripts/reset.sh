#!/usr/bin/env bash
set -euo pipefail

# reset.sh - Drop and recreate the knock database, then run all migrations
# Usage: DATABASE_URL=postgres://user:pass@host:5432/knock ./reset.sh
#
# WARNING: This will destroy ALL data in the knock database.
# Safety check: refuses to run if NODE_ENV=production.

if [ "${NODE_ENV:-}" = "production" ]; then
    echo "ERROR: Cannot reset database in production environment (NODE_ENV=production)."
    echo "This script is for development and testing only."
    exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL environment variable is not set."
    echo "Usage: DATABASE_URL=postgres://user:pass@host:5432/knock $0"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Extract connection components from DATABASE_URL for admin operations
# Parse: postgres://user:pass@host:port/dbname
DB_NAME=$(echo "$DATABASE_URL" | sed -E 's|.*/([^?]+).*|\1|')
# Build a URL pointing to the default 'postgres' database for admin commands
ADMIN_URL=$(echo "$DATABASE_URL" | sed -E "s|/[^/?]+(\?)?|/postgres\1|")

echo "=== Knock Database Reset ==="
echo "WARNING: This will DROP and RECREATE the '$DB_NAME' database."
echo ""
read -p "Are you sure? Type 'yes' to continue: " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Dropping database '$DB_NAME' (if exists)..."
psql "$ADMIN_URL" -c "DROP DATABASE IF EXISTS \"$DB_NAME\";" 2>/dev/null || true

echo "Creating database '$DB_NAME'..."
psql "$ADMIN_URL" -c "CREATE DATABASE \"$DB_NAME\";"

echo "Database '$DB_NAME' recreated."
echo ""

echo "Running migrations..."
"$SCRIPT_DIR/migrate.sh"

echo ""
echo "=== Database reset complete ==="
