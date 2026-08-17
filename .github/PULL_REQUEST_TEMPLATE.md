## What

<!-- What does this PR change? One or two sentences. -->

## Why

<!-- The problem this solves or the reason for the change. -->

## How

<!-- Key implementation notes a reviewer needs. -->

## Security review

<!-- Delete rows that genuinely do not apply. Do not leave a row unchecked
     and unexplained: an unchecked box blocks review. -->

- [ ] **No secrets added** — no keys, tokens, passwords, DSNs, or private hosts
      in code, tests, fixtures, comments, or committed config. New config is
      read from the environment and documented in `.env.example` with an empty
      or placeholder value.
- [ ] **No real infrastructure disclosed** — no internal IPs, hostnames, or
      LAN topology. Example/registry files use RFC 5737 documentation ranges
      (`192.0.2.0/24`).
- [ ] **Authorization checked at every new entry point** — new routes declare
      an auth dependency; ownership is enforced in the query `WHERE` clause,
      not after the fetch. Operator-only surfaces use `require_operator` and
      fail closed.
- [ ] **New API responses are allowlisted** — response models enumerate fields
      explicitly. No source URLs, transcripts, filesystem paths, raw error
      strings, claim tokens, or credentials leak into a DTO.
- [ ] **Untrusted input is validated** — user-supplied URLs, ids, and filenames
      are validated against an allowlist or strict pattern before use. No
      user-controlled value reaches an outbound request target (SSRF), a shell
      command, a path join, or raw SQL.
- [ ] **Dependencies** — any added dependency is justified in *Why*, pinned,
      and free of known CVEs (`pip-audit`, `npm audit`).
- [ ] **Workflow changes** — any `.github/workflows/` edit keeps the least
      privilege `permissions:` block, keeps actions SHA-pinned, and does **not**
      expose the self-hosted runner to fork-triggered events
      (`pull_request`, `pull_request_target`, `issue_comment`).
- [ ] **Migrations are additive and reversible** — downgrade rehearsed; no
      destructive change without a backup step called out in *Deployment*.

<!-- If this PR touches auth, crypto, file serving, job admission, the LLM
     sidecar registry, or CI/CD, say so here and describe the threat you
     considered. -->

Security-sensitive areas touched:

## Testing

<!-- Commands run and their results. Include new/updated tests. -->

- [ ] Backend tests pass (`PYTHONPATH=backend .venv/bin/python -m pytest tests/ -q`)
- [ ] Frontend tests pass (`cd frontend && npx vitest run`)
- [ ] A regression test covers each bug or vulnerability fixed here

## Deployment

<!-- New env vars, migrations, or manual steps. "None" is a valid answer. -->

- New env vars (added to `.env.example`):
- Migrations:
- Manual steps / rollback notes:

## Version

<!-- feat -> minor, fix/security/chore -> patch, BREAKING CHANGE -> major.
     Confirm pyproject.toml / package.json bumped and CHANGELOG.md has an entry. -->

- Version bump:
- CHANGELOG updated: [ ]
