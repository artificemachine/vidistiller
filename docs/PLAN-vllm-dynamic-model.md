# PLAN — Self-healing vLLM model resolution + deploy (fixes prod summarize)

Branch context: all work lands on the existing `feat/llm-health-status` branch (PR #167),
which introduced `backend/app/services/llm_resolution.py` and `llm_health.py`. Verify both
files exist before starting; if the branch was merged/rebased, re-anchor to the current
`backend/app/services/llm_resolution.py` content before editing.

## 1. Scope summary

Build: make vLLM model resolution self-healing — when a user has no model configured,
adopt the model actually loaded on the first reachable fleet VM instead of requesting a
hardcoded name that no longer exists; align the backend/frontend last-resort default
tables; bump `cryptography` to unblock the CI pip-audit gate; deploy v1.13.0 to the prod
VM and verify summarize works end-to-end. NOT building: per-job model picker UI,
auto-loading models via vllm-manager, changing the "summarize task reports success even
when every section fails" behavior (separate bug, out of scope).

Smallest v1: dynamic adoption in `resolve_user_llm` + cryptography floor bump + deploy.

Source: PR #167; prod celery logs 2026-08-07 (`The model 'qwen3-32b-awq' does not exist`,
HTTP 404 on every section); live fleet probe (PRIMARY 192.0.2.10:8000 down; SECONDARY
192.0.2.10:8000 serves `qwen3.6-27b-awq`).

## 2. Prerequisites

- Branch `feat/llm-health-status` checked out; PR #167 open. Files
  `backend/app/services/llm_resolution.py` and `backend/app/services/llm_health.py` exist there.
- Existing code touched:
  - `backend/requirements.txt` (line 48: `cryptography>=41.0.0`)
  - `backend/app/services/llm_resolution.py` (`FLEET_VMS`, `resolve_fleet_url`, `resolve_user_llm`)
  - `backend/app/services/llm_providers.py` (`DEFAULT_MODELS`, ~line 193)
  - `pyproject.toml` (line 3: `version = "1.12.21"`)
  - `tests/test_llm_resolution.py`, `tests/test_diagnostics.py`
- Risks:
  - cryptography 50 API drift — low; Fernet API stable, existing `tests/test_crypto.py` guards.
  - Fleet state can change between plan and deploy — adoption logic is fleet-driven, so this is tolerable; DoD re-probes live before declaring done.
  - Prod `.env` pins `VIDISTILLER_IMAGE_TAG=1.12.20`; deploy workflow pulls the pinned tag, so the tag must be bumped on the VM or nothing deploys.
  - Prod `VLLM_SECONDARY_URL` points at port 8100 (vllm-manager, discovery only — blocks `/v1/chat/completions` with 409 per `backend/app/core/config.py` VLLMFleetSettings docstring). Must be corrected to `:8000` during deploy.

## 3. Iterations

#### Iteration 1 — Unblock CI gate: cryptography >= 50.0.0

**Goal:** Make the `pip-audit` security gate deterministically green (PYSEC-2026-3552 fixed in cryptography 50.0.0).

**Shippable on its own?** Yes — dependency-only change.

**Source references:**
- `backend/requirements.txt` — line 48 currently `cryptography>=41.0.0`; CI resolved 49.0.0 which has PYSEC-2026-3552.
- `backend/app/core/crypto.py` — the only consumer (Fernet); verify no deprecated API use before bumping.

**Files touched:**
- `backend/requirements.txt` (modified)
- `tests/test_dependencies.py` (new)

**Commit message:**
`fix(deps): require cryptography>=50.0.0 to clear pip-audit PYSEC-2026-3552`

**TDD cycle:**
- RED:
  - `tests/test_dependencies.py::test_cryptography_at_least_50` — asserts `importlib.metadata.version("cryptography")` parses to >= (50, 0, 0). Fails now (venv has 47.0.0).
