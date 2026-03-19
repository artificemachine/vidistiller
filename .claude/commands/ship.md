---
name: ship
description: Update docs, run tests, build, commit, and optionally push
---

Run the full ship pipeline. Do each step in order and stop if any step fails:

1. **Update TECH_STACK.md** — Check if any new dependencies were added to `frontend/package.json` or `backend/requirements.txt` that are missing from `TECH_STACK.md`. If so, add them in the appropriate section.

2. **Update CLAUDE.md** — If CLAUDE.md is empty or missing key sections, populate it with current project commands and conventions.

3. **Run all tests** — Run `cd frontend && npm test`. If any test fails, stop and report the failure. Do not continue to commit.

4. **Build check** — Run `cd frontend && npm run build`. If the build fails, stop and report. Do not continue.

5. **Commit** — Stage all changes and create a git commit. Ask me for the commit message before committing.

6. **Push** — Ask me if I want to push to the remote. Only push if I confirm.
