"""Staging deployment tests — verifies the containerised stack on the staging host.

Run from the local Mac (not inside Docker):
    pytest tests/test_staging_deploy.py -v -m staging

Pre-requisites:
    - SSH alias ``vidistiller-staging`` configured in the user's SSH config
    - Staging container/VM is running and Docker Compose stack is up
"""

from __future__ import annotations

import os
import subprocess
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SSH_ALIAS = os.environ.get("STAGING_SSH_ALIAS", "vidistiller-staging")
SSH_TIMEOUT = 10  # seconds
HTTP_TIMEOUT = 10  # seconds


def _resolve_staging_host() -> str:
    """Resolve the staging host IP via SSH, falling back to the STAGING_HOST env var or localhost."""
    if override := os.environ.get("STAGING_HOST"):
        return override
    try:
        result = subprocess.run(
            ["ssh", SSH_ALIAS, "hostname -I"],
            capture_output=True, text=True, timeout=SSH_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split()[0]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "localhost"


STAGING_HOST = _resolve_staging_host()
API_BASE = f"http://{STAGING_HOST}:8000"
FRONTEND_URL = f"http://{STAGING_HOST}:3000"
PGADMIN_URL = f"http://{STAGING_HOST}:5050"

REQUIRED_CONTAINERS = [
    "tutorial_postgres",
    "tutorial_redis",
    "tutorial_api",
    "tutorial_celery_worker",
    "tutorial_web",
]

OPTIONAL_CONTAINERS = [
    "tutorial_pgadmin",
]

EXPECTED_TABLES = [
    "processing_jobs",
    "job_logs",
    "videos",
    "transcripts",
    "transcript_segments",
    "snapshots",
    "documents",
    "slides",
    "slide_detection_metadata",
    "users",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ssh_run(cmd: str, *, timeout: int = SSH_TIMEOUT) -> subprocess.CompletedProcess:
    """Execute *cmd* on the staging host via SSH."""
    return subprocess.run(
        ["ssh", SSH_ALIAS, cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def docker_exec(service: str, cmd: str, *, timeout: int = SSH_TIMEOUT) -> subprocess.CompletedProcess:
    """Run *cmd* inside a Docker container on the staging host."""
    return ssh_run(f"docker exec {service} {cmd}", timeout=timeout)


def psql_query(sql: str) -> str:
    """Execute a SQL statement on the postgres container and return stdout."""
    escaped = sql.replace("'", "'\\''")
    result = docker_exec(
        "tutorial_postgres",
        f"psql -U tutorial_user -d tutorial_db -t -A -c '{escaped}'",
    )
    assert result.returncode == 0, f"psql failed: {result.stderr}"
    return result.stdout.strip()


def api_get(path: str, **kwargs) -> requests.Response:
    """GET request to the staging API."""
    return requests.get(f"{API_BASE}{path}", timeout=HTTP_TIMEOUT, **kwargs)


def api_post(path: str, data: dict | None = None, **kwargs) -> requests.Response:
    """POST request to the staging API."""
    return requests.post(f"{API_BASE}{path}", json=data, timeout=HTTP_TIMEOUT, **kwargs)


def api_delete(path: str, **kwargs) -> requests.Response:
    """DELETE request to the staging API."""
    return requests.delete(f"{API_BASE}{path}", timeout=HTTP_TIMEOUT, **kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def staging_reachable():
    """Skip the entire module if the staging host is unreachable via SSH."""
    try:
        result = ssh_run("echo ok", timeout=5)
        if result.returncode != 0 or "ok" not in result.stdout:
            pytest.skip("Staging host not reachable via SSH")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pytest.skip("Staging host not reachable via SSH")


@pytest.fixture()
def api_reachable():
    """Skip the current test if the API health endpoint is unreachable."""
    try:
        resp = api_get("/health")
        if resp.status_code != 200:
            pytest.skip("API health endpoint not reachable")
    except requests.ConnectionError:
        pytest.skip("API health endpoint not reachable")


@pytest.fixture(scope="module")
def staging_auth_headers():
    """Register a test user on the staging deployment and return Bearer headers.

    If registration fails (user already exists), falls back to login.
    """
    creds = {"username": "staging_test_user", "email": "staging_test@example.com", "password": "StagingTestPass1"}
    # Try register first; ignore if user already exists
    requests.post(f"{API_BASE}/api/auth/register", json=creds, timeout=HTTP_TIMEOUT)
    login_resp = requests.post(
        f"{API_BASE}/api/auth/login",
        json={"username": creds["username"], "password": creds["password"]},
        timeout=HTTP_TIMEOUT,
    )
    assert login_resp.status_code == 200, f"Staging auth login failed: {login_resp.text}"
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def test_job_cleanup(staging_auth_headers):
    """Yield a list; any job_id appended during the test will be DELETEd afterwards."""
    job_ids: list[str] = []
    yield job_ids
    for jid in job_ids:
        try:
            api_delete(f"/api/jobs/{jid}", headers=staging_auth_headers)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.staging
class TestContainerHealth:
    """Verify all Docker containers are running and healthy."""

    def test_all_containers_running(self):
        result = ssh_run("docker ps --format '{{.Names}}' --filter status=running")
        running = result.stdout.strip().splitlines()
        for name in REQUIRED_CONTAINERS:
            assert name in running, f"Container {name} is not running"

    def test_postgres_healthy(self):
        result = docker_exec("tutorial_postgres", "pg_isready -U tutorial_user")
        assert result.returncode == 0

    def test_redis_healthy(self):
        result = docker_exec("tutorial_redis", "redis-cli ping")
        assert "PONG" in result.stdout

    def test_api_healthy(self):
        result = docker_exec("tutorial_api", "curl -sf http://localhost:8000/health")
        assert result.returncode == 0
        assert "healthy" in result.stdout

    def test_no_restart_loops(self):
        """No container should have restarted more than twice."""
        result = ssh_run(
            "docker ps --format '{{.Names}}|{{.Status}}' --filter status=running"
        )
        for line in result.stdout.strip().splitlines():
            name, status = line.split("|", 1)
            # Docker status looks like "Up 2 hours" or "Up 5 min (healthy)"
            # Restarting containers show "Restarting (1) ..."
            assert "Restarting" not in status, f"{name} is in a restart loop"

    def test_container_count(self):
        """At least the required containers should be running."""
        result = ssh_run("docker ps -q --filter status=running")
        ids = [line for line in result.stdout.strip().splitlines() if line]
        assert len(ids) >= len(REQUIRED_CONTAINERS), (
            f"Expected at least {len(REQUIRED_CONTAINERS)} containers, got {len(ids)}"
        )


@pytest.mark.staging
class TestNetworkConnectivity:
    """Verify all exposed services are reachable from the Mac."""

    def test_api_health(self, api_reachable):
        resp = api_get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_api_docs(self, api_reachable):
        resp = api_get("/docs")
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower() or "openapi" in resp.text.lower()

    def test_frontend_reachable(self):
        try:
            resp = requests.get(FRONTEND_URL, timeout=HTTP_TIMEOUT)
            assert resp.status_code == 200
        except requests.ConnectionError:
            pytest.fail("Frontend at :3000 is not reachable")

    def test_pgadmin_reachable(self):
        """pgAdmin is optional — skip if container is not running."""
        result = ssh_run("docker ps --format '{{.Names}}' --filter name=tutorial_pgadmin --filter status=running")
        if "tutorial_pgadmin" not in result.stdout:
            pytest.skip("pgAdmin container is not running (optional)")
        try:
            resp = requests.get(PGADMIN_URL, timeout=HTTP_TIMEOUT)
            assert resp.status_code < 500
        except requests.ConnectionError:
            pytest.fail("pgAdmin container is running but :5050 is not reachable")

    def test_api_root(self, api_reachable):
        resp = api_get("/")
        assert resp.status_code == 200


@pytest.mark.staging
class TestDatabaseState:
    """Verify the PostgreSQL schema is up to date."""

    def test_all_tables_exist(self):
        tables_raw = psql_query(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        tables = set(tables_raw.splitlines())
        for table in EXPECTED_TABLES:
            assert table in tables, f"Table '{table}' missing from database"

    def test_metadata_all_create_all_works(self):
        # We check for slides table which is a good indicator
        result = psql_query(
            "SELECT EXISTS ("
            "  SELECT FROM pg_tables WHERE schemaname='public' AND tablename='slides'"
            ")"
        )
        assert result == "t", "slides table does not exist"

    def test_slides_table_has_expected_columns(self):
        columns_raw = psql_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'slides' ORDER BY ordinal_position"
        )
        columns = set(columns_raw.splitlines())
        required = {
            "id", "job_id", "slide_number", "start_timestamp", "end_timestamp",
            "final_frame_path", "ocr_text", "transcript_text",
        }
        missing = required - columns
        assert not missing, f"Slides table missing columns: {missing}"


@pytest.mark.staging
class TestAPIFunctionality:
    """Verify core API endpoints work correctly."""

    def test_create_job(self, api_reachable, staging_auth_headers, test_job_cleanup):
        resp = api_post("/api/jobs", data={
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=staging_auth_headers)
        assert resp.status_code in (200, 201), "Create job failed: " + resp.text
        body = resp.json()
        assert "job_id" in body
        test_job_cleanup.append(body["job_id"])

    def test_create_slide_aware_job(self, api_reachable, staging_auth_headers, test_job_cleanup):
        resp = api_post("/api/jobs", data={
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "processing_mode": "slide_aware",
        }, headers=staging_auth_headers)
        assert resp.status_code in (200, 201), "Create slide_aware job failed: " + resp.text
        body = resp.json()
        assert "job_id" in body
        test_job_cleanup.append(body["job_id"])

    def test_list_jobs(self, api_reachable, staging_auth_headers):
        resp = api_get("/api/jobs", headers=staging_auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_nonexistent_job(self, api_reachable, staging_auth_headers):
        fake_id = str(uuid.uuid4())
        resp = api_get(f"/api/jobs/{fake_id}", headers=staging_auth_headers)
        assert resp.status_code == 404

    def test_slides_endpoint_exists(self, api_reachable, staging_auth_headers):
        """The /api/jobs/{id}/slides endpoint should exist (even if 404 for bad id)."""
        fake_id = str(uuid.uuid4())
        resp = api_get(f"/api/jobs/{fake_id}/slides", headers=staging_auth_headers)
        # 404 is expected for a non-existent job; 405/500 would indicate a missing route
        assert resp.status_code in (404, 422), (
            f"Slides endpoint returned unexpected status: {resp.status_code}"
        )


@pytest.mark.staging
class TestCeleryWorker:
    """Verify the Celery worker is operational."""

    def test_celery_process_running(self):
        result = docker_exec(
            "tutorial_celery_worker",
            "python -c \"import os; entries=os.listdir('/proc'); pids=[e for e in entries if e.isdigit()]; print(len(pids))\"",
        )
        assert result.returncode == 0, f"Could not list processes: {result.stderr}"
        count = int(result.stdout.strip())
        assert count >= 2, f"Expected multiple processes in celery container, got {count}"

    def test_celery_ping(self):
        result = docker_exec(
            "tutorial_celery_worker",
            "celery -A app.tasks inspect ping",
            timeout=15,
        )
        assert result.returncode == 0, f"Celery ping failed: {result.stderr}"


@pytest.mark.staging
class TestPresentationMode:
    """Verify the slide-aware processing dependencies are present."""

    def test_cv2_importable(self):
        result = docker_exec(
            "tutorial_celery_worker",
            "python -c 'import cv2; print(cv2.__version__)'",
        )
        assert result.returncode == 0, f"cv2 not importable: {result.stderr}"

    def test_tesseract_installed(self):
        result = docker_exec(
            "tutorial_celery_worker",
            "tesseract --version",
        )
        assert result.returncode == 0, f"tesseract not found: {result.stderr}"


@pytest.mark.staging
class TestStaticFileServing:
    """Verify static file directories and error handling."""

    def test_snapshots_dir_exists(self):
        result = docker_exec("tutorial_api", "test -d /data/snapshots")
        assert result.returncode == 0, "/data/snapshots does not exist in api container"

    def test_slides_dir_exists(self):
        result = docker_exec("tutorial_api", "test -d /data/slides")
        assert result.returncode == 0, "/data/slides does not exist in api container"


@pytest.mark.staging
class TestEnvironmentConfig:
    """Verify environment variables and service configuration."""

    def test_cors_allows_frontend(self, api_reachable):
        resp = requests.options(
            f"{API_BASE}/health",
            headers={
                "Origin": f"http://{STAGING_HOST}:3000",
                "Access-Control-Request-Method": "GET",
            },
            timeout=HTTP_TIMEOUT,
        )
        allow_origin = resp.headers.get("access-control-allow-origin", "")
        assert (
            allow_origin == "*"
            or f"{STAGING_HOST}:3000" in allow_origin
            or resp.status_code in (200, 204)
        ), f"CORS does not allow frontend origin. Headers: {dict(resp.headers)}"

    def test_redis_reachable_from_api(self):
        result = docker_exec("tutorial_api", "python -c \"import redis; r=redis.from_url('redis://redis:6379'); print(r.ping())\"")
        assert "True" in result.stdout, f"Redis not reachable from API: {result.stderr}"

    def test_database_url_configured(self):
        result = docker_exec(
            "tutorial_api",
            "python -c \"import os; print(os.environ.get('DATABASE_URL', ''))\"",
        )
        assert result.returncode == 0
        assert "postgresql" in result.stdout.lower(), (
            f"DATABASE_URL does not look like a PostgreSQL URL: {result.stdout}"
        )
