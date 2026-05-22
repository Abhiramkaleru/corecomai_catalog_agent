"""
app/services/telephony/twilio.py
──────────────────────────────────────────────────────────────────────────────
Twilio implementation of TelephonyProvider.
All Twilio-specific logic is ONLY here — nothing else in the app knows about Twilio.
"""

import base64
import json
import urllib.parse

from fastapi import Request, Response
from twilio.request_validator import RequestValidator

from app.core.config import settings
from app.core.languages import get_lang
from app.services.telephony.base import TelephonyProvider


class TwilioProvider(TelephonyProvider):

    def __init__(self):
        self._validator = RequestValidator(settings.TWILIO_AUTH_TOKEN) \
            if settings.TWILIO_AUTH_TOKEN else None

    async def validate_request(self, request: Request) -> bool:
        if not self._validator:
            return True  # dev mode — skip validation
        form = await request.form()
        sig  = request.headers.get("X-Twilio-Signature", "")
        return self._validator.validate(str(request.url), dict(form), sig)

    async def parse_incoming(self, request: Request) -> dict:
        form = await request.form()
        return {
            "call_sid": form.get("CallSid", ""),
            "caller":   form.get("From",    "unknown"),
            "to":       form.get("To",      ""),
        }

    def build_stream_response(
        self,
        call_sid: str,
        caller: str,
        ws_url: str,
        greeting: str,
        language_code: str,
    ) -> Response:
        lang = get_lang(language_code)
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="{lang.twilio_voice}" language="{lang.twilio_language}">{greeting}</Say>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="callSid"  value="{call_sid}" />
            <Parameter name="caller"   value="{urllib.parse.quote(caller)}" />
            <Parameter name="language" value="{language_code}" />
        </Stream>
    </Connect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    def build_empty_response(self) -> Response:
        return Response(
            content="<?xml version='1.0' encoding='UTF-8'?><Response/>",
            media_type="application/xml",
        )

    async def parse_audio_event(self, raw: str) -> dict:
        """Parse Twilio Media Stream WebSocket message into standard format."""
        msg   = json.loads(raw)
        event = msg.get("event", "")

        result = {
            "event":      event,
            "stream_sid": "",
            "call_sid":   "",
            "caller":     "",
            "audio":      None,
            "custom":     {},
        }

        if event == "start":
            start = msg.get("start", {})
            result["stream_sid"] = msg.get("streamSid", "")
            result["call_sid"]   = start.get("callSid", "")
            custom               = start.get("customParameters", {})
            result["caller"]     = urllib.parse.unquote(custom.get("caller", ""))
            result["custom"]     = custom

        elif event == "media":
            result["stream_sid"] = msg.get("streamSid", "")
            payload = msg.get("media", {}).get("payload", "")
            if payload:
                result["audio"] = base64.b64decode(payload)

        elif event == "stop":
            result["stream_sid"] = msg.get("streamSid", "")

        return result

    def encode_audio_message(self, stream_sid: str, audio_bytes: bytes) -> str:
        """Encode audio to send back to Twilio."""
        return json.dumps({
            "event":     "media",
            "streamSid": stream_sid,
            "media":     {"payload": base64.b64encode(audio_bytes).decode("utf-8")},
        })
