"""Tool-based fallback when no LLM API key is configured (local demo)."""

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.patient_store import PatientMemory
from app.memory.session_store import SessionState, SessionStore
from app.scheduling import service as scheduling
from app.scheduling.service import SchedulingError


def _needs_demo(api_key: str) -> bool:
    if not api_key or api_key in ("sk-your-key", "sk-demo", "your-key"):
        return True
    return api_key.startswith("sk-your")


# Multilingual response templates
_GREET = {
    "en": "Hello! I can help book, reschedule, or cancel appointments. Which doctor or date do you need?",
    "hi": "नमस्ते! मैं अपॉइंटमेंट बुक करने, बदलने या रद्द करने में मदद कर सकता हूँ। कौन से डॉक्टर या तारीख चाहिए?",
    "ta": "வணக்கம்! சந்திப்பு பதிவு செய்ய, மாற்ற அல்லது ரத்து செய்ய உதவ முடியும். எந்த மருத்துவர் அல்லது தேதி வேண்டும்?",
}

_NO_APPTS = {
    "en": "You have no upcoming appointments.",
    "hi": "आपकी कोई आगामी अपॉइंटमेंट नहीं है।",
    "ta": "உங்களுக்கு வரவிருக்கும் சந்திப்புகள் எதுவும் இல்லை.",
}

_APPTS_PREFIX = {
    "en": "Your upcoming appointments: ",
    "hi": "आपकी आगामी अपॉइंटमेंट: ",
    "ta": "உங்கள் வரவிருக்கும் சந்திப்புகள்: ",
}

_DOCTORS_PREFIX = {
    "en": "Available doctors: ",
    "hi": "उपलब्ध डॉक्टर: ",
    "ta": "கிடைக்கக்கூடிய மருத்துவர்கள்: ",
}

_NO_SLOTS = {
    "en": "No slots available on {day}. Try another day.",
    "hi": "{day} को कोई स्लॉट उपलब्ध नहीं है। कोई और दिन आज़माएं।",
    "ta": "{day} அன்று இடங்கள் இல்லை. வேறு நாளை முயற்சிக்கவும்.",
}

_BOOKED = {
    "en": "Booked with {doctor} at {time}. Confirmation ID: {id}",
    "hi": "{doctor} के साथ {time} पर अपॉइंटमेंट बुक हो गई। पुष्टि ID: {id}",
    "ta": "{doctor} உடன் {time} மணிக்கு சந்திப்பு பதிவு செய்யப்பட்டது. உறுதிப்படுத்தல் ID: {id}",
}

_DEMO_FALLBACK = {
    "en": "I'm in demo mode (add OPENAI_API_KEY for full AI). I heard: {text}. Available doctors: {doctors}. Say 'book appointment' or 'list my appointments'.",
    "hi": "मैं डेमो मोड में हूँ (पूर्ण AI के लिए OPENAI_API_KEY जोड़ें)। आपने कहा: {text}। उपलब्ध डॉक्टर: {doctors}। 'अपॉइंटमेंट बुक करें' या 'मेरी अपॉइंटमेंट दिखाएं' कहें।",
    "ta": "நான் டெமோ பயன்முறையில் இருக்கிறேன் (முழு AI-க்கு OPENAI_API_KEY சேர்க்கவும்). நீங்கள் சொன்னது: {text}. கிடைக்கும் மருத்துவர்கள்: {doctors}. 'சந்திப்பு பதிவு செய்' அல்லது 'என் சந்திப்புகளை காட்டு' என்று சொல்லுங்கள்.",
}

# Multilingual keyword patterns for intent detection
_GREET_PATTERNS = {
    "en": r"\b(hi|hello|hey|good morning|good afternoon)\b",
    "hi": r"(नमस्ते|हेलो|हाय|नमस्कार)",
    "ta": r"(வணக்கம்|ஹலோ|நமஸ்காரம்)",
}

_LIST_PATTERNS = {
    "en": r"\b(list|show|my).*(appointment|booking)\b",
    "hi": r"(मेरी|दिखाओ|सूची).*(अपॉइंटमेंट|बुकिंग)",
    "ta": r"(என்|காட்டு|பட்டியல்).*(சந்திப்பு|பதிவு)",
}

_DOCTOR_PATTERNS = {
    "en": r"\b(doctor|dr\.?|specialist|cardiolog|pediatric|general)\b",
    "hi": r"(डॉक्टर|चिकित्सक|हृदय|बाल|सामान्य)",
    "ta": r"(மருத்துவர்|டாக்டர்|இதய|குழந்தை|பொது)",
}

_BOOK_PATTERNS = {
    "en": r"\b(book|schedule|appointment|fix|set up)\b",
    "hi": r"(बुक|अपॉइंटमेंट|शेड्यूल|मिलना|दिखाना)",
    "ta": r"(பதிவு|சந்திப்பு|பார்க்க|வேண்டும்)",
}