- GREEN:
  - Change line 48 of `backend/requirements.txt` to `cryptography>=50.0.0`.
  - `.venv/bin/pip install -U cryptography` (expect 50.0.0).
- REFACTOR: None.

**Test pyramid for this iteration:**
- Smoke: `tests/test_crypto.py` still imports and round-trips after the bump.
- Unit: `test_cryptography_at_least_50` (1 test, `tests/test_dependencies.py`).
- Integration: full backend suite runs green against cryptography 50 (`PYTHONPATH=backend .venv/bin/python -m pytest tests/ -q`).
- State machine: N/A — no FSM.
- Contract: the same unit test is the floor contract (keeps future resolves >= 50).
- Regression: N/A — no bug fixed in app code; the CVE clearance is verified by pip-audit itself in CI.
- Chaos: N/A — pure dependency bump.
- E2E: N/A — no user-facing path changes.
- Performance: N/A.
- TDD Parity: 100% (1 new assertion, 1 test).
- Coverage: ~0 delta; no `fail_under` configured in `pyproject.toml`.

**Acceptance criteria (binary):**
- [ ] `tests/test_dependencies.py::test_cryptography_at_least_50` passes.
- [ ] `.venv/bin/pip-audit -r backend/requirements.txt` reports 0 known vulnerabilities (install pip-audit in venv if absent).
- [ ] Full backend suite green with cryptography 50 installed.

**Estimated effort:** S

**Blocked by:** None

**Side-effect fence:** repo tree + local venv only. No live systems.

#### Iteration 2 — Dynamic fleet model adoption

**Goal:** When provider is `vllm` and the user has not configured a model, `resolve_user_llm` adopts the first model actually loaded on the first reachable fleet VM; hardcoded defaults become last resort only.

**Shippable on its own?** Yes — behavior change is confined to the unresolved-model path; pinned-model users are unaffected.

**Source references:**
- `backend/app/services/llm_resolution.py` — verify current `FLEET_VMS`, `resolve_fleet_url`, `resolve_user_llm` shapes before editing (branch may have moved since planning).
- `backend/app/core/config.py` `VLLMFleetSettings` docstring — port 8000 = inference, 8100 = discovery-only; adoption MUST use the env-var URLs (inference ports), never hardcode 8100.
- `tests/test_llm_resolution.py` — existing `_fleet_resp` helper and autouse `_clean_fleet_env` fixture; reuse both.

**Files touched:**
- `backend/app/services/llm_resolution.py` (modified)
- `tests/test_llm_resolution.py` (modified)
- `tests/test_diagnostics.py` (modified)

**Commit message:**
`fix(llm): adopt the loaded fleet model when the user configured none`

**TDD cycle:**
- RED (all in `tests/test_llm_resolution.py` unless noted):
  - `test_vllm_no_user_model_adopts_first_loaded_model` — env PRIMARY set; mocked GET returns `data=[{"id":"gemma4-31b-awq"}]`; assert `resolve_user_llm(_owner(provider="vllm"))` yields model `gemma4-31b-awq`, base_url = PRIMARY URL, fleet_node `primary`.
  - `test_vllm_no_user_model_skips_dead_vm_adopts_from_next` — PRIMARY raises `requests.exceptions.ConnectionError`, SECONDARY returns `qwen3.6-27b-awq`; assert adoption from secondary.
  - `test_vllm_no_user_model_fleet_empty_falls_back_to_default` — all fleet GETs raise ConnectionError; assert model == `DEFAULT_MODELS["vllm"]`, base_url falls back to `VLLM_PRIMARY_URL` env, fleet_node None.
  - `test_vllm_no_user_model_skips_malformed_json` — PRIMARY returns 200 with `json()` raising ValueError, SECONDARY returns a valid model; assert adoption from secondary (no exception).
  - `test_vllm_user_pinned_model_behavior_unchanged` — owner.llm_model set; assert adoption is NOT called (patch `discover_fleet_model` and assert zero calls) and existing fleet-match path still used.
  - `test_non_vllm_provider_never_runs_adoption` — provider ollama; patched `discover_fleet_model` must not be called.
  - `tests/test_diagnostics.py::test_diagnostics_reports_adopted_model` — patch `app.services.llm_resolution.resolve_fleet_url`-level internals is NOT enough; patch `app.services.llm_health.probe_llm` and fleet GETs so the endpoint returns adopted model `qwen3.6-27b-awq` + fleet_node `secondary` for a user with provider vllm and no model.
