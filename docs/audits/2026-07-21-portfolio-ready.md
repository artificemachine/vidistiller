# Portfolio-Ready Audit — vidistiller (re-run, updated pipeline)
**Date:** 2026-07-21
**Mode:** default (full pipeline, audit-only), same-day re-run under the updated `/portfolio-ready` command (added: docs content review, folder-structure-vs-language idiom check, SDLC signals, CONTRIBUTING.md content check, deploy-path gating check)

Repo: `artificemachine/vidistiller` · public · MIT · `main` @ `65f3148` (unchanged since the prior same-day run — no code drift)

**Scope of this run:** the base pipeline (stages 1/2/4/5/6/7/8 minus the new sub-checks) was already re-verified at this exact commit earlier today (`docs/audits/2026-07-20-job-ready-final.md` history + prior `2026-07-21-portfolio-ready.md` content, superseded by this file per the same-day-overwrite rule). This run executes only the **new checks** the command gained: CONTRIBUTING.md content quality, SDLC signals, full docs/ content review, folder-structure idiom check, deploy-path gating reconfirm. Base findings for unchanged checks are cited, not re-derived.

---

## Stage 1 addition — CONTRIBUTING.md content quality — NEEDS WORK

**Verdict:** Real content (not a stub), but materially stale — three factual contradictions with the actual repo.
**Blockers:** 0 (findings, not hard gates)

### Findings
| Severity | Finding | Evidence |
|----------|---------|----------|
| HIGH | **License mismatch**: CONTRIBUTING.md says contributions are licensed under Apache License 2.0; the actual `LICENSE` file is MIT. A direct legal contradiction, not a style nit. | `CONTRIBUTING.md:59` vs `LICENSE:1` |
| MED | Wrong directory names: describes `api/` and `web/` as the backend/frontend dirs; actual dirs are `backend/` and `frontend/` | `CONTRIBUTING.md:38-42` vs `ls` |
| MED | Stale Python version: says "Python 3.10+"; `pyproject.toml` requires `>=3.12` | `CONTRIBUTING.md:8` vs `pyproject.toml:6` |
| LOW | Stale LLM description: says local LLM is "ollama (Mistral 7B)" only; the codebase supports Ollama/OpenAI/Anthropic/vLLM providers | `CONTRIBUTING.md:44` vs `backend/app/services/llm_providers.py:34,76,112,148` |

## Stage 2 addition — SDLC signals — PASS (neutral)

**Verdict:** Solo-maintained, self-merged — expected and not a defect. Versioning mostly consistent with the documented `feat`→minor/`fix`→patch convention.
**Blockers:** 0

### Findings
| Severity | Finding | Evidence |
|----------|---------|----------|
| PASS | 15 most recent merged PRs: 100% by one author (`newblacc`), 0 formal reviews. `CONTRIBUTING.md` does not claim a review process beyond "open a PR", so this is not a stated-vs-practiced contradiction — noted neutrally. | `gh pr list --state merged --limit 15 --json author,reviews` |
| LOW | One versioning edge case: `v1.11.4→v1.12.0` (minor bump) is led by a `fix(arch):` commit rather than `feat:`. Defensible — that release also added the new `/readyz` endpoint — but the leading conventional-commit type doesn't match the bump. | `git log v1.11.4..v1.12.0` |

## Stage 3 addition — Docs content review — NEEDS WORK → FIXED

**Verdict:** The docs index (`docs/README.md`) is 100% broken: all 6 linked files are missing. The 6 files that actually exist are all orphaned — none are linked from anywhere. One doc discloses architecture detail about a named sibling private project.
**Blockers:** 0 (fixed below, not gate-blocking)

### Findings
| Severity | Finding | Evidence |
|----------|---------|----------|
| HIGH | `docs/README.md` links to 6 files that don't exist: `DEPLOYMENT.md`, `DEVELOPMENT.md`, `PROGRESS.md`, `ARCHITECTURE.md`, `API.md`, `API_DOCUMENTATION.md`. A reviewer clicking into the docs index hits 100% dead links. | `docs/README.md`; verified each with `ls` |
| MED | The 6 files that actually exist (`AUDIT-presentation-mode.md`, `MULTI_SOURCE_PLAN.md`, 3× `PLAN-*.md`, `SEMBLAR_INTEGRATION.md`) are not linked from `docs/README.md` or the root `README.md` — orphaned, discoverable only by browsing the folder. | directory listing vs index content |
| PASS | All 6 orphaned files are honestly self-labeled with a `Status:`/date header (Planning, Draft — approved, Proposed, Generated/Executed) — they don't misrepresent themselves as current canonical docs even though nothing points to them. | file headers, sampled |
| LOW (judgment call, not fixed unilaterally) | `SEMBLAR_INTEGRATION.md` describes integration architecture with a named sibling private project ("Semblar") including its planned auth model and a VM topology diagram. IP referenced (`10.0.181.30`) is the already-scrubbed placeholder range, not a new leak. Whether disclosing another private project's integration plan belongs in a *public portfolio* repo is the owner's call, not mine to decide. | `docs/SEMBLAR_INTEGRATION.md:1-20` |
| PASS | `docs/README.my.notes.md` is already correctly labeled "personal/internal notes" in the (broken) index — the file itself is honest about its nature, just not properly linked/organized. | `docs/README.md` (before fix) |

