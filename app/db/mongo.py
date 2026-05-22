"""
app/db/mongo.py
──────────────────────────────────────────────────────────────────────────────
MongoDB connection + all catalog/call persistence operations.

Collections:
  catalogs   — one doc per saved product (from a completed call)
  calls      — one doc per call (metadata + full transcript + session)

Usage anywhere in the app:
  from app.db.mongo import db
  await db.save_catalog(call_sid, catalog_dict)
  await db.save_call(call_sid, session_dict)
"""

import time
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import DESCENDING

from app.core.config import settings


class MongoDB:

    def __init__(self):
        self._client: Optional[AsyncIOMotorClient] = None
        self._db = None

    async def connect(self):
        if self._client:
            return
        self._client = AsyncIOMotorClient(settings.MONGODB_URL)
        self._db = self._client[settings.MONGODB_DB_NAME]
        # Indexes — run once, ignored if already exist
        await self._db.catalogs.create_index("call_sid")
        await self._db.catalogs.create_index("seller_phone")
        await self._db.catalogs.create_index([("created_at", DESCENDING)])
        await self._db.calls.create_index("call_sid", unique=True)
        print(f"[mongo] Connected to {settings.MONGODB_DB_NAME}")

    async def disconnect(self):
        if self._client:
            self._client.close()

    # ── Catalog ───────────────────────────────────────────────────────────

    async def save_catalog(self, call_sid: str, catalog: dict, session: dict = None) -> str:
        """
        Save the extracted product catalog to MongoDB.
        Returns the inserted document _id as a string.
        """
        doc = {
            "call_sid":    call_sid,
            "seller_phone": session.get("caller", "") if session else "",
            "language":    session.get("language", "en") if session else "en",
            "created_at":  time.time(),
            # Full structured catalog from AI extraction
            "intent":      catalog.get("intent"),
            "confidence":  catalog.get("confidence", 0),
            "product":     catalog.get("product", {}),
            "source_summary": catalog.get("source_summary", {}),
            # Raw collected fields from conversation
            "collected":   session.get("collected", {}) if session else {},
            # Full call transcript
            "transcripts": session.get("transcripts", []) if session else [],
            # Image if uploaded during call
            "image_url":   session.get("uploaded_image_url") if session else None,
        }
        result = await self._db.catalogs.insert_one(doc)
        print(f"[mongo] Catalog saved — call_sid={call_sid} id={result.inserted_id}")
        return str(result.inserted_id)

    async def get_catalog(self, catalog_id: str) -> Optional[dict]:
        from bson import ObjectId
        doc = await self._db.catalogs.find_one({"_id": ObjectId(catalog_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def list_catalogs(
        self,
        seller_phone: str = None,
        limit: int = 50,
        skip: int = 0,
    ) -> list[dict]:
        query = {}
        if seller_phone:
            query["seller_phone"] = seller_phone
        cursor = self._db.catalogs.find(query).sort("created_at", DESCENDING).skip(skip).limit(limit)
        docs = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            docs.append(doc)
        return docs

    # ── Calls ─────────────────────────────────────────────────────────────

    async def save_call(self, call_sid: str, session: dict) -> None:
        """
        Upsert the full call session at end of call.
        Stores everything: transcript, language, history, collected fields.
        """
        doc = {
            "call_sid":    call_sid,
            "caller":      session.get("caller", ""),
            "language":    session.get("language", "en"),
            "started_at":  session.get("started_at"),
            "ended_at":    time.time(),
            "turn_count":  session.get("turn_count", 0),
            "is_complete": session.get("is_complete", False),
            "history":     session.get("history", []),
            "transcripts": session.get("transcripts", []),
            "collected":   session.get("collected", {}),
            "image_url":   session.get("uploaded_image_url"),
        }
        await self._db.calls.update_one(
            {"call_sid": call_sid},
            {"$set": doc},
            upsert=True,
        )
        print(f"[mongo] Call saved — {call_sid}")

    async def get_call(self, call_sid: str) -> Optional[dict]:
        doc = await self._db.calls.find_one({"call_sid": call_sid})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc


# Singleton — import this everywhere
db = MongoDB()
