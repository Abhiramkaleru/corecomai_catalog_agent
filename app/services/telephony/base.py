"""
app/services/telephony/base.py
──────────────────────────────────────────────────────────────────────────────
Abstract base class for telephony providers.

To add a new provider (e.g. Exotel, Plivo, Vonage):
  1. Create app/services/telephony/exotel.py
  2. Subclass TelephonyProvider
  3. Implement all abstract methods
  4. Register in get_telephony_provider() at the bottom of this file
  5. Set TELEPHONY_PROVIDER=exotel in .env

Nothing else in the codebase needs to change.
"""

from abc import ABC, abstractmethod
from fastapi import Request, Response


class TelephonyProvider(ABC):

    @abstractmethod
    async def validate_request(self, request: Request) -> bool:
        """Verify the request genuinely came from this provider."""
        ...

    @abstractmethod
    async def parse_incoming(self, request: Request) -> dict:
        """
        Parse an incoming call webhook.
        Returns standard dict:
          {
            "call_sid": str,
            "caller":   str,   # phone number
            "to":       str,   # your number
          }
        """
        ...

    @abstractmethod
    def build_stream_response(
        self,
        call_sid: str,
        caller: str,
        ws_url: str,
        greeting: str,
        language_code: str,
    ) -> Response:
        """
        Return the HTTP response that tells the provider to:
          a. Play a greeting
          b. Stream audio to our WebSocket
        """
        ...

    @abstractmethod
    def build_empty_response(self) -> Response:
        """Return a minimal valid response (used for status callbacks)."""
        ...

    @abstractmethod
    async def parse_audio_event(self, raw: str) -> dict:
        """
        Parse one WebSocket message from the provider.
        Returns standard dict:
          {
            "event":      "connected"|"start"|"media"|"stop",
            "stream_sid": str,
            "call_sid":   str,
            "caller":     str,
            "audio":      bytes | None,   # decoded audio bytes for "media" events
            "custom":     dict,           # custom parameters from stream start
          }
        """
        ...

    @abstractmethod
    def encode_audio_message(self, stream_sid: str, audio_bytes: bytes) -> str:
        """
        Encode audio bytes into the provider's WebSocket message format.
        Returns a JSON string ready to send over WebSocket.
        """
        ...


# ── Factory function ───────────────────────────────────────────────────────

def get_telephony_provider() -> TelephonyProvider:
    """
    Returns the configured telephony provider.
    Change TELEPHONY_PROVIDER in .env to swap providers.
    """
    from app.core.config import settings

    provider = settings.TELEPHONY_PROVIDER.lower()

    if provider == "twilio":
        from app.services.telephony.twilio import TwilioProvider
        return TwilioProvider()

    elif provider == "exotel":
        from app.services.telephony.exotel import ExotelProvider
        return ExotelProvider()

    elif provider == "plivo":
        from app.services.telephony.plivo import PlivoProvider
        return PlivoProvider()

    else:
        raise ValueError(
            f"Unknown TELEPHONY_PROVIDER='{provider}'. "
            f"Supported: twilio, exotel, plivo"
        )
