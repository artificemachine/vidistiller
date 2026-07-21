"""
Authentication Routes

Provides endpoints for user registration, login, token refresh, and user info.
Implements JWT-based authentication with access and refresh tokens.
"""

from datetime import datetime, timedelta, timezone
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status, Header
from typing import Optional
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.schemas import (
    UserCreate,
    UserLogin,
    UserResponse,
    Token,
    PasswordResetRequest,
    PasswordResetConfirm,
    MessageResponse,
)
from app.services.auth import AuthService
from app.services.email import EmailService
from app.core.config import get_settings
from app.core.rate_limit import auth_rate_limit, strict_auth_rate_limit
from app.exceptions import AuthenticationException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_token_from_header(authorization: Optional[str] = Header(None)) -> str:
    """
    Extract JWT token from Authorization header.

    Args:
        authorization: Authorization header value (e.g., "Bearer <token>")

    Returns:
        JWT token string

    Raises:
        AuthenticationException: If header format is invalid or missing
    """
    if not authorization:
        raise AuthenticationException("Missing authorization header")

    if not authorization.startswith("Bearer "):
        raise AuthenticationException("Invalid authorization header format. Expected 'Bearer <token>'")

    return authorization.split(" ", 1)[1]


def get_current_user_from_token(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency to get current authenticated user from JWT token.

    Used with `Depends(get_current_user_from_token)` in protected routes.

    Args:
        authorization: Authorization header from request
        db: Database session

    Returns:
        Authenticated User object

    Raises:
        AuthenticationException: If token is invalid or user not found
    """
    token = get_token_from_header(authorization)
    return AuthService.get_current_user(token, db)


# ==============================================================================
# REGISTER - POST /auth/register
# ==============================================================================

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account",
)
def register(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    _: None = Depends(auth_rate_limit),
) -> UserResponse:
    """
    Register a new user account.

    **Request body:**
    - `username`: Username (3-255 chars, alphanumeric, underscore, hyphen)
    - `email`: Valid email address
    - `password`: Password (8+ chars, must contain uppercase, lowercase, digit)
    - `full_name`: Optional full name

    **Response:** Created user object (without password)

    **Status codes:**
    - 201: User created successfully
    - 422: Invalid input or user already exists
    """
    user = AuthService.register_user(
        db=db,
        username=user_data.username,
        email=user_data.email,
        password=user_data.password,
        full_name=user_data.full_name,
    )

    return UserResponse.model_validate(user)


# ==============================================================================
# LOGIN - POST /auth/login
# ==============================================================================

@router.post(
    "/login",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Login and get JWT token",
    description="Authenticate user and return access token",
)
def login(
    credentials: UserLogin,
    response: Response,
    db: Session = Depends(get_db),
    _: None = Depends(strict_auth_rate_limit),
) -> Token:
    """
    Authenticate user and return JWT access token.

    **Request body:**
    - `username`: Username or email address
    - `password`: Plain text password

    **Response:** JWT access token with expiration time

    **Status codes:**
    - 200: Authentication successful
    - 401: Invalid username or password
    - 422: User account inactive
    """
    user = AuthService.authenticate_user(
        db=db,
        username=credentials.username,
        password=credentials.password,
    )

    access_token, expires_in = AuthService.create_access_token(
        user_id=user.id,
        username=user.username,
        token_version=user.token_version,
    )
    refresh_token_str, _ = AuthService.create_refresh_token(user_id=user.id)

    # Set HttpOnly cookie for Next.js SSR middleware route protection.
    # HttpOnly prevents XSS access; max_age matches the access token lifetime.
    response.set_cookie(
        key="auth_token",
        value=access_token,
        max_age=expires_in,
        httponly=True,
        samesite="lax",
        path="/",
    )

    return Token(
        access_token=access_token,
        refresh_token=refresh_token_str,
        token_type="bearer",
        expires_in=expires_in,
    )


# ==============================================================================
# GET CURRENT USER - GET /auth/me
# ==============================================================================

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user info",
    description="Retrieve authenticated user information",
)
def get_me(
    user: User = Depends(get_current_user_from_token),
) -> UserResponse:
    """
    Retrieve information about the currently authenticated user.

    **Required:** Bearer token in Authorization header

    **Response:** Current user object

    **Status codes:**
    - 200: User info retrieved successfully
    - 401: Missing or invalid token
    """
    response = UserResponse.model_validate(user)
    # Set has_api_key based on whether encrypted key is stored
    response.has_api_key = bool(user.llm_api_key_encrypted)
    return response


# ==============================================================================
# REFRESH TOKEN - POST /auth/refresh
# ==============================================================================

@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token",
    description="Generate new access token from existing token",
)
def refresh_token(
    authorization: Optional[str] = Header(None),
    response: Response = None,
    db: Session = Depends(get_db),
) -> Token:
    """
    Refresh an access token.

    Validates the current token and issues a new one with the same user.
    This allows long-running sessions without requiring re-authentication.

    **Required:** Bearer token in Authorization header

    **Response:** New JWT access token

    **Status codes:**
    - 200: Token refreshed successfully
    - 401: Invalid or expired token
    """
    token = get_token_from_header(authorization)

    # Validate this is a refresh token (not an access token)
    user_id = AuthService.verify_refresh_token(token)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AuthenticationException("User not found")
    if not user.is_active:
        raise AuthenticationException("User account is inactive")

    # Issue new access token and rotate refresh token
    new_access_token, expires_in = AuthService.create_access_token(
        user_id=user.id,
        username=user.username,
        token_version=user.token_version,
    )
    new_refresh_token, _ = AuthService.create_refresh_token(user_id=user.id)

    if response is not None:
        response.set_cookie(
            key="auth_token",
            value=new_access_token,
            max_age=expires_in,
            httponly=True,
            samesite="lax",
            path="/",
        )

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


# ==============================================================================
# LOGOUT - POST /auth/logout
# ==============================================================================

@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout user",
    description="Invalidate user session (client should discard token)",
)
def logout(
    user: User = Depends(get_current_user_from_token),
    response: Response = None,
    db: Session = Depends(get_db),
) -> None:
    """
    Logout the current user and revoke outstanding tokens.

    Bumps the user's token_version, which invalidates every access token issued
    before now — including this one and any issued to another device. The
    HttpOnly auth_token cookie is also cleared so the Next.js middleware stops
    treating the session as authenticated.

    **Required:** Bearer token in Authorization header

    **Status codes:**
    - 204: Logout successful
    - 401: Missing or invalid token
    """
    user.token_version = (user.token_version or 0) + 1
    db.commit()

    if response is not None:
        response.delete_cookie(key="auth_token", path="/", samesite="lax")


# ==============================================================================
# FORGOT PASSWORD - POST /auth/forgot-password
# ==============================================================================

@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a password reset email",
    description="Send a password reset link to the user's email address",
)
async def forgot_password(
    body: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: None = Depends(auth_rate_limit),
) -> MessageResponse:
    """
    Request a password reset email.

    Always returns 200 to prevent email enumeration.
    If the email exists, a reset link is sent.

    **Request body:**
    - `email`: Email address associated with the account

    **Response:** Success message (regardless of whether email exists)
    """
    settings = get_settings()
    user = db.query(User).filter(User.email == body.email).first()

    if user:
        token = AuthService.create_password_reset_token(user.id, user.email)

        user.password_reset_token = token
        user.password_reset_expires = datetime.now(timezone.utc) + timedelta(
            minutes=settings.password_reset.token_expire_minutes
        )
        db.commit()

        reset_link = f"{settings.password_reset.frontend_reset_url}?token={token}"

        background_tasks.add_task(
            EmailService.send_password_reset_email,
            email=user.email,
            username=user.username,
            reset_link=reset_link,
        )

    return MessageResponse(
        message="If an account with that email exists, a password reset link has been sent."
    )


# ==============================================================================
# RESET PASSWORD - POST /auth/reset-password
# ==============================================================================

@router.post(
    "/reset-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset password with token",
    description="Set a new password using a valid reset token",
)
def reset_password(
    body: PasswordResetConfirm,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """
    Reset password using a valid token from the reset email.

    **Request body:**
    - `token`: Password reset token from the email link
    - `new_password`: New password (8+ chars, uppercase, lowercase, digit)

    **Response:** Success message

    **Status codes:**
    - 200: Password reset successfully
    - 401: Invalid or expired token
    - 422: Password doesn't meet complexity requirements
    """
    AuthService.reset_password(db=db, token=body.token, new_password=body.new_password)
    return MessageResponse(message="Password has been reset successfully.")
