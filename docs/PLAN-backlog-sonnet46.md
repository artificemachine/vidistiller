# Implementation Plan — Vidistiller Backlog (Sonnet 4.6 work items)

Scope note: "items for sonnet 4.6" = the implementable, code-level backlog from HANDOFF.md. Excludes fuzzy infra/ops items (hablatone MCP = global tooling, not this repo; `.superharness/` paths = export-only artifact; staging-LXC reduced to one stale config line). 5 iterations; vision pre-pass and Next.js CVE bump deferred (see §6).

---

## 1. Scope summary

Five independently shippable iterations clearing the engineering backlog after v1.8.3: (1) the Node 20→24 CI deadline, (2) deploy automation, (3) slide-run failure visibility, (4) presentation-mode hardening (wire the dead `incremental_ssim_threshold` + populate parent-slide linking), (5) the first real e2e green run. **NOT building:** vision pre-pass, Next.js major bump, staging migration, MCP debugging.

**Smallest possible v1:** Iteration 1 alone (Node 20→24) — the only deadline-driven item (2026-06-16).

**Source design docs:** `docs/AUDIT-presentation-mode.md` (iter 3–4), `docs/ops-runbook.md` (iter 2), `HANDOFF.md` open follow-ups.

---

## 2. Prerequisites

- **Tools:** `actionlint` (iter 1), `shellcheck` + `bats` (iter 2), running `docker-compose.e2e.yml` stack (iter 5). Backend tests via `PYTHONPATH=backend python3.12 -m pytest`.
- **Code areas touched:**
  - `.github/workflows/*.yml` (iter 1)
  - `scripts/deploy.sh` (new), `docs/ops-runbook.md` (iter 2)
  - `backend/app/db/models.py`, `backend/app/tasks.py`, `backend/app/schemas.py` (iter 3)
  - `backend/app/services/slide_detection.py`, `backend/app/core/config.py`, `tests/test_slide_detection.py` (iter 4)
  - `e2e/*`, `docker-compose.e2e.yml`, `.github/workflows/test.yml` (iter 5)
- **Risks:**
  - **`slide_status` column add (iter 3):** alembic is NOT wired (no `alembic.ini`; schema via `Base.metadata.create_all()` at `backend/app/main.py:106`). `create_all` does not ALTER existing tables, so the column won't appear on the live prod DB automatically. Needs a manual `ALTER TABLE` or a startup ensure-column shim — decide before iter 3 deploy.
  - **Iter 1:** bumping pinned action SHAs could change behavior; CI is the test.
  - **Iter 5:** the 6 e2e specs have never run green — unknown how many pass; may surface real selector/app drift.

---

## 3. Iterations

### Iteration 1 — GitHub Actions Node 20 → 24

**Goal:** All workflows run on Node 24-capable action versions before the 2026-06-16 forced cutover, with no deprecation warnings.

**Shippable on its own?** Yes — CI-only.

**Source references:**
- `.github/workflows/docker-publish.yml` — pinned SHAs for checkout/login/setup-buildx/build-push/metadata (all Node 20)
- `.github/workflows/{deploy,test,security}.yml` — same action families
- github.blog deprecation changelog (2025-09-19) — target versions

**Files touched:** `.github/workflows/docker-publish.yml`, `deploy.yml`, `test.yml`, `security.yml` (all modified)

**Commit message:** `ci: bump actions to Node 24-compatible versions ahead of 2026-06-16 cutover`

