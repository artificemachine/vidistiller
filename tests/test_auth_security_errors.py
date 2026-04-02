"""Tests ensuring validation error responses never leak user input."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ALLOWED_DETAIL_KEYS = {"loc", "msg", "type"}


def assert_no_input_leak(response):
    """Assert that no detail item contains an 'input' or 'ctx' field."""
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    for item in body["detail"]:
        assert "input" not in item, f"'input' field leaked in error detail: {item}"
        assert "ctx" not in item, f"'ctx' field leaked in error detail: {item}"
        assert set(item.keys()) == ALLOWED_DETAIL_KEYS, (
            f"Unexpected keys in detail item: {set(item.keys()) - ALLOWED_DETAIL_KEYS}"
        )


class TestRegisterValidationNoLeak:
    """Registration validation errors must never expose user input."""

    def test_short_password_no_input_leak(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "Short",
        })
        assert_no_input_leak(resp)
        # Ensure the actual password value is nowhere in the response body
        assert "Short" not in resp.text

    def test_missing_uppercase_no_input_leak(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "alllowercase1",
        })
        assert_no_input_leak(resp)
        assert "alllowercase1" not in resp.text

    def test_missing_digit_no_input_leak(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "NoDigitHere",
        })
        assert_no_input_leak(resp)
        assert "NoDigitHere" not in resp.text

    def test_weak_password_has_readable_msg(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "short",
        })
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        for item in detail:
            assert isinstance(item["msg"], str)
            assert len(item["msg"]) > 5, "Error message should be human-readable"


class TestLoginValidationNoLeak:
    """Login validation errors must never expose user input."""

    def test_empty_body_no_input_leak(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/login", json={})
        assert_no_input_leak(resp)

    def test_missing_password_no_input_leak(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/login", json={"username": "someone"})
        assert_no_input_leak(resp)


class TestAll422ErrorsStripped:
    """Every 422 detail item must contain only loc, msg, type."""

    def test_register_invalid_email(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "not-an-email",
            "password": "GoodPass1",
        })
        assert_no_input_leak(resp)
        assert "not-an-email" not in resp.text

    def test_register_invalid_username_pattern(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={
            "username": "bad user!",
            "email": "test@example.com",
            "password": "GoodPass1",
        })
        assert_no_input_leak(resp)

    def test_register_missing_all_fields(self, client: TestClient, test_db: Session):
        resp = client.post("/api/auth/register", json={})
        assert_no_input_leak(resp)
