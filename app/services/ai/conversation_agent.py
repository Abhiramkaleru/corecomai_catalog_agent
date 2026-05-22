# """
# app/services/ai/conversation_agent.py
# ──────────────────────────────────────────────────────────────────────────────
# Language-aware stateful conversation agent — provider-agnostic.
# Swap AI_PROVIDER in .env; nothing here changes.
# """

# import json
# import re

# from app.core.config import settings
# from app.core.prompts import build_conversation_system
# from app.core.prompts import build_conversation_system, get_conversation_system
# from app.services.ai.base import ai          # ← active provider singleton
# from app.services.ai.catalog_extractor import extract_catalog
# import app.realtime.call_sessions as sessions
# from app.db.mongo import db
# from app.services.extractors.rule_based import extract_fields
# # Fields the agent must collect before offering to save.
# REQUIRED_FIELDS = {"category", "color", "price", "quantity"}

# # Values that look like answers but carry no real information.
# _VAGUE_VALUES = {None, "", "any", "any size", "all sizes", "any color", "any price"}


# # ─────────────────────────────────────────────────────────────────────────────
# # Internal helpers
# # ─────────────────────────────────────────────────────────────────────────────

# def _parse_agent_response(raw: str) -> dict:
#     clean = re.sub(r"```(?:json)?|```", "", raw).strip()
    
#     try:
#         result = json.loads(clean)
#         if isinstance(result, dict):
#             return result
#         raise ValueError(f"Expected dict got {type(result)}")
#     except (json.JSONDecodeError, ValueError):
#         # Try extracting JSON from partial/truncated response
#         match = re.search(r"\{.*\}", clean, re.DOTALL)
#         if match:
#             try:
#                 result = json.loads(match.group())
#                 if isinstance(result, dict):
#                     return result
#             except json.JSONDecodeError:
#                 pass

#         print(f"[agent] Parse failed — raw={clean[:150]}")
#         return {
#             "response_text":   clean or "Could you please repeat that?",
#             "language":        "en",
#             "collected":       {},
#             "is_complete":     False,
#             "save_catalog":    False,
#             "should_end_call": False,
#             "next_question":   None,
#         }
# def _sanitise_collected(incoming: dict) -> dict:
#     """
#     Strip vague / non-informative values so they never pollute the session.
#     Specifically:
#       - sizes list: remove "any size", "all sizes", empty strings
#       - scalar fields: replace vague strings with None
#     """
#     clean = {}
#     for key, value in incoming.items():
#         if key == "sizes":
#             clean[key] = [
#                 s for s in (value or [])
#                 if s and s.lower() not in {"any size", "all sizes", "any"}
#             ]
#         elif isinstance(value, str) and value.lower() in _VAGUE_VALUES:
#             clean[key] = None
#         else:
#             clean[key] = value
#     return clean


# def _all_required_filled(collected: dict) -> bool:
#     """True only when every required field has a real (non-vague) value."""
#     for field in REQUIRED_FIELDS:
#         val = collected.get(field)
#         if val in _VAGUE_VALUES or val == []:
#             return False
#     return True


# def _resolve_language(session: dict) -> str:
#     """
#     Return the language code for this session.
#     Falls back to DEFAULT_LANGUAGE; never returns 'auto'.
#     """
#     lang = session.get("language", settings.DEFAULT_LANGUAGE)
#     if not lang or lang == "auto":
#         return settings.DEFAULT_LANGUAGE
#     return lang


# # ─────────────────────────────────────────────────────────────────────────────
# # Public API
# # ─────────────────────────────────────────────────────────────────────────────

# async def process_turn(call_sid: str, seller_utterance: str) -> dict:
#     """
#     Process one seller utterance and return the agent's response.

#     Returns:
#         {
#             response_text   : str   — what to say back to the seller
#             language        : str   — detected/confirmed language code
#             is_complete     : bool  — all required fields collected (save prompt shown)
#             save_catalog    : bool  — seller explicitly confirmed save THIS turn
#             should_end_call : bool  — call should be terminated
#             catalog         : dict | None — extracted catalog (only after save)
#             catalog_id      : str  | None — MongoDB id (only after save)
#             collected       : dict  — current accumulated field values
#         }