- GREEN:
  - Add module function `discover_fleet_model() -> tuple[str, str, str] | None` in `llm_resolution.py`: iterate `FLEET_VMS`; for each env-configured URL, `requests.get(url.rstrip("/") + "/v1/models", timeout=3)`; on 200 parse `data[*]["id"]`; return `(first_model_id, url, label)` for the first VM with a non-empty list; transport errors, non-200, bad JSON, empty lists all skip the VM; return None if none qualify. Log adoption at INFO.
  - In `resolve_user_llm`, vllm branch only: if `model_name is None` call `discover_fleet_model()`; on hit set resolved_model/base_url/fleet_node from it and SKIP `resolve_fleet_url`; on miss keep current behavior (`DEFAULT_MODELS.get("vllm")` then `resolve_fleet_url`).
- REFACTOR:
  - Extract `_get_vm_model_ids(url) -> list[str]` helper shared by `resolve_fleet_url` and `discover_fleet_model` (both currently parse the same payload shape).

**Test pyramid for this iteration:**
- Smoke: `resolve_user_llm(None)` returns a `ResolvedLLM` with no fleet env set.
- Unit: 6 new tests listed in RED (all mock `app.services.llm_resolution.requests.get`).
- Integration: `test_diagnostics_reports_adopted_model` exercises route -> resolution -> probe wiring.
- State machine: N/A — no FSM.
- Contract: `ResolvedLLM` field set unchanged (existing endpoint tests assert the shape).
- Regression: `test_vllm_user_pinned_model_behavior_unchanged` + all pre-existing `tests/test_llm_resolution.py` tests stay green.
- Chaos: dead VM (ConnectionError), malformed JSON, empty model list — covered by RED tests above.
- E2E: N/A here — live verification is in the DoD demo (prod deploy).
- Performance: N/A — adoption adds at most the same 3s-timeout GETs the existing fleet lookup already performs.
- TDD Parity: 100% (`discover_fleet_model`, `_get_vm_model_ids` each directly tested).
- Coverage: +1-2% on `backend/app/services/llm_resolution.py` (new branches).

**Acceptance criteria (binary):**
- [ ] All 6 new unit tests + 1 integration test pass.
- [ ] With only `VLLM_SECONDARY_URL=http://192.0.2.10:8000` set, `resolve_user_llm` for an owner with provider=vllm and no model returns model `qwen3.6-27b-awq` (verified by test with mocked GET, re-verified live in DoD).
- [ ] Pre-existing pinned-model tests pass unchanged.

**Estimated effort:** M

**Blocked by:** Iteration 1 (merge ordering only — code is independent)

**Side-effect fence:** repo tree only; tests mock `requests.get`; no live fleet calls.

#### Iteration 3 — Align last-resort defaults + version 1.13.0

**Goal:** One consistent last-resort vllm default (`gemma4-31b`, matching the fleet table in `backend/app/routes/settings.py` and the frontend map) and bump version to 1.13.0.

**Shippable on its own?** Yes.

**Source references:**
- `backend/app/services/llm_providers.py` — `DEFAULT_MODELS["vllm"]` is `"qwen3-32b-awq"` (~line 197); verify before editing.
- `frontend/app/settings/page.tsx` — `DEFAULT_MODELS.vllm` is already `"gemma4-31b"` (~line 38); verify, no change expected.
- `pyproject.toml` — line 3 `version = "1.12.21"`.

**Files touched:**
- `backend/app/services/llm_providers.py` (modified)
- `tests/test_llm_defaults_contract.py` (new)
- `pyproject.toml` (modified)