def _match(text: str, lang: str, patterns: dict) -> bool:
    pattern = patterns.get(lang, patterns.get("en", ""))
    return bool(re.search(pattern, text, re.IGNORECASE))


async def run_demo_turn(
    db: AsyncSession,
    sessions: SessionStore,
    patients: PatientMemory,
    session_id: str,
    patient_id: str,
    user_text: str,
    detected_language: str,
) -> dict[str, Any]:
    state = await sessions.get(session_id)
    if not state:
        state = SessionState(session_id=session_id, patient_id=patient_id)
    state.turn_count += 1
    state.language = detected_language
    lang = detected_language
    text_lower = user_text.lower()

    trace: list[dict[str, Any]] = [
        {"type": "demo_mode", "message": "No OPENAI_API_KEY — using tool-only demo agent"},
        {"type": "language_detected", "language": lang},
    ]

    async def tool(name: str, args: dict[str, Any]) -> Any:
        trace.append({"type": "tool_call", "name": name, "arguments": args})
        try:
            if name == "list_doctors":
                out = await scheduling.list_doctors(db, args.get("specialty"))
            elif name == "get_availability":
                out = await scheduling.get_availability(db, args["doctor_id"], args["day"])
            elif name == "book_appointment":
                out = await scheduling.book_appointment(
                    db, patient_id, args["doctor_id"], args["starts_at"]
                )
            elif name == "list_my_appointments":
                out = await scheduling.list_patient_appointments(db, patient_id)
            elif name == "cancel_appointment":
                out = await scheduling.cancel_appointment(db, patient_id, args["appointment_id"])
            else:
                out = {"error": "unknown_tool"}
        except SchedulingError as exc:
            out = {"error": exc.code, "message": exc.message, "alternatives": exc.alternatives}
        trace.append({"type": "tool_result", "name": name, "result": out})
        return out

    reply = ""

    if _match(text_lower, lang, _GREET_PATTERNS):
        reply = _GREET.get(lang, _GREET["en"])
        state.intent = "inquiry"

    elif _match(text_lower, lang, _LIST_PATTERNS):
        appts = await tool("list_my_appointments", {})
        if appts:
            summary = "; ".join(
                f"{a.get('doctor')} at {a.get('starts_at', '')[:16]}" for a in appts
            )
            reply = _APPTS_PREFIX.get(lang, _APPTS_PREFIX["en"]) + summary
        else:
            reply = _NO_APPTS.get(lang, _NO_APPTS["en"])

    elif _match(text_lower, lang, _DOCTOR_PATTERNS):
        doctors = await tool("list_doctors", {})
        names = ", ".join(f"{d['name']} ({d['specialty']})" for d in doctors)
        reply = _DOCTORS_PREFIX.get(lang, _DOCTORS_PREFIX["en"]) + names
        state.intent = "book"

    elif _match(text_lower, lang, _BOOK_PATTERNS):
        doctors = await scheduling.list_doctors(db)
        if not doctors:
            reply = _NO_SLOTS.get(lang, _NO_SLOTS["en"]).format(day="today")
        else:
            from datetime import UTC, datetime, timedelta

            doctor = doctors[0]
            day = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
            slots = await tool("get_availability", {"doctor_id": doctor["id"], "day": day})
            if slots:
                slot = slots[0]
                booked = await tool(
                    "book_appointment",
                    {"doctor_id": doctor["id"], "starts_at": slot["starts_at"]},
                )
                if isinstance(booked, dict) and "appointment_id" in booked:
                    reply = _BOOKED.get(lang, _BOOKED["en"]).format(
                        doctor=doctor["name"],
                        time=slot["starts_at"][:16],
                        id=booked["appointment_id"],
                    )
                else:
                    reply = _NO_SLOTS.get(lang, _NO_SLOTS["en"]).format(day=day)
                state.intent = "book"
            else:
                reply = _NO_SLOTS.get(lang, _NO_SLOTS["en"]).format(day=day)

    else:
        doctors = await scheduling.list_doctors(db)
        doctor_names = ", ".join(d["name"] for d in doctors)
        reply = _DEMO_FALLBACK.get(lang, _DEMO_FALLBACK["en"]).format(
            text=user_text, doctors=doctor_names
        )

    await sessions.save(state)
    await patients.append_interaction(
        db, patient_id, session_id, summary=f"demo: {user_text[:80]} -> {reply[:80]}"
    )
    trace.append({"type": "llm_response", "content": reply, "finish_reason": "demo"})
    return {
        "reply": reply,
        "language": lang,
        "session": state.to_dict(),
        "trace": trace,
    }