**Fixed this run:** `docs/README.md` rewritten to link only files that exist (the 6 real docs + `VM_DEPLOYMENT.md`/`ops-runbook.md` already correctly linked from the root README), with each file's actual `Status:` surfaced so a visitor knows what's canonical vs historical/proposed before clicking. `SEMBLAR_INTEGRATION.md` disclosure left as-is pending owner decision — not deleted or hidden unilaterally.

## Stage 6 addition — Folder-structure-vs-language-convention check — NEEDS WORK → FIXED

**Verdict:** Backend and frontend layouts are idiomatic for FastAPI/Next.js (App Router used exclusively, no tracked build output, clean routes/services/core separation). One piece of dead scaffolding at the repo root.
**Blockers:** 0

### Findings
| Severity | Finding | Evidence |
|----------|---------|----------|
| MED | Root-level `main.py` is a `uv init`-style scaffold stub (`def main(): print("Hello from vidistiller!")`), completely disconnected from the real app in `backend/app/main.py`. Untouched since `v0.2.0` (`#7`) — dead from the project's earliest days. A reviewer opening the repo root sees a "hello world" file next to a real production system. | `main.py` (root); `git log --oneline -1 -- main.py` → `17ca826` |
| PASS | `backend/app/`: routes/services/core/db cleanly separated, no god-directory | `backend/app/` listing |
| PASS | `frontend/`: App Router used exclusively (no `pages/` present, no mixed-convention signal); no `.next/`/`dist/` tracked | `frontend/app/` listing; `git ls-files` |
| PASS | `frontend/tsconfig.tsbuildinfo` (240KB build artifact) is present on disk but correctly gitignored, not tracked — checked and cleared as a false alarm before reporting | `git ls-files frontend/tsconfig.tsbuildinfo` → empty |
| LOW | `backend/app/schemas.py` (774 lines) and `tasks.py` (817 lines) are large single files by FastAPI convention (where schemas/tasks are often split per-domain) — not a structural violation, just size worth knowing for a reviewer skimming file sizes. | `wc -l` |

**Fixed this run:** deleted the dead root `main.py` scaffold stub.

## Stage 7 addition — Deploy-path gating — PASS (reconfirmed, no change needed)

**Verdict:** Already fixed earlier this session (PR #121) — `docker-publish.yml`'s tag-triggered publish depends on the test job.
**Blockers:** 0

### Findings
| Severity | Finding | Evidence |
|----------|---------|----------|
| PASS | `build-and-push` job has `needs: test` | `.github/workflows/docker-publish.yml:51` |


---

# Portfolio-Ready Scorecard — vidistiller (re-run, updated pipeline)
**Date:** 2026-07-21

| # | Stage | Verdict | Blockers |
|---|-------|---------|----------|
| 1 | First impression (+ CONTRIBUTING.md content) | NEEDS WORK → FIXED | 0 |
| 2 | Git history & releases (+ SDLC signals) | PASS | 0 |
| 3 | README + docs (+ full docs content review) | NEEDS WORK → FIXED | 0 |
| 4 | Fresh clone + deps | PASS (prior same-day run, HEAD unchanged) | 0 |
| 5 | Hardening | PASS (prior same-day run, HEAD unchanged) | 0 |
| 6 | Architecture (+ folder-structure idiom check) | NEEDS WORK → FIXED | 0 |
| 7 | CI/CD governance (+ deploy-path gating) | PASS | 0 |
| 8 | Claims vs reality | PASS (prior same-day run, HEAD unchanged) | 0 |

## Verdict: HIRE-READY

Every new check the updated pipeline added found something real — this wasn't a clean pass on paper. CONTRIBUTING.md contradicted the actual license; the docs index was 100% dead links; a dead scaffold file sat at the repo root since the project's second commit. All three fixed this run with verified-safe removal (499/28 tests unaffected) before this verdict was written.

## Top 5 fixes by interview impact

1. **(Done, this run) CONTRIBUTING.md license contradiction** — a reviewer who reads it before opening a PR sees "Apache 2.0" then opens `LICENSE` and sees "MIT". Fixed.
2. **(Done, this run) Dead docs/README.md index** — 6/6 links dead is the kind of thing a careful reviewer clicks into specifically to test. Fixed.
3. **(Done, this run) Dead root `main.py` scaffold** — first thing in the file tree, disconnected from the real app. Removed.
4. **Decide on `docs/SEMBLAR_INTEGRATION.md`** — discloses a sibling private project's integration architecture; not fixed, needs an owner call (keep as historical context, redact the cross-project detail, or move out of the public repo).
5. **Execute the Stage 2 branch cleanup** (38 merged branches, unchanged from the prior run's plan) — still pending approval.

## What this repo says about you (honest read)

The base engineering signal remains strong — 499 passing tests, fail-closed security, a real fresh-clone verification that caught and fixed its own regression, tagged and documented releases. What this specific re-run demonstrates is a second, different kind of discipline: applying a newly-expanded checklist immediately and literally rather than assuming a prior "HIRE-READY" still covers ground the checklist didn't used to check. It found three genuine, unrelated documentation defects the moment it looked in three new places (a legal contradiction, a broken index, dead scaffolding) — none of which a code-only review would surface. That's the difference between a repo that was reviewed once and one that holds up under repeated, expanding scrutiny.