**Commit message:**
`fix(llm): align vllm last-resort default to gemma4-31b, bump version to 1.13.0`

**TDD cycle:**
- RED:
  - `tests/test_llm_defaults_contract.py::test_vllm_default_matches_fallback` — asserts `DEFAULT_MODELS["vllm"] == FALLBACK_MODEL == "gemma4-31b"`. Fails now (`qwen3-32b-awq`).
- GREEN:
  - Set `DEFAULT_MODELS["vllm"] = "gemma4-31b"` in `llm_providers.py`.
  - Bump `pyproject.toml` version to `1.13.0`.
- REFACTOR: None.

**Test pyramid for this iteration:**
- Smoke: backend suite imports clean.
- Unit: 1 contract test (`tests/test_llm_defaults_contract.py`).
- Integration: N/A — value change only; iteration-2 fallback test now exercises the new value and must stay green.
- State machine: N/A.
- Contract: the test itself (backend parity). Frontend value verified by reading `frontend/app/settings/page.tsx` (already `gemma4-31b`); no frontend test added since nothing changes there.
- Regression: iteration-2 `test_vllm_no_user_model_fleet_empty_falls_back_to_default` (its expected default value updates to `gemma4-31b` in this iteration).
- Chaos: N/A.
- E2E: N/A.
- Performance: N/A.
- TDD Parity: 100%.
- Coverage: ~0 delta.

**Acceptance criteria (binary):**
- [ ] `test_vllm_default_matches_fallback` passes.
- [ ] `pyproject.toml` reads `version = "1.13.0"`.
- [ ] `grep gemma4-31b frontend/app/settings/page.tsx` matches the vllm default line.
- [ ] Full backend suite green.

**Estimated effort:** S

**Blocked by:** Iteration 2

**Side-effect fence:** repo tree only.

## 4. Test inventory summary

| Iter | Smoke | Unit | Integration | State machine | Contract | Regression | Chaos | E2E | Performance | TDD Parity | Coverage Δ |
|------|-------|------|-------------|---------------|----------|------------|-------|-----|-------------|------------|------------|
| 1    | 1     | 1    | 1           | 0             | 1        | 0          | 0     | 0   | 0           | 100%       | ~0         |
| 2    | 1     | 6    | 1           | 0             | 0        | 1          | 3     | 0   | 0           | 100%       | +1-2%      |
| 3    | 1     | 1    | 0           | 0             | 1        | 1          | 0     | 0   | 0           | 100%       | ~0         |

## 5. End-to-end definition of done

Deduplicated acceptance criteria: all iteration checkboxes above, plus the live deploy block
below. Live systems are touched ONLY in this DoD demo — iterations 1-3 stay inside the repo
tree (fence). Rollback named: restore `.env.bak-<date>` on the VM and `docker compose up -d`
(image 1.12.20 stays on disk).

Manual demo script (the single E2E proof):
1. Push the three iteration commits to `feat/llm-health-status`; wait for PR #167 CI green
   (security gate included). `gh pr checks 167`.
2. Merge PR #167 (`gh pr merge 167 --squash`) — operator confirmation required.
3. Tag and push `v1.13.0` — `docker-publish.yml` builds `example-org/vidistiller-backend:1.13.0`
   and `example-org/vidistiller-frontend:1.13.0`. Watch: `gh run list --workflow docker-publish.yml`.
4. On the prod VM (`ssh vidistiller`, dir `/opt/vidistiller`):
   - `cp .env .env.bak-$(date +%F)`
   - Set `VLLM_SECONDARY_URL=http://192.0.2.10:8000` (inference port; was 8100/discovery)
   - Set `VIDISTILLER_IMAGE_TAG=1.13.0`
   - `docker compose -f docker-compose.prod.yml --env-file .env pull`
   - `docker compose -f docker-compose.prod.yml --env-file .env up -d`
   - Wait healthy; `docker compose -f docker-compose.prod.yml exec -T api sh -c 'cd /app && python -m alembic upgrade head'` (no new migrations expected — verify output says nothing to do)
   - `curl -sf http://localhost:8000/health`
