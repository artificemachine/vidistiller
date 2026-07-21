"""Token revocation via a per-user token_version claim.

A stateless JWT can't be individually revoked, so a leaked token stayed valid
until expiry with no way to kill it. Each access token now carries the user's
token_version; bumping that version (on logout or password reset) invalidates
every token issued before the bump, without a Redis denylist.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.auth import AuthService


class TestTokenVersionClaim:
    def test_token_carries_current_version(self):
        token, _ = AuthService.create_access_token(user_id=1, username="u", token_version=3)
        payload = AuthService.verify_token(token)
        assert payload.tv == 3

    def test_token_defaults_to_version_zero(self):
        token, _ = AuthService.create_access_token(user_id=1, username="u")
        payload = AuthService.verify_token(token)
        assert payload.tv == 0


class TestRevocationEnforced:
    def _make_user(self, db: Session, tv: int = 0) -> User:
        from app.services.auth import AuthService as A
        user = User(
            username="revuser",
            email="rev@example.com",
            password_hash=A.hash_password("Str0ngPass!"),
            token_version=tv,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def test_current_version_token_accepted(self, test_db: Session):
        user = self._make_user(test_db, tv=2)
        token, _ = AuthService.create_access_token(user.id, user.username, token_version=2)
        got = AuthService.get_current_user(token, test_db)
        assert got.id == user.id

    def test_stale_version_token_rejected(self, test_db: Session):
        from app.exceptions import AuthenticationException
        user = self._make_user(test_db, tv=0)
        token, _ = AuthService.create_access_token(user.id, user.username, token_version=0)
        # Simulate logout / password reset bumping the version.
        user.token_version = 1
        test_db.commit()
        import pytest
        with pytest.raises(AuthenticationException):
            AuthService.get_current_user(token, test_db)


class TestLogoutBumpsVersion:
    def test_logout_then_old_token_fails(self, client: TestClient, test_db: Session, test_user, auth_headers):
        # A token minted for test_user works before logout.
        r = client.get("/api/jobs", headers=auth_headers)
        assert r.status_code == 200
        # Logout bumps the user's token_version.
        client.post("/api/auth/logout", headers=auth_headers)
        test_db.expire_all()
        # The same token is now stale.
        r2 = client.get("/api/jobs", headers=auth_headers)
        assert r2.status_code == 401
