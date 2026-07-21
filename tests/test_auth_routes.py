"""Integration tests for auth routes: register, login, me, refresh, logout."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.auth import AuthService


# ===========================================================================
# Register Endpoint — POST /api/auth/register
# ===========================================================================

class TestRegisterEndpoint:
    def test_register_success_201(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "StrongPass1",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "alice"
        assert data["email"] == "alice@example.com"

    def test_no_password_hash_in_response(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "StrongPass1",
        })
        data = resp.json()
        assert "password_hash" not in data
        assert "password" not in data

    def test_duplicate_username(self, client: TestClient, test_db: Session, test_user: User):
        resp = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "other@example.com",
            "password": "StrongPass1",
        })
        # ValidationException -> 422 or 400 via exception handlers
        assert resp.status_code in (400, 422)

    def test_invalid_email(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "charlie",
            "email": "not-an-email",
            "password": "StrongPass1",
        })
        assert resp.status_code == 422

    def test_weak_password_no_uppercase(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "david",
            "email": "david@example.com",
            "password": "weakpass1",
        })
        assert resp.status_code == 422

    def test_bad_username_special_chars(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "bad user!",
            "email": "bad@example.com",
            "password": "StrongPass1",
        })
        assert resp.status_code == 422


# ===========================================================================
# Login Endpoint — POST /api/auth/login
# ===========================================================================

class TestLoginEndpoint:
    def test_valid_login(self, client: TestClient, test_db: Session, test_user: User):
        resp = client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "TestPass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_wrong_password(self, client: TestClient, test_db: Session, test_user: User):
        resp = client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "WrongPassword1",
        })
        # AuthenticationException -> 401 via dedicated handler
        assert resp.status_code == 401

    def test_nonexistent_user(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/login", json={
            "username": "ghost",
            "password": "Password123",
        })
        assert resp.status_code == 401

    def test_expires_in_positive(self, client: TestClient, test_db: Session, test_user: User):
        resp = client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "TestPass123",
        })
        assert resp.json()["expires_in"] > 0

    def test_email_login(self, client: TestClient, test_db: Session, test_user: User):
        resp = client.post("/api/auth/login", json={
            "username": "test@example.com",
            "password": "TestPass123",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()


# ===========================================================================
# Me Endpoint — GET /api/auth/me
# ===========================================================================

class TestMeEndpoint:
    def test_valid_token(self, client: TestClient, test_db: Session, test_user: User, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"

    def test_missing_token(self, client: TestClient, test_db: Session):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_wrong_format(self, client: TestClient, test_db: Session):
        resp = client.get("/api/auth/me", headers={"Authorization": "Basic abc123"})
        assert resp.status_code == 401

    def test_malformed_token(self, client: TestClient, test_db: Session):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
        assert resp.status_code == 401


# ===========================================================================
# Refresh Endpoint — POST /api/auth/refresh
# ===========================================================================

class TestRefreshEndpoint:
    def test_valid_refresh(self, client: TestClient, test_db: Session, test_user: User, refresh_headers):
        resp = client.post("/api/auth/refresh", headers=refresh_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_access_token_rejected(self, client: TestClient, test_db: Session, test_user: User, auth_headers):
        """Access tokens must not be accepted at the refresh endpoint."""
        resp = client.post("/api/auth/refresh", headers=auth_headers)
        assert resp.status_code == 401

    def test_new_token_differs(self, client: TestClient, test_db: Session, test_user: User, refresh_headers):
        import time
        # JWT encodes iat as integer seconds — wait so the new token gets a different iat
        time.sleep(1.1)
        resp = client.post("/api/auth/refresh", headers=refresh_headers)
        new_token = resp.json()["access_token"]
        old_token = refresh_headers["Authorization"].split(" ")[1]
        assert new_token != old_token

    def test_missing_token(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/refresh")
        assert resp.status_code == 401


# ===========================================================================
# Logout Endpoint — POST /api/auth/logout
# ===========================================================================

class TestLogoutEndpoint:
    def test_valid_logout(self, client: TestClient, test_db: Session, test_user: User, auth_headers):
        resp = client.post("/api/auth/logout", headers=auth_headers)
        assert resp.status_code == 204

    def test_missing_token(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 401

    def test_token_revoked_after_logout(self, client: TestClient, test_db: Session, test_user: User, auth_headers):
        # Logout bumps token_version, revoking the token used to log out.
        client.post("/api/auth/logout", headers=auth_headers)
        test_db.expire_all()
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 401
