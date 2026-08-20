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
#   - restarts are rate-limited (max/hour, timestamped window)  -> no loops
#   - never restarts Celery
#
# Audit log: /var/log/vidistiller-watchdog.log (no secrets).
set -u

COMPOSE_DIR="${VIDISTILLER_COMPOSE_DIR:-/opt/vidistiller}"
COMPOSE_FILE="${VIDISTILLER_COMPOSE_FILE:-docker-compose.prod.yml}"
SERVICE="api"
HEALTH_URL="${VIDISTILLER_HEALTH_URL:-http://127.0.0.1:8000/health}"
FAILURES_BEFORE_RESTART="${VIDISTILLER_FAILURES_BEFORE_RESTART:-3}"
MAX_RESTARTS_PER_HOUR="${VIDISTILLER_MAX_RESTARTS_PER_HOUR:-3}"
LOCK_FILE="${VIDISTILLER_LOCK_FILE:-/run/vidistiller-watchdog.lock}"
STATE_DIR="${VIDISTILLER_STATE_DIR:-/var/lib/vidistiller-watchdog}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> /var/log/vidistiller-watchdog.log; }

exec 9>"$LOCK_FILE"
flock -n 9 || { log "another watchdog run holds the lock; exiting"; exit 0; }

mkdir -p "$STATE_DIR"

# ---------------------------------------------------------------------------
# Dependency probes: fixed commands, no eval (Review Round 2 F14). The DB and
# Redis container ids are resolved once per run with exact docker invocations.
# ---------------------------------------------------------------------------
postgres_id=$(docker ps --filter name=tutorial_postgres -q | head -1)
redis_id=$(docker ps --filter name=tutorial_redis -q | head -1)

api_ok=0
curl -sf --max-time 5 "$HEALTH_URL" >/dev/null 2>&1 && api_ok=1

db_ok=0
if [[ -n "$postgres_id" ]] && docker exec "$postgres_id" pg_isready -U postgres >/dev/null 2>&1; then
    db_ok=1
fi

redis_ok=0
if [[ -n "$redis_id" ]]; then
    # Authenticated PONG without exposing the password in process arguments:
    # the password is read from the container's own environment by redis-cli.
    if docker exec "$redis_id" sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping 2>/dev/null' | grep -qx PONG; then
        redis_ok=1
    fi
fi

# ---------------------------------------------------------------------------
# Consecutive-failure counter.
# ---------------------------------------------------------------------------
consecutive_failures=0
if [[ -f "$STATE_DIR/failures" ]]; then
    consecutive_failures=$(cat "$STATE_DIR/failures" 2>/dev/null || echo 0)
fi

if [[ $api_ok -eq 1 ]]; then
    echo 0 > "$STATE_DIR/failures"
    exit 0
fi

consecutive_failures=$((consecutive_failures + 1))
echo "$consecutive_failures" > "$STATE_DIR/failures"

if [[ $db_ok -eq 0 || $redis_ok -eq 0 ]]; then
    log "dependency outage (db=$db_ok redis=$redis_ok); API unhealthy but NOT restarting"
    exit 0
fi

if [[ $consecutive_failures -lt $FAILURES_BEFORE_RESTART ]]; then
    log "API unhealthy ($consecutive_failures/$FAILURES_BEFORE_RESTART consecutive); waiting"
    exit 0
fi

# ---------------------------------------------------------------------------
# Rate limit: timestamped restart events, pruned to the last hour.
# ---------------------------------------------------------------------------
now_epoch=$(date +%s)
one_hour_ago=$((now_epoch - 3600))
restart_log="$STATE_DIR/restarts"
touch "$restart_log"
restarts_in_window=0
: > "$restart_log.tmp"
while IFS= read -r ts; do
    [[ -z "$ts" ]] && continue
    if [[ "$ts" -ge "$one_hour_ago" ]]; then
        restarts_in_window=$((restarts_in_window + 1))
        echo "$ts" >> "$restart_log.tmp"
    fi
done < "$restart_log"
mv "$restart_log.tmp" "$restart_log"

if [[ $restarts_in_window -ge $MAX_RESTARTS_PER_HOUR ]]; then
    log "restart rate limit reached ($restarts_in_window in the last hour); alerting, NOT restarting"
    exit 1
fi

# ---------------------------------------------------------------------------
# Restart: fixed arguments only.
# ---------------------------------------------------------------------------
cd "$COMPOSE_DIR" || { log "compose dir missing: $COMPOSE_DIR"; exit 1; }
log "restarting ${SERVICE} (db=$db_ok redis=$redis_ok, failures=$consecutive_failures)"
docker compose -f "$COMPOSE_FILE" restart "$SERVICE" >> /var/log/vidistiller-watchdog.log 2>&1
echo "$now_epoch" >> "$restart_log"
echo 0 > "$STATE_DIR/failures"
log "restart issued (restarts in window: $((restarts_in_window + 1)))"
