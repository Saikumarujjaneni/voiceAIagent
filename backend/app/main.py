from contextlib import asynccontextmanager

import redis.asyncio as redis
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.campaigns.queue import CampaignQueue
from app.config import settings
from app.db import init_db
from app.latency.metrics import LatencyRegistry
from app.memory.patient_store import PatientMemory
from app.memory.session_store import SessionStore
from app.scheduling import service as scheduling
from app.db import SessionLocal

structlog.configure(processors=[structlog.processors.JSONRenderer()])
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = None
    try:
        redis_client = redis.from_url(settings.redis_url, decode_responses=False)
        await redis_client.ping()
        log.info("redis.connected", url=settings.redis_url)
    except Exception as exc:
        log.warning("redis.unavailable", error=str(exc))
        redis_client = None

    app.state.redis = redis_client
    app.state.sessions = SessionStore(redis_client)
    app.state.patients = PatientMemory(redis_client)
    app.state.campaigns = CampaignQueue(redis_client)
    app.state.latency = LatencyRegistry()

    await init_db()
    async with SessionLocal() as db:
        await scheduling.seed_if_empty(db)

    yield

    if redis_client:
        await redis_client.aclose()


app = FastAPI(
    title="Clinical Voice Agent API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "latency_target_ms": settings.latency_target_ms}
