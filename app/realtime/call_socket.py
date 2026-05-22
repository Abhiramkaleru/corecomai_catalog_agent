
# """
# app/realtime/call_socket.py
# ──────────────────────────────────────────────────────────────────────────────
# Production WebSocket handler for live call audio streaming.
# Compatible with Twilio Media Streams and Exotel Stream applet.

# Architecture:
#   Phone ──► Twilio/Exotel ──► WebSocket ──► STT ──► AI ──► TTS ──► back
# """

# from __future__ import annotations

# import asyncio
# import json
# import logging
# import time
# from typing import Optional

# from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# import app.realtime.call_sessions as sessions
# from app.core.languages import detect_from_deepgram, get_lang
# from app.db.mongo import db
# from app.services.ai.conversation_agent import process_turn
# from app.services.stt.base import get_stt_session
# from app.services.telephony.base import get_telephony_provider
# from app.services.tts.base import tts

# log = logging.getLogger(__name__)

# router    = APIRouter()
# telephony = get_telephony_provider()

# # ── Constants ──────────────────────────────────────────────────────────────────

# # 20 ms of 8 kHz µ-law = 160 bytes; 2 frames per write = 320 bytes
# AUDIO_CHUNK_BYTES = 320

# # Maximum concurrent AI/TTS tasks per call (back-pressure)
# MAX_PENDING_RESPONSES = 3


# # ── Helpers ────────────────────────────────────────────────────────────────────

# def _parse_start_event(raw: str) -> Optional[dict]:
#     """
#     Reliably extract start-event fields from raw JSON regardless of how the
#     telephony provider wraps them.

#     Twilio:  { event:'start', streamSid, start:{ callSid, customParameters:{} } }
#     Exotel:  { event:'start', stream_sid, start:{ call_sid, custom_parameters:{} } }

#     Returns dict(stream_sid, call_sid, caller, custom) or None if not a start event.
#     """
#     try:
#         data = json.loads(raw)
#     except Exception:
#         return None

#     if data.get("event") != "start":
#         return None

#     blk = data.get("start", {})

#     stream_sid: str = (
#         blk.get("streamSid")
#         or blk.get("stream_sid")
#         or data.get("streamSid")
#         or data.get("stream_sid")
#         or ""
#     )
#     call_sid: str = (
#         blk.get("callSid")
#         or blk.get("call_sid")
#         or data.get("callSid")
#         or data.get("call_sid")
#         or ""
#     )
#     caller: str = (
#         blk.get("from")
#         or blk.get("caller")
#         or data.get("caller")
#         or "unknown"
#     )
#     custom: dict = (
#         blk.get("customParameters")
#         or blk.get("custom_parameters")
#         or blk.get("custom")
#         or data.get("customParameters")
#         or {}
#     )

#     return {
#         "stream_sid": stream_sid,
#         "call_sid":   call_sid,
#         "caller":     caller,
#         "custom":     custom,
#     }


# async def _send_audio(ws: WebSocket, stream_sid: str, audio: bytes) -> None:
#     if ws.client_state.value != 1:  # not CONNECTED
#         return
#     for offset in range(0, len(audio), AUDIO_CHUNK_BYTES):
#         chunk = audio[offset : offset + AUDIO_CHUNK_BYTES]
#         try:
#             await ws.send_text(telephony.encode_audio_message(stream_sid, chunk))
#         except Exception:
#             return  # stop if connection closed mid-send
#         await asyncio.sleep(0.02)
# # ── Call state ─────────────────────────────────────────────────────────────────

# class CallState:
#     """All mutable state for one WebSocket call lifetime."""

#     __slots__ = (
#         "call_sid", "stream_sid", "caller",
#         "language", "stt", "tts_lock",
#         "pending_responses", "started_at","is_speaking",
#     )

