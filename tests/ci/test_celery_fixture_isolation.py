import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FENCING_TEST = ROOT / "tests/test_celery_redelivery_fencing.py"
FENCING_SOURCE = FENCING_TEST.read_text()


def test_celery_fencing_requires_explicit_isolated_endpoints() -> None:
    for name in (
        "TEST_DATABASE_URL",
        "TEST_REDIS_URL",
        "DATABASE_URL",
        "REDIS_URL",
    ):
        assert f'os.environ.get("{name}")' in FENCING_SOURCE
        assert (
            re.search(rf'os\.environ\.get\(\s*["\']{name}["\']\s*,', FENCING_SOURCE)
            is None
        )
    assert "DATABASE_URL != TEST_DATABASE_URL" in FENCING_SOURCE
    assert 'os.environ.get("REDIS_URL")' in FENCING_SOURCE
    assert "REDIS_URL != TEST_REDIS_URL" in FENCING_SOURCE
    assert "localhost:6379/0" not in FENCING_SOURCE
    assert "localhost:5432/tutorial_db" not in FENCING_SOURCE


def test_celery_cleanup_owns_only_fixture_workers() -> None:
    assert "pkill" not in FENCING_SOURCE
    assert "owned_workers.append(proc)" in FENCING_SOURCE
    assert "for proc in owned_workers" in FENCING_SOURCE
    assert "_stop_worker(proc)" in FENCING_SOURCE


def _run_fencing_tests_without_isolated_endpoints(
    missing_endpoints: set[str],
    mismatch_parent_database: bool = False,
    mismatch_parent_redis: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("TEST_DATABASE_URL", None)
    env.pop("TEST_REDIS_URL", None)
    env["DATABASE_URL"] = "postgresql://fixture.invalid:1/unreachable"
    env["REDIS_URL"] = "redis://fixture.invalid:1/15"
    if "TEST_DATABASE_URL" not in missing_endpoints:
        env["TEST_DATABASE_URL"] = "postgresql://fixture.invalid:1/unreachable"
    if "TEST_REDIS_URL" not in missing_endpoints:
        env["TEST_REDIS_URL"] = "redis://fixture.invalid:1/15"
    if mismatch_parent_database:
        env["DATABASE_URL"] = "postgresql://different.invalid:1/unreachable"
    if mismatch_parent_redis:
        env["REDIS_URL"] = "redis://different.invalid:1/15"

    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(FENCING_TEST)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "missing_endpoints",
    [
        {"TEST_DATABASE_URL"},
        {"TEST_REDIS_URL"},
        {"TEST_DATABASE_URL", "TEST_REDIS_URL"},
    ],
)
def test_missing_test_endpoints_skip_without_connecting(
    missing_endpoints: set[str],
) -> None:
    result = _run_fencing_tests_without_isolated_endpoints(missing_endpoints)

    assert (
        result.returncode == 0
    ), "fencing tests failed without explicit isolated endpoints"
    assert re.search(r"2 skipped", result.stdout)


def test_parent_database_mismatch_skips_without_connecting() -> None:
    result = _run_fencing_tests_without_isolated_endpoints(
        set(), mismatch_parent_database=True
    )

    assert (
        result.returncode == 0
    ), "fencing tests failed with mismatched database endpoints"
    assert re.search(r"2 skipped", result.stdout)


def test_parent_redis_mismatch_skips_without_connecting() -> None:
    result = _run_fencing_tests_without_isolated_endpoints(
        set(), mismatch_parent_redis=True
    )

    assert (
        result.returncode == 0
    ), "fencing tests failed with mismatched Redis endpoints"
    assert re.search(r"2 skipped", result.stdout)
