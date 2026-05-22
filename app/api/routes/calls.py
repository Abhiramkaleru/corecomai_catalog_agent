"""
app/api/routes/calls.py — Telephony webhook entry point.
With Exotel Stream applet: /incoming just creates the session and returns 200.
The Stream applet in the Exotel flow handles opening the WebSocket directly.
"""

import json
from fastapi import APIRouter, Request, Response, HTTPException

from app.core.config import settings
from app.core.languages import get_lang
from app.services.telephony.base import get_telephony_provider
from app.realtime.call_sessions import create_session, update_session
from app.services.ai.base import get_token_stats
router    = APIRouter(prefix="/api/calls", tags=["Calls"])
telephony = get_telephony_provider()


@router.api_route("/incoming", methods=["GET", "POST"])
async def incoming_call(request: Request):
    """
    Entry point for incoming calls from Exotel.

    Flow:
      Exotel flow: Passthru → /api/calls/incoming  (this endpoint)
                   Stream applet → wss://.../ws/call-stream

    This endpoint only creates the session.
    The Stream applet opens the WebSocket independently.
    """

    if not await telephony.validate_request(request):
        raise HTTPException(status_code=403, detail="Invalid provider signature")

    parsed   = await telephony.parse_incoming(request)
    call_sid = parsed.get("call_sid")
    caller   = parsed.get("caller", "unknown")

    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing call_sid")

    print(f"[calls] Incoming — {call_sid} from {caller}")

    language = settings.DEFAULT_LANGUAGE
    await create_session(call_sid, caller)
    await update_session(call_sid, {
        "caller":   caller,
        "language": language,
        "status":   "started",
    })

    # Return empty 200 — Stream applet handles the WebSocket
    return Response(content="OK", status_code=200)

# @router.api_route("/incoming/twilio", methods=["GET", "POST"])
# async def incoming_call_twilio(request: Request):
#     """
#     Entry point for incoming calls from Twilio.
#     Responds with TwiML to connect the call to our WebSocket stream.
#     """
#     form     = await request.form()
#     call_sid = form.get("CallSid", "")
#     caller   = form.get("From", "unknown")
#     host     = request.headers.get("host")

#     if not call_sid:
#         raise HTTPException(status_code=400, detail="Missing CallSid")

#     print(f"[calls] Incoming Twilio — {call_sid} from {caller}")

#     language = settings.DEFAULT_LANGUAGE
#     await create_session(call_sid, caller)
#     await update_session(call_sid, {
#         "caller":   caller,
#         "language": language,
#         "status":   "started",
#     })

#     # Return TwiML — tells Twilio to open WebSocket to our stream
#     twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
# <Response>
#     <Connect>
#         <Stream url="wss://{host}/ws/call-stream">
#             <Parameter name="language" value="{language}"/>
#             <Parameter name="caller" value="{caller}"/>
#             <Parameter name="call_sid" value="{call_sid}"/>
#             <Parameter name="direction" value="inbound"/>
#         </Stream>
#     </Connect>
# </Response>"""

    return Response(content=twiml, media_type="application/xml")
@router.api_route("/status", methods=["GET", "POST"])
async def call_status(request: Request):
    """Call lifecycle callback (completed, failed, etc.)"""
    try:
        form = dict(await request.form())
    except Exception:
        form = {}

    params   = {**dict(request.query_params), **form}
    call_sid = params.get("CallSid", "unknown")
    status   = params.get("CallStatus", params.get("Status", "unknown"))
    duration = params.get("CallDuration", "0")
    print(f"[calls] Status — {call_sid} {status} {duration}s")
    return telephony.build_empty_response()


@router.get("/debug/tokens")
async def token_stats():
    return get_token_stats()