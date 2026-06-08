# Backend Core Configuration
# This file defines all application settings and configurations

from typing import Optional, Union
from enum import Enum
from functools import lru_cache
import string

from pydantic import SecretStr, HttpUrl, field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ==============================================================================
# INDIVIDUAL SETTINGS CLASSES (in order of dependency)
# ==============================================================================


# Configure database connection URL (set DATABASE_URL env var in production)
class DatabaseSettings(BaseSettings):
    """Database connection settings."""

    DATABASE_URL: str = "sqlite:///./dev.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Configure API keys for external services
class OllamaSettings(BaseSettings):
    """Ollama LLM service settings."""

    # API key is optional and masked in logs for security
    api_key: Optional[SecretStr] = None

    # Validates that the URL is a real web address
    base_url: HttpUrl = Field(default="http://localhost:11434", validation_alias="OLLAMA_URL")

    # Defaulting to an Ollama-native model name like 'llama3' or 'mistral'
    model_name: str = Field(default="llama3", validation_alias="OLLAMA_MODEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class YouTubeSettings(BaseSettings):
    """YouTube API settings."""

    api_key: Optional[SecretStr] = None
    # You can validate that the base URL is a real URL
    base_url: HttpUrl = "https://www.googleapis.com/youtube/v3"

    # You can validate that the channel ID is a valid YouTube channel ID
    channel_ids: Optional[list[str]] = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Configure CORS allowed origins
class CorsSettings(BaseSettings):
    """
    CORS (Cross-Origin Resource Sharing) configuration.

    A list of origins is a whitelist of web addresses (protocols, domains, and ports)
    that your backend trustingly allows to access its data.
    """

    # A list of origins that are allowed to make requests
    # Default to an empty list for safety
    origins: list[str] = []

    @field_validator("origins", mode="before")
    @classmethod
    def parse_origins(cls, v: Union[str, list[str]]) -> list[str]:
        """
        Parse origins from environment variable or direct input.

        Pydantic validators run before the field is saved. This one handles
        the case where origins come from an environment variable (string)
        vs direct Python code (list).

        Args:
            cls: CorsSettings class
            v: Value being passed in - can be a string (from env var) or list

        Returns:
            list[str]: Clean list of origins
        """
        import json
        # If it's already a list, return as-is
        if isinstance(v, list):
            return v
        # If the input looks like a JSON array, parse it properly
        if isinstance(v, str) and v.startswith("["):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(i).strip() for i in parsed]
            except json.JSONDecodeError:
                pass
        # Otherwise, split by commas
        if isinstance(v, str):
            return [i.strip() for i in v.split(",")]
        return v

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_prefix="CORS_")


