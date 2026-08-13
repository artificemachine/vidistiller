"""Backup bundle integrity and retention are filesystem-only unit tests."""

import json

from scripts.backup_system import apply_retention, build_manifest, verify_manifest


def test_manifest_covers_database_data_and_safe_configuration(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "app-data").mkdir(parents=True)
    (bundle / "config").mkdir()
    (bundle / "config" / "config").mkdir()
    (bundle / "database.dump").write_bytes(b"database")
    (bundle / "app-data" / "frame.jpg").write_bytes(b"image")
    (bundle / "config" / "docker-compose.prod.yml").write_text("services: {}")
    (bundle / "config" / "config" / "llm_model_profiles.json").write_text('{"profiles": []}')

    manifest = build_manifest(bundle, created_at="2026-08-12T10:00:00+00:00")

    assert manifest["format_version"] == 1
    assert {entry["path"] for entry in manifest["files"]} == {
        "config/config/llm_model_profiles.json",
        "config/docker-compose.prod.yml",
        "app-data/frame.jpg",
        "database.dump",
    }
    assert verify_manifest(bundle, manifest) == []


def test_bad_checksum_is_reported(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    target = bundle / "database.dump"
    target.write_bytes(b"before")
    manifest = build_manifest(bundle, created_at="2026-08-12T10:00:00+00:00")
    target.write_bytes(b"after")

    assert verify_manifest(bundle, manifest) == ["checksum mismatch: database.dump"]


def test_retention_only_removes_recognised_complete_bundles(tmp_path):
    old = tmp_path / "vidistiller-backup-20260101T000000Z"
    new = tmp_path / "vidistiller-backup-20260102T000000Z"
    unrelated = tmp_path / "important-data"
    for path in (old, new, unrelated):
        path.mkdir()
    (old / "manifest.json").write_text("{}")
    (new / "manifest.json").write_text("{}")

    removed = apply_retention(tmp_path, keep=1)

    assert removed == [old]
    assert new.exists()
    assert unrelated.exists()