**TDD cycle:**
- RED: `actionlint` over workflows (0 errors); `tests/ci/test_no_node20_actions.sh` asserts no Node-20-only SHAs remain
- GREEN: bump each action to current major (checkout v5, setup-* current, docker/* current), repin SHAs
- REFACTOR: none (config-only)

**Test pyramid:**
- Smoke: `actionlint .github/workflows/*.yml` exits 0
- Unit: `test_no_node20_actions.sh` SHA allowlist (1)
- Integration: N/A
- State machine: N/A
- Contract: workflows parse; required jobs (backend-tests, frontend-tests, security) present (1)
- Regression: re-run a PR's CI green, warning gone (1)
- Chaos: N/A
- E2E: the next PR's CI run is the proof (1)
- Performance: N/A
- TDD Parity: N/A — no new public symbols (waived)
- Coverage: +0% (no app code; baseline TBD)

**Acceptance criteria:**
- [ ] `actionlint` 0 errors
- [ ] No Node-20-only action SHA remains
- [ ] PR after change shows no Node 20 deprecation annotation
- [ ] backend-tests, frontend-tests, security all pass

**Estimated effort:** S
**Blocked by:** None

---

### Iteration 2 — Orphan-safe deploy script

**Goal:** `scripts/deploy.sh` codifies the verified deploy sequence (force-remove `tutorial_*` by name → pull → up).

**Shippable on its own?** Yes — additive script.

**Source references:**
- `docs/ops-runbook.md` — verified orphan-safe sequence (force-remove by name, NOT a status=created pre-sweep)
- `docker-compose.prod.yml` — service/image names, compose path

**Files touched:** `scripts/deploy.sh` (new), `docs/ops-runbook.md` (modified), `CHANGELOG.md` (modified)

**Commit message:** `chore(deploy): add orphan-safe deploy script (rm -f tutorial_* → pull → up)`

**TDD cycle:**
- RED: `tests/deploy/deploy_dryrun.bats::test_dry_run_prints_force_remove_then_pull_then_up`; `::test_dry_run_makes_no_docker_mutations`
- GREEN: `scripts/deploy.sh [--dry-run]` — resolve `tutorial_*` via `docker container ls -a --no-trunc`, `rm -f`, `compose pull`, `up -d`; dry-run echoes
- REFACTOR: extract `force_remove_project_containers()`; `set -euo pipefail`

**Test pyramid:**
- Smoke: `shellcheck` clean; `--dry-run` exits 0
- Unit: bats dry-run ordering + no-mutation (2)
- Integration: N/A (no VM in CI)
- State machine: N/A
- Contract: accepts `--dry-run`, defaults to prod compose, rejects unknown flags (1)
- Regression: N/A — new file
- Chaos: bats stub with leftover `Created` container → removed (1)
- E2E: N/A (live VM deploy is manual)
- Performance: N/A
- TDD Parity: 100%
- Coverage: N/A (bash)

**Acceptance criteria:**
- [ ] `shellcheck scripts/deploy.sh` clean
- [ ] `--dry-run` prints force-remove → pull → up, mutates nothing
- [ ] Stubbed leftover `Created` container is targeted by remove step
- [ ] One real manual VM deploy via the script succeeds (post-merge)

**Estimated effort:** S
**Blocked by:** None

---

### Iteration 3 — Slide-run failure visibility (slide_status)

**Goal:** A failed/skipped slide run is distinguishable from a clean one via `slide_status`, instead of every outcome reporting COMPLETED.

**Shippable on its own?** Yes — additive field + setters.

**Source references:**
- `backend/app/tasks.py::process_slides` (~line 594) — marks COMPLETED on success, skip, AND failure
- `backend/app/db/models.py` — ProcessingJob (mirror summarize_status, ~line 77), ProcessingStatus
- `backend/app/schemas.py` — JobResponse/JobStatusResponse (~line 408)

**Files touched:** `backend/app/db/models.py`, `backend/app/tasks.py`, `backend/app/schemas.py`, `tests/test_slide_routes.py` (modified); migration/ensure-column shim (see Risks); `CHANGELOG.md`

**Commit message:** `feat(slides): add slide_status to distinguish failed/skipped slide runs`

**TDD cycle:**
- RED: `test_slide_status_completed_on_success`, `test_slide_status_skipped_when_no_video`, `test_slide_status_failed_on_pipeline_exception`, `test_job_response_exposes_slide_status`
- GREEN: nullable `slide_status` column (processing|completed|skipped|failed); set at each process_slides exit; expose in schema
- REFACTOR: collapse the 3 COMPLETED exits into one helper that also sets slide_status

**Test pyramid:**
- Smoke: backend imports; `GET /jobs/{id}` 200 with new field
- Unit: status at 4 exit paths (4)
- Integration: exception path → job COMPLETED but slide_status=failed (1)
- State machine: processing→{completed|skipped|failed} (1)
- Contract: JobResponse includes slide_status; nullable, clients unaffected (1)
- Regression: existing slide-route tests pass; standard jobs leave slide_status null (1)
- Chaos: mid-pipeline raise → slide_status=failed, not stuck in processing (1)
- E2E: N/A
- Performance: N/A
- TDD Parity: 100%
- Coverage: +~2% backend (baseline TBD)

**Acceptance criteria:**
- [ ] `slide_status` on JobResponse, null for non-slide jobs
- [ ] success→completed, no-video→skipped, exception→failed (job still COMPLETED)
- [ ] prod column-add path decided (manual ALTER vs startup shim)
- [ ] existing slide tests green

**Estimated effort:** M
**Blocked by:** None (prod-migration decision in §2 before deploy)

---

### Iteration 4 — Wire incremental_ssim_threshold + parent-slide linking

**Goal:** The dead `incremental_ssim_threshold` config becomes a non-LLM fast-path, and incremental builds are recorded as child slides instead of dropped.

**Shippable on its own?** Yes — internal quality improvement.

**Source references:**
- `backend/app/services/slide_detection.py::slide_grouping` (~line 238) — `continue`s on incremental (drops it); parent_slide_number always None
- `backend/app/services/slide_detection.py` (lines ~515-519) — dead parent-linking block
- `backend/app/core/config.py` — `SlideDetectionSettings.incremental_ssim_threshold = 0.95` (~line 327), never read
- `docs/AUDIT-presentation-mode.md` — the two findings
- `tests/test_slide_detection.py` — TestSlideGrouping to extend

**Files touched:** `backend/app/services/slide_detection.py`, `tests/test_slide_detection.py`, `CHANGELOG.md` (modified)

**Commit message:** `fix(slides): use incremental_ssim_threshold as non-LLM fast-path; record parent links`

**TDD cycle:**
- RED: `test_high_ssim_classified_incremental_without_llm`, `test_incremental_build_records_parent_slide_number`, `test_parent_slide_id_populated_in_pipeline`, `test_below_threshold_still_uses_llm`
- GREEN: if `ssim >= incremental_ssim_threshold` → incremental before LLM; in slide_grouping attach incremental transitions as parent_slide_number instead of dropping
- REFACTOR: extract `_classify_transition(ssim, llm_result)`; name the threshold bands

**Test pyramid:**
- Smoke: service imports; slide_grouping on empty input
- Unit: fast-path + grouping parent-linking + bands (5)
- Integration: run_full_pipeline populates parent_slide_id for synthetic incremental sequence (1)
- State machine: transition|ambiguous|incremental paths (1)
- Contract: Slide rows valid; parent_slide_id FK valid (1)
- Regression: existing TestSlideGrouping unchanged (incremental excluded from top-level count) (1)
- Chaos: provider raises on below-threshold → fallback transition, fast-path still works (1)
- E2E: N/A (live slide job already verified)
- Performance: provider.generate call count drops for high-SSIM set (1)
- TDD Parity: ≥80% (private band constants untested, acceptable)
- Coverage: +~3% backend (baseline TBD)

**Acceptance criteria:**
- [ ] SSIM ≥ threshold → incremental with zero LLM calls
- [ ] Incremental builds appear as children (parent_slide_id set), not dropped
- [ ] Below-threshold ambiguous still hits the fleet LLM
- [ ] all prior slide_detection tests green

**Estimated effort:** M
**Blocked by:** None

---

### Iteration 5 — First e2e green run + CI wiring

**Goal:** The 6 real e2e specs pass against docker-compose.e2e.yml, and an e2e job runs them in CI.

**Shippable on its own?** Yes — test/CI only.

**Source references:**
- `e2e/playwright.config.ts` + `e2e/global-setup.ts` — harness from #63 (discovers 35 tests/6 files)
- `docker-compose.e2e.yml` — stack (web :3000, api :8000)
- `e2e/tests/*.spec.ts` — 6 non-empty specs (auth-flow, auth-protection, password-reset-flow, settings-buttons, settings-vllm, theme-toggle)
- `.github/workflows/test.yml` — where to add the e2e job

**Files touched:** `e2e/*` (modified — fix drift), `.github/workflows/test.yml` (modified), `CHANGELOG.md`

**Commit message:** `test(e2e): first green run of playwright specs + CI e2e job`

**TDD cycle:**
- RED: the 6 existing specs (currently not green) + `tests/ci/test_e2e_job_present.sh`
- GREEN: fix selector/timing/global-setup drift until all pass; add CI job booting the e2e stack
- REFACTOR: shared login/setup fixture if drift reveals repetition

**Test pyramid:**
- Smoke: e2e stack healthy; `--list` = 35/6
- Unit: N/A (e2e layer)
- Integration: global-setup authenticates against live api (1)
- State machine: N/A
- Contract: CI e2e job present, wired to e2e compose (1)
- Regression: backend/frontend unit suites still green (existing)
- Chaos: settings-vllm error-path spec (1)
- E2E: all 6 specs pass (35 tests)
- Performance: e2e job < 8 min (1)
- TDD Parity: N/A (existing specs)
- Coverage: +0% python (e2e black-box)

**Acceptance criteria:**
- [ ] all discovered e2e tests pass locally against docker-compose.e2e.yml
- [ ] CI e2e job boots the stack and runs specs
- [ ] e2e job green on a PR
- [ ] CLAUDE.md e2e count matches actual passing count

**Estimated effort:** L (unknown drift; cap 1 day — split per-spec if deep rework)
**Blocked by:** None

---

## 4. Test inventory summary

| Iter | Smoke | Unit | Integration | State machine | Contract | Regression | Chaos | E2E | Performance | TDD Parity | Coverage Δ |
|------|-------|------|-------------|---------------|----------|------------|-------|-----|-------------|------------|------------|
| 1 | 1 | 1 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | N/A | +0% |
| 2 | 2 | 2 | 0 | 0 | 1 | 0 | 1 | 0 | 0 | 100% | N/A (bash) |
| 3 | 1 | 4 | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 100% | +~2% |
| 4 | 1 | 5 | 1 | 1 | 1 | 1 | 1 | 0 | 1 | ≥80% | +~3% |
| 5 | 1 | 0 | 1 | 0 | 1 | — | 1 | 6 specs | 1 | N/A | +0% |

Coverage baseline TBD — confirm current backend % and `fail_under` in `pyproject.toml` before iter 3.

---

## 5. End-to-end definition of done

**Deduplicated acceptance criteria:**
- [ ] CI fully on Node 24-capable actions; no deprecation warnings; all jobs green (iter 1)
- [ ] `scripts/deploy.sh` shellcheck-clean, dry-run-correct, proven on one real VM deploy (iter 2)
- [ ] `slide_status` distinguishes completed/skipped/failed; prod column-add path decided (iter 3)
- [ ] `incremental_ssim_threshold` drives a non-LLM fast-path; parent links populated; fewer LLM calls (iter 4)
- [ ] all e2e specs pass locally and in a CI e2e job (iter 5)

**Single end-to-end manual demo:**
1. PR with a trivial change → CI green, no Node 20 warning (iter 1).
2. `bash scripts/deploy.sh` on VM → stack healthy, no orphan conflict (iter 2).
3. Slide job that fails download → `slide_status: skipped`/`failed`, not silent completed (iter 3).
4. Slide deck with bullet builds → child slides linked, LLM call count < ambiguous count (iter 4).
5. `docker compose -f docker-compose.e2e.yml up -d && cd frontend && npm run test:e2e` → all pass (iter 5).

**Green command at the end:**
```
PYTHONPATH=backend python3.12 -m pytest tests/test_slide_detection.py tests/test_slide_routes.py tests/test_llm_two_pass.py tests/test_llm_providers_vllm.py -v
cd frontend && npm test
cd frontend && npm run test:e2e   # requires docker-compose.e2e.yml up
shellcheck scripts/deploy.sh && bats tests/deploy/deploy_dryrun.bats
actionlint .github/workflows/*.yml
```

---

## 6. Out of scope

- **Vision pre-pass pipeline** (`describe_image()` into summarization) — L+ effort, underspecified UX; deserves its own `/plan-iter`.
- **Next.js "major version bump" for CVEs** — `package.json` already shows `next ^15.5.15` (latest major); the HANDOFF note reads stale. Verify with `npm audit` before planning (see Open Questions).
- **Staging LXC migration** — infra/ops, not a code iteration; the only repo footprint is one stale config line (`docker-compose.staging.yml:44`).
- **hablatone MCP** — global voice tooling in `~/.claude/mcp.json`, unrelated to this repo.
- **`.superharness/` hardcoded paths** — export-only artifact; source of truth is `state.db`; protocol wants `project_path` absolute.

---

## 7. Open questions

1. **`slide_status` prod migration (iter 3 blocker):** alembic isn't wired and `create_all` won't ALTER the live table. Choose: (a) one-off manual `ALTER TABLE` on prod, (b) startup ensure-column shim in `main.py`, or (c) wire alembic.
2. **Next.js CVEs:** the "major bump" note looks stale (already on 15). Run `npm audit` first and replace the out-of-scope item with a real fix if findings exist?
3. **Iteration set:** confirm this engineering backlog is the intended cut (vs. including vision pre-pass / excluding e2e).
