# Vidistiller — Ops Runbook

Durable notes on deployment gotchas, VM quirks, and operational patterns.
Not session-specific — update in place, never overwrite.

---

## Docker Compose — Orphaned Containers in "Created" State

**Discovered:** 2026-06-09

### Root cause

Containers stuck in `Created` state (created by compose but never fully started) do **not** appear in `docker ps -a` without `--no-trunc`. Because of this, `docker compose down --remove-orphans` silently misses them. The next `docker compose up -d` then fails with:

```
Conflict. The container name "/tutorial_redis" is already in use by container "<full-id>".
```

### When it happens

After a failed or interrupted `docker compose up -d` — for example when a dependency health check times out mid-stack-start.

### Diagnosis

```bash
docker container ls -a --no-trunc --format '{{.ID}} {{.Names}} {{.Status}}'
# Look for any containers in "Created" state
```

### Fix

```bash
# Remove stale Created-state containers by full ID
docker rm <full-id-1> <full-id-2>

# Then bring the stack up normally
docker compose -f docker-compose.prod.yml down --remove-orphans
docker compose -f docker-compose.prod.yml up -d
```

### Permanent fix (TODO)

Add the `--no-trunc` detection + removal step to the deploy script so it runs automatically before every `up -d`.

---

## vLLM Fleet — Port Rules

- **Port 8000** — direct vLLM inference. Use this for `VLLM_VM913_URL`.
- **Port 8100** — vllm-manager. Do NOT use for inference. It intercepts `/v1/chat/completions` as a model-swap trigger and returns 409.

## Docker Compose — Env Var Changes

`docker restart` does NOT re-read `.env`. Any `.env` change on the VM requires:

```bash
docker compose -f docker-compose.prod.yml up -d <service>
```

This recreates the container with the updated env.

## Frontend Build — NEXT_PUBLIC_* Vars

`NEXT_PUBLIC_*` vars are baked into the static JS bundle at build time. Always build with the correct URL:

```bash
NEXT_PUBLIC_API_URL=http://10.255.181.20:8000/api npm run build
```

Never use the default `.env.local` values for VM deploys.
