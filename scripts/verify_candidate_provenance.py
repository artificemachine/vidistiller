#!/usr/bin/env python3
"""Validate Cosign-verified in-toto provenance against a candidate manifest."""

import argparse
import base64
import binascii
import json
import sys
from pathlib import Path
from typing import Any

from release_candidate import ManifestError, load_manifest, validate_manifest

PREDICATE_TYPE = "https://slsa.dev/provenance/v0.2"
IN_TOTO_PAYLOAD_TYPE = "application/vnd.in-toto+json"


def _verified_statements(path: Path) -> list[dict[str, Any]]:
    statements = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read Cosign output {path}: {exc}") from exc
    for number, line in enumerate(lines, 1):
        if not line.lstrip().startswith("{"):
            continue
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: malformed JSON output: {exc}") from exc
        if (
            not isinstance(envelope, dict)
            or envelope.get("payloadType") != IN_TOTO_PAYLOAD_TYPE
        ):
            raise ValueError(f"{path}:{number}: expected an in-toto DSSE envelope")
        encoded = envelope.get("payload")
        if not isinstance(encoded, str):
            raise ValueError(f"{path}:{number}: DSSE payload must be base64 text")
        try:
            payload = base64.b64decode(encoded, validate=True)
            statement = json.loads(payload)
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}:{number}: malformed DSSE payload: {exc}") from exc
        if isinstance(statement, dict):
            statements.append(statement)
    if not statements:
        raise ValueError(
            f"{path}: Cosign output contained no verified in-toto statements"
        )
    return statements


def _subject_name_matches(actual: Any, expected: str) -> bool:
    if actual == expected:
        return True
    aliases = {"docker.io/": "index.docker.io/", "index.docker.io/": "docker.io/"}
    for prefix, alias in aliases.items():
        if expected.startswith(prefix):
            return actual == alias + expected[len(prefix) :]
    first_component = expected.split("/", 1)[0]
    if (
        "/" in expected
        and "." not in first_component
        and ":" not in first_component
        and first_component != "localhost"
    ):
        return actual == "index.docker.io/" + expected
    return False


def _matches(
    statement: dict[str, Any],
    *,
    image_ref: str,
    repository: str,
    commit: str,
    run_id: str,
) -> bool:
    if statement.get("_type") != "https://in-toto.io/Statement/v0.1":
        return False
    if statement.get("predicateType") != PREDICATE_TYPE:
        return False
    name, digest = image_ref.split("@", 1)
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or not any(
        isinstance(subject, dict)
        and _subject_name_matches(subject.get("name"), name)
        and subject.get("digest") == {"sha256": digest.removeprefix("sha256:")}
        for subject in subjects
    ):
        return False
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        return False
    expected_workflow = (
        f"https://github.com/{repository}/.github/workflows/deploy.yml@refs/heads/main"
    )
    if predicate.get("buildType") != expected_workflow:
        return False
    invocation = predicate.get("invocation")
    if not isinstance(invocation, dict):
        return False
    config_source = invocation.get("configSource")
    if config_source != {
        "uri": f"git+https://github.com/{repository}",
        "digest": {"sha1": commit},
        "entryPoint": "deploy.yml",
    }:
        return False
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    builder = predicate.get("builder")
    metadata = predicate.get("metadata")
    return (
        isinstance(builder, dict)
        and builder.get("id") == run_url
        and isinstance(metadata, dict)
        and metadata.get("buildInvocationId") == run_url
    )


def verify(
    manifest: dict[str, Any], repository: str, backend_path: Path, frontend_path: Path
) -> list[str]:
    errors = validate_manifest(manifest)
    if errors:
        return errors
    commit = manifest["commit_sha"]
    run_id = manifest["build"]["run_id"]
    for image_name, path in (("backend", backend_path), ("frontend", frontend_path)):
        try:
            statements = _verified_statements(path)
        except ValueError as exc:
            errors.append(f"{image_name}: {exc}")
            continue
        if not any(
            _matches(
                statement,
                image_ref=manifest["images"][image_name],
                repository=repository,
                commit=commit,
                run_id=run_id,
            )
            for statement in statements
        ):
            errors.append(
                f"{image_name}: no verified provenance matches the manifest image, source commit, repository, and build run"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--backend-attestation", required=True, type=Path)
    parser.add_argument("--frontend-attestation", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = load_manifest(str(args.manifest))
    except ManifestError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    if not isinstance(manifest, dict):
        print("INVALID: candidate manifest must be a JSON object", file=sys.stderr)
        return 1
    errors = verify(
        manifest, args.repository, args.backend_attestation, args.frontend_attestation
    )
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print("OK: verified provenance matches both candidate images and manifest identity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
