#!/usr/bin/env bash
# =============================================================================
# Knock - Redis Cache Rebuild Script
# Reads schools and people from PostgreSQL, writes to Redis as JSON + sorted sets.
# Use after data imports, schema changes, or cache corruption.
#
# Usage: ./rebuild-redis-cache.sh [--flush] [--schools-only] [--people-only]
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
PG_CONTAINER="${PG_CONTAINER:-knock-postgres}"
REDIS_CONTAINER="${REDIS_CONTAINER:-knock-redis}"
PG_DB="${POSTGRES_DB:-knock}"
PG_USER="${POSTGRES_USER:-knock_admin}"

FLUSH_BEFORE="${FLUSH_BEFORE:-false}"
REBUILD_SCHOOLS=true
REBUILD_PEOPLE=true
BATCH_SIZE=500

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "[$(date '+%H:%M:%S')] ${GREEN}[CACHE]${NC} $*"; }
warn() { echo -e "[$(date '+%H:%M:%S')] ${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "[$(date '+%H:%M:%S')] ${RED}[ERROR]${NC} $*" >&2; }
info() { echo -e "[$(date '+%H:%M:%S')] ${CYAN}[INFO]${NC} $*"; }

# -----------------------------------------------------------------------------
# Parse arguments
# -----------------------------------------------------------------------------
for arg in "$@"; do
    case $arg in
        --flush)         FLUSH_BEFORE=true ;;
        --schools-only)  REBUILD_PEOPLE=false ;;
        --people-only)   REBUILD_SCHOOLS=false ;;
        --help|-h)
            echo "Usage: $0 [--flush] [--schools-only] [--people-only]"
            echo "  --flush         Flush all cache keys before rebuild"
            echo "  --schools-only  Only rebuild school cache"
            echo "  --people-only   Only rebuild people cache"
            exit 0
            ;;
        *) err "Unknown argument: $arg"; exit 1 ;;
    esac
done

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
pg_query() {
    docker exec "$PG_CONTAINER" \
        psql -U "$PG_USER" -d "$PG_DB" -t -A -F '|' -c "$1" 2>/dev/null
}

redis_cmd() {
    docker exec "$REDIS_CONTAINER" redis-cli "$@" 2>/dev/null
}

redis_pipe() {
    docker exec -i "$REDIS_CONTAINER" redis-cli --pipe 2>/dev/null
}

# -----------------------------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------------------------
for container in "$PG_CONTAINER" "$REDIS_CONTAINER"; do
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        err "Container '${container}' is not running."
        exit 1
    fi
done

log "Starting Redis cache rebuild..."
SECONDS=0

# -----------------------------------------------------------------------------
# Optional: flush existing cache
# -----------------------------------------------------------------------------
if [[ "$FLUSH_BEFORE" == "true" ]]; then
    warn "Flushing Redis cache keys (knock:* prefix)..."
    # Only flush knock-prefixed keys, not all of Redis
    local_keys=$(redis_cmd KEYS "knock:*" | wc -l)
    if [[ "$local_keys" -gt 0 ]]; then
        redis_cmd KEYS "knock:*" | while read -r key; do
            redis_cmd DEL "$key" > /dev/null
        done
    fi
    log "Flushed $local_keys cache keys."
fi

