import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SECURITY_WORKFLOW = ROOT / ".github/workflows/security.yml"
TEST_WORKFLOW = ROOT / ".github/workflows/test.yml"


def _workflow(path):
    return yaml.safe_load(path.read_text())


def _steps():
    return _workflow(SECURITY_WORKFLOW)["jobs"]["security"]["steps"]


def test_frontend_audit_gate_uses_pinned_node22_and_fails_closed():
    security = _workflow(SECURITY_WORKFLOW)
    tests = _workflow(TEST_WORKFLOW)
    security_steps = security["jobs"]["security"]["steps"]
    test_steps = tests["jobs"]["frontend-tests"]["steps"]
    security_node = next(
        step for step in security_steps if "setup-node" in step.get("uses", "")
    )
    test_node = next(
        step for step in test_steps if "setup-node" in step.get("uses", "")
    )
    assert security_node["uses"] == test_node["uses"]
    assert security_node["with"]["node-version"] == "22"
    assert test_node["with"]["node-version"] == "22"

    install = next(
        step
        for step in security_steps
        if step.get("name") == "Install frontend dependencies for audit"
    )
    audit = next(
        step
        for step in security_steps
        if step.get("name") == "Audit frontend dependencies"
    )
    assert install["working-directory"] == "frontend"
    assert install["run"] == "npm ci --ignore-scripts"
    assert audit["working-directory"] == "frontend"
    assert audit["run"] == "npm audit --audit-level=high"
    assert audit.get("continue-on-error", False) is not True
    assert "|| true" not in audit["run"]


def test_audit_failure_propagates_from_extracted_step(tmp_path):
    install = next(
        step
        for step in _steps()
        if step.get("name") == "Install frontend dependencies for audit"
    )
    audit = next(
        step for step in _steps() if step.get("name") == "Audit frontend dependencies"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "npm-calls"
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "args=sys.argv[1:]\n"
        "print(' '.join(args), file=open(os.environ['CALL_LOG'],'a'))\n"
        "sys.exit(1 if args[:2] == ['audit','--audit-level=high'] else 0)\n"
    )
    npm.chmod(0o755)
    env = os.environ | {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "CALL_LOG": str(log),
    }
    for step in (install, audit):
        result = subprocess.run(
            ["bash", "-e", "-c", step["run"]],
            cwd=ROOT / step["working-directory"],
            env=env,
            capture_output=True,
            text=True,
        )
        if step is audit:
            assert result.returncode != 0
        else:
            assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        "ci --ignore-scripts",
        "audit --audit-level=high",
    ]
