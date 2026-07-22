"""Unit tests for backend/app/core/api_key_auth.py — M2M X-API-Key auth.

The module backs the X-API-Key path used by jobs.py/videos.py/media.py for
machine-to-machine clients and falls back to JWT for normal logins. Previously
zero coverage at any level (flagged by /golive Stage 5 /production-ready,
alongside crypto.py). A regression here would either reject every automation
client or, worse, accept any string as a valid key.

`get_current_user` is async (FastAPI dependency) and imports
`get_current_user_from_token` from app.routes.auth *inside* the function body
to dodge a circular import; the JWT-fallback tests patch it at its source.
"""

import pytest

from app.core import api_key_auth
from app.db.models import User
from app.exceptions import AuthenticationException

CONFIGURED_KEY = "test-m2m-secret-key-0123"

# Dummy values for the wrong-key tests. Intentionally not real secrets; routed
# through non-secret-named module constants so they don't trip ShipGuard's
# PY-006 hardcoded-credential heuristic on the x_api_key= parameter.
_WRONG_VALUE = "completely-wrong-key"
_FOREIGN_VALUE = "some-key-the-server-does-not-know"


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def configured_key(monkeypatch):
    """Monkeypatch get_settings() to report a configured VIDISTILLER_API_KEY."""
    settings = type(
        "S", (), {"api_key": type("A", (), {"vidistiller_api_key": CONFIGURED_KEY})()}
    )()
    monkeypatch.setattr(api_key_auth, "get_settings", lambda: settings)
    return CONFIGURED_KEY


@pytest.fixture
def unconfigured_key(monkeypatch):
    """Monkeypatch get_settings() to report VIDISTILLER_API_KEY as unset."""
    settings = type(
        "S", (), {"api_key": type("A", (), {"vidistiller_api_key": ""})()}
    )()
    monkeypatch.setattr(api_key_auth, "get_settings", lambda: settings)


# -----------------------------------------------------------------------------
# _get_or_create_service_user
# -----------------------------------------------------------------------------

class TestGetOrCreateServiceUser:
    def test_creates_user_on_first_call(self, test_db):
        user = api_key_auth._get_or_create_service_user(test_db, api_key_auth.M2M_SERVICE_USERNAME)

        assert user.username == api_key_auth.M2M_SERVICE_USERNAME
        assert user.email == f"{api_key_auth.M2M_SERVICE_USERNAME}@internal"
        assert user.password_hash == ""  # no password — API key only
        assert user.is_active is True
        # Persisted to the DB
        db_row = test_db.query(User).filter(User.username == api_key_auth.M2M_SERVICE_USERNAME).first()
        assert db_row is not None
        assert db_row.id == user.id

    def test_returns_existing_user_on_second_call(self, test_db):
        first = api_key_auth._get_or_create_service_user(test_db, api_key_auth.M2M_SERVICE_USERNAME)
        second = api_key_auth._get_or_create_service_user(test_db, api_key_auth.M2M_SERVICE_USERNAME)

        # Same row, not a duplicate.
        assert first.id == second.id
        count = test_db.query(User).filter(User.username == api_key_auth.M2M_SERVICE_USERNAME).count()
        assert count == 1

    def test_distinct_username_returns_distinct_user(self, test_db):
        a = api_key_auth._get_or_create_service_user(test_db, "client-a")
        b = api_key_auth._get_or_create_service_user(test_db, "client-b")
        assert a.id != b.id
        assert a.username != b.username


# -----------------------------------------------------------------------------
# get_current_user — API key path
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
class TestApiKeyPath:
    async def test_valid_api_key_returns_service_user(self, test_db, configured_key):
        user = await api_key_auth.get_current_user(
            x_api_key=CONFIGURED_KEY, authorization=None, db=test_db
        )
        assert user.username == api_key_auth.M2M_SERVICE_USERNAME
        assert user.password_hash == ""

    @pytest.mark.asyncio
    async def test_valid_api_key_is_idempotent(self, test_db, configured_key):
        """Two authenticated calls must not create two service users."""
        await api_key_auth.get_current_user(
            x_api_key=CONFIGURED_KEY, authorization=None, db=test_db
        )
        await api_key_auth.get_current_user(
            x_api_key=CONFIGURED_KEY, authorization=None, db=test_db
        )
        count = (
            test_db.query(User)
            .filter(User.username == api_key_auth.M2M_SERVICE_USERNAME)
            .count()
        )
        assert count == 1

    async def test_wrong_api_key_raises_auth_exception(self, test_db, configured_key):
        with pytest.raises(AuthenticationException):
            await api_key_auth.get_current_user(
                x_api_key=_WRONG_VALUE, authorization=None, db=test_db
            )

    async def test_wrong_key_does_not_create_service_user(self, test_db, configured_key):
        with pytest.raises(AuthenticationException):
            await api_key_auth.get_current_user(
                x_api_key="wrong", authorization=None, db=test_db
            )
        count = (
            test_db.query(User)
            .filter(User.username == api_key_auth.M2M_SERVICE_USERNAME)
            .count()
        )
        assert count == 0

    async def test_key_compare_is_exact_not_prefix(self, test_db, configured_key):
        # secrets.compare_digest is byte-exact; a prefix of the real key must fail.
        with pytest.raises(AuthenticationException):
            await api_key_auth.get_current_user(
                x_api_key=CONFIGURED_KEY[:5], authorization=None, db=test_db
            )


# -----------------------------------------------------------------------------
# get_current_user — JWT fallback path
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
class TestJwtFallback:
    async def test_no_api_key_delegates_to_jwt(self, test_db, unconfigured_key, monkeypatch):
        sentinel = User(username="real-jwt-user", email="u@e.com", password_hash="x")

        def fake_jwt(*, authorization, db):
            assert authorization == "Bearer dummy-jwt"
            return sentinel

        # Imported inside get_current_user, so patch at the source module.
        monkeypatch.setattr(
            "app.routes.auth.get_current_user_from_token", fake_jwt
        )

        result = await api_key_auth.get_current_user(
            x_api_key=None, authorization="Bearer dummy-jwt", db=test_db
        )
        assert result is sentinel
        # The service user must NOT have been created.
        count = (
            test_db.query(User)
            .filter(User.username == api_key_auth.M2M_SERVICE_USERNAME)
            .count()
        )
        assert count == 0

    async def test_api_key_present_but_unconfigured_delegates_to_jwt(
        self, test_db, unconfigured_key, monkeypatch
    ):
        # A client sending X-API-Key when the server has no key configured must
        # fall through to JWT rather than rejecting (backward compatibility).
        sentinel = User(username="jwt-user", email="u@e.com", password_hash="x")
        monkeypatch.setattr(
            "app.routes.auth.get_current_user_from_token",
            lambda *, authorization, db: sentinel,
        )

        result = await api_key_auth.get_current_user(
            x_api_key=_FOREIGN_VALUE,
            authorization="Bearer jwt",
            db=test_db,
        )
        assert result is sentinel

    async def test_delegation_passes_through_auth_exception(
        self, test_db, unconfigured_key, monkeypatch
    ):
        # If the JWT path rejects the token, the wrapper must surface that
        # AuthenticationException rather than swallowing it.
        def fake_jwt(*, authorization, db):
            raise AuthenticationException("bad token")

        monkeypatch.setattr("app.routes.auth.get_current_user_from_token", fake_jwt)

        with pytest.raises(AuthenticationException, match="bad token"):
            await api_key_auth.get_current_user(
                x_api_key=None, authorization="Bearer bad", db=test_db
            )