# Configure logging levels and formats
class LoggingSettings(BaseSettings):
    """Logging configuration."""

    # See .env to override this value
    LOG_LEVEL: str = "INFO"
    # Log format for console output
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Authentication & JWT
class JWTSettings(BaseSettings):
    """
    JWT (JSON Web Token) authentication settings.

    Secret Keys: Your JWT_SECRET_KEY should be a SecretStr. Never hardcode a default
    value for production; use a "factory" or leave it without a default to force the
    developer to set it in the .env.

    Algorithms: Set ALGORITHM: str = "HS256" as a default.

    Expirations: Use int values for ACCESS_TOKEN_EXPIRE_MINUTES.
    """

    # Use SecretStr to prevent accidental logging of the key
    # Should be overridden in .env for production (minimum 32 chars with complexity)
    # For development, use: TestSecretKey123!@#abcDEF
    secret_key: SecretStr = SecretStr("TestSecretKey123!@#abcDEF_development_only")

    # Field encryption key for Fernet symmetric encryption of API keys and secrets
    # Should be overridden in .env for production
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    field_encryption_key: Optional[SecretStr] = None

    # Standard JWT defaults
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    @field_validator("secret_key", mode="after")
    @classmethod
    def validate_jwt_secret(cls, v: SecretStr) -> SecretStr:
        """Validate JWT secret key strength and format."""
        raw_value = v.get_secret_value()

        # 1. Length Check
        if len(raw_value) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")

        # 2. Default Value Check (only fail if it looks like placeholder)
        if "change-me" in raw_value.lower():
            raise ValueError("JWT_SECRET_KEY must be changed from the default value")

        # 3. Digit Check
        if not any(c.isdigit() for c in raw_value):
            raise ValueError("JWT_SECRET_KEY must contain at least one digit")

        # 4. Casing Check (Ensures BOTH exist)
        if not any(c.isupper() for c in raw_value):
            raise ValueError(
                "JWT_SECRET_KEY must contain at least one uppercase letter"
            )
        if not any(c.islower() for c in raw_value):
            raise ValueError(
                "JWT_SECRET_KEY must contain at least one lowercase letter"
            )

        # 5. Special Character Check
        # Using string.punctuation: !"#$%&'()*+,-./:;<=>?@[\]^_`{|}~
        if not any(c in string.punctuation for c in raw_value):
            raise ValueError(
                "JWT_SECRET_KEY must contain at least one special character"
            )

        return v

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Configure service timeouts
class ServiceTimeouts(BaseSettings):
    """Service timeout configuration."""

    YOUTUBE_API_TIMEOUT: int = 30  # seconds
    DOC_CONVERSION_TIMEOUT: int = 60  # seconds
    whisper_timeout: int = 300  # seconds (5 min for audio transcription)
    llm_timeout: int = 120  # seconds (2 min for LLM generation)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Configure rate limiting parameters
class RateLimitingConfig(BaseSettings):
    """Rate limiting configuration."""

    MAX_REQUESTS_PER_MINUTE: int = 100
    RATE_LIMIT_WINDOW: int = 60  # seconds
    ENABLE_RATE_LIMITING: bool = True

    model_config = SettingsConfigDict(env_prefix="RATE_LIMIT_", case_sensitive=False, env_file=".env", extra="ignore")


# Configure cache settings
class CacheSettings(BaseSettings):
    """Cache configuration for Redis."""

    cache_type: str = Field(default="redis", description="Cache backend type")
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_password: str | None = Field(default=None, description="Redis password")
    cache_ttl: int = Field(default=3600, description="Default cache TTL in seconds")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


# Define feature flags
class FeatureFlags(BaseSettings):
    """Feature flags for enabling/disabling functionality."""

    ENABLE_ANALYTICS: bool = True
    ENABLE_LOGGING: bool = True
    ENABLE_METRICS: bool = True
    ENABLE_DEBUG_MODE: bool = False

    model_config = SettingsConfigDict(env_prefix="FEATURE_", case_sensitive=False, env_file=".env", extra="ignore")


class EmailSettings(BaseSettings):
    """SMTP email configuration for sending transactional emails."""

    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: SecretStr = SecretStr("")
    MAIL_FROM: str = "noreply@example.com"
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_PORT: int = 587
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class PasswordResetSettings(BaseSettings):
    """Password reset token configuration."""

    token_expire_minutes: int = Field(default=60, validation_alias="PASSWORD_RESET_EXPIRE_MINUTES")
    frontend_reset_url: str = Field(default="http://localhost:3000/reset-password", validation_alias="PASSWORD_RESET_URL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class SentrySettings(BaseSettings):
    """Sentry error monitoring configuration."""

    dsn: str = ""
    enabled: bool = False
    environment: str = "development"
    traces_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)

    model_config = SettingsConfigDict(env_prefix="SENTRY_", env_file=".env", extra="ignore")


