import importlib.util
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/promote-release.yml"
SCRIPT = ROOT / "scripts/check_promotion_tags.py"
SPEC = importlib.util.spec_from_file_location("check_promotion_tags_under_test", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _run_transaction(
    tmp_path, version="v1.2.3", backend_lookup="missing", frontend_lookup="missing"
):
    workflow = _workflow()
    promote = workflow["jobs"]["promote"]["steps"]
    check = next(
        (
            step
            for step in promote
            if step.get("name") == "Check promotion tags are unused"
        ),
        {"run": ""},
    )
    writes = [
        step
        for step in promote
        if step.get("name") in {"Retag backend digest", "Retag frontend digest"}
    ]
    scripts = "\n".join([check["run"], *(step["run"] for step in writes)])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    docker_stub = bin_dir / "docker"
    docker_stub.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:3] == ['buildx', 'imagetools', 'inspect']:\n"
        "    ref = args[-1]\n"
        "    kind = 'BACKEND_LOOKUP' if 'backend' in ref else 'FRONTEND_LOOKUP'\n"
        "    print('inspect ' + ref, file=open(os.environ['CALL_LOG'], 'a'))\n"
        "    outcome = os.environ[kind]\n"
        "    if outcome == 'missing':\n"
        "        first = ref.split('/', 1)[0]\n"
        "        reported = ref if '.' in first or ':' in first or first == 'localhost' else 'docker.io/' + ref\n"
        "        print('ERROR: ' + reported + ': not found', file=sys.stderr); sys.exit(1)\n"
        "    if outcome == 'proxy_404': print('proxy returned 404 Not Found for its upstream connection', file=sys.stderr); sys.exit(1)\n"
        "    if outcome == 'wrong_ref': print('ERROR: docker.io/other/vidistiller-backend:v1.2.3: not found', file=sys.stderr); sys.exit(1)\n"
        "    if outcome != 'present': print({'unauthorized':'401 Unauthorized','forbidden':'403 Forbidden','transport':'connection reset'}[outcome], file=sys.stderr); sys.exit(1)\n"
        "    sys.exit(0)\n"
        "if args[:3] == ['buildx', 'imagetools', 'create']:\n"
        "    print('write ' + args[args.index('-t') + 1], file=open(os.environ['CALL_LOG'], 'a'))\n"
        "    sys.exit(0)\n"
        "sys.exit(2)\n"
    )
    docker_stub.chmod(0o755)
    env = os.environ | {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "CALL_LOG": str(tmp_path / "calls"),
        "NAMESPACE": "example",
        "BACKEND_REF": "example/vidistiller-backend@sha256:abc",
        "FRONTEND_REF": "example/vidistiller-frontend@sha256:def",
        "PROMOTION_VERSION": version,
        "BACKEND_LOOKUP": backend_lookup,
        "FRONTEND_LOOKUP": frontend_lookup,
    }
    result = subprocess.run(
        ["bash", "-e", "-c", scripts], cwd=ROOT, env=env, capture_output=True, text=True
    )
    calls_path = Path(env["CALL_LOG"])
    return result, calls_path.read_text().splitlines() if calls_path.exists() else []


def test_existing_version_prevents_both_retags(tmp_path):
    result, calls = _run_transaction(tmp_path, backend_lookup="present")
    assert result.returncode != 0
    assert calls and all(call.startswith("inspect ") for call in calls)
    assert not any(call.startswith("write ") for call in calls)


def test_existing_frontend_version_prevents_both_retags(tmp_path):
    result, calls = _run_transaction(tmp_path, frontend_lookup="present")
    assert result.returncode != 0
    assert len([call for call in calls if call.startswith("inspect ")]) == 2
    assert not any(call.startswith("write ") for call in calls)


def test_absent_tags_are_both_checked_before_retags(tmp_path):
    result, calls = _run_transaction(tmp_path)
    assert result.returncode == 0, result.stderr
    assert [call.split()[0] for call in calls] == [
        "inspect",
        "inspect",
        "write",
        "write",
    ]
    assert calls[0].endswith("vidistiller-backend:v1.2.3")
    assert calls[1].endswith("vidistiller-frontend:v1.2.3")


def test_version_containing_auth_status_digits_is_still_confirmed_absent(tmp_path):
    for index, version in enumerate(("v1.2.401", "v1.2.403")):
        result, calls = _run_transaction(tmp_path / str(index), version=version)
        assert result.returncode == 0, result.stderr
        assert [call.split()[0] for call in calls] == [
            "inspect",
            "inspect",
            "write",
            "write",
        ]


def test_only_stable_semver_without_leading_zeroes_is_accepted(tmp_path):
    versions = (
        "v1.2.3-rc.1",
        "v01.2.3",
        "v1.02.3",
        "v1.2.03",
        "1.2.3",
        "v1.2",
        "v1.2.3+build",
        "v1.2.3\ninvalid",
    )
    for index, version in enumerate(versions):
        result, calls = _run_transaction(tmp_path / str(index), version=version)
        assert result.returncode != 0, version
        assert not any(call.startswith("write ") for call in calls)


def test_version_is_passed_as_data_not_shell(tmp_path):
    marker = tmp_path / "executed"
    result, calls = _run_transaction(
        tmp_path / "injection", version=f"v1.2.3$(touch {marker})"
    )
    assert result.returncode != 0
    assert not marker.exists()
    assert not any(call.startswith("write ") for call in calls)


def test_registry_auth_and_transport_failures_are_not_missing_tags(tmp_path):
    for outcome in ("unauthorized", "forbidden", "transport", "proxy_404"):
        result, calls = _run_transaction(tmp_path / outcome, frontend_lookup=outcome)
        assert result.returncode != 0, outcome
        assert not any(call.startswith("write ") for call in calls)
        assert "401 Unauthorized" not in result.stderr
        assert "403 Forbidden" not in result.stderr


def test_not_found_must_match_exact_canonical_image_path_and_tag(tmp_path):
    result, calls = _run_transaction(tmp_path, frontend_lookup="wrong_ref")
    assert result.returncode != 0
    assert not any(call.startswith("write ") for call in calls)


def test_lookup_timeout_and_missing_docker_fail_with_sanitized_errors(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            args[0], kwargs["timeout"], output="SECRET", stderr="SECRET"
        )

    monkeypatch.setattr(checker.subprocess, "run", timeout)
    with pytest.raises(checker.TagCheckError, match="timed out") as timeout_error:
        checker._lookup_tag("example/vidistiller-backend:v1.2.3")
    assert "SECRET" not in str(timeout_error.value)

    def missing_docker(*args, **kwargs):
        raise FileNotFoundError("SECRET")

    monkeypatch.setattr(checker.subprocess, "run", missing_docker)
    with pytest.raises(
        checker.TagCheckError, match="Docker CLI could not be started"
    ) as docker_error:
        checker._lookup_tag("example/vidistiller-backend:v1.2.3")
    assert "SECRET" not in str(docker_error.value)


def test_workflow_serializes_full_promotion_and_checks_before_write():
    workflow = _workflow()
    assert workflow["concurrency"] == {
        "group": "promote-release",
        "cancel-in-progress": False,
    }
    promote = workflow["jobs"]["promote"]["steps"]
    assert any(step.get("uses", "").startswith("actions/checkout@") for step in promote)
    check_index = next(
        i
        for i, step in enumerate(promote)
        if step.get("name") == "Check promotion tags are unused"
    )
    first_write = next(
        i
        for i, step in enumerate(promote)
        if step.get("name") == "Retag backend digest"
    )
    assert check_index < first_write
    assert "PROMOTION_VERSION" in promote[check_index]["env"]
