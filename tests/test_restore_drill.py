"""Restore drill safeguards are unit-tested without Docker or production data."""

from pathlib import Path

from scripts.restore_drill import (
    build_drill_project_name,
    drill_paths_are_isolated,
    restore_report,
    verify_bundle,
    verify_restore_evidence,
)


def test_drill_project_name_is_unique_and_scoped():
    first = build_drill_project_name()
    second = build_drill_project_name()

    assert first.startswith("vidistiller-drill-")
    assert first != second


def test_verifier_requires_account_completed_job_transcript_snapshot_and_export():
    missing = verify_restore_evidence({"users": 1, "completed_jobs": 1, "transcripts": 1, "snapshots": 0, "exports": 1})
    complete = verify_restore_evidence({"users": 1, "completed_jobs": 1, "transcripts": 1, "snapshots": 1, "exports": 1})

    assert missing == ["snapshots"]
    assert complete == []


def test_report_contains_numeric_rpo_rto_and_evidence_counts():
    report = restore_report(
        rpo_seconds=120.5,
        rto_seconds=60.25,
        missing_evidence=[],
        evidence={"users": 1, "completed_jobs": 1, "transcripts": 1, "snapshots": 1, "exports": 1},
    )

    assert report["verdict"] == "PASS"
    assert report["rpo_seconds"] == 120.5
    assert report["rto_seconds"] == 60.25


def test_drill_refuses_production_or_bundle_source_paths(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    work = tmp_path / "work"

    assert drill_paths_are_isolated(bundle, work) is True
    assert drill_paths_are_isolated(bundle, bundle / "nested") is False
    assert drill_paths_are_isolated(bundle, "/opt/vidistiller/drill") is False


def test_verify_bundle_rejects_checksum_corruption(tmp_path):
    from scripts.backup_system import build_manifest

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "database.dump").write_bytes(b"before")
    (bundle / "manifest.json").write_text(
        __import__("json").dumps(build_manifest(bundle)), encoding="utf-8"
    )
    (bundle / "database.dump").write_bytes(b"after")

    assert verify_bundle(bundle) == ["checksum mismatch: database.dump"]


def test_sample_runner_verifies_images_before_running_them():
    """The drill must fail closed unless its container images are signed."""
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "restore_drill_sample.sh"
    ).read_text(encoding="utf-8")

    assert 'require_command "cosign"' in script
    assert 'cosign verify --certificate-identity-regexp "$identity"' in script


def test_scheduled_backup_and_restore_use_a_signed_common_bundle_contract():
    root = Path(__file__).resolve().parents[1]
    backup = (root / "scripts" / "backup_to_nas.sh").read_text(encoding="utf-8")
    restore = (root / "scripts" / "restore_drill_sample.sh").read_text(encoding="utf-8")

    assert 'cosign sign-blob --yes --key "$BACKUP_SIGNING_KEY"' in backup
    assert '--bundle "${staging}/SHA256SUMS.bundle"' in backup
    assert 'touch "${staging}/.verified"' in backup
    assert 'cosign verify-blob --key "$BACKUP_SIGNING_PUBLIC_KEY"' in restore
    assert '"$BACKUP_BUNDLE/SHA256SUMS.bundle"' in restore
    assert "VERIFY_CHECKSUMS" not in restore
    assert 'require_digest_reference "$POSTGRES_IMAGE"' in restore
    assert 'require_digest_reference "$BACKEND_IMAGE"' in restore
    assert 'tar -C app-data' in backup
    assert '"${staging}/app-data.tar"' in backup
    assert 'tar -C "$work/app-data" -xf "$BACKUP_BUNDLE/app-data.tar"' in restore


def test_postgres_restore_image_mirror_is_immutable_and_oidc_signed():
    """The restore image must have CI provenance, not an operator-created tag."""
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "publish-postgres-mirror.yml"
    ).read_text(encoding="utf-8")

    assert "postgres@sha256:" in workflow
    assert "${{ vars.DOCKER_IMAGE_NAMESPACE }}/vidistiller-postgres" in workflow
    assert "id-token: write" in workflow
    assert 'cosign sign --yes "${target}@${digest}"' in workflow
    assert 'cosign verify --certificate-identity-regexp' in workflow
