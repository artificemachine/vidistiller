"""Release-candidate manifest contract tests.

Drives scripts/release_candidate.py (create/verify) and the manifest schema
that binds one candidate build to a single immutable identity: a full 40-char
commit SHA, two signed OCI digest refs (backend + frontend), config and
migration identity equal to that commit, the build run ID, and an artifact
attestation reference. Nothing else may deploy: promotion consumes only
manifests that pass this validation.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "release_candidate.py"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "release-candidate-valid.json"

VALID_MANIFEST = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

DELETE = object()

VALID_COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40
VALID_DIGEST_TAIL = "c" * 64


@pytest.fixture(scope="module")
def rc():
    if not SCRIPT_PATH.exists():
        pytest.fail(f"missing implementation: {SCRIPT_PATH} does not exist")
    spec = importlib.util.spec_from_file_location(
        "release_candidate_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mutate(path, value):
    """Copy of the valid manifest with dotted `path` replaced (DELETE removes)."""
    manifest = json.loads(json.dumps(VALID_MANIFEST))
    keys = path.split(".")
    target = manifest
    for key in keys[:-1]:
        target = target[key]
    if value is DELETE:
        del target[keys[-1]]
    else:
        target[keys[-1]] = value
    return manifest


def _has_error(errors, needle):
    return any(needle in error.lower() for error in errors)


# ── Core identity rules ──────────────────────────────────────────────────────


def test_manifest_rejects_short_commit_or_mutable_image_tag(rc):
    for bad_commit in ("abc1234", "a" * 39, "a" * 41, "A" * 40, "g" * 40):
        errors = rc.validate_manifest(_mutate("commit_sha", bad_commit))
        assert errors, f"commit_sha={bad_commit!r} must be rejected"

    bad_refs = (
        "example-org/vidistiller-backend:main",
        "example-org/vidistiller-backend",
        f"example-org/vidistiller-backend:latest@sha256:{VALID_DIGEST_TAIL}",
        f"example-org/vidistiller-backend@sha256:{VALID_DIGEST_TAIL.upper()}",
        f"example-org/vidistiller-backend@sha256:{'c' * 63}",
    )
    for bad_ref in bad_refs:
        for field in ("images.backend", "images.frontend"):
            errors = rc.validate_manifest(_mutate(field, bad_ref))
            assert errors, f"{field}={bad_ref!r} must be rejected"


def test_manifest_binds_both_images_and_config_to_one_commit(rc):
    assert rc.validate_manifest(json.loads(json.dumps(VALID_MANIFEST))) == []

    for path in ("config.compose", "config.alembic", "config.migrations_tree"):
        errors = rc.validate_manifest(_mutate(path, OTHER_COMMIT))
        assert errors, f"{path} must equal the candidate commit"
        assert _has_error(errors, "commit"), f"{path} error must mention the commit"

    for path in ("images.backend", "images.frontend"):
        errors = rc.validate_manifest(_mutate(path, DELETE))
        assert errors, f"{path} is required"

    for path in ("config.compose", "config.alembic", "config.migrations_tree"):
        errors = rc.validate_manifest(_mutate(path, DELETE))
        assert errors, f"{path} is required"

    # Moving the commit while leaving config pinned to the old one breaks the
    # one-commit binding and must be rejected.
    errors = rc.validate_manifest(_mutate("commit_sha", VALID_COMMIT))
    assert errors, "config fields pinned to the previous commit must be rejected"


def test_manifest_requires_run_id_and_artifact_attestation_reference(rc):
    for path in ("build.run_id", "build.attestation_uri"):
        for bad in (DELETE, "", "   \t "):
            errors = rc.validate_manifest(_mutate(path, bad))
            assert errors, f"{path}={bad!r} must be rejected as an unverifiable build identity"


# ── Malformed manifests (parametrized) ──────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        [],  # not an object
        {},
        {"schema_version": 1},  # nothing else
        dict(VALID_MANIFEST, schema_version=0),  # unknown schema version
        dict(VALID_MANIFEST, schema_version="1"),  # version must be an int
        dict(VALID_MANIFEST, schema_version=2),  # future version: not understood here
        dict(VALID_MANIFEST, images={"backend": "x"}),  # frontend missing
    ],
)
def test_malformed_manifest_rejected(rc, payload):
    errors = rc.validate_manifest(payload)
    assert errors, f"malformed manifest must be rejected: {payload!r}"


# ── CLI behavior ─────────────────────────────────────────────────────────────


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_cli_help_exits_zero():
    proc = _run_cli("--help")
    assert proc.returncode == 0, proc.stderr


def test_cli_verify_fixture_exits_zero():
    proc = _run_cli("verify", str(FIXTURE_PATH))
    assert proc.returncode == 0, proc.stderr


def test_cli_verify_rejects_tampered_manifest(tmp_path):
    tampered = _mutate("images.backend", "example-org/vidistiller-backend:main")
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    proc = _run_cli("verify", str(path))
    assert proc.returncode != 0
    assert proc.stderr.strip(), "rejection reason must go to stderr"


def test_cli_verify_rejects_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    proc = _run_cli("verify", str(path))
    assert proc.returncode != 0


def test_cli_create_then_verify_roundtrip(tmp_path):
    out = tmp_path / "candidate-manifest.json"
    digest = "sha256:" + "d" * 64
    proc = _run_cli(
        "create",
        "--commit", VALID_COMMIT,
        "--backend-ref", f"example-org/vidistiller-backend@{digest}",
        "--frontend-ref", f"example-org/vidistiller-frontend@{digest}",
        "--run-id", "123456789",
        "--attestation-uri", f"example-org/vidistiller-backend@{digest}",
        "--output", str(out),
    )
    assert proc.returncode == 0, proc.stderr
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["schema_version"] == 1
    assert written["commit_sha"] == VALID_COMMIT
    assert written["config"]["compose"] == VALID_COMMIT
    assert written["config"]["alembic"] == VALID_COMMIT
    assert written["config"]["migrations_tree"] == VALID_COMMIT

    assert _run_cli("verify", str(out)).returncode == 0
    mismatch = _run_cli("verify", str(out), "--expect-commit", OTHER_COMMIT)
    assert mismatch.returncode != 0


def test_cli_create_rejects_bad_identity(tmp_path):
    out = tmp_path / "nope.json"
    digest = "sha256:" + "d" * 64
    proc = _run_cli(
        "create",
        "--commit", "abc1234",
        "--backend-ref", f"example-org/vidistiller-backend@{digest}",
        "--frontend-ref", f"example-org/vidistiller-frontend@{digest}",
        "--run-id", "1",
        "--attestation-uri", f"example-org/vidistiller-backend@{digest}",
        "--output", str(out),
    )
    assert proc.returncode != 0
    assert not out.exists(), "invalid input must not produce a manifest file"