#     State machine:
#         COLLECTING  → is_complete=False  save_catalog=False
#         CONFIRMING  → is_complete=True   save_catalog=False  (awaiting seller "yes")
#         SAVED       → is_complete=True   save_catalog=True   (catalog written once)
#     """
#     # ── 1. Load or create session ─────────────────────────────────────────
#     session = await sessions.get_session(call_sid)
#     if session is None:
#         session = await sessions.create_session(call_sid)

#     # Guard: if catalog was already saved this call, do not save again.
#     if session.get("catalog_saved"):
#         return {
#             "response_text":   "Your catalog has already been saved. Is there anything else?",
#             "language":        _resolve_language(session),
#             "is_complete":     True,
#             "save_catalog":    False,
#             "should_end_call": False,
#             "catalog":         None,
#             "catalog_id":      session.get("catalog_id"),
#             "collected":       session.get("collected", {}),
#         }

#     language_code: str = _resolve_language(session)

#     # Current collected state
#     collected = session.get("collected", {})
#     rule_fields = extract_fields(seller_utterance)

#     # Merge deterministic extraction into collected state
#     for k, v in rule_fields.items():

#         if v not in [None, "", []]:

#             # Merge sizes safely
#             if k == "sizes":
#                 existing = collected.get("sizes", [])
#                 collected["sizes"] = list(set(existing + v))

#             # Only fill empty fields
#             elif not collected.get(k):
#                 collected[k] = v
#     required_fields = ["category", "color", "price", "quantity"]
#     missing_fields  = [f for f in required_fields if not collected.get(f)]

#         # If all required filled from rule-based alone — mark complete early
#     if not missing_fields:
#             is_complete = True

    
#     history: list[dict] = session.get("history", [])
  

#     system_prompt = build_conversation_system(language_code)
#     prompt = f"""Collected: {json.dumps(collected, ensure_ascii=False)}
# Missing: {missing_fields}
# Seller: {seller_utterance}"""
#     # ── 3. Call LLM ───────────────────────────────────────────────────────
#     raw    = await ai.generate(system=system_prompt, user_message=prompt)
#     parsed = _parse_agent_response(raw)

#     # ── 4. Extract fields from LLM response ──────────────────────────────
#     response_text   = parsed.get("response_text") or "Could you please continue?"
#     collected_new   = _sanitise_collected(parsed.get("collected") or {})
#     is_complete     = bool(parsed.get("is_complete", False))
#     save_catalog    = bool(parsed.get("save_catalog", False))
#     should_end      = bool(parsed.get("should_end_call", False))
#     detected_lang   = parsed.get("language") or language_code

#     # ── 5. Merge collected fields (never overwrite confirmed values) ───────
#     prior = session.get("collected", {})
#     merged = {**prior}
#     for k, v in collected_new.items():
#         # Only update if the new value is meaningful
#         if k == "sizes":
#             existing_sizes = merged.get("sizes") or []
#             new_sizes = v or []
#             # Union — keep existing sizes, add new ones
#             merged["sizes"] = list(dict.fromkeys(existing_sizes + new_sizes))
#         elif v not in _VAGUE_VALUES:
#             if k in ("price", "quantity") and v != prior.get(k):
#                 merged[k] = v  # allow seller to correct price/quantity
#             elif not merged.get(k):
#                 merged[k] = v  # only fill empty fields for other fields

#     # ── 6. Recompute is_complete from ground truth (LLM can be wrong) ─────
#     if _all_required_filled(merged):
#         is_complete = True

#     # ── 7. Persist session ────────────────────────────────────────────────
#     # history.append({
#     #     "role": "user",
#     #     "content": seller_utterance
#     # })

#     history.append({
#         "role": "assistant",
#         "content": response_text
#     })
#     history = history[-4:]
#     await sessions.update_session(call_sid, {
#         "history":     history,
#         "collected":   merged,
#         "is_complete": is_complete,
#         "language":    detected_lang,
#     })

