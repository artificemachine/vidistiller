import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RANGE_SCRIPT = ROOT / "scripts/gitleaks_range.py"
WORKFLOW = ROOT / ".github/workflows/gitleaks.yml"
FIXTURE_MARKER = "test_marker_fixture_abcdef0123456789"


def _gitleaks_binary() -> str:
    binary = os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")
    if not binary:
        pytest.skip(
            "Gitleaks integration needs the pinned 8.27.2 binary; "
            "the Gitleaks workflow runs these tests after installing it"
        )
    version = subprocess.run(
        [binary, "version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert version == "8.27.2", f"expected Gitleaks 8.27.2, got {version!r}"
    return binary


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _create_commit(repo: Path, message: str, parent: str | None = None) -> str:
    tree = _git(repo, "write-tree")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Synthetic Test",
        "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
        "GIT_COMMITTER_NAME": "Synthetic Test",
        "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
    }
    command = ["git", "-C", str(repo), "commit-tree", tree]
    if parent:
        command.extend(["-p", parent])
    command.extend(["-m", message])
    result = subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    commit = result.stdout.strip()
    _git(repo, "update-ref", "HEAD", commit)
    return commit


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "synthetic-repository"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "checkout", "--quiet", "-b", "test/synthetic")
    (repo / "README.md").write_text("Synthetic repository for Gitleaks tests.\n")
    (repo / ".gitleaks.toml").write_text(
        "[[rules]]\n"
        'id = "fixture-marker"\n'
        'description = "Synthetic fixture marker"\n'
        'regex = "test_marker_fixture_[a-f0-9]{16}"\n'
        'keywords = ["test_marker_fixture_"]\n'
    )
    _git(repo, "add", "README.md", ".gitleaks.toml")
    baseline = _create_commit(repo, "baseline")
    return repo, baseline


def _event_range(
    repo: Path,
    event_name: str,
    before: str,
    after: str,
    base_ref: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RANGE_SCRIPT),
            "--event-name",
            event_name,
            "--before",
            before,
            "--after",
            after,
            "--base-ref",
            base_ref,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def _add_and_remove_marker(repo: Path) -> tuple[str, str]:
    (repo / "history.txt").write_text(f"FIXTURE_MARKER={FIXTURE_MARKER}\n")
    _git(repo, "add", "history.txt")
    parent = _git(repo, "rev-parse", "HEAD")
    introduced = _create_commit(repo, "introduce synthetic marker", parent)
    (repo / "history.txt").unlink()
    _git(repo, "add", "-A")
    after = _create_commit(repo, "remove synthetic marker", introduced)
    return introduced, after


def _scan_history(repo: Path, log_options: str) -> subprocess.CompletedProcess[str]:
    binary = _gitleaks_binary()
    return subprocess.run(
        [
            binary,
            "git",
            "--no-banner",
            "--redact",
            "--config",
            str(repo / ".gitleaks.toml"),
            "--log-opts",
            log_options,
            str(repo),
        ],
        capture_output=True,
        text=True,
    )


def test_secret_in_first_pushed_commit_is_detected(tmp_path: Path) -> None:
    repo, before = _repository(tmp_path)
    _introduced, after = _add_and_remove_marker(repo)
    result = _event_range(repo, "push", before, after)
    assert result.returncode == 0, result.stderr

    scan = _scan_history(repo, result.stdout.strip())
    assert scan.returncode == 1, scan.stdout + scan.stderr


def test_first_push_scans_all_history_reachable_from_after(tmp_path: Path) -> None:
    repo, _baseline = _repository(tmp_path)
    _introduced, after = _add_and_remove_marker(repo)
    result = _event_range(repo, "push", "0" * 40, after)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == after

    scan = _scan_history(repo, result.stdout.strip())
    assert scan.returncode == 1, scan.stdout + scan.stderr


def test_missing_nonzero_before_commit_fails_explicitly(tmp_path: Path) -> None:
    repo, _baseline = _repository(tmp_path)
    after = _git(repo, "rev-parse", "HEAD")
    missing = "a" * 40

    result = _event_range(repo, "push", missing, after)

    assert result.returncode != 0
    assert "before" in result.stderr.lower()
    assert re.search(r"[0-9a-f]{40}", result.stderr)


def test_push_commit_ids_are_validated(tmp_path: Path) -> None:
    repo, _baseline = _repository(tmp_path)
    result = _event_range(repo, "push", "not-a-sha", "b" * 40)

    assert result.returncode != 0
    assert "40-character hexadecimal" in result.stderr


def test_push_after_commit_id_is_validated(tmp_path: Path) -> None:
    repo, before = _repository(tmp_path)
    result = _event_range(repo, "push", before, "not-a-sha")

    assert result.returncode != 0
    assert "after must be a 40-character hexadecimal" in result.stderr


def test_pull_request_keeps_base_to_head_range(tmp_path: Path) -> None:
    repo, base = _repository(tmp_path)
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    (repo / "change.txt").write_text("change\n")
    _git(repo, "add", "change.txt")
    after = _create_commit(repo, "PR change", base)

    result = _event_range(repo, "pull_request", "", after, "main")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "origin/main..HEAD"


def test_workflow_passes_event_values_through_environment() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["scan"]["steps"]
    run_step = steps[-1]
    run = run_step["run"]
    environment = run_step["env"]

    assert {
        "GITLEAKS_EVENT",
        "GITLEAKS_BEFORE",
        "GITLEAKS_AFTER",
        "GITLEAKS_BASE_REF",
    } <= set(environment)
    assert "scripts/gitleaks_range.py" in run
    assert "--log-opts" in run
    assert "${{" not in run


def test_workflow_runs_scanner_integration_suite_with_pinned_binary() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["scan"]["steps"]
    test_step = next(
        step for step in steps if step.get("name") == "Test Gitleaks range"
    )

    assert test_step["env"]["GITLEAKS_BIN"] == "/usr/local/bin/gitleaks"
    assert test_step["run"] == (
        "python -m pytest --confcutdir=tests/ci " "tests/ci/test_gitleaks_range.py -q"
    )
