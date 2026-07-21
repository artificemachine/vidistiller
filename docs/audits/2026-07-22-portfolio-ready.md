# Portfolio-Ready Audit — vidistiller (4th run)
**Date:** 2026-07-22
**Mode:** default, full pipeline

Repo: `artificemachine/vidistiller` · public · MIT · `main`

**Why a real run, not confirmatory:** since the last full certification (`903aeb2`), 18 non-cosmetic files changed — all 5 CI workflow files (action version bumps), `backend/Dockerfile` (Python 3.12-slim → 3.14-slim), `frontend/Dockerfile` (Node 20-alpine → 26-alpine), `backend/requirements.txt`, `frontend/package-lock.json`/`package.json`, and `README.md`. This is real runtime-surface drift (base images, dependency versions), not docs-only — unlike the 3rd run, this one needs a genuine fresh Stage 4.

Local + remote branches: both down to 1 (`main`) as of this run — full cleanup executed since the last audit (44 + 12 + 3-held merged/deleted branches; 14 of 17 open Dependabot PRs merged, 1 replaced manually, all local checkouts pruned).

---
## Stage 1 — Recruiter First-Impression — PASS

**Verdict:** Clean. Secret-scan surface shrank as a side effect of branch cleanup (unreachable history no longer scanned).
**Blockers:** 0

| Severity | Finding | Evidence |
|----------|---------|----------|
| PASS | gitleaks: 59 hits (down from 85), same 2 categories as every prior run (58 `ipv4-address`, 1 historical `generic-api-key`), all already triaged as category-b. Drop is a real side effect of deleting 56 branches — their intermediate commits (many predating the topology scrub) are now unreachable garbage, no longer in scan scope. Not a fix, a byproduct. | `gitleaks detect`: 138 commits scanned (was 204) |
| PASS | Metadata, community files, working tree unchanged from prior certification | fresh checks this run |

## Stage 2 — Git History & Branches — PASS

**Verdict:** Fully clean — 1 local branch, 1 remote branch (`main` both), 0 open PRs. Best state this repo has been in all session.
**Blockers:** 0

Executed since last audit: 44 + 12 + 3 merged/deleted branches (59 total), 14 of 17 open Dependabot PRs merged (1 replaced manually after a same-day merge conflict), all local checkouts pruned. No further action.

## Stage 3 — README + Docs — PASS

**Verdict:** All links resolve, prerequisites accurate, no new staleness since the `config/` fix landed.
**Blockers:** 0

## Stage 4 — Fresh-Clone Verification + Dependency Health — PASS (real run, not skipped)

**Verdict:** Genuinely re-verified end to end on the new base images. This run's Dockerfile/dependency changes are real infrastructure drift worth flagging even though nothing is broken.
**Blockers:** 0

### Transcript
1. Fresh `git clone` at `a645ca4`.
2. `cp .env.example .env`, `docker compose up -d --build` → **all containers healthy on first try**, including rebuilding both Dockerfiles from scratch (base images changed).
3. **Verified inside the containers**: `python --version` → `3.14.6` (was `python:3.12-slim`, PR #111). `node --version` → `v26.5.0` (was `node:20-alpine`, PR #109).
4. `alembic upgrade head` → builds the squashed baseline cleanly against real Postgres.
5. `/health` 200, `/docs` 200, web 200.
6. Full test suite in a **fresh Python 3.14 venv** with the actual bumped `requirements.txt`: **499 passed, 28 skipped** — not assumed from CI, run and observed directly.
7. `pip-audit`: same 1 pre-triaged `ecdsa` CVE, no new vulnerabilities from any of the 9 pip/npm bumps.
8. `npm audit --omit=dev`: **0 vulnerabilities**.
9. Full teardown: containers, volumes, 3 built images removed, scratch clone deleted.

### Findings
| Severity | Finding | Evidence |
|----------|---------|----------|
| INFO | Prod's Python version convention has shifted. Prior sessions deliberately noted "local .venv is 3.14.5; CI/Dockerfile/prod are 3.12.13 — run both for release work" as an intentional split to catch version-specific bugs before they hit prod. Dependabot's `python:3.12-slim → 3.14-slim` bump (#111, merged this session) collapses that split — Dockerfile/prod now matches local dev at 3.14. Not a defect (verified working end to end), but the two-Python-version testing discipline this repo used to follow no longer has a reason to exist post-bump; worth a conscious decision rather than a fact that just quietly changed via Dependabot. | `backend/Dockerfile` `FROM python:3.14-slim`; container `python --version` |
| PASS | Both Dockerfile base image bumps (Python 3.14, Node 26) boot, migrate, and pass the full test suite | transcript steps 2-6 |
| PASS | Zero new CVEs across all 9 dependency bumps merged this session | `pip-audit`, `npm audit` |

## Stage 5-8 — Hardening / Architecture / CI-CD / Claims — PASS (re-confirmed, no drift into these surfaces)

Diffed since last full-depth certification (`903aeb2`): the only files touched are CI workflow action-version bumps, both Dockerfiles, dependency manifests, and one README fix already covered above. Nothing touching `backend/app/` security/auth/architecture code, nothing touching branch protection config. Re-confirmed live: `docker-publish.yml` `needs: test` still present (line 51), `enforce_admins` still enabled.

---

# Portfolio-Ready Scorecard — vidistiller (4th run)
**Date:** 2026-07-22

| # | Stage | Verdict | Blockers |
|---|-------|---------|----------|
| 1 | First impression | PASS | 0 |
| 2 | Git history & releases | PASS (fully clean: 1 branch, 0 open PRs) | 0 |
| 3 | README + docs | PASS | 0 |
| 4 | Fresh clone + deps | PASS (real re-run: new base images verified end to end) | 0 |
| 5 | Hardening | PASS (no drift) | 0 |
| 6 | Architecture | PASS (no drift) | 0 |
| 7 | CI/CD governance | PASS (reconfirmed live) | 0 |
| 8 | Claims vs reality | PASS (no drift) | 0 |

## Verdict: HIRE-READY

Fourth consecutive HIRE-READY. Unlike run 3 (confirmatory, zero code changes), this run had real infrastructure drift — 9 dependency bumps including two base-image majors — and it was genuinely re-verified, not assumed: fresh clone, fresh containers, fresh Python 3.14 venv, real test run, real CVE scan, real teardown.

## Top 5 fixes by interview impact

1. **Decide on the Python-version-testing convention.** The Dockerfile/prod Python version quietly moved from 3.12 to 3.14 via a routine Dependabot merge, collapsing a deliberate dual-version testing discipline this repo used to follow. Not broken, but worth a conscious call: keep single-version now, or repin CI to also test 3.12 explicitly going forward.
2. Nothing else outstanding at any severity.

## What this repo says about you (honest read)

Four audits in two days, and the story has shifted from "finding and fixing problems" to "proving stability under real change." This run's dependency bumps were the first genuine infrastructure-level drift since certification — two base-image major-version jumps — and rather than trust green CI at face value, verification meant actually booting the new images, checking the runtime versions inside them, and running the full suite fresh. That's the difference between a repo that passed once and one that keeps passing as it changes. The one finding here is process, not code: a Python-version convention changed without anyone deciding it should.