class ApiKeySettings(BaseSettings):
    """Machine-to-machine API key for trusted internal services (e.g. Semblar)."""

    vidistiller_api_key: str = Field(default="", validation_alias="VIDISTILLER_API_KEY")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class VLLMFleetSettings(BaseSettings):
    """vLLM server URLs for the on-prem GPU fleet.

    Each VM runs vLLM directly on port 8000 (OpenAI-compatible /v1/chat/completions).
    vllm-manager on port 8100 is used only for model discovery/swapping, NOT for
    inference requests — it blocks /v1/chat/completions with 409.
    URLs are read from env so the fleet can be reconfigured without code changes.
    """

    vm913_url: str = Field(default="", validation_alias="VLLM_VM913_URL")
    vm903_url: str = Field(default="", validation_alias="VLLM_VM903_URL")
    vm901_url: str = Field(default="", validation_alias="VLLM_VM901_URL")
    vm2900_url: str = Field(default="", validation_alias="VLLM_VM2900_URL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class StorageSettings(BaseSettings):
    """File storage and upload configuration."""

    data_dir: str = Field(default="", validation_alias="DATA_DIR")
    max_import_size_bytes: int = Field(
        default=100 * 1024 * 1024,  # 100 MB
        validation_alias="MAX_IMPORT_SIZE_BYTES",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Transcript confidence scores — named constants instead of inline magic numbers.
# YouTube's own captions are authoritative transcripts; lower score reflects minor
# formatting artefacts (auto-timing, HTML entities). Whisper is a local model with
# high word-level accuracy on clean audio, hence the higher score.
TRANSCRIPT_CONFIDENCE_CAPTIONS: float = 0.85   # youtube_captions / yt_dlp_captions
TRANSCRIPT_CONFIDENCE_WHISPER: float = 0.90    # whisper_local


class SlideDetectionSettings(BaseSettings):
    """Configuration for slide detection in presentation-style videos."""

    ssim_threshold: float = 0.85
    ssim_ambiguous_low: float = 0.85
    ssim_ambiguous_high: float = 0.93
    sampling_fps: float = 1.0
    min_slide_duration: float = 3.0
    llm_model: str = "mistral"
    llm_timeout: int = 30
    ocr_enabled: bool = True
    layout_sample_count: int = 5
    incremental_ssim_threshold: float = 0.95

    model_config = SettingsConfigDict(env_prefix="SLIDE_", case_sensitive=False, env_file=".env", extra="ignore")


# Add environment-specific settings (dev, test, prod)
class Environment(str, Enum):
    """Application environment."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"

# Combine all settings
class Settings(BaseSettings):
    """
    Main settings class that combines all application configuration.

    This is the single source of truth for all application settings.
    Load from environment variables and .env files.
    """

    database: DatabaseSettings = DatabaseSettings()
    jwt: JWTSettings = JWTSettings()
    logging: LoggingSettings = LoggingSettings()
    cors: CorsSettings = CorsSettings()
    ollama: OllamaSettings = OllamaSettings()
    youtube: YouTubeSettings = YouTubeSettings()
    service_timeouts: ServiceTimeouts = ServiceTimeouts()
    rate_limiting: RateLimitingConfig = RateLimitingConfig()
    cache: CacheSettings = CacheSettings()
    features: FeatureFlags = FeatureFlags()
    slide_detection: SlideDetectionSettings = SlideDetectionSettings()
    sentry: SentrySettings = SentrySettings()
    email: EmailSettings = EmailSettings()
    password_reset: PasswordResetSettings = PasswordResetSettings()
    storage: StorageSettings = StorageSettings()
    api_key: ApiKeySettings = ApiKeySettings()
    vllm_fleet: VLLMFleetSettings = VLLMFleetSettings()
    environment: Environment = Environment.DEVELOPMENT

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

# Cache settings
@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure only one Settings object is created per application run.
    This is the recommended pattern for FastAPI applications.

    Usage in FastAPI:
        from fastapi import Depends

        def get_user(settings: Settings = Depends(get_settings)):
            db_url = settings.database.DATABASE_URL

    Returns:
        Settings: Cached settings instance
    """
    return Settings()