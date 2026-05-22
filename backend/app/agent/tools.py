from typing import Any

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_doctors",
            "description": "List available doctors, optionally filtered by specialty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "specialty": {"type": "string", "description": "Optional specialty filter"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_availability",
            "description": "Get open appointment slots for a doctor on a given day (YYYY-MM-DD).",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "integer"},
                    "day": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["doctor_id", "day"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book an appointment after patient confirms slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "integer"},
                    "starts_at": {"type": "string", "description": "ISO datetime"},
                },
                "required": ["doctor_id", "starts_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancel an existing appointment by id.",
            "parameters": {
                "type": "object",
                "properties": {"appointment_id": {"type": "integer"}},
                "required": ["appointment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": "Reschedule appointment to a new ISO datetime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "integer"},
                    "new_starts_at": {"type": "string"},
                },
                "required": ["appointment_id", "new_starts_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_appointments",
            "description": "List upcoming confirmed appointments for the current patient.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_campaign_outcome",
            "description": "Record outbound campaign result: confirmed, rescheduled, rejected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "outcome": {
                        "type": "string",
                        "enum": ["confirmed", "rescheduled", "rejected", "callback_requested"],
                    },
                    "notes": {"type": "string"},
                },
                "required": ["outcome"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_session_intent",
            "description": "Update conversational state: intent and pending confirmation payload.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "pending_confirmation": {"type": "object"},
                    "slots": {"type": "object"},
                },
            },
        },
    },
]
