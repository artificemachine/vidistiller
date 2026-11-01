import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/promote-release.yml"
SCRIPT = ROOT / "scripts/check_promotion_environment.py"
SPEC = importlib.util.spec_from_file_location(
    "check_promotion_environment_under_test", SCRIPT
)


def _checker():
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    return module


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _environment(scenario):
    reviewer = {"type": "User", "reviewer": {"id": 123, "login": "reviewer"}}
    if scenario == "valid_team":
        reviewer = {
            "type": "Team",
            "reviewer": {"id": 456, "slug": "release-approvers"},
        }
    rules = {
        "empty": [],
        "malformed": [
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [{"type": "Bot", "reviewer": {"id": 9}}],
            }
        ],
        "malformed_self_review": [
            {
                "type": "required_reviewers",
                "prevent_self_review": "false",
                "reviewers": [reviewer],
            }
        ],
        "missing_self_review": [
            {
                "type": "required_reviewers",
                "reviewers": [reviewer],
            }
        ],
        "solo": [
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [reviewer],
            }
        ],
        "valid": [
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [reviewer],
            }
        ],
        "valid_team": [
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [reviewer],
            }
        ],
    }
    return {"name": "production", "protection_rules": rules.get(scenario, [])}


def _run_flow(tmp_path, scenario="empty"):
    jobs = _workflow()["jobs"]
    approval_steps = jobs.get("approve-production", {}).get("steps", [])
    approval_run = next((step["run"] for step in approval_steps if "run" in step), "")
    promote_steps = jobs["promote"]["steps"]
    tag_check = next(
        step
        for step in promote_steps
        if step.get("name") == "Check promotion tags are unused"
    )
    retags = [
        step
        for step in promote_steps
        if step.get("name") in {"Retag backend digest", "Retag frontend digest"}
    ]
    script = "\n".join(
        [approval_run, tag_check["run"], *(step["run"] for step in retags)]
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "gh").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "print('gh ' + ' '.join(sys.argv[1:]), file=open(os.environ['CALL_LOG'], 'a'))\n"
        "if os.environ['GH_SCENARIO'] == 'http_error': print('403 SECRET_TOKEN', file=sys.stderr); sys.exit(1)\n"
        "json.dump(json.loads(os.environ['GH_RESPONSE']), sys.stdout)\n"
    )
    (bin_dir / "docker").write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:3] == ['buildx', 'imagetools', 'inspect']:\n"
        "    ref=args[-1]; print('inspect '+ref, file=open(os.environ['CALL_LOG'],'a')); print('ERROR: docker.io/'+ref+': not found',file=sys.stderr); sys.exit(1)\n"
        "if args[:3] == ['buildx', 'imagetools', 'create']:\n"
        "    print('write '+args[args.index('-t')+1], file=open(os.environ['CALL_LOG'],'a')); sys.exit(0)\n"
        "sys.exit(2)\n"
    )
    for path in bin_dir.iterdir():
        path.chmod(0o755)
    response = _environment(scenario)
    env = os.environ | {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "CALL_LOG": str(tmp_path / "calls"),
        "GH_SCENARIO": scenario,
        "GH_RESPONSE": json.dumps(response),
        "GH_TOKEN": "fixture-secret-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "REPOSITORY": "owner/repo",
        "ENVIRONMENT_NAME": "production",
        "NAMESPACE": "example",
        "BACKEND_REF": "example/vidistiller-backend@sha256:abc",
        "FRONTEND_REF": "example/vidistiller-frontend@sha256:def",
        "PROMOTION_VERSION": "v1.2.3",
    }
    result = subprocess.run(
        ["bash", "-e", "-c", script], cwd=ROOT, env=env, capture_output=True, text=True
    )
    calls_path = Path(env["CALL_LOG"])
    return result, calls_path.read_text().splitlines() if calls_path.exists() else []


def test_retag_requires_protected_environment_approval():
    jobs = _workflow()["jobs"]
    approval = jobs["approve-production"]
    assert approval["environment"] == "production"
    assert "verify-candidate" in approval["needs"]
    assert approval["permissions"] == {"actions": "read", "contents": "read"}
    assert "approve-production" in jobs["promote"]["needs"]
    assert "approve-production" in jobs["deploy-production"]["needs"]
    assert "promote" in jobs["deploy-production"]["needs"]
    assert jobs["deploy-production"]["environment"] == "production"


@pytest.mark.parametrize(
    "scenario",
    [
        "empty",
        "malformed",
        "malformed_self_review",
        "missing_self_review",
        "http_error",
    ],
)
def test_missing_or_invalid_reviewer_configuration_stops_before_docker(
    tmp_path, scenario
):
    result, calls = _run_flow(tmp_path / scenario, scenario)
    assert result.returncode != 0
    assert calls == ["gh api --method GET repos/owner/repo/environments/production"]
    assert not any(call.startswith(("inspect ", "write ")) for call in calls)
    assert "fixture-secret-token" not in result.stderr
    assert "SECRET_TOKEN" not in result.stderr


@pytest.mark.parametrize("scenario", ["valid", "valid_team", "solo"])
def test_eligible_user_or_team_allows_only_post_approval_transaction(
    tmp_path, scenario
):
    result, calls = _run_flow(tmp_path / scenario, scenario)
    assert result.returncode == 0, result.stderr
    assert calls[0].startswith("gh api ")
    assert [call.split()[0] for call in calls[1:]] == [
        "inspect",
        "inspect",
        "write",
        "write",
    ]


def test_environment_api_failure_is_sanitized():
    def failed_request(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 1, stdout="", stderr="fixture-secret-token"
        )

    with pytest.MonkeyPatch.context() as monkeypatch:
        checker = _checker()
        monkeypatch.setattr(checker.subprocess, "run", failed_request)
        with pytest.raises(checker.EnvironmentCheckError) as error:
            checker.fetch_environment("owner/repo", "production")
    assert "fixture-secret-token" not in str(error.value)


def test_environment_timeout_and_missing_cli_fail_without_details(monkeypatch):
    checker = _checker()

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            args[0], kwargs["timeout"], stderr="fixture-secret-token"
        )

    monkeypatch.setattr(checker.subprocess, "run", timed_out)
    with pytest.raises(
        checker.EnvironmentCheckError, match="timed out"
    ) as timeout_error:
        checker.fetch_environment("owner/repo", "production")
    assert "fixture-secret-token" not in str(timeout_error.value)

    def missing_cli(*args, **kwargs):
        raise FileNotFoundError("fixture-secret-token")

    monkeypatch.setattr(checker.subprocess, "run", missing_cli)
    with pytest.raises(
        checker.EnvironmentCheckError, match="could not be started"
    ) as cli_error:
        checker.fetch_environment("owner/repo", "production")
    assert "fixture-secret-token" not in str(cli_error.value)
