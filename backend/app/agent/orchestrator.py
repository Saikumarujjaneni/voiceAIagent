import json
from dataclasses import dataclass, field
from typing import Any

import structlog
from langdetect import detect_langs
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.demo_orchestrator import _needs_demo, run_demo_turn
from app.agent.prompts import SYSTEM_PROMPT, build_context_block
from app.agent.tools import TOOL_DEFINITIONS
from app.config import settings
from app.memory.patient_store import PatientMemory
from app.memory.session_store import SessionState, SessionStore
from app.scheduling import service as scheduling
from app.scheduling.service import SchedulingError

log = structlog.get_logger()


@dataclass
class ReasoningTrace:
    session_id: str
    steps: list[dict[str, Any]] = field(default_factory=list)

    def add(self, step_type: str, payload: dict[str, Any]) -> None:
        self.steps.append({"type": step_type, **payload})


def detect_language(text: str, fallback: str = "en") -> str:
    try:
        langs = detect_langs(text)
        code = langs[0].lang
        mapping = {"en": "en", "hi": "hi", "ta": "ta"}
        return mapping.get(code, fallback)
    except Exception:
        return fallback


class AgentOrchestrator:
    def __init__(
        self,
        db: AsyncSession,
        sessions: SessionStore,
        patients: PatientMemory,
    ):
        self.db = db
        self.sessions = sessions
        self.patients = patients
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key or "sk-demo",
            base_url=settings.openai_base_url,
        )

    async def _execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        state: SessionState,
        trace: ReasoningTrace,
    ) -> str:
        trace.add("tool_call", {"name": name, "arguments": args})
        try:
            if name == "list_doctors":
                result = await scheduling.list_doctors(self.db, args.get("specialty"))
            elif name == "get_availability":
                result = await scheduling.get_availability(
                    self.db,
                    args["doctor_id"],
                    args["day"],
                    args.get("limit", 5),
                )
            elif name == "book_appointment":
                result = await scheduling.book_appointment(
                    self.db,
                    state.patient_id,
                    args["doctor_id"],
                    args["starts_at"],
                )
            elif name == "cancel_appointment":
                result = await scheduling.cancel_appointment(
                    self.db,
                    state.patient_id,
                    args["appointment_id"],
                )
            elif name == "reschedule_appointment":
                result = await scheduling.reschedule_appointment(
                    self.db,
                    state.patient_id,
                    args["appointment_id"],
                    args["new_starts_at"],
                )
            elif name == "list_my_appointments":
                result = await scheduling.list_patient_appointments(self.db, state.patient_id)
            elif name == "log_campaign_outcome":
                state.slots["campaign_outcome"] = args
                result = {"logged": True, **args}
            elif name == "update_session_intent":
                if args.get("intent"):
                    state.intent = args["intent"]
                if "pending_confirmation" in args:
                    state.pending_confirmation = args.get("pending_confirmation")
                if args.get("slots"):
                    state.slots.update(args["slots"])
                result = {"session": state.to_dict()}
            else:
                result = {"error": f"Unknown tool {name}"}
        except SchedulingError as exc:
            result = {
                "error": exc.code,
                "message": exc.message,
                "alternatives": exc.alternatives,
            }
        trace.add("tool_result", {"name": name, "result": result})
        return json.dumps(result)

    async def run_turn(
        self,
        session_id: str,
        patient_id: str,
        user_text: str,
        message_history: list[dict[str, str]] | None = None,
        selected_language: str = "en",
    ) -> dict[str, Any]:
        state = await self.sessions.get(session_id)
        if not state:
            state = SessionState(session_id=session_id, patient_id=patient_id)
        state.turn_count += 1

        profile = await self.patients.get_profile(self.db, patient_id)
        # Use the UI-selected language as the fallback so the user's choice is respected
        detected = detect_language(user_text, selected_language)
        # If detection is uncertain (falls back), honour the selected language directly
        if detected == "en" and selected_language != "en":
            detected = selected_language
        state.language = detected
        await self.patients.update_language(self.db, patient_id, detected)

        # Enrich profile with upcoming appointments for context injection
        if profile is not None:
            try:
                upcoming = await scheduling.list_patient_appointments(self.db, patient_id)
                profile["upcoming_appointments"] = upcoming[:3]
            except Exception:
                pass

        trace = ReasoningTrace(session_id=session_id)
        trace.add("language_detected", {"language": detected})

        if _needs_demo(settings.openai_api_key):
            return await run_demo_turn(
                self.db,
                self.sessions,
                self.patients,
                session_id,
                patient_id,
                user_text,
                detected,
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": build_context_block(
                    profile,
                    state.to_dict(),
                    detected,
                ),
            },
        ]
        if message_history:
            messages.extend(message_history[-12:])
        messages.append({"role": "user", "content": user_text})

        trace.add("llm_request", {"model": settings.agent_model, "message_count": len(messages)})

        for _ in range(6):
            response = await self.client.chat.completions.create(
                model=settings.agent_model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
            )
            choice = response.choices[0]
            msg = choice.message
            trace.add(
                "llm_response",
                {
                    "finish_reason": choice.finish_reason,
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                        for tc in (msg.tool_calls or [])
                    ],
                },
            )

            if msg.tool_calls:
                messages.append(msg.model_dump())
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    tool_result = await self._execute_tool(
                        tc.function.name,
                        args,
                        state,
                        trace,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": tool_result,
                        }
                    )
                continue

            assistant_text = msg.content or ""
            await self.sessions.save(state)
            await self.patients.append_interaction(
                self.db,
                patient_id,
                session_id,
                summary=f"Turn {state.turn_count}: {user_text[:120]} -> {assistant_text[:120]}",
            )
            return {
                "reply": assistant_text,
                "language": detected,
                "session": state.to_dict(),
                "trace": trace.steps,
            }

        return {
            "reply": "I need a moment — could you repeat that?",
            "language": detected,
            "session": state.to_dict(),
            "trace": trace.steps,
        }
