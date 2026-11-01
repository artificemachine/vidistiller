import json
import base64
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_candidate_provenance.py"
MANIFEST_PATH = ROOT / "tests/fixtures/release-candidate-valid.json"
REPOSITORY = "example-org/vidistiller"
COMMIT = "00a68057c8bf685dca16ad2a5a2ed06ff26ad125"
RUN_ID = "17153000000"
PREDICATE_TYPE = "https://slsa.dev/provenance/v0.2"


def _manifest():
    return json.loads(MANIFEST_PATH.read_text())


def _statement(image_ref, commit=COMMIT, run_id=RUN_ID, predicate_type=PREDICATE_TYPE):
    name, digest = image_ref.split("@", 1)
    return {
        "_type": "https://in-toto.io/Statement/v0.1",
        "subject": [{"name": name, "digest": {"sha256": digest.split(":", 1)[1]}}],
        "predicateType": predicate_type,
        "predicate": {
            "builder": {"id": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"},
            "buildType": f"https://github.com/{REPOSITORY}/.github/workflows/deploy.yml@refs/heads/main",
            "invocation": {
                "configSource": {
                    "uri": f"git+https://github.com/{REPOSITORY}",
                    "digest": {"sha1": commit},
                    "entryPoint": "deploy.yml",
                }
            },
            "metadata": {
                "buildInvocationId": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}",
                "completeness": {
                    "parameters": True,
                    "environment": False,
                    "materials": True,
                },
                "reproducible": False,
            },
        },
    }


def _envelope(statement):
    # Cosign v3.0.6 verify-attestation prints the verified DSSE envelope as
    # one JSON line in text mode, following any certificate header.
    payload = json.dumps(statement, separators=(",", ":")).encode()
    envelope = {
        "payloadType": "application/vnd.in-toto+json",
        "payload": base64.b64encode(payload).decode(),
        "signatures": [{"keyid": "fixture", "sig": "fixture"}],
    }
    return json.dumps(envelope)


def _write_verified_output(path, statement):
    if isinstance(statement, str):
        path.write_text(statement)
    elif isinstance(statement, list):
        path.write_text(
            "Certificate subject: fixture\n"
            + "\n".join(_envelope(item) for item in statement)
            + "\n"
        )
    else:
        path.write_text("Certificate subject: fixture\n" + _envelope(statement) + "\n")


def _run(tmp_path, backend=None, frontend=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest = _manifest()
    backend_output = tmp_path / "backend.txt"
    frontend_output = tmp_path / "frontend.txt"
    _write_verified_output(
        backend_output,
        _statement(manifest["images"]["backend"]) if backend is None else backend,
    )
    _write_verified_output(
        frontend_output,
        _statement(manifest["images"]["frontend"]) if frontend is None else frontend,
    )
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(MANIFEST_PATH),
            "--repository",
            REPOSITORY,
            "--backend-attestation",
            str(backend_output),
            "--frontend-attestation",
            str(frontend_output),
        ],
        capture_output=True,
        text=True,
    )


def test_signed_old_image_rejected_for_new_manifest(tmp_path):
    manifest = _manifest()
    old = _statement(manifest["images"]["backend"], commit="a" * 40)
    result = _run(tmp_path, backend=old)
    assert result.returncode != 0


def test_matching_verified_attestations_for_both_images_pass(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr


def test_each_image_requires_its_own_matching_attestation(tmp_path):
    manifest = _manifest()
    wrong = _statement(manifest["images"]["backend"])
    result = _run(tmp_path, frontend=wrong)
    assert result.returncode != 0


def test_wrong_run_id_is_rejected(tmp_path):
    manifest = _manifest()
    result = _run(
        tmp_path,
        backend=_statement(manifest["images"]["backend"], run_id="17153000001"),
    )
    assert result.returncode != 0


def test_malformed_verified_output_is_rejected(tmp_path):
    result = _run(tmp_path, backend={"_type": "truncated"})
    assert result.returncode != 0
    assert result.stderr.strip()


def test_malformed_json_base64_and_empty_output_are_rejected(tmp_path):
    for index, output in enumerate(
        (
            "{broken json}\n",
            '{"payloadType":"application/vnd.in-toto+json","payload":"%%%"}\n',
            "",
        )
    ):
        result = _run(tmp_path / str(index), backend=output)
        assert result.returncode != 0


def test_multiple_verified_jsonl_statements_and_dockerhub_name_normalization(tmp_path):
    manifest = _manifest()
    matching = _statement(manifest["images"]["backend"])
    matching["subject"][0]["name"] = "index.docker.io/" + matching["subject"][0]["name"]
    other = _statement(manifest["images"]["frontend"], commit="a" * 40)
    result = _run(tmp_path, backend=[other, matching])
    assert result.returncode == 0, result.stderr


def test_wrong_predicate_type_is_rejected(tmp_path):
    manifest = _manifest()
    result = _run(
        tmp_path,
        frontend=_statement(manifest["images"]["frontend"], predicate_type="custom"),
    )
    assert result.returncode != 0


def test_unknown_statement_type_is_rejected(tmp_path):
    manifest = _manifest()
    statement = _statement(manifest["images"]["backend"])
    statement["_type"] = "https://in-toto.io/Statement/v1"
    result = _run(tmp_path, backend=statement)
    assert result.returncode != 0


def test_source_identity_mismatches_are_rejected(tmp_path):
    manifest = _manifest()
    mutations = [
        (
            ("predicate", "invocation", "configSource", "uri"),
            "git+https://github.com/other/repo",
        ),
        (("predicate", "invocation", "configSource", "digest"), {"sha1": "a" * 40}),
        (("predicate", "invocation", "configSource", "entryPoint"), "other.yml"),
        (
            ("predicate", "buildType"),
            "https://github.com/other/repo/.github/workflows/deploy.yml@refs/heads/main",
        ),
        (
            ("predicate", "builder", "id"),
            "https://github.com/other/repo/actions/runs/17153000000",
        ),
        (
            ("predicate", "metadata", "buildInvocationId"),
            "https://github.com/example-org/vidistiller/actions/runs/other",
        ),
    ]
    for index, (path, value) in enumerate(mutations):
        statement = _statement(manifest["images"]["backend"])
        target = statement
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        result = _run(tmp_path / str(index), backend=statement)
        assert result.returncode != 0, f"mutation {index} should be rejected"


def test_workflow_captures_and_checks_cosign_verified_payloads():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/promote-release.yml").read_text()
    )
    steps = workflow["jobs"]["verify-candidate"]["steps"]
    verify = next(
        step
        for step in steps
        if step.get("name") == "Verify candidate signatures and attestations"
    )
    script = verify["run"]
    assert "--certificate-identity" in script
    assert (
        "https://github.com/${GITHUB_REPOSITORY}/.github/workflows/deploy.yml@refs/heads/main"
        in script
    )
    assert "cosign verify-attestation" in script
    checker = next(
        step
        for step in steps
        if "verify_candidate_provenance.py" in step.get("run", "")
    )
    assert (
        "backend-attestation" in checker["run"]
        and "frontend-attestation" in checker["run"]
    )
