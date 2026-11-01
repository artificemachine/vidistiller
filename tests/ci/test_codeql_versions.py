from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CODEQL_WORKFLOW = ROOT / ".github/workflows/codeql.yml"
DEPENDABOT_CONFIG = ROOT / ".github/dependabot.yml"
CODEQL_ACTION_COMMIT = "24c54180a607b1449ed407dd24f251e4e9147c8d"


def _load_yaml(path):
    return yaml.safe_load(path.read_text())


def _codeql_actions(workflow):
    return {
        step["uses"].split("@", 1)[0]: step["uses"].split("@", 1)[1].split()[0]
        for step in workflow["jobs"]["analyze"]["steps"]
        if step.get("uses", "").startswith("github/codeql-action/")
    }


def _assert_codeql_actions_share_version(workflow):
    actions = _codeql_actions(workflow)
    assert (
        actions["github/codeql-action/init"] == actions["github/codeql-action/analyze"]
    )
    return actions


def test_codeql_init_analyze_versions_match():
    actions = _assert_codeql_actions_share_version(_load_yaml(CODEQL_WORKFLOW))

    assert actions["github/codeql-action/init"] == CODEQL_ACTION_COMMIT


def test_dependabot_groups_actual_codeql_action_names():
    updates = _load_yaml(DEPENDABOT_CONFIG)["updates"]
    github_actions = next(
        update for update in updates if update["package-ecosystem"] == "github-actions"
    )
    groups = github_actions.get("groups", {})
    group = groups.get("codeql-action", {})
    patterns = group.get("patterns", [])

    assert patterns == ["github/codeql-action/*"]
    assert all(
        any(fnmatchcase(action, pattern) for pattern in patterns)
        for action in ("github/codeql-action/init", "github/codeql-action/analyze")
    )


def test_codeql_matrix_retains_both_languages_and_sarif_permissions():
    workflow = _load_yaml(CODEQL_WORKFLOW)
    actions = _codeql_actions(workflow)
    languages = {
        entry["language"]
        for entry in workflow["jobs"]["analyze"]["strategy"]["matrix"]["include"]
    }

    assert languages == {"python", "javascript-typescript"}
    assert "github/codeql-action/analyze" in actions
    assert workflow["permissions"]["security-events"] == "write"


def test_mismatched_action_versions_are_rejected():
    workflow_text = CODEQL_WORKFLOW.read_text().replace(
        f"github/codeql-action/analyze@{CODEQL_ACTION_COMMIT}",
        "github/codeql-action/analyze@deadbeef",
    )
    workflow = yaml.safe_load(workflow_text)

    with pytest.raises(AssertionError):
        _assert_codeql_actions_share_version(workflow)
