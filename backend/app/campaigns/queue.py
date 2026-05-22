import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog

log = structlog.get_logger()


@dataclass
class CampaignJob:
    id: str
    patient_id: str
    phone: str
    campaign_type: str
    language: str
    context: dict[str, Any]
    scheduled_at: str
    status: str = "pending"

    def to_json(self) -> str:
        return json.dumps(asdict(self))


class CampaignQueue:
    """Redis-backed queue with in-process fallback for local dev."""

    def __init__(self, redis_client: Any | None):
        self._redis = redis_client
        self._local: list[CampaignJob] = []

    async def enqueue(self, job: CampaignJob) -> None:
        if self._redis:
            await self._redis.lpush("campaign:jobs", job.to_json())
        else:
            self._local.append(job)
        log.info("campaign.enqueued", job_id=job.id, patient_id=job.patient_id)

    async def dequeue(self) -> CampaignJob | None:
        if self._redis:
            raw = await self._redis.rpop("campaign:jobs")
            if not raw:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode()
            data = json.loads(raw)
            return CampaignJob(**data)
        return self._local.pop(0) if self._local else None

    async def list_pending(self) -> list[dict[str, Any]]:
        if self._redis:
            items = await self._redis.lrange("campaign:jobs", 0, -1)
            return [json.loads(i.decode() if isinstance(i, bytes) else i) for i in items]
        return [asdict(j) for j in self._local]


def build_reminder_job(
    patient_id: str,
    phone: str,
    language: str,
    appointment: dict[str, Any],
) -> CampaignJob:
    return CampaignJob(
        id=str(uuid4()),
        patient_id=patient_id,
        phone=phone,
        campaign_type="appointment_reminder",
        language=language,
        context={"appointment": appointment},
        scheduled_at=datetime.now(UTC).isoformat(),
    )
