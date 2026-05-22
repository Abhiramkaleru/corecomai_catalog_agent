"""
app/services/tts/base.py
──────────────────────────────────────────────────────────────────────────────
TTS provider abstraction. Change TTS_PROVIDER in .env to swap.

All providers output raw mulaw 8 kHz mono — exactly what Twilio Media Streams
expects. PCM → mulaw conversion is done via Python stdlib `audioop`.

──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import audioop
import logging
from abc import ABC, abstractmethod

from app.core.config import settings

log = logging.getLogger(__name__)


# ── PCM helpers ────────────────────────────────────────────────────────────────

def _pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Convert raw 16-bit little-endian PCM (8 kHz mono) → mulaw 8 kHz."""
    return audioop.lin2ulaw(pcm_bytes, 2)


def _resample_to_8k(pcm_bytes: bytes, src_rate: int) -> bytes:
    """Downsample 16-bit PCM from src_rate → 8000 Hz."""
    if src_rate == 8000:
        return pcm_bytes
    resampled, _ = audioop.ratecv(pcm_bytes, 2, 1, src_rate, 8000, None)
    return resampled


async def _mp3_to_mulaw(mp3_bytes: bytes) -> bytes:
    """Decode MP3 → PCM 16-bit 8 kHz → mulaw. Requires pydub + ffmpeg."""
    try:
        import io
        from pydub import AudioSegment
        audio = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
        audio = audio.set_frame_rate(8000).set_channels(1).set_sample_width(2)
        return _pcm16_to_mulaw(audio.raw_data)
    except ImportError:
        log.error(
            "[tts] pydub not installed — cannot convert MP3 to mulaw. "
            "Run: pip install pydub  (also needs ffmpeg on PATH)"
        )
        raise
    except Exception as exc:
        log.exception("[tts] MP3→mulaw conversion failed: %s", exc)
        raise


# ── Abstract base ──────────────────────────────────────────────────────────────

class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, language_code: str) -> bytes:
        """Return raw mulaw 8 kHz mono bytes ready to stream to Twilio."""
        ...


# ── Cartesia ───────────────────────────────────────────────────────────────────

def _cartesia_voice_id(language_code: str) -> str:
    """
    Return the correct Cartesia voice ID for the given language.
    Reads per-language env vars; falls back to CARTESIA_VOICE_ID (English).
    """
    lang_to_env: dict[str, str | None] = {
        "en": getattr(settings, "CARTESIA_VOICE_ID_EN", None),
        "hi": getattr(settings, "CARTESIA_VOICE_ID_HI", None),
        "te": getattr(settings, "CARTESIA_VOICE_ID_TE", None),
        "ta": getattr(settings, "CARTESIA_VOICE_ID_TA", None),
        "mr": getattr(settings, "CARTESIA_VOICE_ID_MR", None),
        "kn": getattr(settings, "CARTESIA_VOICE_ID_KN", None),
        "bn": getattr(settings, "CARTESIA_VOICE_ID_BN", None),
    }

    # Try language-specific → fall back to base CARTESIA_VOICE_ID
    voice_id = lang_to_env.get(language_code) or getattr(settings, "CARTESIA_VOICE_ID", None)

    if not voice_id:
        raise ValueError(
            f"[tts][cartesia] No voice ID configured for language='{language_code}'. "
            f"Set CARTESIA_VOICE_ID_{language_code.upper()} in your .env file. "
            f"Find voice IDs at https://play.cartesia.ai/voices"
        )

    return voice_id


