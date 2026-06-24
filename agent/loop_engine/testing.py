"""In-memory fakes for loop engine tests and examples."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from loop_engine.models import Decision, RunState, ToolCallRecord, ToolResultRecord


@dataclass
class FakeMemory:
    observed: list[str] = field(default_factory=list)
    stored: list[str] = field(default_factory=list)

    def observe(self, state: RunState) -> str:
        ctx = f"mem:{state.goal_id}:{state.iteration}"
        self.observed.append(ctx)
        return ctx

    def store(self, state: RunState) -> None:
        self.stored.append(state.plan)


@dataclass
class FakeCheckpoints:
    saves: list[RunState] = field(default_factory=list)
    by_id: dict[str, RunState] = field(default_factory=dict)

    def save(self, state: RunState) -> None:
        snap = copy.deepcopy(state)
        self.saves.append(snap)
        self.by_id[state.run_id] = snap

    def load(self, run_id: str) -> RunState | None:
        return copy.deepcopy(self.by_id.get(run_id))


@dataclass
class FakeApproval:
    parked: list[tuple[str, str]] = field(default_factory=list)

    def park(self, state: RunState, question: str) -> str:
        qid = f"q-{len(self.parked)}"
        self.parked.append((state.run_id, question))
        return qid


class FakePlanner:
    def plan(self, state: RunState) -> str:
        return f"plan iter {state.iteration}"


class FakeActor:
    def __init__(self, tool_calls: list[ToolCallRecord] | None = None) -> None:
        self.tool_calls = tool_calls or []

    def act(self, state: RunState) -> tuple[str, list[ToolCallRecord]]:
        return f"acted iter {state.iteration}", self.tool_calls


class FakeReflector:
    def __init__(self, decision: Decision | None = None) -> None:
        self.decision = decision
        self.calls = 0

    def reflect(self, state: RunState) -> tuple[str, Decision | None]:
        self.calls += 1
        if self.decision is not None:
            return "reflection text", self.decision
        return "keep going", None


class FakeToolExecutor:
    def execute(self, state: RunState, call: ToolCallRecord) -> ToolResultRecord:
        return ToolResultRecord(call_id=call.call_id, name=call.name, success=True, output="ok")