"""Serialize/deserialize RunState for SQLite checkpoints."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from loop_engine.models import (
    Decision,
    LoopPhase,
    RunState,
    StopReason,
    ToolCallRecord,
    ToolResultRecord,
)


def run_state_to_dict(state: RunState) -> dict[str, Any]:
    d = asdict(state)
    d["phase"] = state.phase.value
    d["decision"] = state.decision.value
    d["stop_reason"] = state.stop_reason.value
    return d


def run_state_from_dict(data: dict[str, Any]) -> RunState:
    phase = data.get("phase", LoopPhase.OBSERVE.value)
    decision = data.get("decision", Decision.CONTINUE.value)
    stop_reason = data.get("stop_reason", StopReason.CONTINUE.value)
    pending = [ToolCallRecord(**tc) for tc in data.get("pending_tool_calls", [])]
    results = [ToolResultRecord(**tr) for tr in data.get("tool_results", [])]
    return RunState(
        run_id=data["run_id"],
        goal_id=data["goal_id"],
        goal=data["goal"],
        iteration=data.get("iteration", 0),
        phase=LoopPhase(phase),
        decision=Decision(decision),
        status=data.get("status", "initialized"),
        started_at=data.get("started_at", ""),
        updated_at=data.get("updated_at", ""),
        consecutive_failures=data.get("consecutive_failures", 0),
        tool_calls_made=data.get("tool_calls_made", 0),
        last_action_summary=data.get("last_action_summary", ""),
        human_question=data.get("human_question", ""),
        stop_reason=StopReason(stop_reason),
        metadata=data.get("metadata", {}),
        memory_context=data.get("memory_context", ""),
        plan=data.get("plan", ""),
        reflection=data.get("reflection", ""),
        pending_tool_calls=pending,
        tool_results=results,
    )


def run_state_to_json(state: RunState) -> str:
    return json.dumps(run_state_to_dict(state))


def run_state_from_json(payload: str) -> RunState:
    return run_state_from_dict(json.loads(payload))
