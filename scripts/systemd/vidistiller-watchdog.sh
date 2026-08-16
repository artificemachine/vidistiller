#!/usr/bin/env bash
# Least-privilege Vidistiller API watchdog (WP6).
#
# Runs from a root-owned systemd timer on the host (NOT inside a container,
# NO Docker socket mount). It can only ever restart the fixed `api` service
# of the fixed /opt/vidistiller compose project — no caller-supplied
# container or arguments are accepted.
#
# State machine:
#   - liveness fails AND DB+Redis probe OK  -> wedged API        -> restart
#   - liveness fails AND a dependency fails  -> dependency outage -> alert, no restart
#   - restarts are rate-limited (max/hour) with flock + cooldown -> no loops
#   - never restarts Celery
#
# Audit log: /var/log/vidistiller-watchdog.log (no secrets).
set -u

COMPOSE_DIR="${VIDISTILLER_COMPOSE_DIR:-/opt/vidistiller}"
COMPOSE_FILE="${VIDISTILLER_COMPOSE_FILE:-docker-compose.prod.yml}"
SERVICE="api"
HEALTH_URL="${VIDISTILLER_HEALTH_URL:-http://127.0.0.1:8000/health}"
DB_PROBE="${VIDISTILLER_DB_PROBE:-docker exec $(docker ps --filter name=tutorial_postgres -q | head -1) pg_isready -U postgres}"
REDIS_PROBE="${VIDISTILLER_REDIS_PROBE:-docker exec $(docker ps --filter name=tutorial_redis -q | head -1) redis-cli ping}"
FAILURES_BEFORE_RESTART="${VIDISTILLER_FAILURES_BEFORE_RESTART:-3}"
MAX_RESTARTS_PER_HOUR="${VIDISTILLER_MAX_RESTARTS_PER_HOUR:-3}"
LOCK_FILE="${VIDISTILLER_LOCK_FILE:-/run/vidistiller-watchdog.lock}"
STATE_FILE="${VIDISTILLER_STATE_FILE:-/var/lib/vidistiller-watchdog/state}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> /var/log/vidistiller-watchdog.log; }

exec 9>"$LOCK_FILE"
flock -n 9 || { log "another watchdog run holds the lock; exiting"; exit 0; }

mkdir -p "$(dirname "$STATE_FILE")"
: > "$STATE_FILE.tmp"

consecutive_failures=0
[[ -f "$STATE_FILE" ]] && consecutive_failures=$(cat "$STATE_FILE" 2>/dev/null || echo 0)

api_ok=0
curl -sf --max-time 5 "$HEALTH_URL" >/dev/null 2>&1 && api_ok=1

db_ok=0
if eval "$DB_PROBE" >/dev/null 2>&1; then db_ok=1; fi
redis_ok=0
if eval "$REDIS_PROBE" >/dev/null 2>&1; then redis_ok=1; fi

if [[ $api_ok -eq 1 ]]; then
    echo 0 > "$STATE_FILE.tmp"
    mv "$STATE_FILE.tmp" "$STATE_FILE"
    exit 0
fi

consecutive_failures=$((consecutive_failures + 1))
echo "$consecutive_failures" > "$STATE_FILE.tmp"
mv "$STATE_FILE.tmp" "$STATE_FILE"

if [[ $db_ok -eq 0 || $redis_ok -eq 0 ]]; then
    log "dependency outage (db=$db_ok redis=$redis_ok); API unhealthy but NOT restarting"
    exit 0
fi

if [[ $consecutive_failures -lt $FAILURES_BEFORE_RESTART ]]; then
    log "API unhealthy ($consecutive_failures/$FAILURES_BEFORE_RESTART consecutive); waiting"
    exit 0
fi

restart_count=0
[[ -f "$STATE_FILE.count" ]] && restart_count=$(cat "$STATE_FILE.count" 2>/dev/null || echo 0)
if [[ $restart_count -ge $MAX_RESTARTS_PER_HOUR ]]; then
    log "restart rate limit reached ($restart_count/hour); alerting, NOT restarting"
    exit 1
fi

cd "$COMPOSE_DIR" || { log "compose dir missing: $COMPOSE_DIR"; exit 1; }
log "restarting ${SERVICE} (db=$db_ok redis=$redis_ok, failures=$consecutive_failures)"
docker compose -f "$COMPOSE_FILE" restart "$SERVICE" >> /var/log/vidistiller-watchdog.log 2>&1
restart_count=$((restart_count + 1))
echo "$restart_count" > "$STATE_FILE.count"
echo 0 > "$STATE_FILE"
log "restart issued (count this hour: $restart_count)"
