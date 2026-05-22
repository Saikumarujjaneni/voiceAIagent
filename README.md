# Clinical Voice Agent — Real-Time Multilingual Appointment Booking

A production-oriented implementation of the **Real-Time Multilingual Voice AI Agent** assignment. Supports inbound and outbound voice conversations for clinical appointment booking in English, Hindi, and Tamil — with genuine LLM tool orchestration, two-tier memory, scheduling conflict handling, and measured end-to-end latency.

---

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20+
- Redis 7 (optional — in-memory fallback works for local dev)
- `OPENAI_API_KEY` (or compatible endpoint via `OPENAI_BASE_URL`)

### Local run

```powershell
# 1. Start Redis (optional but recommended)
cd clinical-voice-agent
docker compose up -d redis

# 2. Start backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # then set OPENAI_API_KEY in .env
mkdir data
uvicorn app.main:app --reload --port 8000

# 3. Start voice gateway + UI (new terminal, from repo root)
npm run install:all
npm run dev        # starts voice-gateway on :3000
```

Open **http://127.0.0.1:3000** in Chrome or Edge.

### Docker (full stack)

```bash
cd clinical-voice-agent
echo "OPENAI_API_KEY=sk-..." > .env
docker compose up --build
```

Open **http://127.0.0.1:3000**

### URL reference

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:3000 | Demo UI (open this) |
| http://127.0.0.1:8000/docs | Backend Swagger API |
| http://127.0.0.1:8000/health | Health check |

---

## Architecture

```
User Speech
    ↓
Speech-to-Text (Browser Web Speech API)
    ↓  speech_end_ms captured
Language Detection (langdetect)
    ↓
AI Agent (OpenAI function calling, gpt-4o-mini)
    ↓
Tool Orchestration (8 tools)
    ↓
Appointment Service (SQLite + conflict detection)
    ↓
Text Response
    ↓
Text-to-Speech (Browser speechSynthesis, en-IN / hi-IN / ta-IN)
    ↓  tts_first_byte_ms captured
Audio Response
```

### Layer breakdown

| Layer | Stack | Responsibility |
|-------|-------|----------------|
| voice-gateway | TypeScript, Express, WebSocket | STT timing, WS protocol, TTS trigger, barge-in, client-side latency |
| backend | Python, FastAPI | Agent orchestration, tool execution, scheduling, memory, campaigns |
| Redis | TTL keys | Session state (1h TTL) + patient profile cache (90d TTL) |
| SQLite | Persistent store | Doctors, appointments, interaction history |

