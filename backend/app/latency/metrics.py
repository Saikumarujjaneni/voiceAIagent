import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()


@dataclass
class LatencySpan:
    session_id: str
    turn_id: str
    speech_end_ms: float | None = None
    stt_done_ms: float | None = None
    agent_start_ms: float | None = None
    agent_first_token_ms: float | None = None
    agent_done_ms: float | None = None
    tts_first_byte_ms: float | None = None
    extra: dict[str, float] = field(default_factory=dict)

    def mark(self, field_name: str, t: float | None = None) -> None:
        setattr(self, field_name, t if t is not None else time.perf_counter() * 1000)

    def e2e_ms(self) -> float | None:
        if self.speech_end_ms is None or self.tts_first_byte_ms is None:
            return None
        return self.tts_first_byte_ms - self.speech_end_ms

    def breakdown(self) -> dict[str, Any]:
        def delta(a: str, b: str) -> float | None:
            va, vb = getattr(self, a), getattr(self, b)
            if va is None or vb is None:
                return None
            return round(vb - va, 2)

        return {
            "e2e_ms": round(self.e2e_ms(), 2) if self.e2e_ms() else None,
            "stt_ms": delta("speech_end_ms", "stt_done_ms"),
            "agent_ms": delta("stt_done_ms", "agent_done_ms"),
            "tts_ms": delta("agent_done_ms", "tts_first_byte_ms"),
            "target_ms": 450,
            "within_target": (self.e2e_ms() or 9999) < 450,
            "within_target_450ms": (self.e2e_ms() or 9999) < 450,
            "raw": asdict(self),
        }


class LatencyRegistry:
    def __init__(self) -> None:
        self._spans: dict[str, LatencySpan] = {}

    def start(self, session_id: str, turn_id: str) -> LatencySpan:
        span = LatencySpan(session_id=session_id, turn_id=turn_id)
        self._spans[turn_id] = span
        return span

    def get(self, turn_id: str) -> LatencySpan | None:
        return self._spans.get(turn_id)

    def finalize(self, turn_id: str) -> dict[str, Any] | None:
        span = self._spans.get(turn_id)
        if not span:
            return None
        breakdown = span.breakdown()
        log.info("latency.turn", **breakdown)
        return breakdown
