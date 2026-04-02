"""
Field-level encryption utilities using Fernet symmetric encryption.

Used to encrypt sensitive data like API keys before storing in the database.
Key is loaded from settings.jwt.field_encryption_key.
"""

import threading

from cryptography.fernet import Fernet
from app.core.config import get_settings


_cipher: Fernet | None = None
_cipher_lock = threading.Lock()


def _get_cipher() -> Fernet:
    """Initialize and cache the Fernet cipher from settings (thread-safe)."""
    global _cipher

    if _cipher is None:
        with _cipher_lock:
            if _cipher is None:  # double-checked locking
                settings = get_settings()
                if not settings.jwt.field_encryption_key:
                    raise RuntimeError(
                        "FIELD_ENCRYPTION_KEY not configured. "
                        "Generate with: python -c \"from cryptography.fernet import Fernet; "
                        "print(Fernet.generate_key().decode())\" and set in .env"
                    )
                key = settings.jwt.field_encryption_key.get_secret_value()
                _cipher = Fernet(key.encode())

    return _cipher


def encrypt_field(plaintext: str) -> str:
    """
    Encrypt a plaintext string using Fernet symmetric encryption.

    Args:
        plaintext: The string to encrypt (e.g., API key)

    Returns:
        Base64-encoded encrypted token suitable for storage in database
    """
    cipher = _get_cipher()
    token = cipher.encrypt(plaintext.encode())
    return token.decode()


def decrypt_field(token: str) -> str:
    """
    Decrypt an encrypted token back to plaintext.

    Args:
        token: The encrypted token (as returned by encrypt_field)

    Returns:
        Decrypted plaintext string

    Raises:
        cryptography.fernet.InvalidToken: If token is invalid or corrupted
    """
    cipher = _get_cipher()
    plaintext = cipher.decrypt(token.encode())
    return plaintext.decode()
