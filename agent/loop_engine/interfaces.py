"""Narrow Protocol interfaces for the loop engine."""

from __future__ import annotations

from typing import Any, Protocol

from loop_engine.models import Decision, RunState, ToolCallRecord, ToolResultRecord


class Planner(Protocol):
    def plan(self, state: RunState) -> str: ...


class Actor(Protocol):
    def act(self, state: RunState) -> tuple[str, list[ToolCallRecord]]: ...


class Reflector(Protocol):
    def reflect(self, state: RunState) -> tuple[str, Decision | None]: ...


class ToolExecutor(Protocol):
    def execute(self, state: RunState, call: ToolCallRecord) -> ToolResultRecord: ...


class MemoryStore(Protocol):
    def observe(self, state: RunState) -> str: ...

    def store(self, state: RunState) -> None: ...


class CheckpointStore(Protocol):
    def save(self, state: RunState) -> None: ...

    def load(self, run_id: str) -> RunState | None: ...


class EventSink(Protocol):
    def emit(
        self,
        state: RunState,
        step: int,
        phase: Any,
        event: str,
        *,
        status: str = "",
        decision: Decision | None = None,
        stop_reason: Any = None,
        duration_ms: int | None = None,
        data: dict | None = None,
    ) -> None: ...


class ApprovalGate(Protocol):
    def park(self, state: RunState, question: str) -> str: ...