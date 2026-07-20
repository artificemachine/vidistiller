"""
Authentication Service

Handles JWT token generation/validation, password hashing, and user authentication.
Uses bcrypt for password hashing and python-jose for JWT operations.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import logging

from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import User
from app.schemas import TokenPayload
from app.exceptions import AuthenticationException, ValidationException

logger = logging.getLogger(__name__)

# Configure password hashing (argon2id - modern, secure algorithm)
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
)


class AuthService:
    """Service for authentication operations: hashing, token generation, validation."""

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a plain text password using bcrypt.

        Args:
            password: Plain text password to hash

        Returns:
            Hashed password (bcrypt hash)
        """
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Verify a plain text password against a bcrypt hash.

        Args:
            plain_password: Plain text password to verify
            hashed_password: Bcrypt hash to compare against

        Returns:
            True if password matches, False otherwise
        """
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def create_access_token(
        user_id: int,
        username: str,
        expires_delta: Optional[timedelta] = None,
    ) -> Tuple[str, int]:
        """
        Create a JWT access token.

        Args:
            user_id: User database ID
            username: Username for the token
            expires_delta: Custom expiration time (uses config default if not provided)

        Returns:
            Tuple of (token, expires_in_seconds)
        """
        settings = get_settings()

        # Use provided expiration or config default
        if expires_delta is None:
            expires_delta = timedelta(minutes=settings.jwt.access_token_expire_minutes)

        # Calculate expiration timestamp
        now = datetime.now(timezone.utc)
        expire = now + expires_delta
        expires_in_seconds = int(expires_delta.total_seconds())

        # Create JWT payload
        payload = {
            "sub": str(user_id),  # Subject is user ID
            "username": username,
            "iat": now,
            "exp": expire,
            # Every token class is signed with the same key, so the class must be
            # stated explicitly and asserted on the way back in. Without this,
            # verify_token cannot tell an access token from a refresh or
            # password-reset token.
            "type": "access",
        }

        # Encode JWT token
        encoded_jwt = jwt.encode(
            payload,
            settings.jwt.secret_key.get_secret_value(),
            algorithm=settings.jwt.algorithm,
        )

        return encoded_jwt, expires_in_seconds

    @staticmethod
    def create_refresh_token(user_id: int) -> Tuple[str, int]:
        """
        Create a JWT refresh token (longer expiration).

        Args:
            user_id: User database ID

        Returns:
            Tuple of (token, expires_in_seconds)
        """
        settings = get_settings()

        # Refresh token expires in 7 days
        refresh_expires = timedelta(days=7)
        now = datetime.now(timezone.utc)
        expire = now + refresh_expires

        payload = {
            "sub": str(user_id),
            "type": "refresh",
            "iat": now,
            "exp": expire,
        }

        encoded_jwt = jwt.encode(
            payload,
            settings.jwt.secret_key.get_secret_value(),
            algorithm=settings.jwt.algorithm,
        )

        return encoded_jwt, int(refresh_expires.total_seconds())

    @staticmethod
    def verify_refresh_token(token: str) -> int:
        """
        Verify and decode a JWT refresh token.

        Args:
            token: JWT refresh token to verify

        Returns:
            User ID extracted from the token

        Raises:
            AuthenticationException: If token is invalid, expired, or wrong type
        """
        settings = get_settings()

        try:
            payload = jwt.decode(
                token,
                settings.jwt.secret_key.get_secret_value(),
                algorithms=[settings.jwt.algorithm],
            )

            if payload.get("type") != "refresh":
                raise AuthenticationException("Invalid token type: expected refresh token")

            user_id = payload.get("sub")
            if not user_id:
                raise AuthenticationException("Invalid refresh token: missing subject")

            return int(user_id)

        except JWTError as e:
            logger.warning("Refresh token verification failed: %s", e)
            raise AuthenticationException("Invalid or expired refresh token")

    @staticmethod
    def verify_token(token: str) -> TokenPayload:
        """
        Verify and decode a JWT token.

        Args:
            token: JWT token to verify

        Returns:
            TokenPayload with decoded claims

        Raises:
            AuthenticationException: If token is invalid or expired
        """
        settings = get_settings()

        try:
            payload = jwt.decode(
                token,
                settings.jwt.secret_key.get_secret_value(),
                algorithms=[settings.jwt.algorithm],
            )

            # Confine this verifier to access tokens. verify_token backs
            # get_current_user, so whatever it accepts becomes a full API
            # credential. Refresh and password-reset tokens are signed with the
            # same key and also carry "sub", and a reset token is delivered in an
            # emailed URL — so without this check it doubles as a bearer token
            # that survives in browser history and Referer headers.
            # Tokens minted before "type" was introduced have no claim and are
            # rejected here, which forces one re-login on deploy. That is
            # intended.
            if payload.get("type") != "access":
                raise AuthenticationException(
                    "Invalid token type: expected access token"
                )

            user_id: str = payload.get("sub")
            if user_id is None:
                raise AuthenticationException("Invalid token: missing subject")

            return TokenPayload(
                sub=user_id,
                exp=payload.get("exp"),
                iat=payload.get("iat"),
            )

        except JWTError as e:
            logger.warning("Token verification failed: %s", e)
            raise AuthenticationException("Invalid or expired token")

    @staticmethod
    def register_user(
        db: Session,
        username: str,
        email: str,
        password: str,
        full_name: Optional[str] = None,
    ) -> User:
        """
        Register a new user.

        Args:
            db: Database session
            username: Username (must be unique)
            email: Email address (must be unique)
            password: Plain text password
            full_name: Optional full name

        Returns:
            Created User object

        Raises:
            ValidationException: If username/email already exists
        """
        # Check if username exists
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            raise ValidationException(f"Username '{username}' already exists")

        # Check if email exists
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            raise ValidationException(f"Email '{email}' already registered")

        # Hash password and create user
        hashed_password = AuthService.hash_password(password)
        new_user = User(
            username=username,
            email=email,
            password_hash=hashed_password,
            full_name=full_name,
            is_active=True,
        )

        try:
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            logger.info("User registered")
            return new_user
        except Exception as e:
            db.rollback()
            logger.error("User registration failed: %s", e)
            raise ValidationException(f"Failed to register user: {str(e)}")

    @staticmethod
    def authenticate_user(
        db: Session,
        username: str,
        password: str,
    ) -> User:
        """
        Authenticate a user with username and password.

        Args:
            db: Database session
            username: Username or email
            password: Plain text password

        Returns:
            Authenticated User object

        Raises:
            AuthenticationException: If credentials are invalid
        """
        # Try to find user by username or email
        user = db.query(User).filter(
            (User.username == username) | (User.email == username)
        ).first()

        if not user:
            logger.warning("Authentication failed: user not found")
            raise AuthenticationException("Invalid username or password")

        if not AuthService.verify_password(password, user.password_hash):
            logger.warning("Authentication failed: invalid password")
            raise AuthenticationException("Invalid username or password")

        if not user.is_active:
            logger.warning("Authentication failed: inactive user")
            raise AuthenticationException("User account is inactive")

        logger.info("User authenticated")
        return user

    @staticmethod
    def create_password_reset_token(user_id: int, email: str) -> str:
        """
        Create a JWT token for password reset.

        Args:
            user_id: User database ID
            email: User email address

        Returns:
            Encoded JWT token string
        """
        settings = get_settings()
        expires_delta = timedelta(minutes=settings.password_reset.token_expire_minutes)
        now = datetime.now(timezone.utc)
        expire = now + expires_delta

        payload = {
            "sub": str(user_id),
            "email": email,
            "type": "password_reset",
            "iat": now,
            "exp": expire,
        }

        return jwt.encode(
            payload,
            settings.jwt.secret_key.get_secret_value(),
            algorithm=settings.jwt.algorithm,
        )

    @staticmethod
    def verify_password_reset_token(token: str) -> dict:
        """
        Verify and decode a password reset JWT token.

        Args:
            token: JWT token to verify

        Returns:
            Dict with user_id and email

        Raises:
            AuthenticationException: If token is invalid, expired, or wrong type
        """
        settings = get_settings()

        try:
            payload = jwt.decode(
                token,
                settings.jwt.secret_key.get_secret_value(),
                algorithms=[settings.jwt.algorithm],
            )

            if payload.get("type") != "password_reset":
                raise AuthenticationException("Invalid token type")

            user_id = payload.get("sub")
            email = payload.get("email")
            if not user_id or not email:
                raise AuthenticationException("Invalid reset token")

            return {"user_id": int(user_id), "email": email}

        except JWTError as e:
            logger.warning("Password reset token verification failed: %s", e)
            raise AuthenticationException("Invalid or expired reset token")

    @staticmethod
    def reset_password(db: Session, token: str, new_password: str) -> None:
        """
        Reset a user's password using a valid reset token.

        Args:
            db: Database session
            token: Password reset JWT token
            new_password: New plain text password

        Raises:
            AuthenticationException: If token is invalid or already used
        """
        token_data = AuthService.verify_password_reset_token(token)

        user = db.query(User).filter(User.id == token_data["user_id"]).first()
        if not user:
            raise AuthenticationException("User not found")

        if user.password_reset_token != token:
            raise AuthenticationException("Reset token has already been used or is invalid")

        if user.password_reset_expires:
            now = datetime.now(timezone.utc)
            expires = user.password_reset_expires
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now > expires:
                raise AuthenticationException("Reset token has expired")

        user.password_hash = AuthService.hash_password(new_password)
        user.password_reset_token = None
        user.password_reset_expires = None

        try:
            db.commit()
            logger.info("Password reset successful")
        except Exception as e:
            db.rollback()
            logger.error("Password reset failed: %s", e)
            raise AuthenticationException("Failed to reset password")

    @staticmethod
    def get_current_user(token: str, db: Session) -> User:
        """
        Get current user from a JWT token.

        Args:
            token: JWT access token
            db: Database session

        Returns:
            User object

        Raises:
            AuthenticationException: If token is invalid or user not found
        """
        token_payload = AuthService.verify_token(token)

        try:
            user_id = int(token_payload.sub)
        except (ValueError, TypeError):
            raise AuthenticationException("Invalid token format")

        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            logger.warning("User not found for token sub")
            raise AuthenticationException("User not found")

        if not user.is_active:
            raise AuthenticationException("User account is inactive")

        return user
