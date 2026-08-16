"""WP4 acceptance: cross-user isolation and operator RBAC contract tests.

Runs on SQLite (shared conftest fixtures) since the semantics under test are
authorization decisions, not locking. PG-specific admission behavior is
covered by tests/test_admission_lease_pg.py.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.rbac import is_operator, OPERATOR_ROLE
from app.db.models import ProcessingJob, ProcessingStatus, User, UserRole
from app.services.auth import AuthService
from tests.test_static_media_auth import media_root  # noqa: F401 (shared fixture)


@pytest.fixture()
def second_user(test_db) -> User:
    user = User(
        username="seconduser",
        email="second@example.com",
        password_hash=AuthService.hash_password("Str0ngSecondPassw0rd!"),
        full_name="Second User",
        is_active=True,
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)
    return user


@pytest.fixture()
def second_headers(client, second_user) -> dict:
    resp = client.post("/api/auth/login", json={
        "username": "seconduser",
        "password": "Str0ngSecondPassw0rd!",
    })
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_ops_jobs_denied_to_ordinary_user(client, auth_headers):
    """Ordinary users get an indistinguishable 404 on the ops surface."""
    resp = client.get("/api/ops/jobs", headers=auth_headers)
    assert resp.status_code == 404
    resp2 = client.get("/api/ops/sidecars", headers=auth_headers)
    assert resp2.status_code == 404


def test_ops_jobs_requires_auth(client):
    resp = client.get("/api/ops/jobs")
    assert resp.status_code == 401


def test_operator_grant_is_durable_and_enforced(test_db, client, auth_headers):
    """A DB-backed grant enables access; revocation denies it."""
    from app.core.api_key_auth import get_current_user
    from app.core.rbac import require_operator
    from app.db.session import SessionLocal

    # Grant operator to the test user via the same durable mechanism the
    # grant tool uses (user_roles row).
    user = test_db.query(User).filter(User.username == "testuser").first()
    test_db.add(UserRole(user_id=user.id, role=OPERATOR_ROLE, granted_by="tests"))
    test_db.commit()

    assert is_operator(test_db, user.id) is True
    resp = client.get("/api/ops/jobs", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)

    # The operator view exposes only the allowlisted fields on rows.
    if body:
        row = body[0]
        allowed = {
            "job_id", "owner_id", "owner_username", "status", "error_message",
            "admission_state", "queue_reason", "queue_position", "sidecar_id",
            "model", "elapsed_seconds", "progress", "processing_mode",
            "created_at",
        }
        assert set(row.keys()) <= allowed, f"leaked fields: {set(row.keys()) - allowed}"
        assert "video_url" not in row
        assert "transcripts" not in row

    # Revocation is enforced immediately (fail closed).
    grant = test_db.query(UserRole).filter(
        UserRole.user_id == user.id, UserRole.role == OPERATOR_ROLE
    ).first()
    grant.revoked_at = pytest.importorskip("datetime").datetime.now()
    test_db.commit()
    assert is_operator(test_db, user.id) is False
    resp = client.get("/api/ops/jobs", headers=auth_headers)
    assert resp.status_code == 404


def test_cross_user_job_isolation(client, seeded_job, second_headers):
    """A user cannot read another user's job by UUID (IDOR guard)."""
    resp = client.get(f"/api/jobs/{seeded_job.job_id}", headers=second_headers)
    assert resp.status_code == 404

    resp = client.get(f"/api/jobs/{seeded_job.job_id}/status", headers=second_headers)
    assert resp.status_code == 404

    resp = client.get(f"/api/jobs/{seeded_job.job_id}/documents", headers=second_headers)
    assert resp.status_code == 404

    resp = client.get(f"/api/jobs/{seeded_job.job_id}/logs", headers=second_headers)
    assert resp.status_code == 404


def test_cross_user_media_isolation(client, seeded_job, media_root, second_headers):
    """Media under another user's job is indistinguishable from missing."""
    for url in ("/static/snapshots/aaaa-bbbb-cccc/frame_0001.jpg",
                "/static/slides/aaaa-bbbb-cccc/frame_0001.jpg"):
        resp = client.get(url, headers=second_headers)
        assert resp.status_code == 404, url


def test_sidecar_available_is_sanitized(client, auth_headers):
    """The user-facing sidecar list never leaks base_url or load telemetry."""
    resp = client.get("/api/sidecars/available", headers=auth_headers)
    assert resp.status_code == 200
    for row in resp.json():
        assert "base_url" not in row
        assert "vram" not in row
        assert "running_requests" not in row
        assert "registered_id" in row
        assert "label" in row
