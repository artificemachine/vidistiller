"""Tests for config validators and exception class hierarchy."""

import pytest
from pydantic import SecretStr, ValidationError
from app.core.config import ApiKeySettings

from app.core.config import JWTSettings, CorsSettings
from app.exceptions import (
    APIException, ValidationException, AuthenticationException,
    ResourceNotFoundException,
)


# ===========================================================================
# JWT Settings Validation
# ===========================================================================

class TestJWTSettingsValidation:
    def test_valid_key(self):
        s = JWTSettings(secret_key=SecretStr("MyStrongProductionKey!2024#SecureApp"))
        assert len(s.secret_key.get_secret_value()) >= 32

    def test_too_short(self):
        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("Short1!"))

    def test_missing_digit(self):
        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("NoDigitsHereAtAllForThisLongKey!!"))

    def test_missing_upper(self):
        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("nouppercase1234567890!longkeynow"))

    def test_missing_lower(self):
        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("NOLOWERCASE1234567890!LONGKEYNOW"))

    def test_long_high_entropy_key_waives_composition_rules(self):
        """`openssl rand -hex 32` is all-lowercase alphanumeric and strong.

        Composition rules exist to stop weak human-chosen keys. Applying them
        to a 64-char random key rejects the safest thing an operator can do.
        """
        s = JWTSettings(secret_key=SecretStr("a" * 4 + "0123456789abcdef" * 4))
        assert s.secret_key is not None

    def test_long_key_with_no_variety_is_still_rejected(self):
        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("a" * 68))

    def test_missing_special(self):
        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("NoSpecialCharacters1234567890Long"))

    def test_change_me_rejected(self):
        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("change-me-please-this-is-long-enough-1234!A"))

    def test_former_hardcoded_default_is_rejected(self):
        # This exact value used to be the built-in default and passed every
        # strength check, so any deployment that never set JWT_SECRET_KEY signed
        # tokens with a secret published in the repo.
        with pytest.raises(ValidationError):
            JWTSettings(
                secret_key=SecretStr("TestSecretKey123!@#abcDEF_development_only")
            )

    def test_env_example_placeholder_is_rejected(self):
        # Shipped in .env.example, and the documented quickstart is
        # `cp .env.example .env`, so this is the value a self-hoster is most
        # likely to leave in place.
        with pytest.raises(ValidationError):
            JWTSettings(
                secret_key=SecretStr("ChangeMe123!ReplaceThisNow_32charsMin")
            )

    @staticmethod
    def _unconfigured(monkeypatch, environment):
        """A JWTSettings with no secret from any source.

        `_env_file=None` matters: the class reads .env, and a developer's local
        .env almost always sets JWT_SECRET_KEY. Without this these tests assert
        against whatever that file happens to contain.
        """
        monkeypatch.setenv("ENVIRONMENT", environment)
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        return lambda: JWTSettings(_env_file=None)

    def test_unset_secret_is_generated_in_non_production(self, monkeypatch):
        build = self._unconfigured(monkeypatch, "development")
        raw = build().secret_key.get_secret_value()
        assert len(raw) >= 32
        assert "development_only" not in raw

    def test_generated_secret_differs_between_instances(self, monkeypatch):
        build = self._unconfigured(monkeypatch, "development")
        assert build().secret_key.get_secret_value() != build().secret_key.get_secret_value(), (
            "generated dev secret must not be a fixed value"
        )

    def test_unset_secret_fails_in_production(self, monkeypatch):
        build = self._unconfigured(monkeypatch, "production")
        with pytest.raises(ValidationError):
            build()


# ===========================================================================
# Environment variable contract
#
# Every deployment artifact (.env.example, docs, docker-compose*.yml) names
# these variables. The class must read exactly those names, or a correctly
# configured deployment silently falls back to an unconfigured value.
# ===========================================================================

