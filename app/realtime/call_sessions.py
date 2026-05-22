"""
app/realtime/call_sessions.py — Per-call session state manager.
In-memory (dev) or Redis (production) based on REDIS_URL in .env.
"""

import json
import time
from typing import Optional
from app.core.config import settings

_USE_REDIS = bool(settings.REDIS_URL)

if _USE_REDIS:
    import redis.asyncio as aioredis
    _redis: Optional[aioredis.Redis] = None

    async def _get_redis() -> aioredis.Redis:
        global _redis
        if _redis is None:
            _redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return _redis
else:
    _store: dict[str, dict] = {}


def _empty_session(call_sid: str, caller: str = "") -> dict:
    return {
        "call_sid":           call_sid,
        "caller":             caller,
        "started_at":         time.time(),
        "language":           "auto",          # set by Deepgram auto-detect
        "history":            [],
        "collected": {
            "category": None, "color": None, "sizes": [],
            "price": None, "quantity": None, "brand": None,
            "material": None, "gender": None,
        },
        "transcripts":        [],              # full transcript log
        "partial_transcript": "",
        "uploaded_image_url": None,            # image uploaded during call
        "is_complete":        False,
        "should_end_call":    False,
        "catalog":            None,
        "turn_count":         0,
        "last_confidence":    0,
    }


async def create_session(call_sid: str, caller: str = "") -> dict:
    session = _empty_session(call_sid, caller)
    await _save(call_sid, session)
    print(f"[sessions] Created — {call_sid}")
    return session


async def get_session(call_sid: str) -> Optional[dict]:
    return await _load(call_sid)


async def update_session(call_sid: str, updates: dict) -> dict:
    session = await _load(call_sid) or _empty_session(call_sid)
    for key, value in updates.items():
        if key == "collected" and isinstance(value, dict):
            session["collected"].update({k: v for k, v in value.items() if v is not None})
        elif key == "history_append" and isinstance(value, dict):
            session["history"].append(value)
            session["turn_count"] = len(session["history"])
        else:
            session[key] = value
    await _save(call_sid, session)
    return session


async def delete_session(call_sid: str) -> None:
    if _USE_REDIS:
        r = await _get_redis()
        await r.delete(f"session:{call_sid}")
    else:
        _store.pop(call_sid, None)


async def append_history(call_sid: str, role: str, content: str) -> None:
    await update_session(call_sid, {"history_append": {"role": role, "content": content}})


async def update_collected(call_sid: str, fields: dict) -> None:
    await update_session(call_sid, {"collected": fields})


async def set_language(call_sid: str, language: str) -> None:
    await update_session(call_sid, {"language": language})


async def append_transcript(call_sid: str, text: str, confidence: float = 0) -> None:
    session = await _load(call_sid)
    if not session:
        return
    if "transcripts" not in session:
        session["transcripts"] = []
    session["transcripts"].append({
        "text": text, "confidence": confidence, "timestamp": time.time()
    })
    session["last_confidence"] = confidence
    await _save(call_sid, session)


async def set_uploaded_image(call_sid: str, image_url: str) -> None:
    """Called when seller uploads a photo during the call."""
    await update_session(call_sid, {"uploaded_image_url": image_url})
    print(f"[sessions] Image uploaded for {call_sid}: {image_url}")


async def _save(call_sid: str, session: dict) -> None:
    if _USE_REDIS:
        r = await _get_redis()
        await r.setex(f"session:{call_sid}", 7200, json.dumps(session))
    else:
        _store[call_sid] = session


async def _load(call_sid: str) -> Optional[dict]:
    if _USE_REDIS:
        r = await _get_redis()
        raw = await r.get(f"session:{call_sid}")
        return json.loads(raw) if raw else None
    return _store.get(call_sid)
