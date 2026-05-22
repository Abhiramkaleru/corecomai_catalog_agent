"""
app/api/routes/outbound.py
──────────────────────────────────────────────────────────────────────────────
Trigger an outbound call from the bot to a seller.

POST /api/calls/outbound
{
    "to": "+917993119262",
    "language": "hi"
}

Bot calls the seller → seller picks up → same WebSocket stream starts.
Works with Twilio and Exotel.
"""

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.config import settings
from app.core.languages import get_lang
from app.realtime.call_sessions import create_session, update_session

router = APIRouter(prefix="/api/calls", tags=["Calls"])


class OutboundCallRequest(BaseModel):
    to: str                          # seller phone number e.g. "+917993119262"
    language: str = "en"             # hi, te, ta, en, mr, kn
    context: Optional[str] = None    # optional context to pass to AI agent


@router.post("/outbound")
async def initiate_outbound_call(req: OutboundCallRequest):
    """
    Trigger an outbound call from the bot to a seller.
    Bot calls the seller, they pick up, and the WebSocket stream starts.
    """
    provider = settings.TELEPHONY_PROVIDER.lower()

    if provider == "twilio":
        return await _twilio_outbound(req)
    elif provider == "exotel":
        return await _exotel_outbound(req)
    else:
        raise HTTPException(status_code=400, detail=f"Outbound not supported for {provider}")


async def _twilio_outbound(req: OutboundCallRequest):
    """Initiate outbound call via Twilio REST API."""
    try:
        from twilio.rest import Client
    except ImportError:
        raise HTTPException(status_code=500, detail="twilio package not installed")

    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured")

    client   = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    ws_url   = settings.PUBLIC_WS_URL
    lang_obj = get_lang(req.language)

    # TwiML that Twilio will execute when seller picks up
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="language" value="{req.language}" />
            <Parameter name="context"  value="{req.context or ''}" />
        </Stream>
    </Connect>
</Response>"""

    try:
        call = client.calls.create(
            to=req.to,
            from_=settings.TWILIO_PHONE_NUMBER,
            twiml=twiml,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Twilio call failed: {e}")

    # Pre-create session so agent has context ready
    await create_session(call.sid, req.to)
    await update_session(call.sid, {
        "caller":   req.to,
        "language": req.language,
        "status":   "outbound_initiated",
        "context":  req.context,
    })

    print(f"[outbound] Twilio call initiated — sid={call.sid} to={req.to}")
    return {
        "success":  True,
        "call_sid": call.sid,
        "to":       req.to,
        "status":   call.status,
        "provider": "twilio",
    }


async def _exotel_outbound(req: OutboundCallRequest):
    """Initiate outbound call via Exotel REST API."""
    import httpx

    if not settings.EXOTEL_API_KEY or not settings.EXOTEL_API_TOKEN:
        raise HTTPException(status_code=500, detail="Exotel credentials not configured")

    # Exotel outbound call API
    url = f"https://api.exotel.com/v1/Accounts/{settings.EXOTEL_SID}/Calls/connect"

    data = {
        "From":         req.to,                      # seller number
        "To":           settings.EXOTEL_PHONE,       # your ExoPhone
        "CallerId":     settings.EXOTEL_PHONE,
        "Url":          f"{settings.PUBLIC_BASE_URL}/api/calls/incoming",
        "Method":       "GET",
        "StatusCallback": f"{settings.PUBLIC_BASE_URL}/api/calls/status",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                data=data,
                auth=(settings.EXOTEL_API_KEY, settings.EXOTEL_API_TOKEN),
            )
            resp.raise_for_status()
            result = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Exotel call failed: {e}")

    call_sid = result.get("Call", {}).get("Sid", "")

    # Pre-create session
    await create_session(call_sid, req.to)
    await update_session(call_sid, {
        "caller":   req.to,
        "language": req.language,
        "status":   "outbound_initiated",
        "context":  req.context,
    })

    print(f"[outbound] Exotel call initiated — sid={call_sid} to={req.to}")
    return {
        "success":  True,
        "call_sid": call_sid,
        "to":       req.to,
        "status":   result.get("Call", {}).get("Status", ""),
        "provider": "exotel",
    }