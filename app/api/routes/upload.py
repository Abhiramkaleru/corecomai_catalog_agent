"""
app/api/routes/upload.py
──────────────────────────────────────────────────────────────────────────────
Image upload during a live call.

Flow:
  1. Seller is on the phone and says "ek photo bhej raha hoon"
  2. Your seller app (WhatsApp bot / web page) shows an upload button
  3. Seller uploads photo to POST /api/upload/call-image?call_sid=CA...
  4. Image is stored via storage provider
  5. call_sid session is updated with the image URL
  6. On next AI turn, conversation_agent passes image_url to extract_catalog
  7. Gemini vision analyzes the image and fills in product attributes

The seller does NOT need to stop the call — upload happens in parallel.
"""

from fastapi import APIRouter, File, UploadFile, Query, HTTPException
from fastapi.responses import JSONResponse

from app.realtime.call_sessions import get_session, set_uploaded_image
from app.services.storage.base import storage
from app.services.ai.catalog_extractor import analyze_image_bytes

router = APIRouter(prefix="/api/upload", tags=["Upload"])


@router.post("/call-image")
async def upload_call_image(
    call_sid: str = Query(..., description="Active call SID to attach image to"),
    image: UploadFile = File(..., description="Product image jpg/png/webp"),
):
    """
    Upload a product image during an active call.
    The image is analyzed immediately and linked to the call session.
    """
    # Verify call is active
    session = await get_session(call_sid)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"No active call found for call_sid={call_sid}. "
                   "Make sure the call is still in progress."
        )

    # Read image
    img_bytes  = await image.read()
    media_type = image.content_type or "image/jpeg"

    if not media_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image (jpg/png/webp)")

    if len(img_bytes) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="Image too large. Max 10MB.")

    # Store image
    try:
        image_url = await storage.save(
            call_sid=call_sid,
            filename=image.filename or "product.jpg",
            data=img_bytes,
            content_type=media_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage failed: {e}")

    # Link to session
    await set_uploaded_image(call_sid, image_url)

    # Analyze immediately so it's ready for the next AI turn
    analysis = {}
    try:
        analysis = await analyze_image_bytes(img_bytes, media_type)
        from app.realtime.call_sessions import update_session
        await update_session(call_sid, {
            "image_analysis": analysis,
            "image_analyzed": True,
        })
    except Exception as e:
        print(f"[upload] Image analysis failed for {call_sid}: {e}")

    return JSONResponse({
        "success":    True,
        "call_sid":   call_sid,
        "image_url":  image_url,
        "analysis":   analysis,
        "message":    "Image linked to your call. The AI will use it for catalog details.",
    })


@router.post("/standalone-image")
async def upload_standalone_image(
    image: UploadFile = File(..., description="Product image for one-shot analysis"),
):
    """
    Analyze a product image without an active call.
    Used by the HTTP catalog endpoints.
    """
    img_bytes  = await image.read()
    media_type = image.content_type or "image/jpeg"

    try:
        analysis = await analyze_image_bytes(img_bytes, media_type)
        return {"success": True, "analysis": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
