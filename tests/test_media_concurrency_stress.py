"""WP1 acceptance: concurrent authenticated media does not starve the pool.

Requires a real Postgres (docker-compose.test.yml). The 2026-08-16 incident
was a gallery burst pinning one SQLAlchemy connection per media request in an
idle transaction until the 60-connection pool was exhausted, taking down
health and login. This test drives many concurrent authenticated snapshot
responses and asserts the DB session count returns to baseline and no
idle-in-transaction session is left behind.

Runs against a real Uvicorn process with real slow-ish streaming so the
response-body lifetime actually overlaps (the TestClient consumes the body
immediately, which would hide the bug).
"""

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://tutorial_user:tutorial_password@localhost:5432/tutorial_db",
)
API_PORT = int(os.environ.get("TEST_MEDIA_API_PORT", "8899"))


def _postgres_reachable(url: str) -> bool:
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(DATABASE_URL),
    reason="No Postgres reachable at TEST_DATABASE_URL/DATABASE_URL",
)


@pytest.fixture(scope="module")
def media_env(tmp_path_factory):
    """A live Uvicorn API with one media file and a test user."""
    from app.db.session import Base, SessionLocal, engine as app_engine
    from app.db.models import ProcessingJob, ProcessingStatus, User
    from app.services.auth import AuthService

    data_dir = tmp_path_factory.mktemp("media-data")
    media_dir = data_dir / "snapshots" / "aaaa-bbbb-cccc"
    media_dir.mkdir(parents=True)
    blob = os.urandom(256 * 1024)
    (media_dir / "frame_0001.jpg").write_bytes(blob)

    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")

    # Seed a user + owned job via a real session bound to the test DB.
    import sqlalchemy as sa

    app_engine.dispose()  # avoid mixing module engine with the test schema
    os.environ["DATABASE_URL"] = DATABASE_URL
    os.environ["DATA_DIR"] = str(data_dir)
    from app.db.session import SessionLocal as _SL

    db = _SL()
    try:
        user = User(
            username="media_tester",
            email="media@test.local",
            password_hash=AuthService.hash_password("MediaPass123"),
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(
            ProcessingJob(
                job_id="aaaa-bbbb-cccc",
                status=ProcessingStatus.COMPLETED,
                video_url="https://example.com/v",
                user_id=user.id,
            )
        )
        db.commit()
        user_id = user.id
    finally:
        db.close()

    # Launch a real Uvicorn process on a private port with the test DB.
    env = dict(os.environ)
    env["DATABASE_URL"] = DATABASE_URL
    env["DATA_DIR"] = str(data_dir)
    env["ENVIRONMENT"] = "testing"
    env["JWT_SECRET_KEY"] = "TestSecretKey123!@#abcDEF_development_onlyx"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(API_PORT),
        ],
        cwd=str(Path(__file__).resolve().parents[1] / "backend"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for readiness.
    for _ in range(60):
        try:
            if requests.get(f"http://127.0.0.1:{API_PORT}/health", timeout=2).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("API did not become ready")

    yield {"port": API_PORT, "user_id": user_id}

    proc.terminate()
    proc.wait(timeout=15)


@pytest.fixture(scope="module")
def auth_token(media_env):
    resp = requests.post(
        f"http://127.0.0.1:{media_env['port']}/api/auth/login",
        json={"username": "media_tester", "password": "MediaPass123"},
        timeout=10,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _idle_in_transaction_count() -> int:
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE state = 'idle in transaction' AND datname = current_database()"
                )
            ).scalar()
            return int(row)
    finally:
        engine.dispose()


def test_200_concurrent_media_responses_return_sessions_to_baseline(
    media_env, auth_token
):
    port = media_env["port"]
    headers = {"Authorization": f"Bearer {auth_token}"}
    url = f"http://127.0.0.1:{port}/static/snapshots/aaaa-bbbb-cccc/frame_0001.jpg"

    baseline = _idle_in_transaction_count()

    results = []
    errors = []

    def worker():
        try:
            resp = requests.get(url, headers=headers, timeout=30, stream=True)
            # Read the body slowly in chunks so response lifetime overlaps.
            for _chunk in resp.iter_content(chunk_size=1024):
                pass
            results.append(resp.status_code)
        except Exception as exc:  # pragma: no cover - failure evidence
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker) for _ in range(200)]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    elapsed = time.monotonic() - started
    assert not errors, f"errors: {errors[:5]}"
    assert len(results) == 200
    assert all(code == 200 for code in results), f"statuses: {set(results)}"

    # Sessions must return to baseline; no idle-in-transaction left behind.
    time.sleep(2)
    after = _idle_in_transaction_count()
    assert after <= baseline, f"idle-in-tx after: {after} vs baseline {baseline}"

    # Auth path must remain responsive during the load (bounded latency).
    login_start = time.monotonic()
    resp = requests.post(
        f"http://127.0.0.1:{port}/api/auth/login",
        json={"username": "media_tester", "password": "MediaPass123"},
        timeout=10,
    )
    login_latency = time.monotonic() - login_start
    assert resp.status_code == 200
    assert login_latency < 5.0, f"login latency {login_latency:.2f}s"
    assert elapsed < 120, f"total media load {elapsed:.1f}s"
