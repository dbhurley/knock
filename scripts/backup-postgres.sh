#!/usr/bin/env bash
# =============================================================================
# Knock - PostgreSQL Backup Script
# Runs daily via cron. Compresses with gzip. Retains 30 days.
#
# Crontab entry (as deploy user):
#   0 3 * * * /opt/knock/scripts/backup-postgres.sh >> /opt/knock/logs/backup.log 2>&1
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BACKUP_DIR="${BACKUP_DIR:-/opt/knock/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="knock_${TIMESTAMP}.sql.gz"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_FILE}"

# PostgreSQL connection (from environment or defaults)
PG_CONTAINER="${PG_CONTAINER:-knock-postgres}"
PG_DB="${POSTGRES_DB:-knock}"
PG_USER="${POSTGRES_USER:-knock_admin}"

# Optional: DigitalOcean Spaces upload
DO_SPACES_UPLOAD="${DO_SPACES_UPLOAD:-false}"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${GREEN}[BACKUP]${NC} $*"; }
warn() { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${RED}[ERROR]${NC} $*" >&2; }

# -----------------------------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------------------------
mkdir -p "$BACKUP_DIR"

if ! docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
    err "PostgreSQL container '${PG_CONTAINER}' is not running."
    exit 1
fi

# -----------------------------------------------------------------------------
# Create backup
# -----------------------------------------------------------------------------
log "Starting PostgreSQL backup..."
log "Database: ${PG_DB} | Container: ${PG_CONTAINER}"

SECONDS=0

docker exec "$PG_CONTAINER" \
    pg_dump \
        --username="$PG_USER" \
        --dbname="$PG_DB" \
        --format=plain \
        --no-owner \
        --no-privileges \
        --verbose \
        --clean \
        --if-exists \
    2>/dev/null | gzip -9 > "$BACKUP_PATH"

DURATION=$SECONDS
BACKUP_SIZE=$(du -h "$BACKUP_PATH" | cut -f1)

# Verify backup is not empty
if [[ ! -s "$BACKUP_PATH" ]]; then
    err "Backup file is empty. Removing and exiting."
    rm -f "$BACKUP_PATH"
    exit 1
fi

# Verify backup integrity (quick gzip test)
if ! gzip -t "$BACKUP_PATH" 2>/dev/null; then
    err "Backup file is corrupt. Removing and exiting."
    rm -f "$BACKUP_PATH"
    exit 1
fi

log "Backup created: ${BACKUP_FILE} (${BACKUP_SIZE}) in ${DURATION}s"

# -----------------------------------------------------------------------------
# Upload to DigitalOcean Spaces (optional)
# -----------------------------------------------------------------------------
if [[ "$DO_SPACES_UPLOAD" == "true" ]]; then
    if [[ -z "${DO_SPACES_KEY:-}" || -z "${DO_SPACES_SECRET:-}" ]]; then
        warn "DO_SPACES_KEY/DO_SPACES_SECRET not set. Skipping remote upload."
    else
        DO_BUCKET="${DO_SPACES_BUCKET:-knock-backups}"
        DO_REGION="${DO_SPACES_REGION:-nyc3}"
        DO_ENDPOINT="https://${DO_REGION}.digitaloceanspaces.com"
        REMOTE_PATH="postgres/${BACKUP_FILE}"

        log "Uploading to DigitalOcean Spaces: s3://${DO_BUCKET}/${REMOTE_PATH}..."

        if command -v aws &>/dev/null; then
            AWS_ACCESS_KEY_ID="$DO_SPACES_KEY" \
            AWS_SECRET_ACCESS_KEY="$DO_SPACES_SECRET" \
            aws s3 cp "$BACKUP_PATH" \
                "s3://${DO_BUCKET}/${REMOTE_PATH}" \
                --endpoint-url "$DO_ENDPOINT" \
                --quiet

            log "Remote upload complete."
        elif command -v s3cmd &>/dev/null; then
            s3cmd put "$BACKUP_PATH" \
                "s3://${DO_BUCKET}/${REMOTE_PATH}" \
                --host="${DO_REGION}.digitaloceanspaces.com" \
                --host-bucket="%(bucket)s.${DO_REGION}.digitaloceanspaces.com" \
                --access_key="$DO_SPACES_KEY" \
                --secret_key="$DO_SPACES_SECRET" \
                --quiet

            log "Remote upload complete."
        else
            warn "Neither 'aws' CLI nor 's3cmd' found. Skipping remote upload."
            warn "Install with: apt install awscli  OR  pip install s3cmd"
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Prune old backups (local)
# -----------------------------------------------------------------------------
PRUNED=0
while IFS= read -r old_backup; do
    rm -f "$old_backup"
    PRUNED=$((PRUNED + 1))
done < <(find "$BACKUP_DIR" -name "knock_*.sql.gz" -type f -mtime +${RETENTION_DAYS})

if [[ $PRUNED -gt 0 ]]; then
    log "Pruned ${PRUNED} backup(s) older than ${RETENTION_DAYS} days."
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
TOTAL_BACKUPS=$(find "$BACKUP_DIR" -name "knock_*.sql.gz" -type f | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)

log "Backup complete. ${TOTAL_BACKUPS} backup(s) on disk (${TOTAL_SIZE} total)."