class CartesiaTTSProvider(TTSProvider):
    """
    Cartesia sonic-multilingual TTS.
    Returns pcm_s16le 8 kHz from Cartesia; converts to mulaw locally.
    """

    async def synthesize(self, text: str, language_code: str = "en") -> bytes:
        import httpx
        from app.core.languages import get_lang

        # Guard: never send empty text — Cartesia returns 400
        if not text or not text.strip():
            log.warning("[tts][cartesia] synthesize() called with empty text, skipping")
            return b""

        lang     = get_lang(language_code)
        voice_id = _cartesia_voice_id(language_code)

        payload = {
            "model_id":   "sonic-multilingual",
            "transcript": text.strip(),
            "voice":      {"mode": "id", "id": voice_id},
            "output_format": {
                "container":   "raw",
                "encoding":    "pcm_s16le",
                "sample_rate": 8000,
            },
            "language": lang.cartesia_language,
             "speed":    0.6,   # 0.6 = 60% of normal speed; adjust as needed
        }
        headers = {
            "X-API-Key":        settings.CARTESIA_API_KEY,
            "Content-Type":     "application/json",
            "Cartesia-Version": "2024-06-10",
        }

        log.debug(
            "[tts][cartesia] synthesize — lang=%s voice=%s text='%.60s'",
            language_code, voice_id, text
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=45.0, write=10.0, pool=5.0)) as client:
            resp = await client.post(
                "https://api.cartesia.ai/tts/bytes",
                json=payload,
                headers=headers,
            )

            # Log the actual error body BEFORE raise_for_status so the 400
            # reason is visible in logs (Cartesia puts the reason in the body).
            if resp.status_code >= 400:
                log.error(
                    "[tts][cartesia] HTTP %d — voice=%s lang=%s body=%s",
                    resp.status_code, voice_id, language_code, resp.text
                )
            resp.raise_for_status()
            pcm = resp.content

        mulaw = _pcm16_to_mulaw(pcm)
        log.debug("[tts][cartesia] pcm=%d bytes → mulaw=%d bytes", len(pcm), len(mulaw))
        return mulaw


# ── Sarvam AI ──────────────────────────────────────────────────────────────────

_SARVAM_DEFAULT_SPEAKER: dict[str, str] = {
    "hi": "anushka",   # Hindi    — clear female voice
    "te": "anushka",   # Telugu   — anushka works well for Telugu too
    "ta": "anushka",   # Tamil
    "mr": "manisha",   # Marathi
    "kn": "anushka",   # Kannada
    "bn": "anushka",   # Bengali
    "en": "anushka",   # English
}

def _sarvam_speaker(language_code: str) -> str:
    """Return speaker name, allowing per-language env override."""
    env_key = f"SARVAM_SPEAKER_{language_code.upper()}"
    override = getattr(settings, env_key, None)
    if override:
        return override
    return _SARVAM_DEFAULT_SPEAKER.get(language_code, "anushka")


class SarvamTTSProvider(TTSProvider):
    """
    Sarvam AI TTS — purpose-built for Indian languages.
    Returns base64-encoded PCM 8 kHz; converts to mulaw for Twilio.
    """

    async def synthesize(self, text: str, language_code: str = "hi") -> bytes:
        import base64
        import httpx
        from app.core.languages import get_lang

        if not text or not text.strip():
            log.warning("[tts][sarvam] synthesize() called with empty text, skipping")
            return b""

        lang    = get_lang(language_code)
        speaker = _sarvam_speaker(language_code)

        payload = {
            "inputs":               [text.strip()],
            "target_language_code": lang.sarvam_code,
            "speaker":              speaker,
            "pitch":                0,
            "pace":                 1.0,
            "loudness":             1.5,
            "speech_sample_rate":   8000,
            "enable_preprocessing": True,
            "model":                "bulbul:v2",
        }
        headers = {
            "api-subscription-key": settings.SARVAM_API_KEY,
            "Content-Type":         "application/json",
        }

        log.debug(
            "[tts][sarvam] synthesize -- lang=%s speaker=%s text='%.60s'",
            language_code, speaker, text
        )

        # bulbul:v2 cold starts can take 20-30s on first request.
        # Use granular timeout: tight connect, generous read.
        timeout = httpx.Timeout(connect=5.0, read=45.0, write=10.0, pool=5.0)

        data: dict = {}
        for attempt in range(1, 4):   # up to 3 attempts
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        "https://api.sarvam.ai/text-to-speech",
                        json=payload,
                        headers=headers,
                    )
                if resp.status_code >= 400:
                    log.error(
                        "[tts][sarvam] HTTP %d -- lang=%s body=%s",
                        resp.status_code, language_code, resp.text
                    )
                resp.raise_for_status()
                data = resp.json()
                break   # success — exit retry loop

            except httpx.ReadTimeout as exc:
                log.warning(
                    "[tts][sarvam] ReadTimeout attempt %d/3 -- lang=%s retrying...",
                    attempt, language_code
                )
                if attempt == 3:
                    raise httpx.ReadTimeout(
                        f"Sarvam TTS timed out after 3 attempts (lang={language_code}). "
                        "API may be under load -- try again shortly."
                    ) from exc
                import asyncio
                await asyncio.sleep(1.5 * attempt)   # 1.5s, then 3s back-off

            except httpx.HTTPStatusError:
                raise   # 4xx errors won't self-heal, don't retry

        # Validate response structure before indexing
        audios = data.get("audios")
        if not audios or not isinstance(audios, list) or not audios[0]:
            raise ValueError(
                f"[tts][sarvam] Unexpected response structure: {list(data.keys())}"
            )

        pcm   = base64.b64decode(audios[0])
        mulaw = _pcm16_to_mulaw(pcm)
        log.debug("[tts][sarvam] pcm=%d bytes -> mulaw=%d bytes", len(pcm), len(mulaw))
        return mulaw