#     # ── 8. Build base result ──────────────────────────────────────────────
#     result = {
#         "response_text":   response_text,
#         "language":        detected_lang,
#         "is_complete":     is_complete,
#         "save_catalog":    save_catalog,
#         "should_end_call": should_end or (save_catalog and is_complete),
#         "catalog":         None,
#         "catalog_id":      None,
#         "collected":       merged,
#     }

#     # ── 9. Save catalog ONLY on explicit seller confirmation ──────────────
#     if save_catalog and is_complete and not session.get("catalog_saved"):
#         image_url = session.get("uploaded_image_url")

#         catalog = {
#             "intent":    "CREATE_PRODUCT",
#             "confidence": 95,
#             "needs_clarification": False,
#             "clarification_question": None,
#             "possible_duplicate": False,
#             "product": {
#                 "title":       None,
#                 "category":    merged.get("category"),
#                 "description": None,
#                 "brand":       merged.get("brand"),
#                 "gender":      merged.get("gender"),
#                 "attributes": {
#                     "color":       merged.get("color"),
#                     "size":        merged.get("sizes", []),
#                     "material":    merged.get("material"),
#                     "fit":         None,
#                     "pattern":     None,
#                     "sleeve_type": None,
#                     "neck_type":   None,
#                 },
#                 "pricing": {
#                     "mrp":           None,
#                     "selling_price": merged.get("price"),
#                     "currency":      "INR",
#                 },
#                 "inventory": {
#                     "quantity": merged.get("quantity"),
#                     "sku":      None,
#                 },
#                 "variants": [],
#                 "images":   [image_url] if image_url else [],
#                 "ocr_text": None,
#             },
#             "source_summary": {
#                 "transcript_used":     True,
#                 "image_analysis_used": bool(image_url),
#                 "ocr_used":            False,
#             },
#         }

#         try:
#             catalog_id = await db.save_catalog(
#                 call_sid=call_sid,
#                 catalog=catalog,
#                 session=session,
#             )

#             await sessions.update_session(call_sid, {
#                 "catalog_saved": True,
#                 "catalog_id":    catalog_id,
#             })

#             result["catalog"]    = catalog
#             result["catalog_id"] = catalog_id
#             print(f"[agent] Catalog saved — call_sid={call_sid} id={catalog_id}")

#         except Exception as exc:
#             print(f"[agent] Catalog save failed — call_sid={call_sid} error={exc}")
#     return result








"""
app/services/ai/conversation_agent.py
──────────────────────────────────────────────────────────────────────────────
Language-aware stateful conversation agent — provider-agnostic.
3-stage state machine: COLLECTING → CONFIRMING → SAVED

Stage is owned by the server, never by the LLM.
"""

from asyncio import log
import json
import re

from app.core.config import settings
from app.core.prompts import get_conversation_system
from app.services.ai.base import ai
from app.services.extractors.rule_based import extract_fields
import app.realtime.call_sessions as sessions
from app.db.mongo import db



# ── Required fields ───────────────────────────────────────────────────────────
REQUIRED_FIELDS = {"category", "color", "price", "quantity"}

_VAGUE_VALUES = {None, "", "any", "any size", "all sizes", "any color", "any price"}

# ── Confirmation words (seller says yes to save) ──────────────────────────────
_YES_WORDS = {
    # English
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "fine",
    "correct", "confirm", "save", "add", "go ahead", "done", "right",
    # Hindi
    "haan", "ha", "theek", "bilkul", "zaroor", "sahi", "karo",
    # Telugu
    "avunu", "avu", "sare", "cheyyi", "ante",
    # Tamil
    "aamam", "aama", "sari", "sollu",
    # Marathi
    "ho", "hoy",
    # Kannada
    "howdu", "maadi",
}

