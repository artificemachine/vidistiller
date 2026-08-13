"""Unit-level contract checks for signed backup artifacts."""

from scripts.backup_system import build_manifest, verify_manifest


def test_manifest_rejects_a_path_outside_its_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "database.dump").write_bytes(b"database")

    manifest = build_manifest(bundle)
    manifest["files"].append({"path": "../outside", "sha256": "x"})

    assert verify_manifest(bundle, manifest) == ["invalid manifest path"]