#     def __init__(self) -> None:
#         self.call_sid:          str                  = ""
#         self.stream_sid:        str                  = ""
#         self.caller:            str                  = "unknown"
#         self.language:          str                  = "en"
#         self.stt                                     = None
#         self.tts_lock:          asyncio.Lock         = asyncio.Lock()
#         self.pending_responses: asyncio.Semaphore    = asyncio.Semaphore(MAX_PENDING_RESPONSES)
#         self.started_at:        float                = time.monotonic()
#         self.is_speaking: bool = False

#     @property
#     def ready(self) -> bool:
#         """True once STT is open and we know the stream_sid."""
#         return bool(self.stt and self.stream_sid)


# # ── WebSocket endpoint ─────────────────────────────────────────────────────────

# @router.websocket("/ws/call-stream")
# async def websocket_call_stream(ws: WebSocket) -> None:
#     await ws.accept()
#     log.info("[socket] WebSocket accepted")

#     state = CallState()

#     # ── STT transcript callback ────────────────────────────────────────────
#     async def on_transcript(
#         cid: str,
#         text: str,
#         is_final: bool,
#         confidence: float = 0.0,
#         languages: list   = None,
#     ) -> None:
#         if not text.strip():
#             return
#         if state.is_speaking:
#             log.debug("[transcript] bot speaking — ignoring: %r", text)
#             return

#         if languages:
#             detected = detect_from_deepgram(languages)
#             if detected:
#                 state.language = detected
#                 await sessions.set_language(cid, detected)

#         if not is_final:
#             await sessions.update_session(cid, {"partial_transcript": text})
#             return
#         if confidence < 0.70:
#             log.debug("[transcript] low confidence %.2f, ignoring: %r", confidence, text)
#             return
#         if len(text.split()) < 2:
#             log.debug("[transcript] too short, ignoring: %r", text)
#             return

#         log.info("[transcript][%s] %s", cid, text)
#         await sessions.append_transcript(cid, text, confidence)
#         await sessions.update_session(cid, {"partial_transcript": ""})
#         await sessions.append_history(cid, "user", text)
#         print(f"[DEBUG] Seller said: {repr(text)} | collected so far: {await sessions.get_session(cid)}")
#         # Back-pressure: drop utterance if response queue is saturated
#         if state.pending_responses._value > 0:
#             asyncio.create_task(_respond(state, text, ws))
#         else:
#             log.warning("[socket][%s] response queue full — dropping utterance", cid)

#     # ── Main receive loop ──────────────────────────────────────────────────
#     try:
#         async for raw in ws.iter_text():

#             # Parse provider event
#             try:
#                 event_data = await telephony.parse_audio_event(raw)
#             except Exception as exc:
#                 log.warning("[socket] parse error: %s | raw=%.300s", exc, raw)
#                 continue

#             event: str = event_data.get("event", "unknown")

#             # If provider parser missed the start event, use raw fallback
#             if event == "unknown":
#                 try:
#                     raw_event = json.loads(raw).get("event")
#                 except Exception:
#                     raw_event = None

#                 if raw_event == "start":
#                     log.warning("[socket] parse_audio_event missed 'start' — using raw fallback")
#                     fallback = _parse_start_event(raw)
#                     if fallback:
#                         event_data = {**event_data, **fallback, "event": "start"}
#                         event = "start"

#             # ── Event dispatch ─────────────────────────────────────────────

#             if event == "connected":
#                 log.info("[socket] provider connected")

#             elif event == "start":
#                 state.stream_sid = event_data.get("stream_sid") or ""
#                 state.call_sid   = event_data.get("call_sid")   or ""
#                 state.caller     = event_data.get("caller")     or "unknown"
#                 lang_param       = (event_data.get("custom") or {}).get("language", "auto")
#                 state.language   = lang_param if lang_param not in ("", "auto") else "en"

#                 log.info(
#                     "[socket] stream started — call=%s stream=%s caller=%s lang=%s",
#                     state.call_sid, state.stream_sid, state.caller, state.language,
#                 )

#                 if not state.stream_sid:
#                     log.error(
#                         "[socket] stream_sid empty after start — check telephony parser. "
#                         "raw=%.800s", raw,
#                     )

#                 await _boot_session(state, ws, on_transcript)