# ── Stages ────────────────────────────────────────────────────────────────────
STAGE_COLLECTING  = "collecting"
STAGE_CONFIRMING  = "confirming"
STAGE_SAVED       = "saved"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_agent_response(raw: str) -> dict:
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        result = json.loads(clean)
        if isinstance(result, dict):
            return result
        raise ValueError(f"Expected dict, got {type(result)}")
    except (json.JSONDecodeError, ValueError):
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass
        print(f"[agent] Parse failed — raw={clean[:150]}")
        return {
            "response_text":   clean or "Could you please repeat that?",
            "language":        "en",
            "collected":       {},
            "is_complete":     False,
            "save_catalog":    False,
            "should_end_call": False,
            "next_question":   None,
        }


def _sanitise_collected(incoming: dict) -> dict:
    clean = {}
    for key, value in incoming.items():
        if key == "sizes":
            clean[key] = [
                s for s in (value or [])
                if s and s.lower() not in {"any size", "all sizes", "any"}
            ]
        elif isinstance(value, str) and value.lower() in _VAGUE_VALUES:
            clean[key] = None
        else:
            clean[key] = value
    return clean


def _all_required_filled(collected: dict) -> bool:
    for field in REQUIRED_FIELDS:
        val = collected.get(field)
        if val in _VAGUE_VALUES or val == []:
            return False
    return True


def _resolve_language(session: dict) -> str:
    lang = session.get("language", settings.DEFAULT_LANGUAGE)
    if not lang or lang == "auto":
        return settings.DEFAULT_LANGUAGE
    return lang


def _seller_confirmed(utterance: str) -> bool:
    """Return True if the seller's utterance matches any confirmation word."""
    lower = utterance.lower().strip()
    # Check full phrase matches
    if lower in _YES_WORDS:
        return True
    # Check word-by-word
    words = re.findall(r"\w+", lower)
    return any(w in _YES_WORDS for w in words)


