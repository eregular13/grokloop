"""Normalized event schema and sinks for the loop engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loop_engine.models import Decision, LoopPhase, RunState, StopReason


@dataclass
class EngineEvent:
    timestamp: str
    run_id: str
    goal_id: str
    step_id: int
    phase: str
    event: str
    status: str = ""
    decision: str = ""
    stop_reason: str = ""
    duration_ms: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "goal_id": self.goal_id,
            "step_id": self.step_id,
            "phase": self.phase,
            "event": self.event,
        }
        if self.status:
            d["status"] = self.status
        if self.decision:
            d["decision"] = self.decision
        if self.stop_reason:
            d["stop_reason"] = self.stop_reason
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        if self.data:
            d["data"] = self.data
        return d


class InMemoryEventSink:
    """Test double that records events in order."""

    def __init__(self) -> None:
        self.events: list[EngineEvent] = []

    def emit(
        self,
        state: RunState,
        step: int,
        phase: LoopPhase,
        event: str,
        *,
        status: str = "",
        decision: Decision | None = None,
        stop_reason: StopReason | None = None,
        duration_ms: int | None = None,
        data: dict | None = None,
    ) -> None:
        self.events.append(
            EngineEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                run_id=state.run_id,
                goal_id=state.goal_id,
                step_id=step,
                phase=phase.value,
                event=event,
                status=status,
                decision=decision.value if decision else "",
                stop_reason=stop_reason.value if stop_reason else "",
                duration_ms=duration_ms,
                data=data or {},
            )
        )


class JsonlEventSink:
    """Append-only JSONL sink — does not log prompts or secrets."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        state: RunState,
        step: int,
        phase: LoopPhase,
        event: str,
        *,
        status: str = "",
        decision: Decision | None = None,
        stop_reason: StopReason | None = None,
        duration_ms: int | None = None,
        data: dict | None = None,
    ) -> None:
        safe_data = _redact_data(data or {})
        entry = EngineEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            run_id=state.run_id,
            goal_id=state.goal_id,
            step_id=step,
            phase=phase.value,
            event=event,
            status=status,
            decision=decision.value if decision else "",
            stop_reason=stop_reason.value if stop_reason else "",
            duration_ms=duration_ms,
            data=safe_data,
        )
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")


_REDACT_KEYS = frozenset({"prompt", "system_prompt", "api_key", "password", "secret", "token"})


def _redact_data(data: dict) -> dict:
    out: dict = {}
    for k, v in data.items():
        if k.lower() in _REDACT_KEYS:
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = _redact_data(v)
        else:
            out[k] = v
    return out