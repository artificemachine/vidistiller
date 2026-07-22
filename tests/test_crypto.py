"""Unit tests for backend/app/core/crypto.py — Fernet field-level encryption.

These guard the encrypt/decrypt path that protects every user's stored LLM
API key. Previously had zero coverage at any level (flagged by /golive
Stage 5 /production-ready as the audit's most significant QA finding).

The module caches a Fernet cipher at module scope (double-checked locked).
Each test resets the cache and monkeypatches get_settings() so the cipher is
built against a known key, isolating tests from the host's .env / lru_cache.
"""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.core import crypto


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def fresh_cipher(monkeypatch):
    """Reset the module-level cipher cache and wire a known Fernet key.

    Returns the key so individual tests can build a cross-check Fernet if
    they need to assert something the public API doesn't expose directly.
    """
    key = Fernet.generate_key().decode()
    settings = SimpleNamespace(
        jwt=SimpleNamespace(field_encryption_key=SecretStr(key))
    )
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    monkeypatch.setattr(crypto, "_cipher", None)
    return key


@pytest.fixture
def no_key(monkeypatch):
    """Reset the cipher cache and report FIELD_ENCRYPTION_KEY as unset."""
    settings = SimpleNamespace(
        jwt=SimpleNamespace(field_encryption_key=None)
    )
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    monkeypatch.setattr(crypto, "_cipher", None)


# -----------------------------------------------------------------------------
# Round-trip
# -----------------------------------------------------------------------------

class TestEncryptDecryptRoundTrip:
    def test_roundtrip_returns_original_plaintext(self, fresh_cipher):
        plaintext = "sk-prod-llm-key-1234567890"
        token = crypto.encrypt_field(plaintext)
        assert crypto.decrypt_field(token) == plaintext

    def test_roundtrip_preserves_empty_string(self, fresh_cipher):
        # An empty API key is a real edge case (a saved-but-cleared provider).
        token = crypto.encrypt_field("")
        assert crypto.decrypt_field(token) == ""

    def test_roundtrip_handles_unicode(self, fresh_cipher):
        plaintext = "klíč-ÅÆø-🔑-中文"
        token = crypto.encrypt_field(plaintext)
        assert crypto.decrypt_field(token) == plaintext

    def test_roundtrip_handles_long_input(self, fresh_cipher):
        # Fernet has no practical input-size limit for our use case; sanity-check
        # a value much larger than any real API key.
        plaintext = "x" * 10_000
        token = crypto.encrypt_field(plaintext)
        assert crypto.decrypt_field(token) == plaintext


# -----------------------------------------------------------------------------
# Ciphertext properties
# -----------------------------------------------------------------------------

class TestCiphertextProperties:
    def test_encrypt_returns_str(self, fresh_cipher):
        token = crypto.encrypt_field("hello")
        assert isinstance(token, str)

    def test_encrypt_uses_random_iv_so_repeated_plaintext_differs(self, fresh_cipher):
        # Fernet embeds a random IV + timestamp; the same plaintext must not
        # produce a deterministic ciphertext, or equality checks would leak.
        plaintext = "same-value"
        a = crypto.encrypt_field(plaintext)
        b = crypto.encrypt_field(plaintext)
        assert a != b
        # ...but both must still decrypt back to that same plaintext.
        assert crypto.decrypt_field(a) == plaintext
        assert crypto.decrypt_field(b) == plaintext

    def test_distinct_plaintexts_produce_distinct_ciphertexts(self, fresh_cipher):
        a = crypto.encrypt_field("one")
        b = crypto.encrypt_field("two")
        assert a != b


# -----------------------------------------------------------------------------
# Failure modes
# -----------------------------------------------------------------------------

class TestDecryptFailures:
    def test_decrypt_corrupted_token_raises_invalid_token(self, fresh_cipher):
        token = crypto.encrypt_field("real")
        tampered = token[:-4] + "AAAA"  # flip trailing bytes
        with pytest.raises(InvalidToken):
            crypto.decrypt_field(tampered)

    def test_decrypt_garbage_raises_invalid_token(self, fresh_cipher):
        with pytest.raises(InvalidToken):
            crypto.decrypt_field("not-a-real-fernet-token")

    def test_decrypt_token_from_different_key_raises(self, fresh_cipher, monkeypatch):
        # A token encrypted under key A must not decrypt under key B.
        token = crypto.encrypt_field("secret-under-key-A")

        other_key = Fernet.generate_key().decode()
        other_settings = SimpleNamespace(
            jwt=SimpleNamespace(field_encryption_key=SecretStr(other_key))
        )
        monkeypatch.setattr(crypto, "get_settings", lambda: other_settings)
        monkeypatch.setattr(crypto, "_cipher", None)  # force re-init with new key

        with pytest.raises(InvalidToken):
            crypto.decrypt_field(token)


# -----------------------------------------------------------------------------
# Key-missing guard
# -----------------------------------------------------------------------------

class TestKeyMissingGuard:
    def test_encrypt_raises_runtime_error_when_key_unset(self, no_key):
        with pytest.raises(RuntimeError, match="FIELD_ENCRYPTION_KEY not configured"):
            crypto.encrypt_field("anything")

    def test_decrypt_raises_runtime_error_when_key_unset(self, no_key):
        with pytest.raises(RuntimeError, match="FIELD_ENCRYPTION_KEY not configured"):
            crypto.decrypt_field("some-token")

    def test_blank_key_is_treated_as_unset(self, monkeypatch):
        # .env.example placeholders or an empty env var must not silently fall
        # through to a Fernet key built from an empty string (which would raise
        # a less helpful ValueError deep inside cryptography).
        settings = SimpleNamespace(
            jwt=SimpleNamespace(field_encryption_key=SecretStr(""))
        )
        monkeypatch.setattr(crypto, "get_settings", lambda: settings)
        monkeypatch.setattr(crypto, "_cipher", None)
        with pytest.raises(RuntimeError, match="FIELD_ENCRYPTION_KEY not configured"):
            crypto.encrypt_field("anything")


# -----------------------------------------------------------------------------
# Cipher caching
# -----------------------------------------------------------------------------

class TestCipherCaching:
    def test_get_cipher_returns_same_instance_on_repeated_calls(self, fresh_cipher):
        a = crypto._get_cipher()
        b = crypto._get_cipher()
        assert a is b  # cached singleton, not a fresh Fernet per call