def _build_catalog(merged: dict, image_url: str | None) -> dict:
    return {
        "intent":    "CREATE_PRODUCT",
        "confidence": 95,
        "needs_clarification": False,
        "clarification_question": None,
        "possible_duplicate": False,
        "product": {
            "title":       None,
            "category":    merged.get("category"),
            "description": None,
            "brand":       merged.get("brand"),
            "gender":      merged.get("gender"),
            "attributes": {
                "color":       merged.get("color"),
                "size":        merged.get("sizes", []),
                "material":    merged.get("material"),
                "fit":         None,
                "pattern":     None,
                "sleeve_type": None,
                "neck_type":   None,
            },
            "pricing": {
                "mrp":           None,
                "selling_price": merged.get("price"),
                "currency":      "INR",
            },
            "inventory": {
                "quantity": merged.get("quantity"),
                "sku":      None,
            },
            "variants": [],
            "images":   [image_url] if image_url else [],
            "ocr_text": None,
        },
        "source_summary": {
            "transcript_used":     True,
            "image_analysis_used": bool(image_url),
            "ocr_used":            False,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def process_turn(call_sid: str, seller_utterance: str) -> dict:
    """
    Process one seller utterance.

    State machine (owned by server, never LLM):
        COLLECTING  →  gather fields, ask LLM for next question
        CONFIRMING  →  all fields full, waiting for seller "yes"
        SAVED       →  catalog written to DB, end call
    """

    # ── 1. Load session ───────────────────────────────────────────────────
    session = await sessions.get_session(call_sid)
    if session is None:
        session = await sessions.create_session(call_sid)

    detected_lang: str = _resolve_language(session)
    stage: str         = session.get("stage", STAGE_COLLECTING)

    # ── 2. Guard: already saved ───────────────────────────────────────────
    if stage == STAGE_SAVED or session.get("catalog_saved"):
        return {
            "response_text":   "Your catalog has already been saved. Goodbye!",
            "language":        detected_lang,
            "is_complete":     True,
            "save_catalog":    True,
            "should_end_call": True,
            "catalog":         None,
            "catalog_id":      session.get("catalog_id"),
            "collected":       session.get("collected", {}),
        }

    collected = dict(session.get("collected") or {})
    image_analysis = session.get("image_analysis", {})
    if image_analysis and not session.get("image_fields_merged"):
        if image_analysis.get("color") and not collected.get("color"):
            collected["color"] = image_analysis["color"]
        if image_analysis.get("detected_category") and not collected.get("category"):
            collected["category"] = image_analysis["detected_category"]
        if image_analysis.get("material_guess") and not collected.get("material"):
            collected["material"] = image_analysis["material_guess"]
        if image_analysis.get("pattern") and not collected.get("pattern"):
            collected["pattern"] = image_analysis["pattern"]

        await sessions.update_session(call_sid, {"image_fields_merged": True})
        print(f"[agent] image fields merged from session — call={call_sid}")
    # ── 3. STAGE: CONFIRMING — seller is answering "yes/no" ───────────────
    if stage == STAGE_CONFIRMING:
        if _seller_confirmed(seller_utterance):
            # Save catalog now
            merged    = collected
            image_url = session.get("uploaded_image_url")
            catalog   = _build_catalog(merged, image_url)

            try:
                catalog_id = await db.save_catalog(
                    call_sid=call_sid,
                    catalog=catalog,
                    session=session,
                )
                await sessions.update_session(call_sid, {
                    "catalog_saved": True,
                    "catalog_id":    catalog_id,
                    "catalog":       catalog,
                    "stage":         STAGE_SAVED,
                })
                print(f"[agent] Catalog saved — call_sid={call_sid} id={catalog_id}")

                return {
                    "response_text":   _save_confirmation_text(detected_lang),
                    "language":        detected_lang,
                    "is_complete":     True,
                    "save_catalog":    True,
                    "should_end_call": True,
                    "catalog":         catalog,
                    "catalog_id":      catalog_id,
                    "collected":       merged,
                }
            except Exception as exc:
                print(f"[agent] Catalog save failed — call_sid={call_sid} error={exc}")
                return {
                    "response_text":   "Sorry, I couldn't save your catalog. Please try again.",
                    "language":        detected_lang,
                    "is_complete":     False,
                    "save_catalog":    False,
                    "should_end_call": False,
                    "catalog":         None,
                    "catalog_id":      None,
                    "collected":       merged,
                }
        else:
            # Seller said no or something unclear — stay in confirming, ask again
            await sessions.append_history(call_sid, "assistant", _confirm_prompt_text(detected_lang, collected))
            return {
                "response_text":   _confirm_prompt_text(detected_lang, collected),
                "language":        detected_lang,
                "is_complete":     True,
                "save_catalog":    False,
                "should_end_call": False,
                "catalog":         None,
                "catalog_id":      None,
                "collected":       collected,
            }

    # ── 4. STAGE: COLLECTING — run rule extractor + LLM ──────────────────
    # 4a. Rule-based extraction (fast, deterministic)
    rule_fields = extract_fields(seller_utterance)
    for k, v in rule_fields.items():
        if v not in [None, "", []]:
            if k == "sizes":
                existing = collected.get("sizes") or []
                collected["sizes"] = list(set(existing + v))
            elif not collected.get(k):
                collected[k] = v

    missing_fields = [f for f in ["category", "color", "price", "quantity"] if not collected.get(f)]

    # 4b. Call LLM for natural language response + additional extraction
    history: list[dict] = session.get("history", [])
    # system_prompt = await get_conversation_system (detected_lang)
    # prompt = (
    #     f"Collected: {json.dumps(collected, ensure_ascii=False)}\n"
    #     f"Missing: {missing_fields}\n"
    #     f"Seller: {seller_utterance}"
    # )
    # NEW
    system_prompt = await get_conversation_system(detected_lang)

    image_url      = session.get("uploaded_image_url")
    image_analyzed = session.get("image_analyzed", False)

    if image_url and image_analyzed:
        image_note = "Seller uploaded a product image — color/category may already be filled from it. Skip asking fields already in Collected."
    elif image_url:
        image_note = "Seller uploaded a product image but analysis pending."
    else:
        image_note = "No image uploaded. After first turn, mention seller can send a product photo to speed up catalog creation."

    prompt = (
        f"Collected: {json.dumps(collected, ensure_ascii=False)}\n"
        f"Missing: {missing_fields}\n"
        f"Image: {image_note}\n"
        f"Seller: {seller_utterance}"
    )
    raw    = await ai.generate(system=system_prompt, user_message=prompt)
    parsed = _parse_agent_response(raw)

    response_text = parsed.get("response_text") or "Could you please continue?"
    detected_lang = parsed.get("language") or detected_lang

    # 4c. Merge LLM-extracted fields into collected (never overwrite confirmed)
    collected_new = _sanitise_collected(parsed.get("collected") or {})
    merged = dict(collected)
    for k, v in collected_new.items():
        if k == "sizes":
            existing_sizes = merged.get("sizes") or []
            new_sizes = v or []
            merged["sizes"] = list(dict.fromkeys(existing_sizes + new_sizes))
        elif v not in _VAGUE_VALUES:
            if k in ("price", "quantity") and v != collected.get(k):
                merged[k] = v   # allow correction
            elif not merged.get(k):
                merged[k] = v   # fill empty

    # 4d. Persist collected + history (assistant side only — user was appended upstream)
    history.append({"role": "assistant", "content": response_text})
    history = history[-6:]  # keep last 3 pairs

    await sessions.update_session(call_sid, {
        "history":   history,
        "collected": merged,
        "language":  detected_lang,
        # stage stays "collecting" until we transition below
    })

    # ── 5. Check if all required fields are now filled ────────────────────
    if _all_required_filled(merged):
        # Transition to CONFIRMING — ask seller to confirm
        confirm_text = _confirm_prompt_text(detected_lang, merged)

        await sessions.update_session(call_sid, {
            "stage":     STAGE_CONFIRMING,
            "collected": merged,
        })
        # Append confirmation prompt to history
        history.append({"role": "assistant", "content": confirm_text})
        await sessions.update_session(call_sid, {"history": history[-6:]})

        return {
            "response_text":   confirm_text,
            "language":        detected_lang,
            "is_complete":     True,   # all fields full
            "save_catalog":    False,  # NOT saved yet
            "should_end_call": False,  # do NOT close — waiting for yes
            "catalog":         None,
            "catalog_id":      None,
            "collected":       merged,
        }

    # ── 6. Still collecting ────────────────────────────────────────────────
    return {
        "response_text":   response_text,
        "language":        detected_lang,
        "is_complete":     False,
        "save_catalog":    False,
        "should_end_call": False,
        "catalog":         None,
        "catalog_id":      None,
        "collected":       merged,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Language-specific strings (inline to avoid import cycles)
# ─────────────────────────────────────────────────────────────────────────────

def _confirm_prompt_text(lang: str, merged: dict) -> str:
    color    = merged.get("color", "")
    category = merged.get("category", "")
    price    = merged.get("price", "")
    qty      = merged.get("quantity", "")

    summary = f"{color} {category}, ₹{price}, {qty} pieces"

    phrases = {
        "hi": f"Theek hai — {summary}. Kya main catalog save karun?",
        "te": f"Sare — {summary}. Catalog save cheyyanaa?",
        "ta": f"Sari — {summary}. Catalog save pannattuma?",
        "mr": f"Theek aahe — {summary}. Catalog save karaycha ka?",
        "kn": f"Sari — {summary}. Catalog save maadali?",
    }
    return phrases.get(lang, f"Got it — {summary}. Shall I save this catalog?")


def _save_confirmation_text(lang: str) -> str:
    phrases = {
        "hi": "Ho gaya! Aapka product catalog mein save ho gaya. Dhanyavaad!",
        "te": "Ayindi! Mee product catalog lo save aindi. Dhanyavadalu!",
        "ta": "Achu! Ungal product catalog-la save aagidhu. Nandri!",
        "mr": "Zala! Tumcha product catalog madhye save zala. Dhanyavaad!",
        "kn": "Aayitu! Nimma product catalog-alli save aagide. Dhanyavaadagalu!",
    }
    return phrases.get(lang, "Done! Your product has been saved to the catalog. Thank you!")