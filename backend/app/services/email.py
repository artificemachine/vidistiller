"""
Email Service

Handles sending transactional emails (password reset, etc.) using fastapi-mail.
"""

import logging

from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _get_mail_config() -> ConnectionConfig:
    """Build fastapi-mail ConnectionConfig from application settings."""
    settings = get_settings()
    return ConnectionConfig(
        MAIL_USERNAME=settings.email.MAIL_USERNAME,
        MAIL_PASSWORD=settings.email.MAIL_PASSWORD.get_secret_value(),
        MAIL_FROM=settings.email.MAIL_FROM,
        MAIL_PORT=settings.email.MAIL_PORT,
        MAIL_SERVER=settings.email.MAIL_SERVER,
        MAIL_STARTTLS=settings.email.MAIL_STARTTLS,
        MAIL_SSL_TLS=settings.email.MAIL_SSL_TLS,
        USE_CREDENTIALS=bool(settings.email.MAIL_USERNAME),
    )


class EmailService:
    """Service for sending transactional emails."""

    @staticmethod
    async def send_password_reset_email(
        email: str,
        username: str,
        reset_link: str,
    ) -> None:
        """
        Send a password reset email with a clickable reset link.

        Args:
            email: Recipient email address
            username: Username for personalisation
            reset_link: Full URL with token for resetting the password
        """
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #2563eb;">Password Reset Request</h2>
            <p>Hi {username},</p>
            <p>We received a request to reset your password. Click the button below to set a new password:</p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="{reset_link}"
                   style="background-color: #2563eb; color: white; padding: 12px 32px;
                          text-decoration: none; border-radius: 8px; font-weight: bold;">
                    Reset Password
                </a>
            </div>
            <p>If you didn't request this, you can safely ignore this email.
               The link will expire in 1 hour.</p>
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;" />
            <p style="color: #6b7280; font-size: 12px;">
                This is an automated message. Please do not reply.
            </p>
        </body>
        </html>
        """

        message = MessageSchema(
            subject="Password Reset Request",
            recipients=[email],
            body=html_body,
            subtype=MessageType.html,
        )

        conf = _get_mail_config()
        fm = FastMail(conf)

        try:
            await fm.send_message(message)
            logger.info(f"Password reset email sent to {email}")
        except Exception as e:
            logger.error(f"Failed to send password reset email to {email}: {e}")
            raise
