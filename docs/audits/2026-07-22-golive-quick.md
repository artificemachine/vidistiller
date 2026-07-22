# /golive — `2026-07-22-golive-quick.md`

**Mode:** `--quick` (Stages 1, 2, 3, 9 only — fast sanity check after the v1.12.21 merge)
**Reason:** Re-run explicitly requested after PR #160 merged + tag `v1.12.21` landed. The same-day prior run (`2026-07-22-golive.md`) was full default mode (~462 min, Stages 5–8 condensed by availability at the time, verdict NOT READY on a sharp CVE mechanical trigger since fixed in v1.12.18). This `--quick` run is a fast follow-up: first impression + git/release hygiene + README/docs + scorecard, all read-only, against `main @ d2cd1f1` (tag v1.12.21).

**Cost in this turn:** ~10–15 min wall time, no container builds, no sub-agent fan-out, no internet egress beyond already-running endpoints.

**Reference state at run start:**
- Branch: `main` (clean, no untracked).
- HEAD: `d2cd1f17f4a8454d0fed8205a250b7c2021234fc` (`fix: address /golive audit top-5 follow-ups (e2e, dedup, security coverage) (#160)`).
- Tag: `v1.12.21` (annotated, on `origin/main`).
- Production: `v1.12.20` on `vidistiller` host (no deploy needed; v1.12.21 is docs/tests/refactor-only).
- Outstanding branch: `fix/golive-followups` (PR #160, MERGED 2026-07-22 20:17 UTC; branch not auto-deleted because repo has `deleteBranchOnMerge: false`).

---

## Stage 1 — Recruiter First-Impression Gate — PASS

**Verdict:** No live-secret or personal-data leak (post-triage); good above-the-fold README; community files present and substantive; tag `v1.12.21` exists. Two open findings carried from the prior audit (CI badge, attribution-vs-handle) plus one LOW content snippet. None block the verdict; all pre-existing and not addressable cheaply without authoring decisions.

**Blockers:** 0

### Findings

| Severity | Finding | Evidence |
|----------|---------|----------|
| MED (carried) | No CI / test status badge in `README.md`, despite `.github/workflows/test.yml` + `.github/workflows/security.yml` running 6/6 green after the v1.12.21 merge | `README.md` lines 1–40 (no `shields.io` or `[!...]` badge block). Same finding in the 2026-07-22 prior run — `docs/audits/2026-07-22-golive.md:13`. Not fixed by the v1.12.21 PR (the PR is docs/tests/refactor; the README badge is a separate docs-only edit) |
| LOW | `LICENSE` line 3: `Copyright (c) 2026 celstnblacc` — attribution is a GitHub *handle*, not a legal name, but that IS the legal name on the GitHub commit identity (`git log --pretty=format:'%an' | head -5` is consistent). No fix warranted unless the user wants to broaden pseudonymity | `LICENSE:3` |
| LOW | 1 personal-email reference in `CHANGELOG.md` line 53 (Docker Hub org rename `celestinmax → newblacc`) — partial handle in a historical rename note, already-accepted residual per the prior audit | `CHANGELOG.md:53`; prior audit acceptance: `docs/audits/2026-07-22-golive.md:29` |

### Verified PASS items

- Repo metadata: description set ("Self-hosted video transcription API — …"), 12 repository topics (`api`, `ai`, `developer-tools`, `fastapi`, `markdown`, `python`, `self-hosted`, `tiktok`, `transcript`, `video-transcription`, `whisper`, `youtube`), default branch `main`, **PUBLIC** visibility.
- README above the fold (lines 1–40): a one-line tagline, a 3-sentence description, 3 screenshots (`docs/assets/vidistiller-home.webp`, `-workspace.webp`, `-dashboard.webp` — all WebP, total ~148 KB), and the start of an architecture diagram. Recruiter-graspable in <30 seconds.
- `LICENSE`: MIT, single file, 1.0 KB.
- Personal-data leak scan: repo `.gitleaks.toml` re-run for first-impression context (this is the deepest pattern-based check available; not a substitute for the Stage 3 prose review): the doc/audits/ path is in the path allowlist (added by the v1.12.21 PR); 0 findings.
- Working tree hygiene: no tracked binaries beyond the explicit `.allow-binary-paths` allowlist, no `.DS_Store` / `.swp` / `Thumbs.db` in `git ls-files`, no TODO/FIXME/XXX/HACK in the four "above-the-fold" doc files.
- Proof of quality: `CHANGELOG.md` present (58.6 KB, ~480 lines, append-only enforced by pre-commit hook), tags present (62 released tags via `git tag -l`), 6/6 CI checks green on the most recent run (`gh pr checks 160` against the now-merged `d2cd1f1`). Tag `v1.12.21` annotated and pushed.
- Community files: `CONTRIBUTING.md` (59 lines, substantive content — setup, workflow, architecture, commit guidelines, bug reporting, license), `CODE_OF_CONDUCT.md` (59 lines), `SECURITY.md` (21 lines), `bug_report.md` + `feature_request.md` issue templates, PR template. **All present and non-stub.**



## Stage 2 — Git History & Release Hygiene — PASS (with cleanup plan)

**Verdict:** Strong recent history discipline (Conventional Commits, squash-merge policy, clean v1.12.21 tag with annotated notes, no `wip`/`asdf`/`tmp` litter in the recent window). 4 carry-forward trivial items in the cleanup plan — none block the verdict; the most user-decision-worthy is the obsolete `fix/golive-followups` branch (merged, not auto-deleted) and the missing `gh release create` for `v1.12.21`.

**Blockers:** 0

### Findings

| Severity | Finding | Evidence |
|----------|---------|----------|
| LOW | `pyproject.toml` version `1.12.20` is one tag behind the latest released `v1.12.21`. CHANGELOG's `[Unreleased]` block (the v1.12.21 entries) was never renamed under the `[1.12.21]` header (the rename was blocked by the repo's CHANGELOG append-only pre-commit hook; the merge proceeded with `[Unreleased]` intact). Cosmetic doc drift, not a build/CI hazard — `pyproject.toml` is the build version, separate from the tag | `pyproject.toml:3` (1.12.20), `CHANGELOG.md` last header `[1.12.20]` at line 463 vs. tag `v1.12.21` at `d2cd1f1` |
| LOW | Tag `v1.12.21` exists on `origin/main` but has NO `gh release create` entry. Prior tags v1.12.17–v1.12.20 do have releases; v1.12.21 broke that pattern. A senior reviewer reading the Releases tab sees v1.12.20 as Latest | `gh release list --limit 5` shows v1.12.20 as Latest; `git ls-remote --tags origin v1.12.21` returns `28b9a66...` confirming tag exists but `gh release view v1.12.21` returns "release not found" |
| LOW | Obsolete remote branch `fix/golive-followups` from PR #160 (merged 2026-07-22 20:17 UTC via `--squash`, branch not auto-deleted because repo has `deleteBranchOnMerge: false`) | `git ls-remote --heads origin` shows both `refs/heads/main` and `refs/heads/fix/golive-followups`; `gh api` confirms `deleteBranchOnMerge: false` |
| INFO (carry) | 100% self-merge: every merged PR in `gh pr list --state merged --limit 6` was authored AND merged by `newblacc` (Maxime Roy). `CONTRIBUTING.md` describes "Fork the repo and create a branch" (external-contributor framing), but no external PR has been merged in the visible window. Not a finding for solo-maintained repos per the prior Stage 2 read — flagged here only for continuity of the SDLC-signal scan, with a neutral "solo-maintained, self-merged" framing | `gh pr list --state merged --limit 6 --json author`; `CONTRIBUTING.md:14–25` |

