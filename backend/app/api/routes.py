from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.orchestrator import AgentOrchestrator
from app.campaigns.queue import CampaignQueue, build_reminder_job
from app.db import get_db
from app.latency.metrics import LatencyRegistry
from app.memory.session_store import SessionState
from app.scheduling import service as scheduling
from app.scheduling.service import SchedulingError

router = APIRouter()


class TurnRequest(BaseModel):
    session_id: str
    patient_id: str
    text: str
    patient_name: str = "Guest Patient"
    phone: str = "0000000000"
    language: str = "en"
    history: list[dict[str, str]] = Field(default_factory=list)
    turn_id: str | None = None
    latency: dict[str, float] | None = None


class TurnResponse(BaseModel):
    reply: str
    language: str
    trace: list[dict[str, Any]]
    session: dict[str, Any]
    latency: dict[str, Any] | None = None


class OutboundStartRequest(BaseModel):
    patient_id: str
    phone: str
    language: str = "en"
    appointment: dict[str, Any]


@router.post("/agent/turn", response_model=TurnResponse)
async def agent_turn(req: TurnRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await scheduling.ensure_patient(
        db, req.patient_id, req.patient_name, req.phone, req.language
    )
    orchestrator = AgentOrchestrator(
        db,
        request.app.state.sessions,
        request.app.state.patients,
    )
    registry: LatencyRegistry = request.app.state.latency
    turn_id = req.turn_id or str(uuid4())
    span = registry.get(turn_id) or registry.start(req.session_id, turn_id)
    span.mark("agent_start_ms")

    try:
        result = await orchestrator.run_turn(
            req.session_id,
            req.patient_id,
            req.text,
            req.history,
            req.language,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Agent failed: {exc}. Check OPENAI_API_KEY in backend/.env",
        ) from exc
    span.mark("agent_done_ms")
    latency_report = registry.finalize(turn_id)

    return TurnResponse(
        reply=result["reply"],
        language=result["language"],
        trace=result["trace"],
        session=result["session"],
        latency=latency_report,
    )


@router.get("/trace/{session_id}")
async def get_session_trace(session_id: str, request: Request):
    state = await request.app.state.sessions.get(session_id)
    if not state:
        raise HTTPException(404, "Session not found")
    return state.to_dict()


@router.post("/sessions/outbound")
async def start_outbound(req: OutboundStartRequest, request: Request, db: AsyncSession = Depends(get_db)):
    session_id = str(uuid4())
    state = SessionState(
        session_id=session_id,
        patient_id=req.patient_id,
        intent="campaign_followup",
        language=req.language,
        outbound_context={
            "type": "appointment_reminder",
            "appointment": req.appointment,
        },
    )
    await request.app.state.sessions.save(state)
    job = build_reminder_job(
        req.patient_id,
        req.phone,
        req.language,
        req.appointment,
    )
    queue: CampaignQueue = request.app.state.campaigns
    await queue.enqueue(job)
    opener = {
        "en": f"Hello, this is City Clinic calling about your appointment with {req.appointment.get('doctor')} on {req.appointment.get('starts_at')}. Would you like to confirm, reschedule, or cancel?",
        "hi": f"नमस्ते, City Clinic से कॉल है। आपकी {req.appointment.get('doctor')} के साथ अपॉइंटमेंट {req.appointment.get('starts_at')} के बारे में — क्या आप पुष्टि, पुनर्निर्धारण या रद्द करना चाहेंगे?",
        "ta": f"வணக்கம், City Clinic-இலிருந்து அழைப்பு. {req.appointment.get('doctor')} உடன் {req.appointment.get('starts_at')} அன்று உங்கள் சந்திப்பு — உறுதிப்படுத்த, மாற்ற அல்லது ரத்து செய்ய விரும்புகிறீர்களா?",
    }
    return {
        "session_id": session_id,
        "job_id": job.id,
        "opening_prompt": opener.get(req.language, opener["en"]),
        "state": state.to_dict(),
    }


@router.get("/campaigns/pending")
async def pending_campaigns(request: Request):
    queue: CampaignQueue = request.app.state.campaigns
    return {"jobs": await queue.list_pending()}


@router.get("/doctors")
async def doctors(db: AsyncSession = Depends(get_db)):
    return await scheduling.list_doctors(db)


@router.get("/appointments/{patient_id}")
async def appointments(patient_id: str, db: AsyncSession = Depends(get_db)):
    return await scheduling.list_patient_appointments(db, patient_id)


@router.get("/latency/recent")
async def recent_latency(request: Request):
    registry: LatencyRegistry = request.app.state.latency
    return {
        "spans": [
            s.breakdown()
            for s in list(registry._spans.values())[-20:]
        ]
    }
