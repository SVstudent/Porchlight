"""Environment-driven settings. The .env file lives in backend/ and is never committed."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env", override=True)  # backend/.env wins over stray shell exports


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    # --- identity ---
    COMMUNITY_NAME = os.getenv("COMMUNITY_NAME", "Maryvale Neighbors Network")
    COORDINATOR_NAME = os.getenv("COORDINATOR_NAME", "Block Captain")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5173").rstrip("/")

    # --- model provider ---
    # auto | bedrock | anthropic | ollama
    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "auto").lower()
    BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL_ID = os.getenv("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.2"))

    # --- feeds ---
    NWS_USER_AGENT = os.getenv("NWS_USER_AGENT", "porchlight-agent (contact@example.com)")
    SENTINEL_INTERVAL_MINUTES = _int("SENTINEL_INTERVAL_MINUTES", 15)
    FOLLOWUP_INTERVAL_MINUTES = _int("FOLLOWUP_INTERVAL_MINUTES", 2)
    FOLLOWUP_GRACE_MINUTES = _int("FOLLOWUP_GRACE_MINUTES", 20)
    HEAT_INDEX_ACTIVATE_F = float(os.getenv("HEAT_INDEX_ACTIVATE_F", "105"))
    AQI_ACTIVATE = _int("AQI_ACTIVATE", 151)
    COLD_ACTIVATE_F = float(os.getenv("COLD_ACTIVATE_F", "15"))
    SENTINEL_ENABLED = _bool("SENTINEL_ENABLED", True)

    # --- outbound channels ---
    # live => real sends through configured providers; console => log only (development)
    SEND_MODE = os.getenv("SEND_MODE", "console").lower()
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    SES_FROM_EMAIL = os.getenv("SES_FROM_EMAIL", "")
    # Optional: redirect every outbound message to one number/chat/email for demos
    DEMO_OVERRIDE_PHONE = os.getenv("DEMO_OVERRIDE_PHONE", "")
    DEMO_OVERRIDE_TELEGRAM_CHAT_ID = os.getenv("DEMO_OVERRIDE_TELEGRAM_CHAT_ID", "")
    DEMO_OVERRIDE_EMAIL = os.getenv("DEMO_OVERRIDE_EMAIL", "")

    # --- policy ---
    AUTO_APPROVE_ESCALATIONS = _bool("AUTO_APPROVE_ESCALATIONS", False)

    # --- storage ---
    DATA_DIR = Path(os.getenv("DATA_DIR", str(BACKEND_DIR / "data")))
    SESSION_DIR = DATA_DIR / "sessions"
    DB_PATH = DATA_DIR / "porchlight.db"

    # --- server ---
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = _int("PORT", 8000)
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
