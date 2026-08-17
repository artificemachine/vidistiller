# Stability & Capacity Control Surface — Design (2026-08-16)

Driver: `deepseek/deepseek-v4-flash` (cloud) · Reviews: `openai-codex/gpt-5.6-sol` (xhigh)
This design folds IMPLEMENTATION-PLAN-2026-08-16.md and Review Round 1 findings (R1#n).

## R1 Blocker resolution — fencing external sidecar work (R1#5)

A DB lease TTL alone cannot stop an in-flight vLLM request from a worker that
was redelivered. Design:

1. **Per-incarnation execution UUID**: every task execution mints `exec_uuid =
   uuid4()` at start. Claims, heartbeats, completions, releases use
   `(exec_uuid, generation)` — never the Celery `request.id` (which is
   preserved across redelivery).
2. **Generation counter**: each `resource_slots` row carries a monotonic
   `generation`. Every transition (acquire→heartbeat→release/reclaim)
   increments it and is a conditional UPDATE on `generation = g`.
3. **Independent heartbeat**: workers heartbeat the lease with DB time on a
   bounded interval, decoupled from the blocking LLM call (heartbeat issued
   from a wrapper thread/interval check inside the LLM loop; DB server time).
4. **Conservative reclamation**: a lease is only reaped after
   `expires_at` AND a quarantine window ≥ configured max LLM request timeout
   + grace (default TTL 1200s, max LLM timeout 600s, quarantine 900s). Slots
   move to `expired` state, never directly back to `free`. Operator or the
   watchdog may confirm zero in-flight (via vLLM `/v1/models` running count
   where available) before manual reset; auto-reset only after quarantine
   expiry, documented as bounded-conservative.
5. **Cancellation order**: fence first (state=cancelled, generation bump in
   same txn), then request termination (Celery revoke), then release.

## WP1 — DB lifecycle (R1#1,2,3,4,15,16)

- Media authorization uses its **own short-lived session** (explicit
  `SessionLocal` in a context manager), closes before building `FileResponse`;
  no `Depends(get_db)` on media routes; immutable `(job_id, user_id, path)`
  copied out. Range requests, cache headers, traversal/containment checks,
  and indistinguishable-404 behavior preserved. `Vary` header added.
- Configurable pool: `DB_POOL_SIZE` (default 20), `DB_MAX_OVERFLOW` (40),
  `DB_POOL_TIMEOUT` (30s), `DB_POOL_RECYCLE` (3600s), `DB_POOL_PRE_PING`.
- Application guard for `idle_in_transaction_session_timeout`:
  `SET idle_in_transaction_session_timeout` executed per PG connection at
  connect (configurable `DB_IDLE_IN_TX_TIMEOUT`, default 30000ms). Long
  worker transactions are restructured so no worker session idles in a
  transaction across network work.
- Metrics: SQLAlchemy pool events → checked-out, wait, timeout counters;
  request latency and auth-failure counters; exposed at `/metrics` (plain
  Prometheus text, no new deps).
- `/health` stays dependency-free; `/readyz` gains a bounded probe (short
  pool timeout via dedicated `pool_timeout` param on `health_check`), Redis
  connect+read timeouts, and explicit startup boolean handling.

## WP2 — Admission & leases (R1#6,7)

New tables (migration 0004):

- `admission_counters(key PK, active INT, limit INT, updated_at)` — rows
  `global` and `user:<id>`; locked in deterministic global→user order.
- `job_admissions(job_id PK/FK, state queued|admitted|finished|failed,
  queue_reason, admitted_at, policy_version)`.
- `resource_slots(id, sidecar_id FK, slot_index, enabled, state free|leased|
  expired, job_id, claim_exec_uuid, generation, heartbeat_at, expires_at,
  updated_at)` unique (sidecar_id, slot_index).
- `lease_events(id, slot_id, job_id, event acquire|heartbeat|release|reclaim|
  expire, exec_uuid, generation, created_at)` append-only audit.
- `task_outbox(id, job_id, stage, generation, state pending|published|
  delivered, payload, created_at)` — at-least-once dispatch.

Admission txn (one DB txn): lock `admission_counters` rows (global then user)
FOR UPDATE; verify limits; if full → insert `job_admissions(queued, reason)` +
queue position derived; else admit + acquire slot (FOR UPDATE SKIP LOCKED,
generation+1, expires_at=now+TTL) + write outbox(pending) + audit. Commit;
then post-commit `.delay()` for published stage; a recovery sweep on API
startup re-publishes pending outbox rows (also on interval).

Release/reclaim: conditional UPDATE on `(exec_uuid, generation)`; counters
decrement exactly once.

Celery config (app.tasks): `broker_transport_options.visibility_timeout`
(default 900s), `task_reject_on_worker_lost=True`, explicit
`task_time_limit`/`task_soft_time_limit` per task, `worker_concurrency`
explicit at compose (2 CPU / default), late-ack + prefetch 1 preserved.
CPU/download/transcript work and LLM/vision work are separable queues where
compose declares them; default CPU concurrency matches the 2-CPU quota.

## WP3 — Sidecars (R1#8,12,13,14)

- `sidecars(id, registered_id unique, label, base_url, capabilities JSON,
  declared_model, enabled, created_at, updated_at)` — trusted operator
  configuration (config/sidecars.json + env), never client-supplied.
- `JobCreate.sidecar_preference`: `"auto"` (default) or a registered id from
  the server-side registry. Stored as the ID only; resolved server-side at
  admission and again before execution. Unknown/URL-shaped/unregistered →
  422. Unavailable/full → visible queue with reason or explicit fallback
  policy.
- Load-aware inventory: probe health, served model (`/v1/models`), running/
  waiting requests and cache/VRAM where the sidecar exposes them
  (vllm-manager `/status`), plus Vidistiller-reserved slots from
  `resource_slots`; telemetry timestamped; stale (> TTL) fails closed for
  new allocations, never kills in-flight work.
- Model-manifest drift fix: production `config/llm_model_profiles.json`
  updated `qwen3.6-27b` → `qwen3.8-27b` (verified served model); the
  checked-in template keeps the empty-manifest legacy behavior until an
  operator certifies profiles. Inventory identity comes from the live
  probe, not the declaration.
- Slide classification: bounded batch requests (deterministic stable IDs,
  schema validation, retry only failed items, sequential fallback, bounded
  concurrency under the sidecar lease) with a fixed-fixture benchmark.

## WP4 — RBAC (R1#9,10,11)

- `user_roles(id, user_id FK, role, granted_by, granted_at, revoked_at)`.
- `require_operator` dependency: DB-backed, fail closed (503/deny on
  lookup/DB error), no username/M2M/ownership inference.
- One-time grant: `scripts/grant-operator.py <user_id>` (audit trail, no
  hardcoded usernames).
- `/api/ops/jobs`: sanitized allowlisted DTO (owner id, status, stage, queue
  reason/position, sidecar/model, elapsed, progress, ETA range, failure
  category) — never URLs/transcripts/paths/tokens. Ordinary users keep
  their own-job views; cross-user isolation contract tests.
- `_get_job_for_user` hardened: ownership in the WHERE clause.

## WP5 — Progress & ETA (R1 acceptance)

- Real counters wired through `set_step_progress` (download, frames scanned/
  total, transitions classified/total, slides captured/total, finalization),
  monotonic within stage, persisted across reconnect.
- ETA: calibrated from historical completed jobs by (mode, media duration,
  stage, model/sidecar); range + confidence; cold-start/low-confidence
  labeled; observed-throughput updates. Backtest with temporal holdout; MAE
  and P90 APE metrics.

## WP6 — Resilience & observability (R1#15,16)

- Host/systemd watchdog (`scripts/systemd/vidistiller-watchdog.{service,
  timer}`): root-owned fixed-argument helper that restarts only
  `tutorial_api`; state machine (liveness fail + independent DB/Redis OK →
  wedged → restart after N consecutive failures; dependency outage → alert,
  no restart; restart loops rate-limited + audit log). No Docker socket in
  containers. Never auto-restarts Celery.
- Dashboards/alerts + runbook: `deploy/grafana/`, `docs/runbook-*.md`.

## Rollback & migration (R1#17,18)

- Additive migrations only; separate admission state (no extension of
  `processingstatus` enum); nullable-first columns; server defaults where
  scheduler inserts need them; indexes for queued ordering, user admission,
  lease expiry, active roles. Downgrade rehearsed head→0003→head on
  production-like PG. Backup before any production migration. Mixed old/new
  workers on leased queues are not allowed (drain + fence before worker
  rollback).

## Test matrix (R1#19,20)

Real-PostgreSQL concurrency tests (atomic races, lease expiry, worker-loss,
queued recovery), 200-concurrent authenticated media stress with slow
readers, cross-user isolation contract tests, SSRF/allowlist tests, fixed
fixture slide batching quality comparison, ETA backtest with defined pass
thresholds, migration upgrade/downgrade/re-upgrade with representative data,
watchdog state-machine tests, Compose/config validation.
