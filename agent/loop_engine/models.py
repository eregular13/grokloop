"""Typed models for the deterministic loop engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class LoopPhase(str, Enum):
    OBSERVE = "observe"
    PLAN = "plan"
    ACT = "act"
    TOOLS = "tools"
    REFLECT = "reflect"
    STORE = "store"
    DECIDE = "decide"
    FINISH = "finish"


class Decision(str, Enum):
    CONTINUE = "continue"
    DONE = "done"
    ASK_HUMAN = "ask_human"


class StopReason(str, Enum):
    CONTINUE = "continue"
    COMPLETED = "completed"
    ASK_HUMAN = "ask_human"
    MAX_ITERATIONS = "max_iterations"
    MAX_ELAPSED_TIME = "max_elapsed_time"
    MAX_CONSECUTIVE_FAILURES = "max_consecutive_failures"
    MAX_TOOL_CALLS = "max_tool_calls"
    POLICY_VIOLATION = "policy_violation"
    ERROR = "error"


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    call_id: str = ""


@dataclass
class ToolResultRecord:
    call_id: str
    name: str
    success: bool
    output: str
    error: str = ""


@dataclass
class StepRecord:
    step_id: int
    phase: LoopPhase
    event: str
    status: str = ""
    decision: Decision | None = None
    stop_reason: StopReason | None = None
    duration_ms: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunConfig:
    max_iterations: int = 50
    max_elapsed_seconds: float | None = 3600.0
    max_consecutive_failures: int = 5
    max_tool_calls: int = 200
    step_timeout_seconds: float | None = 120.0  # placeholder for per-step enforcement


@dataclass
class RunState:
    run_id: str
    goal_id: str
    goal: str
    iteration: int = 0
    phase: LoopPhase = LoopPhase.OBSERVE
    decision: Decision = Decision.CONTINUE
    status: str = "initialized"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    consecutive_failures: int = 0
    tool_calls_made: int = 0
    last_action_summary: str = ""
    human_question: str = ""
    stop_reason: StopReason = StopReason.CONTINUE
    metadata: dict[str, Any] = field(default_factory=dict)
    # Working memory for the current iteration
    memory_context: str = ""
    plan: str = ""
    reflection: str = ""
    pending_tool_calls: list[ToolCallRecord] = field(default_factory=list)
    tool_results: list[ToolResultRecord] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


@dataclass
class RunResult:
    run_id: str
    goal_id: str
    status: str
    stop_reason: StopReason
    iterations: int
    tool_calls_made: int
    final_state: RunState