# ── ElevenLabs ─────────────────────────────────────────────────────────────────

class ElevenLabsTTSProvider(TTSProvider):
    """
    ElevenLabs TTS — returns MP3, decoded via pydub+ffmpeg → mulaw.
    Requires: pip install pydub  +  ffmpeg on PATH.
    """

    async def synthesize(self, text: str, language_code: str = "en") -> bytes:
        import httpx

        if not text or not text.strip():
            log.warning("[tts][elevenlabs] synthesize() called with empty text, skipping")
            return b""

        headers = {
            "xi-api-key":   settings.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "text":           text.strip(),
            "model_id":       "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=45.0, write=10.0, pool=5.0)) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{settings.ELEVENLABS_VOICE_ID}",
                json=payload,
                headers=headers,
            )
            if resp.status_code >= 400:
                log.error(
                    "[tts][elevenlabs] HTTP %d — body=%s",
                    resp.status_code, resp.text
                )
            resp.raise_for_status()
            mp3 = resp.content

        mulaw = await _mp3_to_mulaw(mp3)
        log.debug("[tts][elevenlabs] mp3=%d bytes → mulaw=%d bytes", len(mp3), len(mulaw))
        return mulaw

class EdgeTTSProvider(TTSProvider):
    """
    Microsoft Edge TTS — free, no API key, excellent Indian language support.
    pip install edge-tts
    """

    # Best voices for Indian languages
    _VOICES = {
        "en": "en-IN-NeerjaNeural",      # Indian English female
        "hi": "hi-IN-SwaraNeural",       # Hindi female
        "te": "te-IN-ShrutiNeural",      # Telugu female
        "ta": "ta-IN-PallaviNeural",     # Tamil female
        "mr": "mr-IN-AarohiNeural",      # Marathi female
        "kn": "kn-IN-SapnaNeural",       # Kannada female
        "bn": "bn-IN-TanishaaNeural",    # Bengali female
    }

    async def synthesize(self, text: str, language_code: str = "en") -> bytes:
        import edge_tts
        import io
        import audioop

        if not text or not text.strip():
            return b""

        voice = self._VOICES.get(language_code, "en-IN-NeerjaNeural")

        # Generate MP3 audio
        communicate = edge_tts.Communicate(text.strip(), voice)
        mp3_buffer  = io.BytesIO()

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buffer.write(chunk["data"])

        mp3_bytes = mp3_buffer.getvalue()
        if not mp3_bytes:
            log.warning("[tts][edge] empty audio for: %r", text[:50])
            return b""

        # Convert MP3 → mulaw 8kHz
        mulaw = await _mp3_to_mulaw(mp3_bytes)
        log.debug("[tts][edge] mulaw=%d bytes lang=%s", len(mulaw), language_code)
        return mulaw
# ── Factory ────────────────────────────────────────────────────────────────────

def get_tts_provider() -> TTSProvider:
    p = (settings.TTS_PROVIDER or "").lower()
    if p == "cartesia":
        return CartesiaTTSProvider()
    elif p == "sarvam":
        return SarvamTTSProvider()
    elif p == "elevenlabs":
        return ElevenLabsTTSProvider()
    elif p == "edge":
        return EdgeTTSProvider()
    else:
        raise ValueError(
            f"Unknown TTS_PROVIDER='{p}'. "
            "Set TTS_PROVIDER in .env to one of: cartesia, sarvam, elevenlabs"
        )


tts = get_tts_provider()