5. Verify the feature: login (`~/.vidistiller` creds) -> `GET /api/diagnostics/llm` ->
   expect `provider=vllm`, `model=qwen3.6-27b-awq`, `reachable=true`, `model_found=true`,
   `fleet_node=secondary` for the service user (no LLM settings configured).
6. Verify summarize: `POST /api/jobs/{id}/summarize` on an existing completed job ->
   celery logs (`docker logs tutorial_celery_worker --since 5m`) show NO
   `model ... does not exist` and the created document contains a real summary.

Exact test commands that must return green at the end:
- `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_dependencies.py tests/test_llm_resolution.py tests/test_llm_health.py tests/test_llm_defaults_contract.py tests/test_diagnostics.py -v`
- `PYTHONPATH=backend .venv/bin/python -m pytest tests/ -q` (full suite)
- `cd frontend && npm test -- --run` (unchanged suite, still green)

## 6. Out of scope

- Summarize task reports `completed` even when every section fails (degraded/empty document shipped as success) — separate bug; file an issue after this deploy.
- Auto-loading a model via vllm-manager when no fleet VM has one loaded — needs vllm-manager API design; uncertain demand.
- Per-job model picker in the UI — niche; settings-level config covers current use.
- Fixing PRIMARY (192.0.2.10:8000 is down, `/v1/models` empty) — infra issue; report to operator, do not touch in this plan.
- Making the frontend defaults table API-driven (single source of truth) — later refactor; low blast radius today since dynamic adoption bypasses defaults in the common path.

## 7. Open questions

None.

## Build outcome — 2026-08-07

- Shipped: 3 iterations, 3 commits on `feat/llm-health-status` (on top of PR #167):
  - `42db302` — `fix(deps): require cryptography>=50.0.0 to clear pip-audit PYSEC-2026-3552`
  - `cc8e2b9` — `fix(llm): adopt the loaded fleet model when the user configured none`
  - `cfd180a` — `fix(llm): align vllm last-resort default to gemma4-31b, bump version to 1.13.0`
- Deviations from plan:
  - **fastapi-mail metadata caps cryptography <50** in 1.6.5 (latest). `pip install -r backend/requirements.txt` emits a warning but installs fine; `tests/test_password_reset.py` (9 passed) + module import both work. Floor kept at `cryptography>=50.0.0`; the ecosystem gap is non-blocking but a future fastapi-mail release that lifts the ceiling would be the cleanest fix.
  - **`pyproject.toml` has no `fail_under` configured** — coverage delta is approximate (new branches in `llm_resolution.py` add ~1-2%, no enforcement to update).
- Verified locally: `pip-audit` → 0 critical/high findings; backend suite **569 passed, 29 skipped** (was 559 baseline; +10 new tests across `test_dependencies.py`, `test_llm_resolution.py::TestDynamicFleetAdoption`, `test_diagnostics.py::TestLLMDiagnosticsEndpoint::test_diagnostics_reports_adopted_model`,`, `test_llm_defaults_contract.py`; two pre-existing assertions updated to the new default value). Frontend: **249 passed**, `tsc --noEmit` clean.
- Live verification (DoD demo) and tag/push remain for the operator: merge PR #167 once CI is green, tag `v1.13.0`, on the VM set `VLLM_SECONDARY_URL=http://192.0.2.10:8000` (was 8100/manager) and bump `VIDISTILLER_IMAGE_TAG=1.13.0`, then `compose pull && up -d`, then exercise `/api/diagnostics/llm` + a summarize to confirm `qwen3.6-27b-awq` flows through.
- Learned: the producer-side enumeration (port 8100 lists 3 managed models) and the inference endpoint (port 8000 reports one actually-loaded model) are different sets — fleet resolution must point at the inference port, never at the manager.
