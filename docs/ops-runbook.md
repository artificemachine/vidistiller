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

### Important: a pre-`up` sweep does NOT catch them (verified 2026-06-09)

The conflicting container is created **during** the failing `up`, not before it. So filtering for `status=created` *before* running `up` finds nothing, then `up` recreates the conflict and fails again. Do not rely on a pre-sweep — remove by **name** instead.

### Fix (reliable)

```bash
cd /opt/vidistiller
# Force-remove ALL project containers by name, any status, then bring the stack up
names=$(docker container ls -a --no-trunc --format '{{.Names}}' | grep '^tutorial_')
[ -n "$names" ] && docker rm -f $names
docker compose -f docker-compose.prod.yml up -d
```

`docker rm -f` by name handles running, exited, and `Created`-state containers in one shot — which is what makes it reliable where `down --remove-orphans` + a `status=created` sweep is not.

### Permanent fix (TODO)

Add the force-remove-by-name step to the deploy script so it runs automatically before every `up -d`.

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