class TestJWTSettingsEnvContract:
    KEY = "MyStrongProductionKey!2024#SecureApp"

    def test_reads_jwt_secret_key_env_var(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("JWT_SECRET_KEY", self.KEY)
        assert JWTSettings().secret_key.get_secret_value() == self.KEY

    def test_still_reads_secret_key_env_var(self, monkeypatch):
        """Prod was hand-patched with SECRET_KEY; it must keep working."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.setenv("SECRET_KEY", self.KEY)
        assert JWTSettings().secret_key.get_secret_value() == self.KEY

    def test_jwt_secret_key_wins_over_secret_key(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", self.KEY)
        monkeypatch.setenv("SECRET_KEY", "AnotherStrongKey!2024#DifferentValue")
        assert JWTSettings().secret_key.get_secret_value() == self.KEY

    def test_blank_jwt_secret_key_treated_as_unset_in_development(self, monkeypatch):
        """docker-compose.yml passes JWT_SECRET_KEY: ${JWT_SECRET_KEY} with no
        default, so an unset value in .env arrives in the container as an empty
        string, not an absent variable. A blank secret must fall through to the
        same auto-generate path as a truly-unset one, or a genuinely fresh
        `docker compose up -d` refuses to boot."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET_KEY", "")
        s = JWTSettings(_env_file=None)
        assert len(s.secret_key.get_secret_value()) >= 32

    def test_blank_jwt_secret_key_still_fails_in_production(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", "")
        with pytest.raises(ValidationError):
            JWTSettings(_env_file=None)

    def test_whitespace_only_jwt_secret_key_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET_KEY", "   ")
        s = JWTSettings(_env_file=None)
        assert len(s.secret_key.get_secret_value()) >= 32

    def test_blank_allowed_llm_hosts_falls_back_to_defaults(self, monkeypatch):
        """docker-compose passes `${ALLOWED_LLM_HOSTS:-}`, i.e. an empty string
        when the operator has not set it. Taking that literally would produce an
        empty allowlist and reject the local Ollama the stock install ships."""
        from app.core.config import Settings

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("ALLOWED_LLM_HOSTS", "   ")
        assert "localhost" in Settings().allowed_llm_host_list

    def test_reads_field_encryption_key_env_var(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "a-fernet-key-value")
        s = JWTSettings()
        assert s.field_encryption_key.get_secret_value() == "a-fernet-key-value"


# ===========================================================================
# CORS Settings Parsing
# ===========================================================================

class TestCorsSettingsParsing:
    def test_comma_separated(self):
        s = CorsSettings(origins="http://localhost:3000,http://localhost:8080")
        assert s.origins == ["http://localhost:3000", "http://localhost:8080"]

    def test_json_array(self):
        s = CorsSettings(origins='["http://localhost:3000", "http://localhost:8080"]')
        assert s.origins == ["http://localhost:3000", "http://localhost:8080"]

    def test_list_passthrough(self):
        s = CorsSettings(origins=["http://localhost:3000"])
        assert s.origins == ["http://localhost:3000"]

    def test_single_origin(self):
        s = CorsSettings(origins="http://localhost:3000")
        assert s.origins == ["http://localhost:3000"]


# ===========================================================================
# Exception Class Hierarchy
# ===========================================================================

class TestExceptionClassHierarchy:
    def test_validation_is_api_exception(self):
        exc = ValidationException("test")
        assert isinstance(exc, APIException)
        assert exc.code == "VALIDATION_ERROR"

    def test_auth_is_api_exception(self):
        exc = AuthenticationException("test")
        assert isinstance(exc, APIException)
        assert exc.code == "AUTHENTICATION_ERROR"

    def test_resource_not_found_with_id(self):
        exc = ResourceNotFoundException("Job", "abc-123")
        assert "abc-123" in exc.message
        assert exc.code == "NOT_FOUND"

    def test_resource_not_found_without_id(self):
        exc = ResourceNotFoundException("Job")
        assert "Job not found" in exc.message
        assert exc.code == "NOT_FOUND"


class TestApiKeySettings:
    def test_field_exists(self):
        assert hasattr(ApiKeySettings(), "vidistiller_api_key")

    def test_defaults_to_empty_string(self):
        s = ApiKeySettings()
        assert s.vidistiller_api_key == ""

    def test_accepts_value_from_env(self, monkeypatch):
        monkeypatch.setenv("VIDISTILLER_API_KEY", "test-secret-123")
        s = ApiKeySettings()
        assert s.vidistiller_api_key == "test-secret-123"


# ===========================================================================
# VLLM Fleet Settings — reads VLLM_VM{913,903,901,2900}_URL from env
# ===========================================================================

class TestVLLMFleetSettings:
    def test_defaults_empty(self, monkeypatch):
        for var in ("VLLM_VM913_URL", "VLLM_VM903_URL", "VLLM_VM901_URL", "VLLM_VM2900_URL"):
            monkeypatch.delenv(var, raising=False)
        from app.core.config import VLLMFleetSettings
        s = VLLMFleetSettings()
        assert s.vm913_url == ""
        assert s.vm903_url == ""
        assert s.vm901_url == ""
        assert s.vm2900_url == ""

    def test_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("VLLM_VM913_URL", "http://10.0.150.36:8100")
        monkeypatch.setenv("VLLM_VM903_URL", "http://10.0.150.16:8100")
        monkeypatch.setenv("VLLM_VM901_URL", "http://10.0.150.10:8100")
        monkeypatch.setenv("VLLM_VM2900_URL", "http://10.0.150.20:8100")
        from app.core.config import VLLMFleetSettings
        s = VLLMFleetSettings()
        assert s.vm913_url == "http://10.0.150.36:8100"
        assert s.vm903_url == "http://10.0.150.16:8100"
        assert s.vm901_url == "http://10.0.150.10:8100"
        assert s.vm2900_url == "http://10.0.150.20:8100"

    def test_settings_exposes_vllm_fleet(self):
        from app.core.config import Settings
        s = Settings()
        assert hasattr(s, "vllm_fleet")
        assert hasattr(s.vllm_fleet, "vm913_url")
