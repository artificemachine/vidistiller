# Plan — Public history privacy rewrite

Status: prepared only. Do not execute without an explicit maintenance window
and confirmation from every collaborator.

## Scope

Remove from all reachable commits:

- private-network addresses and host identifiers;
- personal paths, handles, and email addresses where not required publicly;
- the encryption-key value formerly present in the environment template.

Use the redacted local Gitleaks report to build a private replacement mapping.
Never add that mapping or any recovered value to this repository.

## Preconditions

1. Rotate the exposed encryption key in every environment that used it. The
   production key was checked on 2026-08-13 and did not match the exposed
   historical value; no user API-key ciphertexts were present there.
2. Notify collaborators that they must re-clone after the rewrite.
3. Create an offline, encrypted backup of the bare repository.
4. Pause merges and record the current branch protections and tags.

## Execution (operator-only)

1. Work from a fresh mirror clone on a private workstation.
2. Run `git filter-repo --replace-text <private-replacements-file>` using only
   the locally generated mapping; replace each sensitive literal with a
   neutral marker.
3. Scan all rewritten refs with Gitleaks and the repository PII scan.
4. Inspect tags, default branch, release artifacts, and CI configuration.
5. Force-push branches and tags only after the scans pass and operators approve.
6. Revoke stale clones, CI caches, release artifacts, and package images that
   still embed the old history.

## Acceptance criteria

- Gitleaks Git scan reports no secrets or private-network findings.
- The PII scan reports no personal paths, handles, or host topology.
- A fresh clone passes the test suites and points to the intended public remote.
- Collaborators have acknowledged the re-clone requirement.