#             elif event == "media":
#                 # Safety net: bootstrap if start was somehow missed
#                 if not state.ready:
#                     state.stream_sid = event_data.get("stream_sid") or state.stream_sid
#                     state.call_sid   = (
#                         event_data.get("call_sid") or state.call_sid or state.stream_sid
#                     )
#                     if state.call_sid and not state.stt:
#                         log.warning(
#                             "[socket] start never received — bootstrapping from first media. "
#                             "call=%s stream=%s", state.call_sid, state.stream_sid,
#                         )
#                         await _boot_session(state, ws, on_transcript)

#                 if not state.ready:
#                     log.debug("[socket] media dropped — session not ready")
#                     continue

#                 audio = event_data.get("audio")
#                 if audio:
#                     await state.stt.send_audio(audio)

#             elif event == "stop":
#                 # Recover call_sid from event_data if it was never set
#                 if not state.call_sid:
#                     state.call_sid = event_data.get("call_sid") or state.stream_sid or ""
#                 log.info(
#                     "[socket] stream stopped — call=%s reason=%s",
#                     state.call_sid, event_data.get("reason", "unknown"),
#                 )
#                 break

#             else:
#                 log.debug("[socket] unhandled event %r", event)

#     except WebSocketDisconnect:
#         log.info("[socket] client disconnected — call=%s", state.call_sid)
#     except Exception as exc:
#         log.exception("[socket] unhandled error — call=%s: %s", state.call_sid, exc)
#     finally:
#         await _teardown(state)


# # ── Session bootstrap ──────────────────────────────────────────────────────────

# async def _boot_session(
#     state: CallState,
#     ws: WebSocket,
#     on_transcript,
# ) -> None:
#     """
#     Idempotent: create the call session, open STT, send greeting.
#     Safe to call more than once — no-ops if STT is already open.
#     """
#     if state.stt:
#         return

#     if not await sessions.get_session(state.call_sid):
#         await sessions.create_session(state.call_sid, state.caller)

#     await sessions.set_language(state.call_sid, state.language)

#     state.stt = get_stt_session(state.call_sid, on_transcript)
#     await state.stt.connect()
#     log.info("[stt] session open — call=%s", state.call_sid)

#     lang_obj       = get_lang(state.language)
#     greeting_audio = await tts.synthesize(lang_obj.greeting, language_code=state.language)
#     await _send_audio(ws, state.stream_sid, greeting_audio)
#     log.info("[tts] greeting sent (%d bytes) — call=%s", len(greeting_audio), state.call_sid)


# # ── AI response ────────────────────────────────────────────────────────────────

# async def _respond(state: CallState, utterance: str, ws: WebSocket) -> None:
#     async with state.pending_responses:
#         async with state.tts_lock:
#             try:
#                 if ws.client_state.value != 1:
#                     return

#                 result   = await process_turn(state.call_sid, utterance)
#                 reply    = result["response_text"]
#                 language = result.get("language") or state.language

#                 if result.get("collected"):
#                     await sessions.update_collected(state.call_sid, result["collected"])

#                 log.info("[agent][%s] %s", state.call_sid, reply)

#                 audio = await tts.synthesize(reply, language_code=language)
#                 if not audio:
#                     log.warning("[tts] empty audio — skipping")
#                     return

#                 if state.stream_sid and ws.client_state.value == 1:
#                     state.is_speaking = True
#                     await _send_audio(ws, state.stream_sid, audio)
#                     await asyncio.sleep(0.3)  # brief pause after speaking
#                     state.is_speaking = False

#                 if result.get("should_end_call") or result.get("is_complete"):
#                     if result.get("catalog"):
#                         await sessions.update_session(
#                             state.call_sid, {"catalog": result["catalog"]}
#                         )
#                     if ws.client_state.value == 1:
#                         closing_audio = await tts.synthesize(
#                             get_lang(language).closing, language_code=language
#                         )
#                         if state.stream_sid and closing_audio:
#                             state.is_speaking = True
#                             await _send_audio(ws, state.stream_sid, closing_audio)
#                             state.is_speaking = False

