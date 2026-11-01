import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/promote-release.yml"


def _steps():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "run" in step
    ]


def _run_workflow_script(script, inputs, tmp_path, stubs=""):
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    (stub_dir / "gh").write_text('#!/bin/bash\nprintf \'%s\\n\' "$*" >> "$CALL_LOG"\n')
    (stub_dir / "docker").write_text(
        '#!/bin/bash\nprintf \'%s\\n\' "$*" >> "$CALL_LOG"\n'
    )
    for path in stub_dir.iterdir():
        path.chmod(0o755)
    env = os.environ | {
        "PATH": str(stub_dir) + os.pathsep + os.environ["PATH"],
        "CALL_LOG": str(tmp_path / "calls"),
        "GITHUB_REPOSITORY": "owner/repo",
        "NAMESPACE": "example",
        "BACKEND_REF": "example/backend@sha256:abc",
        "FRONTEND_REF": "example/frontend@sha256:def",
        "CANDIDATE_RELEASE_ID": inputs.get("candidate_release_id", ""),
        "PROMOTION_VERSION": inputs.get("version", ""),
    }
    result = subprocess.run(
        ["bash", "-e", "-c", stubs + "\n" + script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    return result, Path(env["CALL_LOG"])


def test_workflow_inputs_are_bound_at_every_consumer():
    steps = _steps()
    assert all("${{ inputs." not in step["run"] for step in steps)
    expected = {
        "Validate promotion inputs": {
            "CANDIDATE_RELEASE_ID": "candidate_release_id",
            "PROMOTION_VERSION": "version",
        },
        "Fetch candidate draft release by ID": {
            "CANDIDATE_RELEASE_ID": "candidate_release_id"
        },
        "Retag backend digest": {"PROMOTION_VERSION": "version"},
        "Retag frontend digest": {"PROMOTION_VERSION": "version"},
        "Re-verify approved manifest before touching anything": {
            "CANDIDATE_RELEASE_ID": "candidate_release_id"
        },
    }
    for name, bindings in expected.items():
        step = next(step for step in steps if step.get("name") == name)
        for variable, input_name in bindings.items():
            assert step["env"][variable] == "${{ inputs." + input_name + " }}"


def test_dispatch_input_cannot_execute_shell(tmp_path):
    step = next(
        step for step in _steps() if step.get("name") == "Validate promotion inputs"
    )
    validate = step["run"]
    payloads = [
        f"$(touch {tmp_path / 'executed-id'})",
        "123\ninvalid",
        '"123"',
        "123\n",
    ]
    for index, payload in enumerate(payloads):
        marker = tmp_path / "executed-id"
        result, _ = _run_workflow_script(
            validate,
            {"candidate_release_id": payload, "version": "v1.2.3"},
            tmp_path / str(index),
        )
        assert result.returncode != 0
        assert not marker.exists()
    for index, payload in enumerate(
        [
            f"$(touch {tmp_path / 'executed-version'})",
            "v1.2.3\ninvalid",
            '"v1.2.3"',
            "v1.2.3\n",
        ]
    ):
        result, _ = _run_workflow_script(
            validate,
            {"candidate_release_id": "123", "version": payload},
            tmp_path / f"version-{index}",
        )
        assert result.returncode != 0
        assert not (tmp_path / "executed-version").exists()


def test_valid_candidate_id_and_version_reach_stubbed_commands(tmp_path):
    scripts = "\n".join(
        step["run"]
        for step in _steps()
        if step.get("name")
        in {
            "Validate promotion inputs",
            "Retag backend digest",
            "Retag frontend digest",
        }
    )
    result, calls = _run_workflow_script(
        scripts,
        {"candidate_release_id": "12345", "version": "v1.2.3"},
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "imagetools create" in calls.read_text()
    assert "vidistiller-backend:v1.2.3" in calls.read_text()


def test_malformed_inputs_fail_before_mutation(tmp_path):
    scripts = "\n".join(
        step["run"]
        for step in _steps()
        if step.get("name")
        in {
            "Validate promotion inputs",
            "Retag backend digest",
            "Retag frontend digest",
        }
    )
    for index, values in enumerate(
        (
            {"candidate_release_id": "abc", "version": "v1.0"},
            {"candidate_release_id": "1", "version": "v1;touch invalid"},
            {"candidate_release_id": "123\ninvalid", "version": "v1.2.3"},
            {"candidate_release_id": "123", "version": "v1.2.3\ninvalid"},
        )
    ):
        result, calls = _run_workflow_script(scripts, values, tmp_path / str(index))
        assert result.returncode != 0
        assert not calls.exists() or calls.read_text() == ""