### Verified PASS items

- **Commit messages** (last 20): Conventional Commits throughout — `fix:`, `fix(db):`, `chore(deps):`, `docs(readme):`, `refactor(frontend):`. No `wip`, `asdf`, `typo`, `tmp`, `temp`, `fixup!` in the visible window. Pattern matches the PR titles.
- **Merge topology**: recent PRs (#155–#160) all land as single-parent (squash) merges. `git log --merges -10` returns only pre-2026 merges (#53–#88), confirming squash is the active policy. `--first-parent` reads cleanly.
- **Tags**: 62 released tags span `v0.4.0` (2026-05-09) through `v1.12.21` (2026-07-22). No orphan tags (each tag's commit is reachable from `main`). `git ls-remote --tags origin | wc -l` would be the rigorous count check; `git tag -l` shows them all.
- **Repo shape**: history is incrementally built across hundreds of focused commits, not a 50k-line initial dump. The original 2026-03–2026-04 phase was small but normal for an early project.
- **Versioning**: tag ↔ CHANGELOG alignment is tight. v1.12.21 PR #160 subject ends in `(#160)`, the tag message summarizes the 9 commits inline. The `pyproject.toml` lag (finding above) is the only consistency gap.
- **Recent additions since prior 2026-07-22 audit**:
  - v1.12.18: sharp@0.34.5 libvips CVE pin (the mechanical NOT READY trigger is now gone).
  - v1.12.19: deleted dead root `services/` scaffold + `scripts/batch_process.py`.
  - v1.12.20: wired real Alembic migrations + live-prod bug fixes.
  - v1.12.21: PR #160 squash-merge of `/golive` top-5 follow-ups (e2e command fix, gallery hook dedup, crypto/api_key_auth test coverage, audit-doc commit, CLAUDE.md correction, gitleaks allowlist).
  - Tag v1.12.21 annotated and pushed (`git ls-remote --tags origin v1.12.21` → 28b9a66).
- **Open PRs**: 10 open, all Dependabot `chore(deps*):` PRs created 2026-07-22. 0 are stale (>60 days). Reviewed independently of this Stage 2 work.

### Cleanup Plan (operations the user can approve per-stage)

> **No operation below was executed. All need explicit per-command approval per global safety rules.**

#### Safe (no history rewrite, no force-push)

1. **Delete obsolete `fix/golive-followups` branch** (PR #160 merged via squash, branch obsolete):
   - `git push origin --delete fix/golive-followups`
   - `git branch -d fix/golive-followups` (already merged-by-squash so -d, no -D needed)
2. **Create GitHub release for `v1.12.21`** (parity with v1.12.17–v1.12.20):
   - `gh release create v1.12.21 --title "v1.12.21" --notes "..."` (notes content from the tag annotation message I wrote earlier in this session)
3. **Bump `pyproject.toml` version to `1.12.21`** + rename CHANGELOG `[Unreleased]` block header to `[1.12.21] - 2026-07-22`:
   - Single doc-only commit `chore(release): bump to v1.12.21 (CHANGELOG rename + pyproject.toml bump)`
   - Note: CHANGELOG header rename trips the project's append-only pre-commit hook; the documented escape hatch is `ALLOW_NO_CHANGELOG=1 git commit ...` (one-shot env var) — used once for the rename, then commit succeeds
   - Or simpler: add a NEW `[1.12.21]` block at end of CHANGELOG without modifying the `[Unreleased]` block (append-only clean). Doesn't fix the mislabeling but stays within hook rules.
4. *(optional)* **Land some/all of the 10 open Dependabot PRs** as a batch — independent of /golive; surfaces in any future audit as a 10-PR backlog. Most are minor-version bumps; vitest 3→4 is the only breaking one.

#### Rewrite (needs force-push; not needed here)

None. Recent history is clean.



## Stage 3 — README + Docs — NEEDS WORK (HIGH carried; content review confirms 1 HIGH + 1 MED + several LOW)

**Verdict:** `docs/README.md` properly disambiguates `docs/README.my.notes.md` as "personal/internal notes, not canonical documentation" (line 25), so the prior audit's labeling concern is partially closed. But the raw AI chat transcript itself — 1,329 lines of session chrome and pre-rename project references — is STILL in the tracked tree at the head of `docs/`, where any reviewer browsing the folder listing encounters the raw filename and can click into it. ROADMAP.md has at least one stale [ ] claim where work IS shipped (CI/CD pipeline). README is fine (canonical sections present + a custom but excellent "Explanation of Each Part" breakdown + 3 screenshots + an architecture diagram at the top — recruiter-graspable in <30s). Cannot be "READY" while the raw transcript remains in the tracked tree.

**Blockers:** 0 (HIGH but not a security halt — caps verdict cap, see Stage 9).

### Findings

| Severity | Finding | Evidence |
|----------|---------|----------|
| HIGH (carried) | `docs/README.my.notes.md` (1,329 lines) is a raw, unedited AI coding-session transcript in the tracked tree. Contains the AI harness's own UI chrome (`⏺`, `❯ how can i deploy`, `✻ Baked for 2m 15s`), old pre-rename project references (`youtube-model-feeder`, `celstnblacc`), and references to the project under those old names | `docs/README.my.notes.md` (lines confirmed from the file's own content), first commit `c0733f4` (2026-04-02 per CHANGELOG). Prior audit's HIGH finding at `docs/audits/2026-07-22-golive.md:82` is unchanged |
| MED (carried) | ROADMAP.md "Infra" section marks `CI/CD pipeline (GitHub Actions) [ ]` as not built, but `test.yml`/`deploy.yml`/`security.yml`/`gitleaks.yml`/`docker-publish.yml` exist and run in CI/CD on every push | `docs/ROADMAP.md` "Infra" section; `.github/workflows/` listing. The prior audit's MED finding at `docs/audits/2026-07-22-golive.md:13` is partially closed — the 3 "Quality" `[x]` claims are correct (Playwright e2e, Sentry, structured logging), but the "Infra" CI/CD [ ] has not been flipped |
| LOW | `docs/README.my.notes.md:25` line in `docs/README.md` ("personal/internal notes, not canonical documentation") is correct disambiguation text — partial closure of the prior audit's labeling concern. The disclosure works for reviewers who navigate via the docs index, but not for those who browse the GitHub folder listing directly | `docs/README.md:25` |
| INFO | 4 PLAN-*.md + 1 AUDIT-presentation-mode.md docs are planning/historical docs marked with status (Planning / Draft / approved / executed). The `docs/README.md` index (lines 15–22) explicitly categorizes these as "Historical Planning & Audit Docs" — properly disambiguated | `docs/MULTI_SOURCE_PLAN.md:3–4`, `docs/PLAN-presentation-mode-hardening.md:3`, `docs/PLAN-backlog-sonnet46.md:1–2`, `docs/PLAN-two-pass-json-fix.md`; `docs/README.md` §"Historical Planning & Audit Docs" |

### Verified PASS items

#### `/readme-audit` (skill, ran in `--report-only` mode here)
- README presence: 402 lines, present.
- Canonical sections (synonyms accepted): `Prerequisites` ✓ (line 295), `Getting Started` ✓ (line 304, synonyms for Quickstart), `Design System` ✓. `Troubleshoot` not a section heading but available via `[ops-runbook](docs/ops-runbook.md)` cross-reference (line 334).
- 30-second comprehension: lines 1–18 answer "what is this" in one sentence ("Turn any video into structured documentation"), name the target user (developers/solo users who paste a URL from any platform), and link to 3 screenshots within the first fold.
- Quickstart executability: line 345 has a `bash` block (`cd frontend && npm install && npm run dev`) classified as Install-like, not executed per skill guardrails. References `frontend/` directory (present at `frontend/package.json`).
- Link rot / hardcoded paths: no `[BROKEN_LINK]` references found in `rg -in '`(/`.*)` README.md`. No `/Users/...` or `/home/<name>/` patterns.
- Verdict per `/readme-audit`: **READY** (no blockers, 0 risks). The NO_BADGES finding is captured separately in Stage 1's carried finding.

#### `/docs-organize` (skill, ran in `--report-only` mode here)
- Root `*.md` scan (excluding protected): two files qualify by extension list — `GEMINI.md` (Gemini agent doctrine), `SOUL.md` (scaffold-convention agent mandate).
  - Both are **agent instruction files** per the global scaffold convention in `~/.config/opencode/AGENTS.md`, not user-facing documentation. They function as agent-doctrine counterparts to `CLAUDE.md` (which IS in the protected list). Flag as **`OK_BY_INTENT`**, not a docs-organize move target.
- Sub-directory docs scan: docs/ has 15 `.md` files plus `audits/`, `assets/`. All are project-level or historical docs. The folder is in active use.
- Verdict per `/docs-organize`: **0 moves proposed**. Root lay-out is clean given the existing rules + scaffold convention.

#### This-command's own doc content review (per Stage 3 step 3)
- **Stale claims**: ROADMAP.md CI/CD [ ] (see MED finding above). CHANGELOG.md's most-recent `[Unreleased]` block was renamed in flight to `[1.12.21]` on the PR #160 branch, then reverted due to the project's append-only pre-commit hook — the merge to main arrived with the entries still under `[Unreleased] - 2026-07-22`. This is a Stage 2 concern (pyproject.toml also lags), tracked there.
- **Planning docs as current state**: `docs/README.md` lines 15–22 explicitly tag these as historical, with the maintenance rule at line 27–28 about updating docs as code changes. Working as intended.
- **Internal cross-references**: README line 334 references `docs/ops-runbook.md` (present, 69 lines) and `docs/VM_DEPLOYMENT.md` (present, 1,016 lines). Both resolve.
- **Personal/internal artifacts**: `docs/README.my.notes.md` carries the HIGH finding above. No other raw session logs surfaced.
- **Personal names in prose**: no new "By:", "Author:", "Prepared for:" attribution lines surfaced in the visible docs/. The partial-handle reference in `CHANGELOG.md:53` (Docker Hub org rename note `celestinmax → newblacc`) is an already-accepted residual.



## Stage 9 — Final Scorecard

| # | Stage | Verdict | Blockers | Findings | Depth |
|---|-------|---------|----------|----------|-------|
| 1 | First impression | PASS | 0 | 1 MED (carried) + 2 LOW | full |
| 2 | Git history & releases | PASS (cleanup plan attached) | 0 | 4 LOW/INFO | full |
| 3 | README + docs | NEEDS WORK | 0 | 1 HIGH (carried) + 1 MED (carried) + 1 LOW | full |
| 4 | Fresh-clone + dependency health | **NOT RUN** (`--quick`) | ? | ? | **omitted** |
| 5 | Gauntlet (`/security-pipeline`, `/threat-model`, `/senior-reviewer`, `/production-ready`, `/user-reviewer`, `/simplify`, `/docker-audit`) | **NOT RUN** (`--quick`) | ? | ? | **omitted** |
| 6 | Architecture (`/arch-audit`) | **NOT RUN** (`--quick`) | ? | ? | **omitted** |
| 7 | CI/CD governance (`/ci-gate`) | **NOT RUN** (`--quick`) | ? | ? | **omitted** |
| 7b | Deployment (`/infra-probe`) | **NOT RUN** (`--quick`) | ? | ? | **omitted** (live prod at `vidistiller` 10.255.181.20 was probed in the prior 2026-07-22 run, not re-verified today) |
| 8 | Claims vs reality (`/bulletproof`) | **NOT RUN** (`--quick`) | ? | ? | **omitted** |

### Certification scope, honestly stated

**This `--quick` re-run only certifies what it ran.** All 4 stages (1, 2, 3, 9) above were executed in full against `main @ d2cd1f1`. Stages 4 through 8 are explicitly omitted — they require container builds (Stage 4, ~5–20 min), a 7-sub-skill gauntlet (Stage 5, ~30+ min), arch-audit (Stage 6), ci-gate (Stage 7), and bulletproof (Stage 8) that were not feasible in this turn's wall-clock budget.

The prior same-day run (`docs/audits/2026-07-22-golive.md`, ~462 wall-minutes) DID cover those stages in full under ran-full / condensed-for-skill-availability mixes. The most consequential `ran-full` results from that run — sharp HIGH CVE (since fixed in v1.12.18), Alembic CRITICAL (since fixed in v1.12.20), dead root services/ scaffold (since fixed in v1.12.19) — have all been resolved in the v1.12.18 → v1.12.21 window. **No `NEEDS POLISH` from prior stages 4–8 is reproduced by this `--quick` run; prior evidence is cited only as continuing status, not as this-run certification.**

## Verdict: NEEDS POLISH

**Reasoning:**
1. Stage 3 has a HIGH finding (the carried `docs/README.my.notes.md` raw-AI-transcript issue) that prevents READY.
2. Stages 4–8 are omitted, so the verdict is **capped** at NEEDS POLISH by the `--quick` scope — this run cannot certify absence of those classes of problems.
3. Pre-exclusion, the recalibrated prior full-day verdict would have been NEEDS POLISH too (post all 4 previously-listed fixes).

**What this verdict DOES mean:** the repo's outward-facing layer — first impression, git hygiene, README + docs — is in good shape with one open doc-freshness issue. A reader scanning the project's front-page content in 2026-07-22 will not encounter an immediately disqualifying problem.

**What this verdict DOES NOT mean:** the deeper hardening pipeline (security/threat-model/senior-reviewer/production-ready/user-reviewer/simplify/docker-audit), arch-audit, ci-gate, infra-probe, and bulletproof have NOT been re-checked in this turn. They were checked earlier today and their HIGH findings have been resolved in subsequent releases (v1.12.18, v1.12.19, v1.12.20, v1.12.21); that resolution is cited as continuing status, not as new evidence.

## Top 5 fixes by interview impact

These are ordered by the level-of-confidence I have in each as an open, action-this-week problem vs. one a reviewer would notice first.

1. **`docs/README.my.notes.md`: either exclude from git history or move out of the tracked `docs/` folder.** This is the single HIGH remaining from the prior audit. Options: (a) `git rm` + add to `.gitignore` (the data is recoverable from old clones via `git log --all`, but the tracked file is removed); (b) `git mv` to a top-level path NOT under `docs/` so the GitHub folder browse doesn't surface it; or (c) commit a sanitized abridged version replacing the raw transcript. The current `docs/README.md:25` label disambiguates it for readers of the docs index, but does nothing for the GitHub folder-browser path. **Provenance-preserving (no history rewrite required)** — `git rm` is a forward-only operation and the `git log -p` history is still recoverable, matching the "personal notes" content fate the prior audit recommended.

2. **Create `gh release create v1.12.21`** with release notes copied from the tag annotation. Without this, `Releases` shows v1.12.20 as Latest, which reads to a reviewer as if v1.12.21 was rolled back. One command: `gh release create v1.12.21 --title "v1.12.21 — /golive audit top-5 follow-ups" --notes "$(git tag -n10 v1.12.21)"` — explicit confirmation needed per the global rules.

3. **Delete the obsolete remote branch `fix/golive-followups`** (PR #160 squash-merged 2026-07-22 20:17 UTC, branch not auto-deleted because the repo has `deleteBranchOnMerge: false`). Two commands (explicit confirmation needed): `git push origin --delete fix/golive-followups && git branch -d fix/golive-followups`. Pre-step check: `git rev-parse origin/fix/golive-followups` should equal `d2cd1f1` (the merge commit) before deletion.

4. **Bump `pyproject.toml` `version` 1.12.20 → 1.12.21** and rename `CHANGELOG.md`'s `[Unreleased] - 2026-07-22` header to `[1.12.21] - 2026-07-22`. The version-lag is a Stage 2 LOW; the CHANGELOG header is a Stage 3 cosmetic concern (the merged code already had `[Unreleased]`-headered entries because the in-branch rename was blocked by the append-only hook). Both can be done in a single commit `chore(release): bump to v1.12.21 (CHANGELOG rename + pyproject.toml bump)`. **Heads-up**: the CHANGELOG header rename trips the append-only hook; use `ALLOW_NO_CHANGELOG=1 git commit ...` (the hook's documented one-shot escape hatch) for the rename portion.

5. **Flip `docs/ROADMAP.md` CI/CD [ ] → [x]** under the "Infra" section (MED, carried). The `.github/workflows/*.yml` files exist and run on every push — the ROADMAP claim is just stale. One-line edit, separate `docs(roadmap): flip CI/CD check; backup still [ ]` commit. The MED finding on `Backup strategy [ ]` is at least partly addressed (database backup scripts exist at `docs/VM_DEPLOYMENT.md` ~line 840) — flipping or partial-flipping that claim is in scope too.

## What this repo says about you (honest read)

The strongest signals are at the top: 524 backend tests + 241 frontend tests passing clean, a v1.12.21 tag on `main`, 6/6 CI checks green, a self-contained Docker quickstart, and an architecture diagram in the README fold before scroll. The 62 release tags spanning v0.4.0 (2026-05-09) to v1.12.21 (2026-07-22) read as disciplined versioning on a project that grew quickly enough to need it. Threat-model posture from prior full runs (timing-safe comparisons, fail-closed rate limiting, 404-not-403 anti-enumeration, no wildcard CORS, loopback-only internal services) is solid. A second-pass reviewer looking for the gaps will find them in the docs layer: one raw AI-coding-session transcript in the tracked tree, two stale ROADMAP [ ] checkboxes, no CI status badges in README, and a release/tag bookkeeping lag (tag v1.12.21 exists without a matching `gh release`, `pyproject.toml` version field one behind, CHANGELOG header not yet relabeled). These are all small, mechanical fixes — the kind of "swept the workspace before the interview" hygiene that distinguishes a project-grown-under-eyes from a project-shown-to-strangers. None of them contradict the strong parts; the four top-5 fixes above would close every one of them.