# -----------------------------------------------------------------------------
# Rebuild school cache
# -----------------------------------------------------------------------------
if [[ "$REBUILD_SCHOOLS" == "true" ]]; then
    log "Rebuilding school cache..."

    SCHOOL_COUNT=$(pg_query "SELECT COUNT(*) FROM schools;")
    info "Found ${SCHOOL_COUNT} schools in PostgreSQL."

    OFFSET=0
    PROCESSED=0

    while true; do
        # Fetch a batch of schools as JSON
        BATCH=$(pg_query "
            SELECT json_build_object(
                'id', s.id,
                'name', s.name,
                'nces_id', s.nces_id,
                'school_type', s.school_type,
                'city', s.city,
                'state', s.state,
                'zip', s.zip,
                'enrollment_total', s.enrollment_total,
                'tuition_low', s.tuition_low,
                'tuition_high', s.tuition_high,
                'religious_affiliation', s.religious_affiliation,
                'coed_status', s.coed_status,
                'boarding_status', s.boarding_status,
                'grade_low', s.grade_low,
                'grade_high', s.grade_high,
                'website', s.website
            )::text
            FROM schools s
            ORDER BY s.name
            LIMIT $BATCH_SIZE OFFSET $OFFSET;
        ")

        # Break if no more rows
        [[ -z "$BATCH" ]] && break

        # Pipe batch to Redis
        while IFS= read -r row; do
            # Extract ID and state from the JSON (lightweight parsing)
            SCHOOL_ID=$(echo "$row" | jq -r '.id' 2>/dev/null || echo "")
            SCHOOL_STATE=$(echo "$row" | jq -r '.state // empty' 2>/dev/null || echo "")
            SCHOOL_NAME=$(echo "$row" | jq -r '.name // empty' 2>/dev/null || echo "")
            ENROLLMENT=$(echo "$row" | jq -r '.enrollment_total // 0' 2>/dev/null || echo "0")

            [[ -z "$SCHOOL_ID" ]] && continue

            # Store full JSON object
            redis_cmd SET "knock:school:${SCHOOL_ID}" "$row" EX 86400 > /dev/null

            # Add to state-based sorted set (scored by enrollment for ranking)
            if [[ -n "$SCHOOL_STATE" ]]; then
                redis_cmd ZADD "knock:schools:state:${SCHOOL_STATE}" "${ENROLLMENT:-0}" "$SCHOOL_ID" > /dev/null
            fi

            # Add to global sorted set
            redis_cmd ZADD "knock:schools:all" "${ENROLLMENT:-0}" "$SCHOOL_ID" > /dev/null

            # Add to name lookup hash
            if [[ -n "$SCHOOL_NAME" ]]; then
                redis_cmd HSET "knock:schools:names" "$SCHOOL_ID" "$SCHOOL_NAME" > /dev/null
            fi

            PROCESSED=$((PROCESSED + 1))
        done <<< "$BATCH"

        OFFSET=$((OFFSET + BATCH_SIZE))
        info "  Processed ${PROCESSED}/${SCHOOL_COUNT} schools..."
    done

    # Store metadata
    redis_cmd SET "knock:schools:count" "$PROCESSED" > /dev/null
    redis_cmd SET "knock:schools:last_rebuild" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /dev/null

    log "School cache rebuilt: ${PROCESSED} schools indexed."
fi

# -----------------------------------------------------------------------------
# Rebuild people cache
# -----------------------------------------------------------------------------
if [[ "$REBUILD_PEOPLE" == "true" ]]; then
    log "Rebuilding people cache..."

    PEOPLE_COUNT=$(pg_query "SELECT COUNT(*) FROM people;")
    info "Found ${PEOPLE_COUNT} people in PostgreSQL."

    OFFSET=0
    PROCESSED=0

    while true; do
        # Fetch a batch of people as JSON
        BATCH=$(pg_query "
            SELECT json_build_object(
                'id', p.id,
                'first_name', p.first_name,
                'last_name', p.last_name,
                'email', p.email,
                'phone', p.phone,
                'current_title', p.current_title,
                'current_school_id', p.current_school_id,
                'city', p.city,
                'state', p.state,
                'linkedin_url', p.linkedin_url,
                'years_experience', p.years_experience,
                'is_candidate', p.is_candidate,
                'candidate_status', p.candidate_status
            )::text
            FROM people p
            ORDER BY p.last_name, p.first_name
            LIMIT $BATCH_SIZE OFFSET $OFFSET;
        ")

        [[ -z "$BATCH" ]] && break

        while IFS= read -r row; do
            PERSON_ID=$(echo "$row" | jq -r '.id' 2>/dev/null || echo "")
            PERSON_STATE=$(echo "$row" | jq -r '.state // empty' 2>/dev/null || echo "")
            LAST_NAME=$(echo "$row" | jq -r '.last_name // empty' 2>/dev/null || echo "")
            FIRST_NAME=$(echo "$row" | jq -r '.first_name // empty' 2>/dev/null || echo "")
            IS_CANDIDATE=$(echo "$row" | jq -r '.is_candidate // false' 2>/dev/null || echo "false")
            YEARS_EXP=$(echo "$row" | jq -r '.years_experience // 0' 2>/dev/null || echo "0")

            [[ -z "$PERSON_ID" ]] && continue

            # Store full JSON object (24h TTL)
            redis_cmd SET "knock:person:${PERSON_ID}" "$row" EX 86400 > /dev/null

            # Add to state-based sorted set (scored by experience)
            if [[ -n "$PERSON_STATE" ]]; then
                redis_cmd ZADD "knock:people:state:${PERSON_STATE}" "${YEARS_EXP:-0}" "$PERSON_ID" > /dev/null
            fi

            # Add to global sorted set
            redis_cmd ZADD "knock:people:all" "${YEARS_EXP:-0}" "$PERSON_ID" > /dev/null

            # If active candidate, add to candidates set
            if [[ "$IS_CANDIDATE" == "true" || "$IS_CANDIDATE" == "t" ]]; then
                redis_cmd ZADD "knock:candidates:active" "${YEARS_EXP:-0}" "$PERSON_ID" > /dev/null
            fi

            # Name lookup hash
            redis_cmd HSET "knock:people:names" "$PERSON_ID" "${LAST_NAME}, ${FIRST_NAME}" > /dev/null

            PROCESSED=$((PROCESSED + 1))
        done <<< "$BATCH"

        OFFSET=$((OFFSET + BATCH_SIZE))
        info "  Processed ${PROCESSED}/${PEOPLE_COUNT} people..."
    done

    # Store metadata
    redis_cmd SET "knock:people:count" "$PROCESSED" > /dev/null
    redis_cmd SET "knock:people:last_rebuild" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /dev/null

    log "People cache rebuilt: ${PROCESSED} people indexed."
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
DURATION=$SECONDS
REDIS_KEYS=$(redis_cmd DBSIZE | grep -oP '\d+')

log "============================================"
log "  Cache rebuild complete in ${DURATION}s"
log "  Total Redis keys: ${REDIS_KEYS}"
log "============================================"
