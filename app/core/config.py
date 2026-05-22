"""
app/core/config.py
──────────────────────────────────────────────────────────────────────────────
Central configuration. Set these in .env — never hardcode in service files.

PROVIDER SWITCHES (change once here → works everywhere):
  TELEPHONY_PROVIDER  = twilio | exotel | plivo
  STT_PROVIDER        = deepgram | sarvam | google | whisper
  TTS_PROVIDER        = cartesia | sarvam | elevenlabs | edge
  AI_PROVIDER         = gemini | openai | groq | ollama | vllm
  STORAGE_PROVIDER    = local | s3 | gcs
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:

    # ── Provider switches ────────────────────────────────────────────────
    # Change ONLY these to swap vendors — nothing else in the codebase changes
    TELEPHONY_PROVIDER: str = os.getenv("TELEPHONY_PROVIDER", "exotel")
    STT_PROVIDER: str       = os.getenv("STT_PROVIDER",       "deepgram")
    TTS_PROVIDER: str       = os.getenv("TTS_PROVIDER",       "edge")
    AI_PROVIDER: str        = os.getenv("AI_PROVIDER",        "groq")
    STORAGE_PROVIDER: str   = os.getenv("STORAGE_PROVIDER",   "local")

    # ── AI Keys ──────────────────────────────────────────────────────────
    GEMINI_API_KEY: str  = os.getenv("GEMINI_API_KEY",  "")
    OPENAI_API_KEY: str  = os.getenv("OPENAI_API_KEY",  "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    # Self-hosted LLM
    OLLAMA_URL:          str = os.getenv("OLLAMA_URL",   "http://localhost:11434")
    OLLAMA_MODEL:        str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    OLLAMA_VISION_MODEL: str = os.getenv("OLLAMA_VISION_MODEL", "llava:7b")
    VLLM_URL:            str = os.getenv("VLLM_URL",    "http://localhost:8000/v1")
    VLLM_MODEL:          str = os.getenv("VLLM_MODEL",  "meta-llama/Llama-3.1-8B")

    # ── Telephony: Twilio ────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str  = os.getenv("TWILIO_ACCOUNT_SID",  "")
    TWILIO_AUTH_TOKEN: str   = os.getenv("TWILIO_AUTH_TOKEN",   "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")

    # ── Telephony: Exotel (swap-in replacement for Twilio) ───────────────
    EXOTEL_API_KEY: str    = os.getenv("EXOTEL_API_KEY",    "")
    EXOTEL_API_TOKEN: str  = os.getenv("EXOTEL_API_TOKEN",  "")
    EXOTEL_SID: str        = os.getenv("EXOTEL_SID",        "")
    EXOTEL_PHONE: str      = os.getenv("EXOTEL_PHONE",      "")

    # ── Telephony: Plivo ─────────────────────────────────────────────────
    PLIVO_AUTH_ID: str    = os.getenv("PLIVO_AUTH_ID",    "")
    PLIVO_AUTH_TOKEN: str = os.getenv("PLIVO_AUTH_TOKEN", "")
    PLIVO_PHONE: str      = os.getenv("PLIVO_PHONE",      "")

    # ── Public URLs ──────────────────────────────────────────────────────
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "https://fruity-aviana-exploringly.ngrok-free.dev")
    PUBLIC_WS_URL: str   = os.getenv("PUBLIC_WS_URL",   "wss://fruity-aviana-exploringly.ngrok-free.dev/ws/call-stream")

    # ── STT: Deepgram ────────────────────────────────────────────────────
    DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", "")
    #whisper is also supported as an STT provider, but it runs locally and is not as accurate as Deepgram, so it's optional. If you set STT_PROVIDER=whisper, make sure to set the model (tiny, base, small, medium, large)
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
    # ── STT/TTS: Sarvam AI (best for Indian languages) ───────────────────
    SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "")

    # ── TTS: Cartesia ────────────────────────────────────────────────────
    CARTESIA_API_KEY: str  = os.getenv("CARTESIA_API_KEY",  "")
    CARTESIA_VOICE_ID: str = os.getenv("CARTESIA_VOICE_ID", "")
    # Per-language voices
    CARTESIA_VOICE_ID_EN: str = os.getenv(
        "CARTESIA_VOICE_ID_EN",
        "28ca2041-5dda-42df-8123-f58ea9c3da00"
    )

    CARTESIA_VOICE_ID_HI: str = os.getenv(
        "CARTESIA_VOICE_ID_HI",
        "a81fccdc-5595-4dfc-ae76-4de6a515b8a2"
    )

    CARTESIA_VOICE_ID_TE: str = os.getenv(
        "CARTESIA_VOICE_ID_TE",
        "cf061d8b-a752-4865-81a2-57570a6e0565"
    )

    # ── TTS: ElevenLabs ──────────────────────────────────────────────────
    ELEVENLABS_API_KEY: str  = os.getenv("ELEVENLABS_API_KEY",  "")
    ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "")

    # ── Storage ──────────────────────────────────────────────────────────
    # local
    LOCAL_UPLOAD_DIR: str = os.getenv("LOCAL_UPLOAD_DIR", "./uploads")
    # AWS S3
    AWS_ACCESS_KEY: str    = os.getenv("AWS_ACCESS_KEY",    "")
    AWS_SECRET_KEY: str    = os.getenv("AWS_SECRET_KEY",    "")
    AWS_BUCKET: str        = os.getenv("AWS_BUCKET",        "")
    AWS_REGION: str        = os.getenv("AWS_REGION",        "ap-south-1")
    # Google Cloud Storage
    GCS_BUCKET: str             = os.getenv("GCS_BUCKET",             "")
    GCS_CREDENTIALS_JSON: str   = os.getenv("GCS_CREDENTIALS_JSON",   "")

    # ── MongoDB ──────────────────────────────────────────────────────────
    MONGODB_URL: str     = os.getenv("MONGODB_URL",     "mongodb://localhost:27017")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "seller_catalog")

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "")  # blank = in-memory

    # ── App ──────────────────────────────────────────────────────────────
    APP_ENV: str   = os.getenv("APP_ENV",   "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── Language ─────────────────────────────────────────────────────────
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "en")
    AUTO_DETECT_LANGUAGE: bool = os.getenv("AUTO_DETECT_LANGUAGE", "true").lower() == "true"

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV == "development"

    def validate(self):
        """Call on startup — warn about missing keys."""
        warnings = []
        if not self.GEMINI_API_KEY and self.AI_PROVIDER == "gemini":
            warnings.append("GEMINI_API_KEY not set")
        if not self.OPENAI_API_KEY and self.AI_PROVIDER == "openai":
            warnings.append("OPENAI_API_KEY not set")
        if not self.GROQ_API_KEY and self.AI_PROVIDER == "groq":
            warnings.append("GROQ_API_KEY not set")
        if not self.DEEPGRAM_API_KEY and self.STT_PROVIDER == "deepgram":
            warnings.append("DEEPGRAM_API_KEY not set")
        if not self.CARTESIA_API_KEY and self.TTS_PROVIDER == "cartesia":
            warnings.append("CARTESIA_API_KEY not set")
        if not self.TWILIO_AUTH_TOKEN and self.TELEPHONY_PROVIDER == "twilio":
            warnings.append("TWILIO_AUTH_TOKEN not set — signature validation disabled")
        for w in warnings:
            print(f"[config] WARNING: {w}")
        return warnings


settings = Settings()
