# Vidistiller operations runbook (WP6)

Concise operator procedures for the stability/capacity control surface.
Production: VM900 `192.0.2.181` (SSH user `sysadmin`, deployment
`/opt/vidistiller/docker-compose.prod.yml`). All times UTC.

## 0. Health surface

| Endpoint | Meaning |
|---|---|
| `GET /health` | Liveness — process up. No DB dependency. |
| `GET /readyz` | Readiness — DB + Redis probe (bounded 2s pool timeout). 503 when a dependency is down. |
| `GET /metrics` | Prometheus text: pool checked-out/timeouts, request latency buckets, auth failures, idle-in-tx aborts. |
| `GET /api/ops/jobs` | Operator global job view (owner, admission state, queue reason/position, sidecar, progress, ETA). |
| `GET /api/ops/sidecars` | Operator live sidecar inventory (served model, load, reserved slots, staleness). |

Operator access: `python scripts/grant-operator.py grant <user_id> --actor <name>`
(one-time, audited; `revoke` and `list` also available).

## 1. Unhealthy API / login failures

1. `curl -s -m 5 http://127.0.0.1:8000/health` and `/readyz`.
2. Check DB sessions: `SELECT state, count(*) FROM pg_stat_activity GROUP BY state;`
   — many `idle in transaction` means a pool-starvation wedge.
3. Check `/metrics` for `vidistiller_pool_timeout_total` growth and
   `vidistiller_requests_5xx_total`.
4. If readyz shows `database: false` while Postgres itself is healthy, the app
   pool is saturated: restart only the API:
   `cd /opt/vidistiller && docker compose -f docker-compose.prod.yml restart api`.
5. Never restart Celery as part of API recovery. Never restart while a job
   step is mid-write; the step claim tokens make retries safe, but avoid
   restarting a worker with active tasks unless the task is stuck.

The host watchdog (`scripts/systemd/vidistiller-watchdog.{service,timer}`)
does this automatically after 3 consecutive liveness failures when DB+Redis
probe OK, rate-limited to 3 restarts/hour, with an audit log at
`/var/log/vidistiller-watchdog.log`.

## 2. Queue saturation

1. `GET /api/ops/jobs?status_filter=pending` — jobs in `queued` admission
   state show `queue_reason` (`global active-job limit reached` /
   `per-user active-job limit reached`) and `queue_position`.
2. `GET /api/ops/sidecars` — `reserved_slots` vs `total_slots` per sidecar.
3. Raise limits via `.env`:
   `ADMISSION_GLOBAL_ACTIVE_LIMIT`, `ADMISSION_PER_USER_ACTIVE_LIMIT`,
   `SIDECAR_SLOTS` — then `docker compose -f docker-compose.prod.yml up -d api`
   (recreates with new env; queued jobs are picked up by the admission sweep
   on next API restart or when capacity frees).
4. Queued jobs are dispatched by the outbox sweep on API startup — a restart
   of the API (not workers) publishes pending dispatches.

## 3. Sidecar outage

1. `GET /api/ops/sidecars` — `healthy: false` or `stale: true`.
2. Jobs prefer another compatible sidecar automatically (deterministic
   ranking); a job that explicitly preferred the dead sidecar is queued with
   a visible reason rather than run on an incompatible lane.
3. Telemetry fails closed for NEW allocations; in-flight work is never killed
   by stale telemetry.
4. Fix the sidecar (vLLM / vllm-manager) — no Vidistiller change needed.
   Slots are reclaimed after TTL + quarantine (`LEASE_TTL_SECONDS`,
   `LEASE_QUARANTINE_SECONDS`).

## 4. Leaked lease

A lease is "leaked" when a worker died mid-stage. The lease reaper (runs on
API startup; extend to a periodic sweep if needed) moves expired leases to
`expired`; slots are only reused after the quarantine window, so a stale
external request can never be overcommitted.

To inspect: `SELECT * FROM resource_slots WHERE state <> 'free';` and the
`lease_events` audit table. To force a reviewed reset (only after confirming
no in-flight sidecar request): move the row past quarantine
(`UPDATE resource_slots SET updated_at = now() - interval '1 hour' WHERE id = <id>;`)
then trigger the sweep, or reset manually and record the action in
`lease_events`.

## 5. Rollback

1. Code rollback while keeping the additive schema: deploy the previous
   image digests; new tables/columns are ignored by old code (all additive).
2. Before rolling back worker code: stop submissions, stop dispatch, drain or
   fence active leases (`resource_slots` → check for leased rows), set old
   worker concurrency to a safe value. Do NOT run mixed old/new worker
   generations on leased queues.
3. Schema rollback (destructive) is a separate maintenance action: back up
   first, then `alembic downgrade` stepwise. 0004/0005 downgrades drop the
   new tables only; `processing_jobs.sidecar_preference` is dropped in 0005.

## 6. Model manifest drift

The live served model is the routing authority (`/v1/models` probe). The
operator manifest (`config/llm_model_profiles.json`) declares expectations;
if they disagree (e.g. `qwen3.6-27b` declared, `qwen3.8-27b` served), update
the manifest to the actually-served model and verify readback via
`GET /api/ops/sidecars` (`served_models` vs `declared_model`).
