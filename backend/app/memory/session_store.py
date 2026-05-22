import json
from dataclasses import asdict, dataclass, field
from typing import Any

import redis.asyncio as redis

from app.config import settings


@dataclass
class SessionState:
    session_id: str
    patient_id: str
    intent: str | None = None
    pending_confirmation: dict[str, Any] | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    turn_count: int = 0
    language: str = "en"
    campaign_id: str | None = None
    outbound_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SessionStore:
    def __init__(self, redis_client: redis.Redis | None):
        self._redis = redis_client
        self._local: dict[str, str] = {}

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}"

    async def get(self, session_id: str) -> SessionState | None:
        raw = None
        if self._redis:
            raw = await self._redis.get(self._key(session_id))
        else:
            raw = self._local.get(session_id)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return SessionState.from_dict(json.loads(raw))

    async def save(self, state: SessionState) -> None:
        payload = json.dumps(state.to_dict())
        if self._redis:
            await self._redis.setex(
                self._key(state.session_id),
                settings.session_ttl_seconds,
                payload,
            )
        else:
            self._local[state.session_id] = payload

    async def delete(self, session_id: str) -> None:
        if self._redis:
            await self._redis.delete(self._key(session_id))
        else:
            self._local.pop(session_id, None)
