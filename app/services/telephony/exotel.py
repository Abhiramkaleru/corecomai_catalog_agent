"""
app/services/telephony/exotel.py
──────────────────────────────────────────────────────────────────────────────
Exotel implementation — popular Indian telephony provider.
Set TELEPHONY_PROVIDER=exotel in .env to use this instead of Twilio.
"""

import base64
import ipaddress
import json
import hmac
import hashlib

from fastapi import Request, Response

from app.core.config import settings
from app.services.telephony.base import TelephonyProvider


# ── Exotel source IP ranges (including Mumbai/ap-south-1 seen in logs) ────
_EXOTEL_IP_RANGES = [
    "54.251.51.0/24",
    "54.169.0.0/16",
    "13.251.0.0/16",
    "18.136.0.0/15",
    "52.74.0.0/16",
    "54.254.0.0/16",
    "13.200.0.0/13",   # ap-south-1 (Mumbai)
    "43.204.0.0/14",   # ap-south-1
    "65.0.0.0/13",     # ap-south-1
    "15.206.0.0/15",   # ap-south-1
    "3.108.0.0/14",    # ap-south-1
    "127.0.0.1/32",    # localhost / dev
]
_EXOTEL_NETS = [ipaddress.ip_network(r) for r in _EXOTEL_IP_RANGES]


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _is_exotel_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in _EXOTEL_NETS)
    except ValueError:
        return False


class ExotelProvider(TelephonyProvider):

    async def validate_request(self, request: Request) -> bool:
        validate_sig = getattr(settings, "EXOTEL_VALIDATE_SIGNATURE", False)
        validate_ip  = getattr(settings, "EXOTEL_VALIDATE_IP", True)

        if validate_sig and settings.EXOTEL_API_TOKEN:
            signature = (
                request.headers.get("X-Exotel-Signature")
                or request.headers.get("Exotel-Signature", "")
            )
            if signature:
                try:
                    body   = await request.body()
                    digest = hmac.new(
                        settings.EXOTEL_API_TOKEN.encode("utf-8"),
                        body,
                        hashlib.sha256,
                    ).hexdigest()
                    return hmac.compare_digest(digest, signature)
                except Exception as e:
                    print(f"[exotel] Signature validation error: {e}")
                    return False

        if validate_ip:
            client_ip = _get_client_ip(request)
            allowed   = _is_exotel_ip(client_ip)
            if not allowed:
                print(f"[exotel] Rejected non-Exotel IP: {client_ip!r}")
            return allowed

        print("[exotel] WARNING: no webhook validation — allowing all requests")
        return True

    async def parse_incoming(self, request: Request) -> dict:
        query = dict(request.query_params)
        form  = {}
        if request.method == "POST":
            try:
                form = dict(await request.form())
            except Exception:
                pass

        params = {**query, **form}

        def pick(*keys, default=""):
            for key in keys:
                v = params.get(key)
                if v and str(v).lower() not in ("null", "none", ""):
                    return str(v)
            return default

        return {
            "call_sid": pick("CallSid"),
            "caller":   pick("From", "CallFrom", default="unknown"),
            "to":       pick("To",   "CallTo"),
        }

    def build_stream_response(
        self,
        call_sid: str,
        caller: str,
        ws_url: str,
        greeting: str,
        language_code: str,
    ) -> Response:
        # NOTE: When using Exotel's Stream applet in the flow dashboard,
        # this response is not used — the applet handles the WebSocket directly.
        # This is kept for fallback / ExoML-based flows.
        print(f"[exotel] build_stream_response — call_sid={call_sid}")
        return self.build_empty_response()

    def build_empty_response(self) -> Response:
        return Response(
            content="<?xml version='1.0' encoding='UTF-8'?><Response/>",
            media_type="application/xml",
        )

    async def parse_audio_event(self, raw: str) -> dict:
        msg   = json.loads(raw)
        event = msg.get("event", "")

        result = {
            "event":      event,
            "stream_sid": msg.get("stream_sid", ""),   # Exotel uses snake_case
            "call_sid":   "",
            "caller":     "",
            "audio":      None,
            "custom":     {},
        }

        if event == "start":
            start = msg.get("start", {})
            # stream_sid is at top level AND inside start{}
            result["stream_sid"] = msg.get("stream_sid", "") or start.get("stream_sid", "")
            result["call_sid"]   = start.get("call_sid", "")
            result["custom"]     = start.get("customParameters", {})
            result["caller"]     = (
                result["custom"].get("caller")
                or start.get("from", "")
            )
            # Log full media_format so we know what Exotel expects
            media_fmt = start.get("media_format", {})
            print(f"[exotel] media_format from Exotel: {media_fmt}")

        elif event == "media":
            payload = msg.get("media", {}).get("payload", "")
            if payload:
                result["audio"] = base64.b64decode(payload)

        elif event == "stop":
            stop = msg.get("stop", {})
            result["call_sid"] = stop.get("call_sid", "")

        return result

    def encode_audio_message(self, stream_sid: str, audio_bytes: bytes) -> str:
        """
        Send audio back to Exotel over WebSocket.
        Audio must be: mulaw, 8000 Hz, mono — raw bytes, base64-encoded.
        Chunk size: send in ~20ms chunks (160 bytes each) for smooth playback.
        """
        return json.dumps({
            "event":     "media",
            "streamSid": stream_sid,
            "media": {
                "payload": base64.b64encode(audio_bytes).decode("utf-8"),
            },
        })

    def encode_audio_chunks(self, stream_sid: str, audio_bytes: bytes, chunk_size: int = 160):
        """
        Generator: yields JSON strings for each ~20ms audio chunk.
        Use this instead of encode_audio_message for smooth TTS playback.
        """
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i:i + chunk_size]
            yield json.dumps({
                "event":     "media",
                "streamSid": stream_sid,
                "media": {
                    "payload": base64.b64encode(chunk).decode("utf-8"),
                },
            })