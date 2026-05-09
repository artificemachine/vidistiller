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

    def test_missing_special(self):
        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("NoSpecialCharacters1234567890Long"))

    def test_change_me_rejected(self):
        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("change-me-please-this-is-long-enough-1234!A"))

    def test_default_development_key_accepted(self):
        # The default value should pass validation
        s = JWTSettings()
        assert "development" in s.secret_key.get_secret_value()


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
        monkeypatch.setenv("VLLM_VM913_URL", "http://10.255.150.36:8100")
        monkeypatch.setenv("VLLM_VM903_URL", "http://10.255.150.16:8100")
        monkeypatch.setenv("VLLM_VM901_URL", "http://10.255.150.10:8100")
        monkeypatch.setenv("VLLM_VM2900_URL", "http://10.255.150.20:8100")
        from app.core.config import VLLMFleetSettings
        s = VLLMFleetSettings()
        assert s.vm913_url == "http://10.255.150.36:8100"
        assert s.vm903_url == "http://10.255.150.16:8100"
        assert s.vm901_url == "http://10.255.150.10:8100"
        assert s.vm2900_url == "http://10.255.150.20:8100"

    def test_settings_exposes_vllm_fleet(self):
        from app.core.config import Settings
        s = Settings()
        assert hasattr(s, "vllm_fleet")
        assert hasattr(s.vllm_fleet, "vm913_url")
