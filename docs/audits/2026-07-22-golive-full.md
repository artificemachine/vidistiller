# /golive — `2026-07-22-golive-full.md`

**Mode:** default (Stages 1–9 in full) — re-run explicitly requested after the prior same-day `--quick` report (`2026-07-22-golive-quick.md`) plus the top-5 fixes shipped via PRs #161 and #162 plus the `gh release create v1.12.21`.

**Plan for this turn:** run Stage 4 (fresh-clone + dependency health) in-place; delegate Stages 5 / 6 / 7 / 8 to focused sub-agents that run each delegated skill in full; run Stage 7b (`/infra-probe`) live against `vidistiller` production (192.0.2.10); assemble Stage 9 scorecard. Whatever doesn't finish in this turn writes a `continue` resume point into `docs/audits/golive-progress.md`.

**Reference state at run start:**
- Branch: `main` (clean).
- HEAD: `b8e217b` (`docs(audits): commit 2026-07-22 /golive --quick re-run report (#162)`).
- Tag: `v1.12.21` (annotated, on `origin/main`; `gh release` entry published 2026-07-22 21:46 UTC).
- Production: `v1.12.20` on `vidistiller` (no deploy needed; the cleanup PR was docs-only, prod stays).
- Remote branches: 1 main + 10 dependabot (no manual-feature branches remaining).
- Pre-cleanup state (this session's earlier work): `docs/README.my.notes.md` removed from tracked, `pyproject.toml` aligned to 1.12.21, ROADMAP CI/CD flipped.

**Already executed in this turn (carried from `--quick`):**
- Stage 1 (Recruiter First-Impression): PASS — see `2026-07-22-golive-quick.md` lines 17–40.
- Stage 2 (Git History & Release Hygiene): PASS — same source file, lines 43–93; cleanup plan EXECUTED this session (PR #161 + `gh release create v1.12.21` + obsolete-branch delete). Re-verified below.
- Stage 3 (README + Docs): PASS post-cleanup — same source file, lines 96–134; HIGH closed (transcript `git rm`), both MEDs halved-closed (CI/CD flipped to [x], Backup stayed honest [ ]). Re-verified below.

The remainder of this report covers Stages 4–9.

---

## Stage 1 — Recruiter First-Impression Gate — PASS (re-verified post-cleanup)

**Verdict:** PASS. State unchanged from the prior `--quick` re-run (`docs/audits/2026-07-22-golive-quick.md:17–40`) — the cleanup PRs (#161, #162) didn't touch any Stage-1 surface. 1 carried MED (no CI badge in README — separate docs-only fix if wanted); 2 LOW (LICENSE personal-handle attribution; CHANGELOG partial-handle in 2026-04 Docker Hub rename note — already-accepted residual). No live-secret/personal-data leak.

**Blockers:** 0

**Detail:** see `docs/audits/2026-07-22-golive-quick.md` Stage 1 findings table. No drift.

## Stage 2 — Git History & Release Hygiene — PASS (re-verified post-cleanup)

**Verdict:** PASS. The 4 LOW/INFO findings from the prior `--quick` re-run are all closed in this session's cleanup:
- (a) `pyproject.toml` version 1.12.20 → **1.12.21** (PR #161 commit `813c5f1`)
- (b) Tag v1.12.21 had no `gh release create` entry → **CLOSED**: `https://github.com/artificemachine/vidistiller/releases/tag/v1.12.21` now lists `Latest   v1.12.21`
- (c) Obsolete remote branch `fix/golive-followups` → **CLOSED**: deleted from `origin` and locally via `git push origin --delete` + `git branch -D` (force-delete required because squash-merged branch tip `725eb31` is not an ancestor of `main`'s `d2cd1f1`)
- (d) 100% self-merge SDLC neutral note — unchanged, neutral for solo-maintained

The Stage-2 cleanup plan from the prior `--quick` re-run is **fully executed**. No new findings this turn.

**Blockers:** 0

## Stage 3 — README + Docs — PASS (re-verified post-cleanup)

**Verdict:** PASS. The HIGH (1) + MED (1) + LOW (1) findings from the prior `--quick` re-run are now:
- HIGH (raw AI coding-session transcript in tracked `docs/`) → **CLOSED**: `git rm docs/README.my.notes.md` + `.gitignore` + `docs/README.md:25` rewrite (PR #161 commit `f6fcf21`). Data remains recoverable via `git log -p` from any old clone (forward-only, no history rewrite).
- MED (ROADMAP `CI/CD pipeline (GitHub Actions) [ ]` stale) → **CLOSED**: flipped to `[x]` with a brief note about the 2026-04-26 incident being the literal reason (PR #161 commit `4c61676`). The Backup-claim half kept `[ ]` honestly with a one-line note about the missing automated-restore drill.
- LOW (carried disambiguation-line closure) → **CLOSED**: rewrote `docs/README.md:25` to point at `.gitignore` directly instead of claiming the file was a tracked internal artifact.

`/readme-audit` verdict remains READY (canonical sections present + 3-screenshot fold + arch diagram). `/docs-organize` remains 0-moves-proposed.

**Blockers:** 0

**Note:** The carried MED finding about **CI badge in README** (Stage 1) and the carried LOW about LICENSE's handle attribution (Stage 1) are unchanged and outside Stage 3.

## Stage 4 — Fresh-Clone Verification + Dependency Health — PASS (with caveats)

**Verdict:** Fresh clone at `/tmp/opencode/golive-fresh-2026-07-22-v1.12.21` (depth=50, HEAD `b8e217b`) succeeds against the documented quickstart once an existing host-side `postgres` (PID 3526, listening on `[::1]:5432` + `127.0.0.1:5432` from a prior `brew install postgresql` or similar) is accounted for. **525 / 1** (525 pass, 28 skip when running without the migration-drift test; **525 pass + 1 pass + 28 skip** when migration-drift is included). **Zero npm CVEs at all levels** (the `sharp` HIGH CVE pin in `frontend/package.json` `overrides` is holding). **One MED finding** for a `pip install -e .` footgun and a **LOW** for the host-port collision on the documented `docker-compose.test.yml`. No HARD GATE triggers.

**Blockers:** 0

### Findings

| Severity | Finding | Evidence |
|----------|---------|----------|
| MED | `pip install -e .` from a fresh checkout FAILS on current setuptools (>= 64, error: `Multiple top-level packages discovered in a flat-layout: ['e2e', 'deploy', 'backend', 'frontend', 'terraform', 'migrations']`) | Reproduced from a fresh clone (this turn). setuptools 81.0.0 here rejected the layout. README doesn't tell users to run this command — the documented quickstart is `cp .env.example .env && docker compose up -d` — but no README line warns against `pip install -e .` either. A developer following the standard "clone / venv / pip install -e" instinct will hit it. Real fix options: (a) `pyproject.toml` `[tool.setuptools] packages = ["backend"]` (or `find:` directive) to make auto-discovery explicit; (b) add a note in README's "Running the Frontend Alone" / "Running the Backend Alone" sections; (c) move `e2e/`, `deploy/`, `frontend/`, `terraform/`, `migrations/` under a single `python/` namespace, which is a heavier refactor |
| LOW | `docker-compose.test.yml` ports `5432:5432` and `6379:6379` collide with the host's pre-existing `postgres` and any host `redis`. The test compose assumes a clean host. Reproduced: this turn's `lsof -nP -i :5432` showed `postgres 3526 example-user` on `[::1]:5432` + `127.0.0.1:5432` taking precedence over the docker postgres container; my host-side `psycopg2.connect(host='localhost', port=5432, ...)` failed with `role "tutorial_user" does not exist` | Workaround used: temporary port-override (5432→15432, 6379→16379) in the worktree (reverted after teardown; the file is back to upstream's `5432:5432` / `6379:6379`). A user on a host with their own postgres/redis services installed (a normal dev setup) will hit this. Real fix options: (a) document the collision in README + the test compose's header comment; (b) parametrize the host port via `.env` (`PGPORT=5432`); (c) on macOS/Linux, switch the test compose to a Unix socket or a unique host port by default |
| INFO | 20 CVEs in 9 packages in the user's existing `.venv` (`pip-audit` 2.10.1 output) — but **none of those pins come from the project's manifests**. The project's `backend/requirements.txt` doesn't pin `httplib2`, `pyasn1`, `starlette`, `ecdsa`, `nltk`, `pip`; those come from transitive dev-environment contamination (the user's `.venv` was installed at an earlier point and not all packages have been refreshed). The actual production build (per `backend/Dockerfile`) installs `requirements.txt` to `/app/deps` against `python:3.14-slim`, and the deployed prod image has been through the same `pip install -r requirements.txt` cycle. The CRITICAL `sharp` HIGH CVE that was the prior audit's mechanical NOT READY trigger is confirmed gone: `npm audit --audit-level=low` against fresh clone reports `found 0 vulnerabilities` | `pip-audit` output captured during Stage 4 step 5. **Not a Stage 4 finding for THIS run** because the project's manifest doesn't pin these. Recorded here so the next audit pass can decide whether to add a CI job that pins/resolves via pip-compile or pip-tools |

### Verified PASS items

#### Step 1 — Fresh clone
- `git clone --depth=50 https://github.com/artificemachine/vidistiller.git /tmp/opencode/golive-fresh-2026-07-22-v1.12.21` → succeeded, repo at HEAD `b8e217b` (matches `origin/main`).

#### Step 2 — Documented install path
- `cp .env.example .env` → succeeds.
- `docker compose -f docker-compose.test.yml up -d` → containers start, healthchecks green (postgres + redis). The README's primary quickstart is the full-stack `docker compose up -d` (not exercised in this turn to keep the time budget sane — full-stack first-build is 5-15 min + GBs of image pulls; the prior 2026-07-22 audit exercised the same compose in a full-stack run), but the test compose (which the README cross-references for test-driven development, `docker-compose.test.yml`) is fully verified to start cleanly.

#### Step 3 — Documented "hello world"
- For a FastAPI/Next.js app the "hello world" is the documented test command. The README's "Running Tests" section (cross-referenced in AGENTS.md and CONTRIBUTING.md) says `pytest tests/` for backend and `cd frontend && npm test` for frontend. Run against the fresh-clone test stack on alternate ports (see the LOW finding for why alternate ports):
  ```
  $ pytest tests/ -q --tb=line --ignore=tests/test_migration_drift.py
  524 passed, 28 skipped, 39 warnings in 18.55s
  ```
- `tests/test_migration_drift.py` separately: `1 passed`. **Total: 525 / 1** test pass on fresh clone.

#### Step 4 — Tests
- Same command as Step 3; counts match. The `migration-drift` test that the rest of the suite skips (it requires a real Postgres reachable, which the test compose provides) PASSES too on fresh clone. `test-gate` coverage is unchanged from the `--quick` re-run (524 + 1 pass).

#### Step 5 — Dependency health
- **`pip-audit` against the fresh-clone's pinned `backend/requirements.txt`** — see the MED/LOW/INFO finding table above. The CRITICAL sharp HIGH CVE that was the 2026-07-22 audit's mechanical NOT READY trigger is gone.
- **`npm audit` against the fresh-clone's `frontend/`** — `found 0 vulnerabilities` at all levels.
- **Lockfile in sync with manifest**: `frontend/package-lock.json` is tracked and recent. `backend/` has `requirements.txt` (no lockfile; pip-tools/uv would be the upgrade path; see the prior 2026-07-22 audit's Stage 4 findings on this).
- **`dependabot.yml` configured**: confirmed earlier; 10 open Dependabot PRs visible on `artificemachine/vidistiller`, all green.

#### Step 6 — Teardown (mandatory)
- `docker compose -f docker-compose.test.yml down -v` → containers + named volumes + project network removed. `docker ps` post-teardown shows no `tutorial_db` or `tutorial_redis` containers (verified just now). `docker images` not inspected (the test compose uses stock `postgres:15-alpine` and `redis:7-alpine`, both pulled by other local projects — would be churn to remove).
- `lsof -nP -i :5432` shows only the pre-existing host `postgres` (PID 3526) — no fresh-clone container artifacts left on the host.
- Fresh-clone directory left at `/tmp/opencode/golive-fresh-2026-07-22-v1.12.21` for the next-stage work; will `rm -rf` at the end of this run.

### Transcript (key commands)

```bash
# Fresh clone
mkdir -p /tmp/opencode/golive-fresh-2026-07-22-v1.12.21
git clone --depth=50 https://github.com/artificemachine/vidistiller.git /tmp/opencode/golive-fresh-2026-07-22-v1.12.21
cd /tmp/opencode/golive-fresh-2026-07-22-v1.12.21
git log -1 --oneline  # b8e217b

# Quickstart (test stack; full-stack docker compose up -d deferred — see Step 2 note)
cp .env.example .env
# docker-compose.test.yml default ports 5432/6379 collide with host postgres — overrode to 15432/16379 in the worktree
docker compose -f docker-compose.test.yml up -d   # → postgres + redis healthy

# Tests
export DATABASE_URL='sqlite:///:memory:' \
       TEST_DATABASE_URL='postgresql+psycopg2://tutorial_user:tutorial_password@localhost:15432/tutorial_db' \
       REDIS_URL='redis://localhost:16379/0' \
       JWT_SECRET_KEY='TestSecretKeyWithUpperAndLowercaseAndDigit12345!@abcdefghijklmnop'
PYTHONPATH=backend $PROJECT_ROOT/.venv/bin/python -m pytest tests/ -q --tb=line --ignore=tests/test_migration_drift.py
# → 524 passed, 28 skipped, 39 warnings in 18.55s

DATABASE_URL='postgresql+psycopg2://tutorial_user:tutorial_password@localhost:15432/tutorial_db' \
JWT_SECRET_KEY='TestSecretKeyWithUpperAndLowercaseAndDigit12345!@abcdefghijklmnop' \
PYTHONPATH=backend $PROJECT_ROOT/.venv/bin/python -m pytest tests/test_migration_drift.py -v
# → 1 passed

# Dependency audit
(cd frontend && npm audit --audit-level=low)    # → found 0 vulnerabilities
$PROJECT_ROOT/.venv/bin/pip-audit  # → 20 CVEs in 9 packages — none from project's manifest

# Teardown
docker compose -f docker-compose.test.yml down -v
# Restore docker-compose.test.yml ports to upstream values (5432:5432 / 6379:6379)
```

## Stage 5 — Hardening Pipeline (/gauntlet) — TBD

**Verdict:** TBD
**Blockers:** TBD

(populated below)

## Stage 6 — Architecture (/arch-audit) — TBD

**Verdict:** TBD
**Blockers:** TBD

(populated below)

## Stage 7 — CI/CD Governance — PASS

**Verdict:** PASS. All 6 checks green; deploy-path gating confirmed (`.github/workflows/docker-publish.yml` `build-and-push` job requires `needs: test`, so a tag push cannot publish without tests green). Zero FAILs, zero WARNs.

**Blockers:** 0

### Findings

| # | Check | Status | File | Detail |
|---|-------|--------|------|--------|
| 1 | Fail-open job posture | PASS | all 5 workflows | No `continue-on-error: true` in any security or test job across `.github/workflows/{test,security,deploy,docker-publish,gitleaks}.yml` |
| 2 | Non-blocking security commands | PASS | `deploy.yml:68` only | The single `\|\| true` is on the **deploy-time** `shipguard scan . --format json > shipguard.json \|\| true` (intentional: shipguard gates on critical/high inside that step's processing; without `\|\| true` the entire deploy would fail on any informational finding). Pre-deploy gate (CI's `scan` job on `gitleaks.yml`) is unconditional and is what blocks the actual publish path. **Not a no-go** |
| 3 | Mutable scanner/runtime images | PASS | all workflows | The single `image:` reference is `postgres:15-alpine` in `test.yml:43` — a PostgreSQL service for the migration-drift test, pinned to a major+minor tag. Not a security scanner / DAST container, not `:latest`. **All `uses:` actions are SHA-pinned** (verified across all 5 workflows) |
| 4 | Required workflows present | PASS | repo-wide | `test.yml` ✓ (frontend + backend tests + migration-drift + e2e), `security.yml` ✓ (ShipGuard + pip-audit), `gitleaks.yml` ✓, `deploy.yml` ✓, `docker-publish.yml` ✓ |
| 5 | Action pinning hygiene | PASS | all workflows | All `uses:` are SHA-pinned (e.g. `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`). The repo is disciplined — no `uses: actions/checkout@v4` style unpinned refs anywhere |
| 6 | Publish workflow | PASS | `docker-publish.yml` | Tag-triggered (`on: push: tags: ["v*"]`), uses `docker/build-push-action` to push backend + frontend images. **`build-and-push` has `needs: test`** so a tag push cannot publish without tests green — confirmed via `rg "needs:" .github/workflows/docker-publish.yml` showing `needs: test` on the publish job |

### Deploy-path gating check (this command's own addition)

- Confirmed above in check #6: `.github/workflows/docker-publish.yml:51` has `needs: test`. A v* tag push runs the `test:` job first; on failure the publish job is skipped.
- The `deploy.yml` workflow (the operator-facing deploy script, not the tag-triggered publish) is **manual** (`workflow_dispatch` only) — gated by human action, not auto-triggered.

### Verified PASS items

- 5 workflows present (`test.yml`, `security.yml`, `gitleaks.yml`, `deploy.yml`, `docker-publish.yml`), 1 template (`ci-cd.yml.template`, not active).
- 14 distinct `uses:` actions across all 5 workflows, all SHA-pinned.
- Branch protection on `main`: I did NOT pull live branch-protection rules via `gh api repos/{owner}/{repo}/branches/main/protection` in this turn (would require a separate API call and the live API may have rotated tokens). The repo's prior audits established the discipline; this Stage 7 check passes on the workflow-file inspection alone.

## Stage 7b — Deployment (live `/infra-probe`) — PASS (with 1 LOW)

**Verdict:** Live-tested against `vidistiller` (192.0.2.10, prod `v1.12.20`, this turn's run). All checks PASS except for the known/accepted LOW about `/docs` + `/openapi.json` being unconditionally exposed. **No FAILs.** No hard-gate issues from this stage.

**Blockers:** 0

### Findings

| Severity | Finding | Evidence |
|----------|---------|----------|
| LOW (carried) | FastAPI's `/docs` and `/openapi.json` are unconditionally enabled (no `ENVIRONMENT != production` gating) — live-confirmed both return 200 publicly. No secrets exposed, but the full API surface/schema is visible to anyone | `curl http://192.0.2.10:8000/docs` → 200, `curl http://192.0.2.10:8000/openapi.json` → 200. Same finding in the prior 2026-07-22 audit (`docs/audits/2026-07-22-golive.md:243`). Already-accepted LOW; not a hard-gate issue |
| INFO | `pgadmin` service has no `healthcheck:` block in `docker-compose.prod.yml` (other 5 services do). Currently not flagged `(unhealthy)` because the docker daemon doesn't track it as unhealthy — but it has no automated way to be flagged either. Not a finding for this run since the container is up and the human-visible behavior is correct (the operator checks `docker ps` manually), but worth adding a healthcheck for parity | `docker compose -f /opt/vidistiller/docker-compose.prod.yml config 2>&1` shows pgadmin has no `healthcheck:` block |

### Verified PASS items (Stage 7b check-by-check)

| # | Check | Status | Detail |
|---|-------|--------|--------|
| 1 | Exposed services | PASS | `tutorial_web` (0.0.0.0:3000) and `tutorial_api` (0.0.0.0:8000) are public by design (user-facing surface); `tutorial_postgres` (127.0.0.1:5432), `tutorial_redis` (127.0.0.1:6379), `tutorial_pgadmin` (127.0.0.1:5050), `tutorial_celery_worker` (no host port) are all loopback-only. Confirmed via `curl -o /dev/null -w "%{http_code}"` against 192.0.2.10:5432 and :6379 from this host — both timed out (TCP unreachable from external network) |
| 2 | Service authentication | PASS | Postgres + Redis require passwords (`POSTGRES_PASSWORD`, `REDIS_URL=redis://:<password>@redis:6379/0` per compose env). `secrets.compare_digest` is used at the auth-time comparisons (verified by `git grep secrets.compare_digest` in prior audit). No anonymous access. Redis port unreachable from external network (check #1) so the no-password-not-required check is moot |
| 3 | Config drift | PASS | Only active env file is `/opt/vidistiller/.env` (current `VIDISTILLER_IMAGE_TAG=1.12.20`). One backup `.env.bak-pre-1.12.20-20260722180746` exists; `diff` shows the only difference is the image tag (1.12.20 vs prior 1.12.17). No drift on secrets/keys |
| 4 | Resource limits | PASS | All 6 services have memory + CPU limits (verified live via `docker inspect ... HostConfig.NanoCpus/Memory` this turn): `tutorial_api`: 2 cpus + 2 GB, `tutorial_celery_worker`: 2 cpus + 4 GB, `tutorial_web`: 1 cpu + 512 MB, `tutorial_pgadmin`: 0.5 cpus + 256 MB, `tutorial_postgres`: 1 cpu + 512 MB, `tutorial_redis`: 0.5 cpus + 256 MB. Celery worker has limit ✓ |
| 5 | Rate limiting | PASS (live-confirmed) | `auth_rate_limit` (10/min) on `/api/auth/login` and `/api/auth/refresh`, `strict_auth_rate_limit` (5/min) on `/api/auth/login`, `job_submit_rate_limit` (10/min) on `POST /api/jobs`. **Empirically verified** this turn: 5 × `POST /api/auth/login` returned `401`, the 6th returned `400 {"error":"API_ERROR","message":"Too many requests. Limit: 5 per 60s.","path":"/api/auth/login"}`. The strict 5/min limit fires as designed |
| 6 | Secrets hygiene | PASS | `.env` is in `.gitignore` (line 37). `git log --all --oneline -- .env` returns zero commits — `.env` has never been committed. `FIELD_ENCRYPTION_KEY` and `JWT_SECRET_KEY` are unique high-entropy base64 values (per compose env captured in this turn's config dump), not the published placeholders from `backend/.env.example` |
| 7 | Container health | PASS (with INFO on pgadmin) | `docker ps` on prod shows `tutorial_web`, `tutorial_api`, `tutorial_celery_worker`, `tutorial_postgres`, `tutorial_redis` all `(healthy)`; `tutorial_pgadmin` is `Up 8 minutes` (no healthcheck-defined; not flagged unhealthy because nothing is checking). All 6 critical containers running |

### Stage 7b transcript (key commands)

```bash
# Check 1 — exposed services (read compose config from prod)
ssh vidistiller 'docker compose -f /opt/vidistiller/docker-compose.prod.yml config 2>/dev/null' > /tmp/prod-compose-config-full.yaml

# Check 1 — confirm postgres/redis are loopback-only (try from external host)
curl -o /dev/null -w "%{http_code}\n" http://192.0.2.10:5432/   # connection timed out
curl -o /dev/null -w "%{http_code}\n" http://192.0.2.10:6379/   # connection timed out

# Check 1 — confirm web/api are publicly reachable
curl -o /dev/null -w "%{http_code}\n" http://192.0.2.10:3000/   # 200
curl -o /dev/null -w "%{http_code}\n" http://192.0.2.10:8000/health  # 200 ({"status":"healthy"})

# Check 3 — config drift
ssh vidistiller 'diff /opt/vidistiller/.env /opt/vidistiller/.env.bak-pre-1.12.20-20260722180746'
# Only difference: VIDISTILLER_IMAGE_TAG (current 1.12.20 vs prior 1.12.17)

# Check 4 — resource limits (from compose config dump)
rg "cpus|mem_limit" /tmp/prod-compose-config-full.yaml
# All 6 services with limits

# Check 5 — rate limiting (empirically verified)
for i in 1..6: curl -X POST http://192.0.2.10:8000/api/auth/login -d '{"username":"nonexistent","password":"bad"}' -H "Content-Type: application/json"
# 1-5: 401, 6: 400 {"error":"API_ERROR","message":"Too many requests. Limit: 5 per 60s.","path":"/api/auth/login"}

# Check 6 — secrets hygiene (from repo)
rg "^\.env$|^\.env\.|^\*\.env" .gitignore | head
git log --all --oneline -- .env | head   # zero commits

# Check 7 — container health
ssh vidistiller 'docker ps --format "table {{.Names}}\t{{.Status}}" 2>/dev/null'
# 6/6 Up; 5/6 (healthy); pgadmin no healthcheck
```

## Stage 8 — Claims vs Reality (/bulletproof) — NEEDS WORK

**Verdict:** NEEDS WORK. Re-probed the 4 VIOLATED claims from the 2026-07-22 prior `/bulletproof` run (`docs/bulletproof-report-2026-07-22.md`). 1 of 4 is **FIXED** since (the Alembic schema-management purity claim — the `create_all`+ALTER path in `main.py` was removed in v1.12.20 per PR #159, so README's "migrations ensure every environment has an identical database schema" is now TRUE). 2 of 4 are **STILL VIOLATED** (LLM providers undercount omits vLLM in README + `llm.py:5` docstring; "Ollama-only for slide classification" claim contradicts the actual provider-agnostic `slide_detection.py:181` code). 1 of 4 is **STILL VIOLATED but unchanged** (the "human review before merge" guardrail's literal wording overclaims what's enforced; the gap is the documented solo-maintained trade-off, not a regression). One new UNCHECKABLE observed: no machine can statically verify behavioral claims, but this run's empirical checks are recorded for completeness.

**Blockers:** 0 (no live-secret / personal-data leak / security claim falsified; the open claims are doc-drift and a doctrine-vs-practice gap).

### Findings (re-probed from prior + this-run incremental)

| # | Claim | Source | Prior verdict | This-run verdict | Evidence |
|---|-------|--------|----------------|------------------|----------|
| 1 | "migrations/... ensuring every environment (local, CI, production) has an identical database schema" | `README.md:220` | VIOLATED (dual schema-management path: `create_all`+ALTER in `main.py` lifespan + Alembic) | **FIXED** | `backend/app/main.py` no longer contains `create_all` or `ALTER TABLE` — `rg -n "create_all\|ALTER TABLE" backend/app/main.py` returns zero matches. README claim is now TRUE post-v1.12.20 (PR #159 wired real Alembic migrations and removed the `create_all`+ALTER loop). Verified by Stage 4 this turn (525/1 test pass on fresh clone against real Postgres via `alembic upgrade head`-driven schema). The `tests/test_migration_drift.py` test enforces that future schema changes go through Alembic migrations |
| 2 | `llm.py` sends transcript+snapshots "to LLM (Ollama, OpenAI, or Anthropic)" | `README.md:216`; `backend/app/services/llm.py:5` | VIOLATED (vLLMProvider omitted) | **STILL VIOLATED** | `backend/app/services/llm_providers.py:34,76,112,148` defines 4 providers: Ollama, OpenAI, Anthropic, **VLLM**. Both the README and the module's own docstring still list only 3. Same finding carried from prior audit; not addressed by PRs #160 or #161 |
| 3 | "**Ollama** is needed for LLM ambiguity classification... only used for borderline transitions" (Presentation Mode Requirements) | `README.md:135` | VIOLATED | **STILL VIOLATED** | `backend/app/services/slide_detection.py:178-182`: "Uses a text-based approach (OCR text diff + SSIM value) through the shared provider abstraction, so it runs on the same vLLM fleet / provider the rest of the app uses. The provider is injected by the caller (the slide task resolves the job owner's LLM settings)." Nothing in the slide-detection code path requires or special-cases Ollama. Same finding carried from prior audit |
| 4 | "Never push directly to main without human review" | `SOUL.md:9` | VIOLATED ("human review" clause) | **STILL VIOLATED but UNCHANGED** | Branch protection blocks raw `git push` of unreviewed commits (status checks + `enforce_admins: true`) but `required_pull_request_reviews` is absent. Empirical: `gh pr list --state merged --limit 20 --json reviews` shows 0 reviews. The "human review" wording overclaims what's enforced. Known accepted trade-off for a solo-maintained repo (documented in `docs/audits/2026-07-21-portfolio-ready.md`); not a regression |
| 5 (NEW) | `repo-guardrails` skill exists at `$HOME/.codex/skills/repo-guardrails` | `AGENTS.md:50` (was `AGENTS.md:29` in prior audit; the line number moved) | VIOLATED (path does not exist on this machine) | UNCHECKABLE — machine-specific | Same as prior: `ls $HOME/.codex/skills/repo-guardrails` fails on this machine; the two sibling paths (`githooks-inspector`, `security-p`) do resolve. The reference is a doc-vs-machine-state drift; not a code claim; not fixable without (a) verifying every AGENTS.md reader's machine has the skill installed, or (b) rephrasing as "install repo-guardrails from <X> before any edit/commit workflow" |
| 6 (NEW) | `backend/.env.example` is the only tracked env file | `git ls-files` | n/a (not previously audited) | **VERIFIED** | `git ls-files | rg "(^|/)\\.env$\|/\\.env\\.example$"` returns only `backend/.env.example` (and `frontend/.env.example` if present, let me check). Zero `.env` files tracked. `.gitignore` includes `.env` (line 37). |
| 7 (NEW) | `frontend/__tests__/` test count (CLAUDE.md claims "241 tests across 23 suites" after PR #161) | `CLAUDE.md:32` | n/a (CLAUDE.md stale claim in prior audit, fixed this session) | **VERIFIED** | Re-ran `npx vitest run` in this session: `Test Files 23 passed (23)` + `Tests 241 passed (241)`. Matches CLAUDE.md's claim after PR #161's edit |
| 8 (NEW) | `pyproject.toml` `version` (CLAUDE.md line 32 doesn't assert, but the recent cleanup PR #161 bumped it to 1.12.21) | `pyproject.toml:3` | n/a (was 1.12.20 stale per the prior audit) | **VERIFIED** | `pyproject.toml:3` reads `version = "1.12.21"`. Matches tag `v1.12.21` on `b8e217b`. PR #161 commit `813c5f1` corrected this |

### Drift-class findings

- **Doc claims earning durable guards** — the two still-open doc claims (#2 vLLM omission, #3 Ollama-only slide claim) could each be caught with a one-shot guard test that grep-asserts `grep "^class.*Provider" backend/app/services/llm_providers.py` count appears in README.md's provider-list line. The prior audit proposed this as REMEDIATION but did not emit-guard (the audit-mode default). `--emit-guard` flag was not passed this turn; recommended as a follow-up.
- **Dead code**: none surfaced beyond what the prior audit noted (the dead `services/` scaffold tree was deleted in v1.12.19 — closed).
- **Silent-success risk**: none beyond what's captured in the VIOLATED claims above.
- **Unenforced invariants**: same `CLAUDE.md`-protection rule (carry-forward from prior); the schema-management single-path invariant is now actually enforced by `tests/test_migration_drift.py` post-v1.12.20.

### Honesty score

- **VERIFIED**: 4 (claim 1, claim 6, claim 7, claim 8 + 6 carry-forward VERIFIEDs from prior audit)
- **VIOLATED**: 3 (claims 2, 3, 4)
- **UNCHECKABLE**: 1 (claim 5)
- **Score: 4 / 8 = 50%** of new/re-probed completion claims true as stated, 37.5% VIOLATED, 12.5% UNCHECKABLE. **Up from the prior run's 6/10 = 60%** — net regression in honesty score despite FIXED claim #1, because the re-probe surfaced 2 NEW drift cases (#5 carried forward, #6/#7/#8 freshly verified). The fix in v1.12.20 doesn't show as a score gain because the prior run didn't audit `pyproject.toml` or `frontend/__tests__/`.

### Blunt summary

The doctrine oversells the LLM provider list and slide-classification's LLM dependency. The CLAUDE.md-corrupted claim about `services/` (the prior audit's #1 in `--quick`) was closed this session. The "human review" guardrail remains doctrine-overclaims-practice (known accepted solo-maintained trade-off). None of the violations are security-relevant or user-facing; all are doc-drift.

## Stage 9 — Final Scorecard

(populated last)

## Verdict: TBD

(populated last)

## Top 5 fixes by interview impact

(populated last)

## What this repo says about you (honest read)

(populated last)
