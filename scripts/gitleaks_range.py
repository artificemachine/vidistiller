#!/usr/bin/env python3
"""Choose the Git history range Gitleaks scans for the current event."""

import argparse
import re
import subprocess
import sys

ZERO_SHA = "0" * 40


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _require_commit(revision: str, label: str) -> None:
    result = _git("cat-file", "-e", f"{revision}^{{commit}}")
    if result.returncode != 0:
        raise ValueError(f"{label} commit {revision} is not available in the checkout")


def _push_range(before: str, after: str) -> str:
    if before != ZERO_SHA and not re.fullmatch(r"[0-9a-f]{40}", before):
        raise ValueError(
            "before must be the all-zero SHA or a 40-character hexadecimal commit SHA"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", after):
        raise ValueError("after must be a 40-character hexadecimal commit SHA")
    _require_commit(after, "after")
    if before == ZERO_SHA:
        return after
    _require_commit(before, "before")
    return f"{before}..{after}"


def _pull_request_range(base_ref: str) -> str:
    if not base_ref or base_ref.startswith("-"):
        raise ValueError("pull request base ref must be a valid branch name")
    result = _git("check-ref-format", "--branch", base_ref)
    if result.returncode != 0:
        raise ValueError(f"pull request base ref {base_ref!r} is invalid")
    remote_ref = f"origin/{base_ref}"
    result = _git("rev-parse", "--verify", "--quiet", f"{remote_ref}^{{commit}}")
    if result.returncode != 0:
        raise ValueError(
            f"pull request base ref {remote_ref} is not available in the checkout"
        )
    return f"{remote_ref}..HEAD"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--before", default="")
    parser.add_argument("--after", default="")
    parser.add_argument("--base-ref", default="")
    args = parser.parse_args()

    try:
        if args.event_name == "push":
            log_range = _push_range(args.before, args.after)
        elif args.event_name == "pull_request":
            log_range = _pull_request_range(args.base_ref)
        else:
            raise ValueError(f"unsupported event {args.event_name!r}")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(log_range)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
