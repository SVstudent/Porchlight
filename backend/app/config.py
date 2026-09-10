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
    # auto | bedrock | anthropic | tokenrouter
    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "auto").lower()
    BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL_ID = os.getenv("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")
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
    # Seconds Telegram holds the poll open. Above zero a reply arrives in about a second rather than
    # waiting for the next tick; zero returns immediately and is what the tests use.
    TELEGRAM_POLL_WAIT_S = _int("TELEGRAM_POLL_WAIT_S", 25)
    SES_FROM_EMAIL = os.getenv("SES_FROM_EMAIL", "")
    # Voice webhooks: skip Twilio signature validation (local testing only)
    VOICE_SKIP_SIGNATURE = _bool("VOICE_SKIP_SIGNATURE", False)
    # Optional: redirect every outbound message to one number/chat/email for demos
    DEMO_OVERRIDE_PHONE = os.getenv("DEMO_OVERRIDE_PHONE", "")
    DEMO_OVERRIDE_TELEGRAM_CHAT_ID = os.getenv("DEMO_OVERRIDE_TELEGRAM_CHAT_ID", "")
    # In a demo you hold one phone, but the roster has a dozen neighbours. Naming one member here makes
    # that member the only one whose messages really send; everyone else is logged to the activity feed as
    # in practice mode. Without it, a twelve-person dispatch arrives as twelve messages on one phone.
    DEMO_LIVE_MEMBER_ID = os.getenv("DEMO_LIVE_MEMBER_ID", "")

    # TokenRouter: one OpenAI-compatible endpoint in front of many providers.
    TOKENROUTER_API_KEY = os.getenv("TOKENROUTER_API_KEY", "")
    TOKENROUTER_BASE_URL = os.getenv("TOKENROUTER_BASE_URL", "https://api.tokenrouter.com/v1")
    TOKENROUTER_MODEL_ID = os.getenv("TOKENROUTER_MODEL_ID", "z-ai/glm-5.3-free")
    # GLM-5.3 reasons before it answers. Left alone it spends 45 seconds thinking about a two-line reply to a
    # neighbour, so ask for the least reasoning that still produces a usable answer.
    TOKENROUTER_REASONING_EFFORT = os.getenv("TOKENROUTER_REASONING_EFFORT", "minimal")
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