#             except Exception as exc:
#                 state.is_speaking = False  # always unblock on error
#                 if "websocket" not in str(exc).lower():
#                     log.exception("[agent] error — call=%s: %s", state.call_sid, exc)
# # ── Cleanup ────────────────────────────────────────────────────────────────────

# async def _teardown(state: CallState) -> None:
#     """Close STT, persist the call record, remove in-memory session."""
#     duration = round(time.monotonic() - state.started_at, 1)

#     if state.stt:
#         try:
#             await state.stt.close()
#             log.info("[stt] closed — call=%s", state.call_sid)
#         except Exception as exc:
#             log.warning("[stt] close error — call=%s: %s", state.call_sid, exc)

#     if state.call_sid:
#         try:
#             session = await sessions.get_session(state.call_sid)
#             if session:
#                 session["duration_sec"] = duration
#                 await db.save_call(state.call_sid, session)
#                 log.info("[db] call saved — call=%s duration=%ss", state.call_sid, duration)

#                 if session.get("catalog"):
#                     catalog_id = await db.save_catalog(
#                         state.call_sid, session["catalog"], session
#                     )
#                     log.info("[db] catalog saved — id=%s", catalog_id)

#             await sessions.delete_session(state.call_sid)
#         except Exception as exc:
#             log.exception("[db] teardown error — call=%s: %s", state.call_sid, exc)

#     log.info("[socket] cleaned up — call=%s duration=%ss", state.call_sid, duration)






