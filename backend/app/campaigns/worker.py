"""ARQ worker entrypoint for processing outbound campaign jobs."""

from typing import Any

import structlog

from app.campaigns.queue import CampaignJob, CampaignQueue

log = structlog.get_logger()


async def process_campaign_job(ctx: dict[str, Any], job_payload: dict[str, Any]) -> dict[str, Any]:
    """Background worker: marks job processed; voice gateway initiates actual call."""
    job = CampaignJob(**job_payload)
    log.info(
        "campaign.processed",
        job_id=job.id,
        patient_id=job.patient_id,
        campaign_type=job.campaign_type,
    )
    return {"job_id": job.id, "status": "ready_for_dial", "context": job.context}


class WorkerSettings:
    functions = [process_campaign_job]
    redis_settings = None  # set via env in arq worker CLI
