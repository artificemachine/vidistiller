#!/usr/bin/env python3
"""Preflight utilities for an isolated, evidence-producing restore drill.

The operational runner must pass a downloaded bundle directory. This module
never accepts production data paths as a deletion target; Docker orchestration
is deliberately left to a reviewed deployment command using the generated
project name and temporary paths.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from scripts.backup_system import verify_manifest


REQUIRED_EVIDENCE = ("users", "completed_jobs", "transcripts", "snapshots", "exports")
PRODUCTION_ROOT = Path("/opt/vidistiller")


def build_drill_project_name() -> str:
    """Return a compose project name that cannot collide with production."""
    return f"vidistiller-drill-{uuid.uuid4().hex[:12]}"


def verify_bundle(bundle_dir: Path) -> list[str]:
    """Validate a downloaded bundle before any restore command can be issued."""
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.is_file():
        return ["missing manifest.json"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["invalid manifest.json"]
    return verify_manifest(bundle_dir, manifest)


def drill_paths_are_isolated(bundle_dir: Path | str, work_dir: Path | str) -> bool:
    """Ensure the drill work directory cannot be production or the source bundle."""
    bundle = Path(bundle_dir).resolve()
    work = Path(work_dir).resolve()
    try:
        work.relative_to(bundle)
        return False
    except ValueError:
        pass
    try:
        work.relative_to(PRODUCTION_ROOT)
        return False
    except ValueError:
        return True


def verify_restore_evidence(evidence: dict[str, int]) -> list[str]:
    """Require at least one restored instance of every recovery invariant."""
    return [name for name in REQUIRED_EVIDENCE if evidence.get(name, 0) < 1]


def restore_report(
    *,
    rpo_seconds: float,
    rto_seconds: float,
    missing_evidence: list[str],
    evidence: dict[str, int],
) -> dict[str, Any]:
    """Produce a machine-readable drill verdict with measured recovery data."""
    return {
        "format_version": 1,
        "verdict": "PASS" if not missing_evidence else "FAIL",
        "rpo_seconds": float(rpo_seconds),
        "rto_seconds": float(rto_seconds),
        "evidence": evidence,
        "missing_evidence": missing_evidence,
    }
