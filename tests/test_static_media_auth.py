"""Access control for the snapshot and slide media routes.

These files were previously served by a bare StaticFiles mount, so anyone who
learned a job UUID could read that job's entire frame set without logging in.
Frame filenames are deterministic, so a single leaked UUID exposed everything
under it permanently.
"""

import pytest

from app.core.config import get_settings
from app.db.models import User
from app.services.auth import AuthService


@pytest.fixture()
def media_root(tmp_path, monkeypatch):
    """Point DATA_DIR at a tmp tree holding one snapshot and one slide."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    for kind in ("snapshots", "slides"):
        d = tmp_path / kind / "aaaa-bbbb-cccc"
        d.mkdir(parents=True)
        (d / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff-not-a-real-jpeg")

    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture()
def other_user(test_db) -> User:
    user = User(
        username="intruder",
        email="intruder@example.com",
        password_hash=AuthService.hash_password("TestPass123"),
        is_active=True,
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)
    return user


@pytest.fixture()
def other_headers(client, other_user) -> dict:
    resp = client.post("/api/auth/login", json={
        "username": "intruder",
        "password": "TestPass123",
    })
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


SNAPSHOT_URL = "/static/snapshots/aaaa-bbbb-cccc/frame_0001.jpg"
SLIDE_URL = "/static/slides/aaaa-bbbb-cccc/frame_0001.jpg"


@pytest.mark.parametrize("url", [SNAPSHOT_URL, SLIDE_URL])
def test_anonymous_request_is_rejected(client, seeded_job, media_root, url):
    resp = client.get(url)
    assert resp.status_code == 401


@pytest.mark.parametrize("url", [SNAPSHOT_URL, SLIDE_URL])
def test_owner_can_read_with_bearer_token(client, seeded_job, media_root, auth_headers, url):
    resp = client.get(url, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xff\xd8\xff")


@pytest.mark.parametrize("url", [SNAPSHOT_URL, SLIDE_URL])
def test_owner_can_read_with_auth_cookie(client, seeded_job, media_root, test_user, url):
    """Browsers cannot attach an Authorization header to <img src>, so the
    httpOnly auth_token cookie set at login must also be accepted."""
    client.post("/api/auth/login", json={"username": "testuser", "password": "TestPass123"})
    resp = client.get(url)  # TestClient carries the cookie jar
    assert resp.status_code == 200


@pytest.mark.parametrize("url", [SNAPSHOT_URL, SLIDE_URL])
def test_non_owner_cannot_read(client, seeded_job, media_root, other_headers, url):
    """404 rather than 403 — a wrong-owner 403 confirms the job exists."""
    resp = client.get(url, headers=other_headers)
    assert resp.status_code == 404


def test_unknown_job_is_not_found(client, media_root, auth_headers):
    resp = client.get("/static/snapshots/no-such-job/frame_0001.jpg", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.parametrize("filename", ["../../../etc/passwd", "..%2f..%2fsecrets.env", "sub/dir.jpg"])
def test_path_traversal_is_rejected(client, seeded_job, media_root, auth_headers, filename):
    resp = client.get(
        f"/static/snapshots/aaaa-bbbb-cccc/{filename}", headers=auth_headers
    )
    assert resp.status_code in (400, 404)
    assert b"root:" not in resp.content


def test_missing_file_under_owned_job_is_not_found(client, seeded_job, media_root, auth_headers):
    resp = client.get(
        "/static/snapshots/aaaa-bbbb-cccc/frame_9999.jpg", headers=auth_headers
    )
    assert resp.status_code == 404


def test_response_is_not_publicly_cacheable(client, seeded_job, media_root, auth_headers):
    """A shared cache must not hold per-user media."""
    resp = client.get(SNAPSHOT_URL, headers=auth_headers)
    assert "public" not in resp.headers.get("cache-control", "").lower()
