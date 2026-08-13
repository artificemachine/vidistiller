#!/usr/bin/env python3
"""Create a verified Vidistiller backup bundle and copy it off-machine.

The command is intentionally explicit: it never reads a production .env,
never deletes input data, and requires an rclone destination for an actual
backup. Its pure manifest helpers are shared with the restore drill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SAFE_CONFIG_FILES = ("docker-compose.prod.yml", ".env.example", "alembic.ini")
SAFE_CONFIG_PATHS = ("config/llm_model_profiles.json",)
BUNDLE_PREFIX = "vidistiller-backup-"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(bundle_dir: Path, *, created_at: str | None = None) -> dict[str, Any]:
    """Generate checksums for every bundle payload file, excluding its manifest."""
    files = []
    for path in sorted(bundle_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append({
                "path": path.relative_to(bundle_dir).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            })
    return {
        "format_version": 1,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "files": files,
    }


def verify_manifest(bundle_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """Return every missing or corrupted payload; an empty list is success."""
    errors: list[str] = []
    for entry in manifest.get("files", []):
        relative = entry.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            errors.append("invalid manifest path")
            continue
        target = bundle_dir / relative
        if not target.is_file():
            errors.append(f"missing: {relative}")
        elif sha256_file(target) != entry.get("sha256"):
            errors.append(f"checksum mismatch: {relative}")
    return errors


def apply_retention(output_dir: Path, *, keep: int) -> list[Path]:
    """Remove only older, complete bundles inside the explicit output directory."""
    if keep < 1:
        raise ValueError("keep must be at least one")
    candidates = sorted(
        (
            path for path in output_dir.iterdir()
            if path.is_dir() and path.name.startswith(BUNDLE_PREFIX) and (path / "manifest.json").is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    removed = candidates[keep:]
    for bundle in removed:
        shutil.rmtree(bundle)
    return removed


def create_backup(
    *,
    output_dir: Path,
    data_dir: Path,
    database_url: str,
    project_root: Path,
    rclone_destination: str,
    keep: int,
    signing_key: Path,
    signing_password_file: Path,
) -> Path:
    """Create DB + data + non-secret config, verify it, then copy it off-machine."""
    if not rclone_destination:
        raise ValueError("an rclone destination is required for an off-machine backup")
    if not data_dir.is_dir():
        raise ValueError(f"data directory does not exist: {data_dir}")
    if not signing_key.is_file() or not signing_password_file.is_file():
        raise ValueError("a readable backup signing key and password file are required")
    output_dir.mkdir(parents=True, exist_ok=True)
    name = BUNDLE_PREFIX + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle = output_dir / name
    if bundle.exists():
        raise FileExistsError(bundle)
    bundle.mkdir()
    try:
        subprocess.run(
            ["pg_dump", "--format=custom", "--file", str(bundle / "database.dump"), database_url],
            check=True,
        )
        shutil.copytree(data_dir, bundle / "app-data")
        config_dir = bundle / "config"
        config_dir.mkdir()
        for filename in SAFE_CONFIG_FILES:
            source = project_root / filename
            if source.is_file():
                shutil.copy2(source, config_dir / filename)
        for relative_path in SAFE_CONFIG_PATHS:
            source = project_root / relative_path
            if source.is_file():
                destination = config_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        migrations = project_root / "migrations"
        if migrations.is_dir():
            shutil.copytree(migrations, config_dir / "migrations")
        manifest = build_manifest(bundle)
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        problems = verify_manifest(bundle, manifest)
        if problems:
            raise RuntimeError("bundle checksum verification failed: " + "; ".join(problems))
        checksum_file = bundle / "SHA256SUMS"
        checksum_file.write_text(
            "".join(
                f"{entry['sha256']}  {entry['path']}\n" for entry in build_manifest(bundle)["files"]
            ),
            encoding="utf-8",
        )
        signing_env = os.environ | {
            "COSIGN_PASSWORD": signing_password_file.read_text(encoding="utf-8").strip()
        }
        subprocess.run(
            [
                "cosign",
                "sign-blob",
                "--yes",
                "--key",
                str(signing_key),
                "--output-signature",
                str(bundle / "SHA256SUMS.sig"),
                str(checksum_file),
            ],
            check=True,
            env=signing_env,
        )
        (bundle / ".verified").touch()
        subprocess.run(["rclone", "copy", str(bundle), f"{rclone_destination.rstrip('/')}/{bundle.name}"], check=True)
        apply_retention(output_dir, keep=keep)
        return bundle
    except Exception:
        # A partial local bundle is never a valid recovery point.
        if bundle.exists():
            shutil.rmtree(bundle)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--database-url", required=True, help="PostgreSQL URL; never write it to the bundle")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--rclone-destination", required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--signing-password-file", type=Path, required=True)
    parser.add_argument("--keep", type=int, default=7)
    args = parser.parse_args()
    bundle = create_backup(**vars(args))
    print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
