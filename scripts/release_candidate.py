#!/usr/bin/env python3
"""Create and verify release-candidate manifests.

A candidate manifest binds one release candidate to a single immutable
identity so that promotion can consume exactly what was built and signed:

- the full 40-character commit SHA the images were built from,
- backend and frontend OCI references pinned by digest (name@sha256:...),
- config and migration identity (compose, alembic, migrations tree) equal
  to that same commit,
- the CI build run ID, and
- an artifact attestation reference for the signed provenance.

Nothing may be promoted or deployed from a manifest that fails
`validate_manifest`; the workflows in .github/workflows call this script's
`verify` subcommand before any retag or container restart.

Manifest schema (schema_version 1)::

    {
      "schema_version": 1,
      "commit_sha": "<40-hex>",
      "images": {
        "backend": "<name>@sha256:<64-hex>",
        "frontend": "<name>@sha256:<64-hex>"
      },
      "config": {
        "compose": "<same 40-hex commit>",
        "alembic": "<same 40-hex commit>",
        "migrations_tree": "<same 40-hex commit>"
      },
      "build": {
        "run_id": "<non-empty run identifier>",
        "attestation_uri": "<non-empty reference, no whitespace>"
      }
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, List, Optional

SCHEMA_VERSION = 1

COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

IMAGE_FIELDS = ("backend", "frontend")
CONFIG_FIELDS = ("compose", "alembic", "migrations_tree")


class ManifestError(ValueError):
    """Raised when a manifest cannot be loaded or built."""


# ── Validation helpers ───────────────────────────────────────────────────────


def _require_object(value: Any, field: str, errors: List[str]) -> dict:
    if not isinstance(value, dict):
        errors.append(f"{field}: expected a JSON object, got {type(value).__name__}")
        return {}
    return value


def _validate_commit_sha(value: Any, field: str, errors: List[str]) -> Optional[str]:
    if not isinstance(value, str) or not COMMIT_SHA_PATTERN.fullmatch(value):
        errors.append(
            f"{field}: must be a full 40-character lowercase hex commit SHA"
        )
        return None
    return value


def _validate_digest_ref(value: Any, field: str, errors: List[str]) -> Optional[str]:
    """Accept only immutable digest references (name@sha256:<64-hex>).

    Mutable forms are rejected: bare tags (name:tag), bare names, tagged
    digest refs (name:tag@sha256:...), and uppercase/short digests. A single
    colon followed by digits before the first slash is allowed (registry
    host:port).
    """
    if not isinstance(value, str) or not value:
        errors.append(
            f"{field}: must be an immutable image reference of the form "
            "name@sha256:<digest>"
        )
        return None
    name, sep, digest = value.rpartition("@")
    if not sep or not name or not DIGEST_PATTERN.fullmatch(digest):
        errors.append(
            f"{field}: {value!r} is not an immutable digest reference "
            "(name@sha256:<digest>)"
        )
        return None
    if ":" in name:
        port_and_path = name.split(":", 1)[1]
        port = port_and_path.split("/", 1)[0]
        if not port.isdigit():
            errors.append(
                f"{field}: {value!r} carries a mutable tag; "
                "use name@sha256:<digest>"
            )
            return None
    return value


def _validate_build_identity(build: dict, errors: List[str]) -> None:
    run_id = build.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        errors.append("build.run_id: must be a non-empty build run identifier")

    attestation = build.get("attestation_uri")
    if (
        not isinstance(attestation, str)
        or not attestation.strip()
        or any(char.isspace() for char in attestation)
    ):
        errors.append(
            "build.attestation_uri: must be a non-empty attestation reference "
            "without whitespace"
        )


# ── Manifest API ─────────────────────────────────────────────────────────────


def validate_manifest(manifest: Any) -> List[str]:
    """Return every identity error found in `manifest`; empty list means valid."""
    if not isinstance(manifest, dict):
        return [
            "manifest: expected a JSON object, got "
            f"{type(manifest).__name__}"
        ]

    errors: List[str] = []

    version = manifest.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        errors.append(f"schema_version: must be the integer {SCHEMA_VERSION}")

    commit = _validate_commit_sha(manifest.get("commit_sha"), "commit_sha", errors)

    images = _require_object(manifest.get("images"), "images", errors)
    for name in IMAGE_FIELDS:
        _validate_digest_ref(images.get(name), f"images.{name}", errors)

    config = _require_object(manifest.get("config"), "config", errors)
    for name in CONFIG_FIELDS:
        sha = _validate_commit_sha(config.get(name), f"config.{name}", errors)
        if sha is not None and commit is not None and sha != commit:
            errors.append(
                f"config.{name}: {sha} does not match the candidate commit {commit}"
            )

    build = _require_object(manifest.get("build"), "build", errors)
    _validate_build_identity(build, errors)

    return errors


def build_manifest(
    commit_sha: str,
    backend_ref: str,
    frontend_ref: str,
    run_id: str,
    attestation_uri: str,
) -> dict:
    """Build a manifest binding every identity field to `commit_sha`."""
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "commit_sha": commit_sha,
        "images": {"backend": backend_ref, "frontend": frontend_ref},
        "config": {name: commit_sha for name in CONFIG_FIELDS},
        "build": {"run_id": run_id, "attestation_uri": attestation_uri},
    }
    errors = validate_manifest(manifest)
    if errors:
        raise ManifestError("; ".join(errors))
    return manifest


def load_manifest(path: str) -> Any:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path}: invalid JSON: {exc}") from exc


# ── CLI ──────────────────────────────────────────────────────────────────────


def cmd_create(args: argparse.Namespace) -> int:
    manifest = build_manifest(
        commit_sha=args.commit,
        backend_ref=args.backend_ref,
        frontend_ref=args.frontend_ref,
        run_id=args.run_id,
        attestation_uri=args.attestation_uri,
    )
    payload = json.dumps(manifest, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    errors = validate_manifest(manifest)
    if args.expect_commit:
        expected = args.expect_commit.strip().lower()
        recorded = manifest.get("commit_sha") if isinstance(manifest, dict) else None
        if recorded != expected:
            errors.append(
                f"commit_sha: {recorded!r} does not match the expected commit {expected}"
            )
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1

    print(f"OK: candidate manifest binds commit {manifest['commit_sha']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and verify release-candidate manifests."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create", help="build and validate a candidate manifest"
    )
    create.add_argument("--commit", required=True, help="full 40-char commit SHA")
    create.add_argument(
        "--backend-ref", required=True, help="backend image ref (name@sha256:...)"
    )
    create.add_argument(
        "--frontend-ref", required=True, help="frontend image ref (name@sha256:...)"
    )
    create.add_argument("--run-id", required=True, help="CI build run ID")
    create.add_argument(
        "--attestation-uri", required=True, help="attestation reference for the build"
    )
    create.add_argument("--output", help="write JSON here instead of stdout")
    create.set_defaults(func=cmd_create)

    verify = subparsers.add_parser("verify", help="validate a candidate manifest")
    verify.add_argument("manifest", help="path to candidate-manifest.json")
    verify.add_argument(
        "--expect-commit",
        help="fail unless the manifest records this exact commit SHA",
    )
    verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ManifestError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