"""
app/realtime/call_socket.py
──────────────────────────────────────────────────────────────────────────────
Production WebSocket handler for live call audio streaming.
Compatible with Twilio Media Streams and Exotel Stream applet.

Architecture:
  Phone ──► Twilio/Exotel ──► WebSocket ──► STT ──► AI ──► TTS ──► back

State machine (owned by conversation_agent):
  COLLECTING → CONFIRMING → SAVED → (end call)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import app.realtime.call_sessions as sessions
from app.core.languages import detect_from_deepgram, get_lang
from app.db.mongo import db
from app.services.ai.conversation_agent import process_turn
from app.services.stt.base import get_stt_session
from app.services.telephony.base import get_telephony_provider
from app.services.tts.base import tts

log = logging.getLogger(__name__)

router    = APIRouter()
telephony = get_telephony_provider()

# ── Constants ──────────────────────────────────────────────────────────────────

# 20 ms of 8 kHz µ-law = 160 bytes; 2 frames per write = 320 bytes
AUDIO_CHUNK_BYTES = 320

# Maximum concurrent AI/TTS tasks per call (back-pressure)
MAX_PENDING_RESPONSES = 3


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_start_event(raw: str) -> Optional[dict]:
    """
    Reliably extract start-event fields from raw JSON regardless of how the
    telephony provider wraps them.

    Twilio:  { event:'start', streamSid, start:{ callSid, customParameters:{} } }
    Exotel:  { event:'start', stream_sid, start:{ call_sid, custom_parameters:{} } }

    Returns dict(stream_sid, call_sid, caller, custom) or None if not a start event.
    """
    try:
        data = json.loads(raw)
    except Exception:
        return None

    if data.get("event") != "start":
        return None

    blk = data.get("start", {})

    stream_sid: str = (
        blk.get("streamSid")
        or blk.get("stream_sid")
        or data.get("streamSid")
        or data.get("stream_sid")
        or ""
    )
    call_sid: str = (
        blk.get("callSid")
        or blk.get("call_sid")
        or data.get("callSid")
        or data.get("call_sid")
        or ""
    )
    caller: str = (
        blk.get("from")
        or blk.get("caller")
        or data.get("caller")
        or "unknown"
    )
    custom: dict = (
        blk.get("customParameters")
        or blk.get("custom_parameters")
        or blk.get("custom")
        or data.get("customParameters")
        or {}
    )

    return {
        "stream_sid": stream_sid,
        "call_sid":   call_sid,
        "caller":     caller,
        "custom":     custom,
    }


async def _send_audio(ws: WebSocket, stream_sid: str, audio: bytes) -> None:
    if ws.client_state.value != 1:  # not CONNECTED
        return
    for offset in range(0, len(audio), AUDIO_CHUNK_BYTES):
        chunk = audio[offset : offset + AUDIO_CHUNK_BYTES]
        try:
            await ws.send_text(telephony.encode_audio_message(stream_sid, chunk))
        except Exception:
            return  # stop if connection closed mid-send
        await asyncio.sleep(0)


# ── Call state ─────────────────────────────────────────────────────────────────

class CallState:
    """All mutable state for one WebSocket call lifetime."""

    __slots__ = (
        "call_sid", "stream_sid", "caller",
        "language", "stt", "tts_lock",
        "pending_responses", "started_at", "is_speaking",
        "end_call_requested",
    )

    def __init__(self) -> None:
        self.call_sid:           str               = ""
        self.stream_sid:         str               = ""
        self.caller:             str               = "unknown"
        self.language:           str               = "en"
        self.stt                                   = None
        self.tts_lock:           asyncio.Lock      = asyncio.Lock()
        self.pending_responses:  asyncio.Semaphore = asyncio.Semaphore(MAX_PENDING_RESPONSES)
        self.started_at:         float             = time.monotonic()
        self.is_speaking:        bool              = False
        # Set True ONLY when should_end_call=True comes back from agent.
        # Prevents re-entry on subsequent transcripts while we're closing.
        self.end_call_requested: bool              = False

    @property
    def ready(self) -> bool:
        """True once STT is open and we know the stream_sid."""
        return bool(self.stt and self.stream_sid)


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@router.websocket("/ws/call-stream")
async def websocket_call_stream(ws: WebSocket) -> None:
    await ws.accept()
    log.info("[socket] WebSocket accepted")

    state = CallState()

    # ── STT transcript callback ────────────────────────────────────────────
    async def on_transcript(
        cid: str,
        text: str,
        is_final: bool,
        confidence: float = 0.0,
        languages: list   = None,
    ) -> None:
        if not text.strip():
            return

        # If we are already closing, discard new transcripts
        if state.end_call_requested:
            log.debug("[transcript] end_call in progress — ignoring: %r", text)
            return

        if state.is_speaking:
            log.debug("[transcript] bot speaking — ignoring: %r", text)
            return

        if languages:
            detected = detect_from_deepgram(languages)
            if detected:
                state.language = detected
                await sessions.set_language(cid, detected)

        if not is_final:
            await sessions.update_session(cid, {"partial_transcript": text})
            return
        if confidence < 0.70:
            log.debug("[transcript] low confidence %.2f, ignoring: %r", confidence, text)
            return
        if len(text.split()) < 2:
            log.debug("[transcript] too short, ignoring: %r", text)
            return

        log.info("[transcript][%s] %s", cid, text)
        await sessions.append_transcript(cid, text, confidence)
        await sessions.update_session(cid, {"partial_transcript": ""})
        await sessions.append_history(cid, "user", text)
        print(f"[DEBUG] Seller said: {repr(text)} | collected so far: {await sessions.get_session(cid)}")

        # Back-pressure: drop utterance if response queue is saturated
        if state.pending_responses._value > 0:
            asyncio.create_task(_respond(state, text, ws))
        else:
            log.warning("[socket][%s] response queue full — dropping utterance", cid)

    # ── Main receive loop ──────────────────────────────────────────────────
    try:
        async for raw in ws.iter_text():
            log.info("[DEBUG ALL EVENTS] %s", raw[:200])
            # Parse provider event
            try:
                event_data = await telephony.parse_audio_event(raw)
            except Exception as exc:
                log.warning("[socket] parse error: %s | raw=%.300s", exc, raw)
                continue

            event: str = event_data.get("event", "unknown")

            # If provider parser missed the start event, use raw fallback
            if event == "unknown":
                try:
                    raw_event = json.loads(raw).get("event")
                except Exception:
                    raw_event = None

                if raw_event == "start":
                    log.warning("[socket] parse_audio_event missed 'start' — using raw fallback")
                    fallback = _parse_start_event(raw)
                    if fallback:
                        event_data = {**event_data, **fallback, "event": "start"}
                        event = "start"

            # ── Event dispatch ─────────────────────────────────────────────

            if event == "connected":
                log.info("[socket] provider connected")

            elif event == "start":
                state.stream_sid = event_data.get("stream_sid") or ""
                state.call_sid   = event_data.get("call_sid")   or ""
                state.caller     = event_data.get("caller")     or "unknown"
                lang_param       = (event_data.get("custom") or {}).get("language", "auto")
                state.language   = lang_param if lang_param not in ("", "auto") else "en"

                log.info(
                    "[socket] stream started — call=%s stream=%s caller=%s lang=%s",
                    state.call_sid, state.stream_sid, state.caller, state.language,
                )

                if not state.stream_sid:
                    log.error(
                        "[socket] stream_sid empty after start — check telephony parser. "
                        "raw=%.800s", raw,
                    )

                await _boot_session(state, ws, on_transcript)

            elif event == "media":
                log.info("[DEBUG RAW MEDIA] %s", raw[:500])
                if not state.ready:
                    state.stream_sid = event_data.get("stream_sid") or state.stream_sid
                    state.call_sid   = (
                        event_data.get("call_sid") or state.call_sid or state.stream_sid
                    )
                    if state.call_sid and not state.stt:
                        log.warning(
                            "[socket] start never received — bootstrapping from first media. "
                            "call=%s stream=%s", state.call_sid, state.stream_sid,
                        )
                        await _boot_session(state, ws, on_transcript)

                if not state.ready:
                    log.debug("[socket] media dropped — session not ready")
                    continue

                # If call end was requested, drain remaining audio but stop processing
                if state.end_call_requested:
                    continue

                audio = event_data.get("audio") or (event_data.get("media") or {}).get("payload")
                if audio:
                    await state.stt.send_audio(audio)

            elif event == "stop":
                # Recover call_sid from event_data if it was never set
                if not state.call_sid:
                    state.call_sid = event_data.get("call_sid") or state.stream_sid or ""
                log.info(
                    "[socket] stream stopped — call=%s reason=%s",
                    state.call_sid, event_data.get("reason", "unknown"),
                )
                break

            else:
                log.debug("[socket] unhandled event %r", event)

    except WebSocketDisconnect:
        log.info("[socket] client disconnected — call=%s", state.call_sid)
    except RuntimeError as exc:
        if "not connected" in str(exc).lower() or "accept" in str(exc).lower():
            log.info(
                "[socket] provider closed connection abruptly (Exotel) — call=%s",
                state.call_sid,
            )
        else:
            log.exception("[socket] unhandled RuntimeError — call=%s: %s", state.call_sid, exc)
    except Exception as exc:
        log.exception("[socket] unhandled error — call=%s: %s", state.call_sid, exc)
    finally:
        await _teardown(state)


# ── Session bootstrap ──────────────────────────────────────────────────────────

async def _boot_session(
    state: CallState,
    ws: WebSocket,
    on_transcript,
) -> None:
    """
    Idempotent: create the call session, open STT, send greeting.
    Safe to call more than once — no-ops if STT is already open.
    """
    if state.stt:
        return

    if not await sessions.get_session(state.call_sid):
        await sessions.create_session(state.call_sid, state.caller)

    await sessions.set_language(state.call_sid, state.language)

    state.stt = get_stt_session(state.call_sid, on_transcript)
    await state.stt.connect()
    log.info("[stt] session open — call=%s", state.call_sid)
    await asyncio.sleep(1.0)
    lang_obj       = get_lang(state.language)
    greeting_audio = await tts.synthesize(lang_obj.greeting, language_code=state.language)
    await _send_audio(ws, state.stream_sid, greeting_audio)
    log.info("[tts] greeting sent (%d bytes) — call=%s", len(greeting_audio), state.call_sid)


# ── AI response ────────────────────────────────────────────────────────────────

async def _respond(state: CallState, utterance: str, ws: WebSocket) -> None:
    async with state.pending_responses:
        async with state.tts_lock:
            try:
                if ws.client_state.value != 1:
                    return

                # Double-check: don't process if end already triggered
                if state.end_call_requested:
                    return

                result   = await process_turn(state.call_sid, utterance)
                reply    = result["response_text"]
                language = result.get("language") or state.language

                if result.get("collected"):
                    await sessions.update_collected(state.call_sid, result["collected"])

                log.info("[agent][%s] %s", state.call_sid, reply)

                audio = await tts.synthesize(reply, language_code=language)
                if not audio:
                    log.warning("[tts] empty audio — skipping")
                    return

                if state.stream_sid and ws.client_state.value == 1:
                    try:
                        state.is_speaking = True
                        await _send_audio(ws, state.stream_sid, audio)
                        await asyncio.sleep(0.3)
                    finally:
                        state.is_speaking = False  # ensure we always reset this flag   

                # ── ONLY end the call when agent explicitly says so ────────
                # is_complete=True alone does NOT close the call.
                # We need should_end_call=True (set only after catalog saved).
                # if result.get("should_end_call"):
                #     state.end_call_requested = True

                #     lang_obj = get_lang(language)
                #     if ws.client_state.value == 1:
                #         closing_audio = await tts.synthesize(
                #             lang_obj.closing, language_code=language
                #         )
                #         if state.stream_sid and closing_audio:
                #             state.is_speaking = True
                #             await _send_audio(ws, state.stream_sid, closing_audio)
                #             await asyncio.sleep(0.5)   # let audio drain
                #             state.is_speaking = False

                #     # Close the WebSocket — triggers _teardown via finally block
                #     try:
                #         # await ws.close()
                #             await asyncio.sleep(0.5)
                #             await ws.close()
                #     except Exception:
                #         pass  # already closed is fine
                if result.get("should_end_call"):
                    state.end_call_requested = True

                    lang_obj = get_lang(language)
                    if ws.client_state.value == 1:
                        closing_audio = await tts.synthesize(
                            lang_obj.closing, language_code=language
                        )
                        if state.stream_sid and closing_audio:
                            state.is_speaking = True
                            await _send_audio(ws, state.stream_sid, closing_audio)
                            await asyncio.sleep(0.5)
                            state.is_speaking = False
            except Exception as exc:
                state.is_speaking = False  # always unblock on error
                if "websocket" not in str(exc).lower():
                    log.exception("[agent] error — call=%s: %s", state.call_sid, exc)


# ── Cleanup ────────────────────────────────────────────────────────────────────

async def _teardown(state: CallState) -> None:
    """
    Clean up resources.

    IMPORTANT: This function must NEVER write business records (catalog, etc).
    Catalog saving is the exclusive responsibility of conversation_agent.process_turn.
    teardown only persists call metadata (duration, closed_at).
    """
    call_sid = state.call_sid or "unknown"
    log.info("[teardown] starting — call=%s", call_sid)

    # ── Close STT ─────────────────────────────────────────────────────────
    if state.stt:
        try:
            await state.stt.close()
            log.info("[stt] closed — call=%s", call_sid)
        except Exception as exc:
            log.warning("[stt] close error — call=%s: %s", call_sid, exc)

    # ── Persist call record (metadata only) ───────────────────────────────
    if call_sid and call_sid != "unknown":
        try:
            session = await sessions.get_session(call_sid)
            if session:
                duration = time.monotonic() - state.started_at
                await db.save_call(
                    call_sid=call_sid,
                    session=session,
                    # duration=duration,
                )
                log.info("[mongo] Call saved — %s (%.1fs)", call_sid, duration)
        except Exception as exc:
            log.warning("[mongo] save_call failed — call=%s: %s", call_sid, exc)

    log.info("[teardown] done — call=%s", call_sid)