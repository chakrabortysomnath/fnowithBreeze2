"""
config.py — Application configuration via environment variables.

All secrets are read from the environment (or a local .env file).
Never hardcode credentials here.

Required env vars:
    BREEZE_API_KEY        — Your ICICI Direct Breeze API key
    BREEZE_API_SECRET     — Your ICICI Direct Breeze API secret
    BREEZE_SESSION_TOKEN  — Daily session token (regenerate each morning)

Optional env vars (with sensible defaults):
    DEFAULT_BROKERAGE     — Fixed brokerage per leg in INR (default: 40.0)
    DEFAULT_STT_RATE      — STT rate as decimal (default: 0.001 = 0.1%)
    DEFAULT_GST_RATE      — GST rate on brokerage (default: 0.18 = 18%)
    QUOTAGUARDSTATIC_URL  — Proxy URL for static outbound IP (Phase 5, optional)
    LOG_LEVEL             — Python logging level (default: INFO)
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Reads configuration from environment variables.

    pydantic-settings automatically reads from a .env file if present,
    and falls back to actual environment variables.
    """

    # --- Breeze API credentials (required) ---
    BREEZE_API_KEY: str = Field(..., description="ICICI Breeze API key")
    BREEZE_API_SECRET: str = Field(..., description="ICICI Breeze API secret")
    BREEZE_SESSION_TOKEN: str = Field(..., description="Daily Breeze session token")

    # --- Charge defaults (optional) ---
    DEFAULT_BROKERAGE: float = Field(
        default=40.0, description="Fixed brokerage per leg in INR"
    )
    DEFAULT_STT_RATE: float = Field(
        default=0.001, description="STT rate (0.001 = 0.1% on premium)"
    )
    DEFAULT_GST_RATE: float = Field(
        default=0.18, description="GST on brokerage (0.18 = 18%)"
    )

    # --- Static IP proxy (Phase 5, optional) ---
    QUOTAGUARDSTATIC_URL: str | None = Field(
        default=None,
        description="QuotaGuard Static proxy URL; if set, Breeze calls route through it",
    )

    # --- Logging ---
    LOG_LEVEL: str = Field(default="INFO", description="Python logging level")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (parsed once at startup)."""
    return Settings()


# Module-level convenience alias used throughout the app
settings = get_settings()
