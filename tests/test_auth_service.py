"""Unit tests for AuthService: hashing, tokens, registration, authentication."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.auth import AuthService
from app.exceptions import AuthenticationException, ValidationException


# ===========================================================================
# Password Hashing
# ===========================================================================

class TestPasswordHashing:
    def test_hash_differs_from_plaintext(self):
        hashed = AuthService.hash_password("MyPassword1")
        assert hashed != "MyPassword1"

    def test_verify_correct_password(self):
        hashed = AuthService.hash_password("MyPassword1")
        assert AuthService.verify_password("MyPassword1", hashed) is True

    def test_verify_wrong_password(self):
        hashed = AuthService.hash_password("MyPassword1")
        assert AuthService.verify_password("WrongPassword", hashed) is False

    def test_salt_uniqueness(self):
        h1 = AuthService.hash_password("SamePassword")
        h2 = AuthService.hash_password("SamePassword")
        assert h1 != h2

    def test_long_password(self):
        long_pw = "A" * 500 + "b1"
        hashed = AuthService.hash_password(long_pw)
        assert AuthService.verify_password(long_pw, hashed) is True


# ===========================================================================
# Create Access Token
# ===========================================================================

class TestCreateAccessToken:
    def test_sub_claim(self):
        token, _ = AuthService.create_access_token(user_id=42, username="alice")
        payload = AuthService.verify_token(token)
        assert payload.sub == "42"

    def test_username_in_token(self):
        from jose import jwt
        from app.core.config import get_settings
        settings = get_settings()
        token, _ = AuthService.create_access_token(user_id=1, username="bob")
        decoded = jwt.decode(token, settings.jwt.secret_key.get_secret_value(), algorithms=[settings.jwt.algorithm])
        assert decoded["username"] == "bob"

    def test_expiry_time_matches_config(self):
        from app.core.config import get_settings
        settings = get_settings()
        _, expires_in = AuthService.create_access_token(user_id=1, username="u")
        assert expires_in == settings.jwt.access_token_expire_minutes * 60

    def test_custom_delta(self):
        _, expires_in = AuthService.create_access_token(
            user_id=1, username="u", expires_delta=timedelta(hours=2),
        )
        assert expires_in == 7200

    def test_returns_tuple(self):
        result = AuthService.create_access_token(user_id=1, username="u")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], int)


# ===========================================================================
# Verify Token
# ===========================================================================

class TestVerifyToken:
    def test_valid_token(self):
        token, _ = AuthService.create_access_token(user_id=7, username="valid")
        payload = AuthService.verify_token(token)
        assert payload.sub == "7"

    def test_expired_token(self):
        token, _ = AuthService.create_access_token(
            user_id=1, username="u", expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(AuthenticationException):
            AuthService.verify_token(token)

    def test_tampered_token(self):
        token, _ = AuthService.create_access_token(user_id=1, username="u")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(AuthenticationException):
            AuthService.verify_token(tampered)

    def test_missing_sub(self):
        from jose import jwt
        from app.core.config import get_settings
        settings = get_settings()
        payload = {"username": "nosub", "exp": 9999999999, "iat": 1000000000}
        token = jwt.encode(payload, settings.jwt.secret_key.get_secret_value(), algorithm=settings.jwt.algorithm)
        with pytest.raises(AuthenticationException, match="missing subject"):
            AuthService.verify_token(token)


# ===========================================================================
# Register User
# ===========================================================================

class TestRegisterUser:
    def test_creates_row(self, test_db: Session):
        user = AuthService.register_user(test_db, "newuser", "new@example.com", "Password123")
        assert user.id is not None
        assert user.username == "newuser"

    def test_hashes_password(self, test_db: Session):
        user = AuthService.register_user(test_db, "newuser2", "new2@example.com", "Password123")
        assert user.password_hash != "Password123"
        assert AuthService.verify_password("Password123", user.password_hash)

    def test_duplicate_username_rejected(self, test_db: Session):
        AuthService.register_user(test_db, "dup", "dup1@example.com", "Password123")
        with pytest.raises(ValidationException, match="already exists"):
            AuthService.register_user(test_db, "dup", "dup2@example.com", "Password123")

    def test_duplicate_email_rejected(self, test_db: Session):
        AuthService.register_user(test_db, "user1", "same@example.com", "Password123")
        with pytest.raises(ValidationException, match="already registered"):
            AuthService.register_user(test_db, "user2", "same@example.com", "Password123")


# ===========================================================================
# Authenticate User
# ===========================================================================

class TestAuthenticateUser:
    def test_valid_credentials(self, test_db: Session, test_user: User):
        user = AuthService.authenticate_user(test_db, "testuser", "TestPass123")
        assert user.id == test_user.id

    def test_wrong_password(self, test_db: Session, test_user: User):
        with pytest.raises(AuthenticationException, match="Invalid username or password"):
            AuthService.authenticate_user(test_db, "testuser", "WrongPass")

    def test_nonexistent_user(self, test_db: Session):
        with pytest.raises(AuthenticationException, match="Invalid username or password"):
            AuthService.authenticate_user(test_db, "ghost", "Password123")

    def test_inactive_user(self, test_db: Session):
        user = User(
            username="inactive",
            email="inactive@example.com",
            password_hash=AuthService.hash_password("Password123"),
            is_active=False,
        )
        test_db.add(user)
        test_db.commit()

        with pytest.raises(AuthenticationException, match="inactive"):
            AuthService.authenticate_user(test_db, "inactive", "Password123")


# ===========================================================================
# Get Current User
# ===========================================================================

class TestGetCurrentUser:
    def test_valid_token(self, test_db: Session, test_user: User):
        token, _ = AuthService.create_access_token(user_id=test_user.id, username=test_user.username)
        user = AuthService.get_current_user(token, test_db)
        assert user.id == test_user.id

    def test_invalid_token(self, test_db: Session):
        with pytest.raises(AuthenticationException):
            AuthService.get_current_user("totally.invalid.token", test_db)

    def test_deleted_user(self, test_db: Session, test_user: User):
        token, _ = AuthService.create_access_token(user_id=test_user.id, username=test_user.username)
        test_db.delete(test_user)
        test_db.commit()
        with pytest.raises(AuthenticationException, match="not found"):
            AuthService.get_current_user(token, test_db)
