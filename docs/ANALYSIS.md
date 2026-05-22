# Design Analysis — Clinical Voice Agent

## System overview

A real-time multilingual voice AI agent for clinical appointment booking. The system handles inbound patient calls (book, reschedule, cancel) and outbound reminder campaigns in English, Hindi, and Tamil.

---

## Architecture decisions

### Two-service split (TypeScript gateway + Python backend)

The voice-gateway (TypeScript) handles all real-time concerns: WebSocket connections, STT timing, TTS triggering, barge-in, and client-side latency measurement. The backend (Python/FastAPI) handles all AI concerns: agent reasoning, tool execution, scheduling, and memory.

This split means:
- The gateway can scale independently from the AI backend
- Python's async ecosystem (asyncio, SQLAlchemy, redis-py) is better suited for the agent loop
- TypeScript's event model is better suited for real-time WebSocket handling

### Agent design: function calling over prompt engineering

The agent uses OpenAI function calling rather than prompt-engineered JSON extraction. This gives:
- Structured tool arguments with schema validation
- Reliable tool invocation without regex parsing
- Visible reasoning trace (every tool call + result logged)
- Up to 6 tool rounds per turn for multi-step operations (e.g. list doctors → check availability → book)

### Memory: two-tier Redis + SQLite

**Session memory (Redis, 1h TTL):** Stores conversational state within a call — intent, pending confirmation, language, outbound context. Injected into the system prompt each turn so the agent has full context without re-reading history.

**Persistent memory (Redis cache + SQLite):** Patient profile (name, language preference, last 5 interactions, upcoming appointments) cached in Redis with 90-day TTL. SQLite is the source of truth. Cache invalidated on every new interaction to keep summaries fresh.

This avoids sending full conversation history to the LLM on every turn (cost + latency), while still giving the agent relevant context.

### Language detection + enforcement

Language is detected via `langdetect` on the user's text each turn. The UI language selector provides the fallback when detection is uncertain (e.g. short messages, code-switching). The detected language is:
1. Stored on the patient record for cross-session preference
2. Injected into the system prompt with an explicit instruction to reply in that language
3. Used to set the browser STT recognition locale and TTS voice locale

The system prompt includes concrete examples of Hindi and Tamil responses to prevent the LLM from defaulting to English.

### Scheduling: service layer with typed errors

All scheduling logic lives in `app/scheduling/service.py`. The agent never writes SQL — it calls service functions via the tool executor. `SchedulingError` carries a typed code (`double_booking`, `past_time`, `outside_hours`, `doctor_unavailable`) plus alternative slots, which the agent can present naturally to the patient.

A unique DB constraint on `(doctor_id, starts_at)` prevents double booking even under concurrent requests.

### Outbound campaigns

Outbound sessions are created via `POST /api/v1/sessions/outbound`. This:
1. Creates a `SessionState` with `outbound_context` (appointment details)
2. Enqueues a `CampaignJob` to Redis
3. Returns a pre-localized opening prompt in the patient's language

The ARQ worker (`app/campaigns/worker.py`) processes jobs from the queue. In the demo, the UI's "Outbound call" button simulates the patient receiving the call.

---

## Latency design

Target: **< 450 ms** from speech end to first audio byte.

```
speech_end_ms
    ↓  [STT: browser Web Speech API final result]
stt_done_ms
    ↓  [network: WS → backend]
agent_start_ms
    ↓  [LLM + tool calls]
agent_done_ms
    ↓  [network: backend → WS → speechSynthesis.speak()]
tts_first_byte_ms
```

Each stage is timestamped and returned in the API response. The UI displays the breakdown and flags turns that exceed 450 ms.

**Why 450 ms is hard without streaming:**

| Stage | Browser demo | Production path |
|-------|-------------|-----------------|
| STT | ~100–300 ms (browser, non-streaming) | ~50–100 ms (Deepgram streaming) |
| Agent | ~300–1500 ms (gpt-4o-mini, no streaming) | ~100–300 ms (Groq/streaming) |
| TTS | ~50–200 ms (browser speechSynthesis) | ~50–100 ms (ElevenLabs streaming) |

The architecture is designed to slot in streaming providers without structural changes — the gateway already captures `tts_first_byte_ms` via `speechSynthesis.onstart`, which maps directly to a streaming TTS first-chunk callback.

---

## Trade-offs

| Decision | Trade-off |
|----------|-----------|
| SQLite over PostgreSQL | Simpler local setup; not suitable for multi-instance production |
| Browser STT/TTS | Zero infrastructure; quality varies by OS/browser |
| gpt-4o-mini | Low cost + latency; less capable than gpt-4o for complex multi-step reasoning |
| In-memory fallback for Redis | Works without Redis; loses TTL semantics and cross-process sharing |
| Demo mode (regex fallback) | Enables local testing without API key; responses are deterministic, not agentic |
| langdetect | Fast, no API call; less accurate for short messages and code-switching |

---

## Known limitations

- No streaming STT/LLM/TTS — latency floor is ~800 ms in browser demo
- No PSTN integration — voice is browser-only (Twilio/Exotel would slot after voice-gateway)
- No authentication or rate limiting on the API
- No audit logging for HIPAA/GDPR compliance
- Tamil/Hindi STT accuracy depends on browser engine
- SQLite is single-node; production needs PostgreSQL

---

## Production upgrade path

1. Replace browser STT with Deepgram/AssemblyAI streaming WebSocket
2. Replace `chat.completions.create` with streaming + first-token latency tracking
3. Replace browser TTS with ElevenLabs/Cartesia streaming
4. Add Twilio/Exotel PSTN gateway after voice-gateway
5. Migrate SQLite to PostgreSQL
6. Add API key auth + per-patient rate limiting
7. Add structured audit log for compliance
8. Deploy voice-gateway + backend as separate auto-scaling services behind a load balancer