Architecture diagram: [`docs/architecture.mmd`](docs/architecture.mmd) — render at [mermaid.live](https://mermaid.live) or export with `npx @mermaid-js/mermaid-cli`.

---

## Features

### Appointment lifecycle

- Book appointment (with doctor + slot confirmation before committing)
- Reschedule appointment (cancel old + book new atomically)
- Cancel appointment
- List upcoming appointments
- Check doctor availability by day
- Conflict detection with alternative slot suggestions

### Multilingual voice conversation

| Language | Example input |
|----------|--------------|
| English | "Book appointment with cardiologist tomorrow" |
| Hindi | "मुझे कल डॉक्टर से मिलना है" |
| Tamil | "நாளை மருத்துவரை பார்க்க வேண்டும்" |

- `langdetect` identifies language from user text each turn
- UI language selector sets the fallback when detection is uncertain
- Agent replies in the detected language (enforced via system prompt)
- Browser STT uses `en-IN`, `hi-IN`, `ta-IN` recognition locales
- Browser TTS uses matching voice locale for natural pronunciation
- Language preference persisted to patient record across sessions

### Contextual memory

**Session memory (Redis, TTL 1h)**
- Current intent: `book | reschedule | cancel | inquiry | campaign_followup`
- `pending_confirmation` — slot awaiting patient yes/no
- `slots` — campaign outcome bag
- `language` — detected language for this session
- `outbound_context` — campaign appointment details

**Persistent memory (Redis cache + SQLite)**
- Patient profile: name, phone, preferred language
- Last 5 interaction summaries (injected into agent context each turn)
- Upcoming appointments (injected into agent context)
- Redis cache with 90-day TTL; invalidated on new interaction

### Outbound campaigns

1. `POST /api/v1/sessions/outbound` — creates session + enqueues Redis job
2. Pre-localized opening prompts in EN/HI/TA
3. Patient can confirm, reschedule, cancel, or request callback
4. Agent calls `log_campaign_outcome` to record result
5. ARQ worker stub in `app/campaigns/worker.py` for background processing
6. Demo: **Outbound call** button in UI simulates a reminder call

### Latency measurement

Every turn captures per-stage timestamps:

```
speech_end_ms → stt_done_ms → agent_start_ms → agent_done_ms → tts_first_byte_ms
```

| Stage | Measurement |
|-------|-------------|
| STT | `speech_end_ms` on Web Speech API final result |
| Agent | `agent_start_ms` → `agent_done_ms` in backend |
| TTS | `speechSynthesis.onstart` as first-byte proxy |
| E2E | `speech_end_ms` → `tts_first_byte_ms` |

Target: **< 450 ms**. Latency breakdown visible in UI panel and `GET /api/v1/latency/recent`.

**Realistic numbers:**

| Environment | Typical e2e |
|-------------|-------------|
| Browser + gpt-4o-mini (no streaming) | 800–2500 ms (LLM bound) |
| Streaming STT + Groq + streaming TTS | 300–500 ms achievable |

Sub-450 ms reliably requires streaming STT + streaming LLM + streaming TTS and edge deployment. This repo implements the full instrumentation contract and a browser demo path. The architecture is designed to slot in Deepgram/AssemblyAI (STT), Groq (LLM), and ElevenLabs/Cartesia (TTS) without structural changes.

### Barge-in (interrupt)

- **Interrupt** button cancels `speechSynthesis` mid-playback
- Sends `barge_in` WebSocket event; backend acknowledges
- Patient can speak over the agent at any time

---

## Memory design

### Session memory (Redis)

Key: `session:{session_id}` — TTL: `SESSION_TTL_SECONDS` (default 3600s)

```json
{
  "session_id": "...",
  "patient_id": "...",
  "intent": "book",
  "pending_confirmation": { "doctor_id": 2, "starts_at": "2026-05-23T10:00:00+00:00" },
  "slots": {},
  "language": "hi",
  "outbound_context": null
}
```

Retrieved and injected into the system prompt each turn via `build_context_block()`.

### Persistent memory (SQLite + Redis cache)

Key: `patient:{patient_id}` — TTL: `PATIENT_MEMORY_TTL_SECONDS` (default 90 days)

```json
{
  "patient_id": "patient-demo-1",
  "name": "Ravi Kumar",
  "preferred_language": "hi",
  "recent_interactions": ["Turn 1: book -> confirmed", "..."],
  "upcoming_appointments": [{ "doctor": "Dr. Arun Kumar", "starts_at": "..." }]
}
```

Cache invalidated on every new interaction; refreshed on next profile read.

---

## Agent & tools

OpenAI function calling drives all scheduling actions. The agent never invents data.

| Tool | Description |
|------|-------------|
| `list_doctors` | List doctors, optionally filtered by specialty |
| `get_availability` | Open slots for a doctor on a given day |
| `book_appointment` | Book after patient confirms slot |
| `cancel_appointment` | Cancel by appointment ID |
| `reschedule_appointment` | Cancel + rebook atomically |
| `list_my_appointments` | Upcoming confirmed appointments |
| `log_campaign_outcome` | Record outbound result (confirmed/rescheduled/rejected) |
| `update_session_intent` | Explicitly persist intent + pending confirmation |

Reasoning traces returned in every `/api/v1/agent/turn` response — visible in the UI trace panel.

**Demo mode:** When `OPENAI_API_KEY` is missing or set to `sk-your-key`, the system falls back to a regex-based intent detector that still executes real scheduling tools and responds in the correct language (EN/HI/TA).

---

## Scheduling & conflict handling

| Error code | Behavior |
|------------|----------|
| `double_booking` | Returns 3 alternative slots within 7 days |
| `past_time` | Rejects booking |
| `outside_hours` | Clinic hours 09:00–18:00, Mon–Sat |
| `doctor_unavailable` | Doctor not found in DB |

Unique DB constraint on `(doctor_id, starts_at)` prevents double booking at the persistence layer.

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/agent/turn` | Text turn — returns reply, language, trace, latency |
| POST | `/api/v1/sessions/outbound` | Start outbound campaign session |
| GET | `/api/v1/trace/{session_id}` | Session state |
| GET | `/api/v1/doctors` | List doctors |
| GET | `/api/v1/appointments/{patient_id}` | Upcoming appointments |
| GET | `/api/v1/latency/recent` | Recent latency breakdowns |
| GET | `/health` | Health check |

---

## Project structure

```
clinical-voice-agent/
├── backend/
│   ├── app/
│   │   ├── agent/          # orchestrator, prompts, tools, demo fallback
│   │   ├── api/            # FastAPI routes
│   │   ├── campaigns/      # outbound queue + ARQ worker
│   │   ├── latency/        # per-stage span tracking
│   │   ├── memory/         # session store + patient store
│   │   ├── scheduling/     # models, service, conflict detection
│   │   ├── config.py
│   │   ├── db.py
│   │   └── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── voice-gateway/
│   ├── src/
│   │   ├── server.ts       # WebSocket server + message routing
│   │   ├── pipeline.ts     # text turn pipeline
│   │   └── latency.ts      # client-side latency utilities
│   ├── public/index.html   # demo UI
│   └── Dockerfile
├── docs/
│   ├── architecture.mmd    # Mermaid diagram source
│   └── ANALYSIS.md         # design decisions + trade-offs
├── scripts/
│   └── start-local.ps1
└── docker-compose.yml
```

---

## Evaluation alignment

| Criterion | Implementation |
|-----------|----------------|
| Real-time architecture (20%) | WebSocket pipeline, per-stage timestamps, barge-in, target discussion |
| Agent reasoning (20%) | Real OpenAI function calling, 6-round tool loop, visible trace |
| Memory design (15%) | Session Redis TTL + patient Redis/SQLite, injected into every turn |
| Scheduling logic (10%) | SQL unique constraint, conflict codes, 7-day alternative search |
| Multilingual (10%) | langdetect + UI selector fallback, persisted preference, localized outbound + demo responses |
| Performance optimization (10%) | gpt-4o-mini, bounded tool rounds, Redis caching, latency instrumentation |
| Code structure (10%) | Separated packages per concern, TypeScript gateway + Python backend |
| Documentation (5%) | This README, ANALYSIS.md, architecture diagram |

### Bonus features

- Barge-in interrupt handling
- Redis memory with TTL
- Horizontal scalability (stateless API + Redis)
- Background campaign queue (Redis + ARQ worker)

---

## Known limitations

- Browser STT/TTS quality varies by OS and browser engine; not telephony-grade
- LLM latency dominates without streaming inference
- Tamil/Hindi STT accuracy depends on browser engine quality
- No real PSTN integration (Twilio/Exotel would slot after voice-gateway)
- SQLite is single-node; production should use PostgreSQL

---

## License

MIT — assignment reference implementation.
