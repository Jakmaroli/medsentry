"""
config.py — Centralized configuration for MedSentry.

Design rule (Security Pillar #1 — see docs/SPEC.md "Effective Trust" section):
No secret, API key, or password is ever hardcoded here or anywhere else in this
repo. Everything sensitive is read from environment variables at runtime and
has a safe, non-secret default so the app still boots (in DEMO_MODE) with a
clean checkout and zero configuration.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SKILLS_DIR = BASE_DIR / "skills"


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- Model / ADK ---
    # "gemini-flash-latest" is a rolling alias maintained by Google that always
    # resolves to the current recommended Flash model, so this default never
    # goes stale even as Gemini versions change. Override with GEMINI_MODEL.
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    google_api_key: str | None = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

    # --- Mode ---
    # DEMO_MODE runs the full multi-agent workflow with deterministic,
    # rule-based logic instead of live Gemini calls. This is what lets judges,
    # CI, and first-time users run MedSentry with *zero* setup and no API key,
    # and it's what this repo runs in by default. Live mode switches on
    # automatically the moment a real key is present, unless force-disabled.
    demo_mode: bool = field(default_factory=lambda: _env_bool("MEDSENTRY_DEMO_MODE", True))

    # --- Security (see app/security.py) ---
    # Fernet key for at-rest encryption of patient records. In DEMO_MODE a
    # fresh key is generated in-memory each run (data is fictional/seeded).
    # In production, set MEDSENTRY_SECRET_KEY to a persisted 32-byte urlsafe
    # base64 key (e.g. output of `python -c "from cryptography.fernet import
    # Fernet; print(Fernet.generate_key().decode())"`) via your secret
    # manager / environment — never commit it.
    secret_key: str | None = os.getenv("MEDSENTRY_SECRET_KEY")

    # --- Storage ---
    db_path: str = os.getenv("MEDSENTRY_DB_PATH", str(BASE_DIR / "medsentry.db"))

    # --- Server ---
    host: str = os.getenv("MEDSENTRY_HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", os.getenv("MEDSENTRY_PORT", "8080")))

    # --- MCP ---
    mcp_transport: str = os.getenv("MEDSENTRY_MCP_TRANSPORT", "stdio")  # stdio | http


settings = Settings()


def live_mode_available() -> bool:
    """True only when a real Gemini key is configured AND demo mode isn't forced."""
    return bool(settings.google_api_key) and not settings.demo_mode
