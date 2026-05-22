import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.scheduling.models import InteractionLog, Patient


class PatientMemory:
    """Cross-session memory: Redis cache + SQLite source of truth."""

    def __init__(self, redis_client: redis.Redis | None):
        self._redis = redis_client
        self._local: dict[str, str] = {}

    def _key(self, patient_id: str) -> str:
        return f"patient:{patient_id}"

    async def get_profile(self, db: AsyncSession, patient_id: str) -> dict[str, Any] | None:
        cached = await self._get_cache(patient_id)
        if cached:
            return cached

        patient = await db.get(Patient, patient_id)
        if not patient:
            return None

        logs = (
            await db.execute(
                select(InteractionLog)
                .where(InteractionLog.patient_id == patient_id)
                .order_by(InteractionLog.created_at.desc())
                .limit(5)
            )
        ).scalars().all()

        profile = {
            "patient_id": patient.id,
            "name": patient.name,
            "phone": patient.phone,
            "preferred_language": patient.preferred_language,
            "recent_interactions": [log.summary for log in logs],
        }
        await self._set_cache(patient_id, profile)
        return profile

    async def update_language(self, db: AsyncSession, patient_id: str, language: str) -> None:
        patient = await db.get(Patient, patient_id)
        if patient:
            patient.preferred_language = language
            await db.commit()
        cached = await self._get_cache(patient_id)
        if cached:
            cached["preferred_language"] = language
            await self._set_cache(patient_id, cached)

    async def append_interaction(
        self,
        db: AsyncSession,
        patient_id: str,
        session_id: str,
        summary: str,
    ) -> None:
        db.add(
            InteractionLog(
                patient_id=patient_id,
                session_id=session_id,
                summary=summary,
                created_at=datetime.now(UTC),
            )
        )
        await db.commit()
        await self._redis_delete(patient_id)

    async def _get_cache(self, patient_id: str) -> dict[str, Any] | None:
        raw = None
        if self._redis:
            raw = await self._redis.get(self._key(patient_id))
        else:
            raw = self._local.get(patient_id)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)

    async def _set_cache(self, patient_id: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data)
        if self._redis:
            await self._redis.setex(
                self._key(patient_id),
                settings.patient_memory_ttl_seconds,
                payload,
            )
        else:
            self._local[patient_id] = payload

    async def _redis_delete(self, patient_id: str) -> None:
        if self._redis:
            await self._redis.delete(self._key(patient_id))
        else:
            self._local.pop(patient_id, None)
