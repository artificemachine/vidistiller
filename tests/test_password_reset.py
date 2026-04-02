"""Tests for password reset flow: forgot-password and reset-password endpoints."""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.auth import AuthService


# ===========================================================================
# Forgot Password — POST /api/auth/forgot-password
# ===========================================================================

class TestForgotPasswordEndpoint:
    def test_valid_email_returns_200_and_sends_email(
        self, client: TestClient, test_db: Session, test_user: User
    ):
        with patch(
            "app.routes.auth.EmailService.send_password_reset_email",
            new_callable=AsyncMock,
        ) as mock_send:
            resp = client.post("/api/auth/forgot-password", json={
                "email": "test@example.com",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "message" in data

            # Email should have been queued
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args
            assert call_kwargs[1]["email"] == "test@example.com"
            assert call_kwargs[1]["username"] == "testuser"
            assert "token=" in call_kwargs[1]["reset_link"]

        # Token should be stored on user
        test_db.refresh(test_user)
        assert test_user.password_reset_token is not None
        assert test_user.password_reset_expires is not None

    def test_unknown_email_returns_200_no_email_sent(
        self, client: TestClient, test_db: Session
    ):
        with patch(
            "app.routes.auth.EmailService.send_password_reset_email",
            new_callable=AsyncMock,
        ) as mock_send:
            resp = client.post("/api/auth/forgot-password", json={
                "email": "nobody@example.com",
            })
            assert resp.status_code == 200
            mock_send.assert_not_called()

    def test_invalid_email_format_returns_422(
        self, client: TestClient, test_db: Session
    ):
        resp = client.post("/api/auth/forgot-password", json={
            "email": "not-an-email",
        })
        assert resp.status_code == 422


# ===========================================================================
# Reset Password — POST /api/auth/reset-password
# ===========================================================================

class TestResetPasswordEndpoint:
    def _get_reset_token(
        self, client: TestClient, test_db: Session, test_user: User
    ) -> str:
        """Helper: trigger forgot-password to get a token stored on user."""
        with patch(
            "app.routes.auth.EmailService.send_password_reset_email",
            new_callable=AsyncMock,
        ):
            client.post("/api/auth/forgot-password", json={
                "email": "test@example.com",
            })
        test_db.refresh(test_user)
        return test_user.password_reset_token

    def test_valid_reset_changes_password(
        self, client: TestClient, test_db: Session, test_user: User
    ):
        token = self._get_reset_token(client, test_db, test_user)

        resp = client.post("/api/auth/reset-password", json={
            "token": token,
            "new_password": "NewSecure1",
        })
        assert resp.status_code == 200
        assert "successfully" in resp.json()["message"].lower()

        # Old password should fail
        login_resp = client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "TestPass123",
        })
        assert login_resp.status_code == 401

        # New password should work
        login_resp = client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "NewSecure1",
        })
        assert login_resp.status_code == 200
        assert "access_token" in login_resp.json()

    def test_token_single_use(
        self, client: TestClient, test_db: Session, test_user: User
    ):
        token = self._get_reset_token(client, test_db, test_user)

        # First use succeeds
        resp = client.post("/api/auth/reset-password", json={
            "token": token,
            "new_password": "NewSecure1",
        })
        assert resp.status_code == 200

        # Second use fails
        resp = client.post("/api/auth/reset-password", json={
            "token": token,
            "new_password": "AnotherPass1",
        })
        assert resp.status_code == 401

    def test_bogus_token_returns_401(
        self, client: TestClient, test_db: Session
    ):
        resp = client.post("/api/auth/reset-password", json={
            "token": "not.a.valid.jwt.token",
            "new_password": "NewSecure1",
        })
        assert resp.status_code == 401

    def test_weak_password_returns_422(
        self, client: TestClient, test_db: Session, test_user: User
    ):
        token = self._get_reset_token(client, test_db, test_user)

        # No uppercase
        resp = client.post("/api/auth/reset-password", json={
            "token": token,
            "new_password": "weakpass1",
        })
        assert resp.status_code == 422

    def test_short_password_returns_422(
        self, client: TestClient, test_db: Session, test_user: User
    ):
        token = self._get_reset_token(client, test_db, test_user)

        resp = client.post("/api/auth/reset-password", json={
            "token": token,
            "new_password": "Ab1",
        })
        assert resp.status_code == 422

    def test_access_token_cannot_be_used_as_reset_token(
        self, client: TestClient, test_db: Session, test_user: User
    ):
        """Access tokens have no 'type: password_reset' claim and must be rejected."""
        access_token, _ = AuthService.create_access_token(
            user_id=test_user.id, username=test_user.username
        )
        resp = client.post("/api/auth/reset-password", json={
            "token": access_token,
            "new_password": "NewSecure1",
        })
        assert resp.status_code == 401
