"""
app/services/ai/catalog_extractor.py
──────────────────────────────────────────────────────────────────────────────
One-shot catalog extraction — provider-agnostic.
Swap AI_PROVIDER in .env; nothing here changes.
"""

import json
import re
from typing import Optional

from app.core.prompts import IMAGE_ANALYSIS_SYSTEM, CATALOG_EXTRACTION_SYSTEM
from app.services.ai.base import ai          # ← active provider singleton


def _parse_json(text: str) -> dict:
    clean = re.sub(r"```(?:json)?|```", "", text).strip()
    return json.loads(clean)


# ── Image analysis ────────────────────────────────────────────────────────

async def analyze_image_bytes(image_bytes: bytes, media_type: str) -> dict:
    """Analyze a product image supplied as raw bytes."""
    raw = await ai.generate_with_image(
        system=IMAGE_ANALYSIS_SYSTEM,
        image=image_bytes,
        media_type=media_type,
        text_prompt="Analyze this product image and return ONLY valid JSON.",
    )
    try:
        return _parse_json(raw)
    except Exception:
        return {"additional_notes": raw.strip()}


async def analyze_image_url(image_url: str) -> dict:
    """Analyze a product image from a public URL."""
    raw = await ai.generate_with_image(
        system=IMAGE_ANALYSIS_SYSTEM,
        image=image_url,
        media_type="image/jpeg",
        text_prompt="Analyze this product image and return ONLY valid JSON.",
    )
    try:
        return _parse_json(raw)
    except Exception:
        return {"additional_notes": raw.strip()}


# ── Catalog extraction ────────────────────────────────────────────────────

async def extract_catalog(
    transcript: Optional[str],
    image_analysis: Optional[dict],
    ocr_text: Optional[str],
    existing_context: Optional[str],
    image_url: Optional[str] = None,
) -> dict:
    """
    Build the structured catalog entry from all available sources.
    Works with any Indian language transcript.
    """
    parts = []
    source_summary = {
        "transcript_used":     False,
        "image_analysis_used": False,
        "ocr_used":            False,
    }

    if transcript and transcript.strip():
        parts.append(f"Transcript: {transcript}")
        source_summary["transcript_used"] = True

    if image_analysis:
        parts.append(f"Image Analysis: {json.dumps(image_analysis)}")
        source_summary["image_analysis_used"] = True

    if ocr_text and ocr_text.strip():
        parts.append(f"OCR Text: {ocr_text}")
        source_summary["ocr_used"] = True

    if existing_context and existing_context.strip():
        parts.append(f"Existing Catalog Context: {existing_context}")

    user_message = "\n".join(parts) or "No input provided."

    # If an image URL was uploaded during the call, pass it to the vision call
    if image_url:
        source_summary["image_analysis_used"] = True
        raw = await ai.generate_with_image(
            system=CATALOG_EXTRACTION_SYSTEM,
            image=image_url,
            media_type="image/jpeg",
            text_prompt=user_message,
        )
    else:
        raw = await ai.generate(
            system=CATALOG_EXTRACTION_SYSTEM,
            user_message=user_message,
        )

    result = _parse_json(raw)
    result["source_summary"] = source_summary
    return result