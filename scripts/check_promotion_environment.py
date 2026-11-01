#!/usr/bin/env python3
"""Fail closed unless production has valid required reviewers and an explicit self-review policy."""

import argparse
import json
import re
import subprocess
import sys
from typing import Any

REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class EnvironmentCheckError(Exception):
    """A safe-to-report environment approval configuration failure."""


def _eligible_reviewer(entry: Any) -> bool:
    if not isinstance(entry, dict) or entry.get("type") not in {"User", "Team"}:
        return False
    reviewer = entry.get("reviewer")
    if not isinstance(reviewer, dict):
        return False
    reviewer_id = reviewer.get("id")
    if (
        isinstance(reviewer_id, bool)
        or not isinstance(reviewer_id, int)
        or reviewer_id <= 0
    ):
        return False
    identity = (
        reviewer.get("login") if entry["type"] == "User" else reviewer.get("slug")
    )
    return isinstance(identity, str) and bool(identity.strip())


def validate_environment(payload: Any, environment: str) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
        raise EnvironmentCheckError("GitHub returned a malformed environment response")
    if payload["name"].casefold() != environment.casefold():
        raise EnvironmentCheckError(
            "GitHub returned an unexpected deployment environment"
        )
    rules = payload.get("protection_rules")
    if not isinstance(rules, list):
        raise EnvironmentCheckError(
            "production environment protection rules are missing or malformed"
        )
    reviewer_rules = [
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
    ]
    if not reviewer_rules:
        raise EnvironmentCheckError(
            "production environment has no required reviewers rule"
        )
    for rule in reviewer_rules:
        reviewers = rule.get("reviewers")
        if not isinstance(rule.get("prevent_self_review"), bool):
            continue
        if not isinstance(reviewers, list) or not 1 <= len(reviewers) <= 6:
            continue
        if all(_eligible_reviewer(reviewer) for reviewer in reviewers):
            return
    raise EnvironmentCheckError(
        "production environment reviewer configuration is absent, invalid, or malformed"
    )


def fetch_environment(repository: str, environment: str) -> dict[str, Any]:
    if not REPOSITORY_PATTERN.fullmatch(repository) or environment != "production":
        raise EnvironmentCheckError("repository or environment name is invalid")
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                f"repos/{repository}/environments/{environment}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise EnvironmentCheckError("GitHub environment lookup timed out") from exc
    except OSError as exc:
        raise EnvironmentCheckError("GitHub CLI could not be started") from exc
    if result.returncode != 0:
        raise EnvironmentCheckError("GitHub environment configuration is inaccessible")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise EnvironmentCheckError(
            "GitHub returned malformed environment JSON"
        ) from exc
    validate_environment(payload, environment)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--environment", required=True)
    args = parser.parse_args()
    try:
        fetch_environment(args.repository, args.environment)
    except EnvironmentCheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "OK: production environment has eligible reviewers and an explicit self-review policy"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
