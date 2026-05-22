"""
app/api/routes/catalog.py — HTTP catalog endpoints (non-call usage).
"""

import json
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Query

from app.services.ai.catalog_extractor import analyze_image_bytes, extract_catalog
from app.services.stt.base import transcribe_file
from typing import Optional, Annotated
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from app.db.mongo import db
router = APIRouter(prefix="/api/catalog", tags=["Catalog"])


@router.post("/from-text")
async def catalog_from_text(
    transcript: str = Form(...),
    ocr_text: Optional[str] = Form(default=None),
    existing_context: Optional[str] = Form(default=None),
    language: str = Form("en", description="hi, te, ta, en, mr, kn"),
    image: Optional[UploadFile] = File(default=None, description="Product image (optional)"),
):
    """Text transcript → structured catalog JSON. Supports all Indian languages."""
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty.")

    image_analysis = None
    if image:
        img_bytes = await image.read()
        try:
            image_analysis = await analyze_image_bytes(img_bytes, image.content_type or "image/jpeg")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Image analysis failed: {e}")

    try:
        catalog = await extract_catalog(
            transcript,
            image_analysis,
            ocr_text,
            existing_context
        )

        catalog_id = await db.save_catalog(
            call_sid="manual-api",
            catalog=catalog,
            session={
                "language": language,
                "transcripts": [transcript],
                "collected": catalog.get("product", {}),
            }
        )

        catalog["catalog_id"] = catalog_id

        return catalog
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/from-audio")
async def catalog_from_audio(
    audio: UploadFile = File(...),
    language: str = Form("en", description="hi, te, ta, en, mr, kn"),
    image: Optional[UploadFile] = File(default=None, description="Product image (optional)"),
    ocr_text: Optional[str] = Form(default=None),
    existing_context: Optional[str] = Form(default=None),
):
    audio_bytes = await audio.read()
    try:
        transcript = await transcribe_file(audio_bytes, language=language)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {e}")

    image_analysis = None
    if image:
        img_bytes = await image.read()
        try:
            image_analysis = await analyze_image_bytes(img_bytes, image.content_type or "image/jpeg")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Image analysis failed: {e}")

    try:
        result = await extract_catalog(
            transcript,
            image_analysis,
            ocr_text,
            existing_context,
        )

        # save into mongodb
        catalog_id = await db.save_catalog(
            call_sid="manual-audio-api",
            catalog=result,
            session={
                "language": language,
                "transcripts": [transcript],
                "collected": result.get("product", {}),
            },
        )

        result["catalog_id"] = catalog_id
        result["transcript"] = transcript

        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/analyze-image")
async def analyze_image_route(image: UploadFile = File(...)):
    """Product image → visual attributes JSON."""
    img_bytes = await image.read()
    try:
        return await analyze_image_bytes(img_bytes, image.content_type or "image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/transcribe")
async def transcribe_only(
    audio: UploadFile = File(...),
    language: str = Form("hi"),
):
    """Audio → transcript only."""
    audio_bytes = await audio.read()
    try:
        return {"transcript": await transcribe_file(audio_bytes, language=language)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
