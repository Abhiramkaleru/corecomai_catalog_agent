"""
main.py — FastAPI application entrypoint.

Run:
  uvicorn main:app --reload --port 8000

Swap any provider by editing .env — nothing else changes:
  TELEPHONY_PROVIDER = twilio | exotel | plivo
  STT_PROVIDER       = deepgram
  TTS_PROVIDER       = cartesia | sarvam | elevenlabs
  AI_PROVIDER        = gemini | openai
  STORAGE_PROVIDER   = local | s3 | gcs
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.mongo import db

# Routers
from app.api.routes.calls   import router as calls_router
from app.api.routes.catalog import router as catalog_router
from app.api.routes.upload  import router as upload_router
from app.realtime.call_socket import router as socket_router
from app.api.routes.outbound import router as outbound_router

app = FastAPI(
    title="Core Com Ai Seller Catalog Voice Agent",
    description="AI voice agent for Indian sellers — multilingual, provider-swappable.",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded images at /uploads/<call_sid>/<file>
os.makedirs(settings.LOCAL_UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.LOCAL_UPLOAD_DIR), name="uploads")

# Register all routers
app.include_router(calls_router)
app.include_router(catalog_router)
app.include_router(upload_router)
app.include_router(socket_router)
app.include_router(outbound_router)


@app.get("/health", tags=["Health"])
def health():
    return {
        "status":    "ok",
        "version":   "4.0.0",
        "providers": {
            "telephony": settings.TELEPHONY_PROVIDER,
            "stt":       settings.STT_PROVIDER,
            "tts":       settings.TTS_PROVIDER,
            "ai":        settings.AI_PROVIDER,
            "storage":   settings.STORAGE_PROVIDER,
        },
    }
@app.get("/", tags=["Welcome"])
def rootcheck():
    return {
        "status":    "ok",
    }



@app.on_event("startup")
async def startup():
    await db.connect()
    settings.validate()
    print(f"[app] v4.0.0 started — env={settings.APP_ENV}")
    print(f"[app] Telephony : {settings.TELEPHONY_PROVIDER}")
    print(f"[app] STT       : {settings.STT_PROVIDER}")
    print(f"[app] TTS       : {settings.TTS_PROVIDER}")
    print(f"[app] AI        : {settings.AI_PROVIDER}")
    print(f"[app] Storage   : {settings.STORAGE_PROVIDER}")
    print(f"[app] WS URL    : {settings.PUBLIC_WS_URL}")


@app.on_event("shutdown")
async def shutdown():
    await db.disconnect()
    print("[app] shutdown")
