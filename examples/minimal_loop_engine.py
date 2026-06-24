#!/usr/bin/env python3
"""Run the loop engine with fake components — no Ollama, Redis, or Docker."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from loop_engine.engine import LoopEngine
from loop_engine.events import InMemoryEventSink
from loop_engine.models import Decision, RunConfig, ToolCallRecord
from loop_engine.testing import (
    FakeActor,
    FakeApproval,
    FakeCheckpoints,
    FakeMemory,
    FakePlanner,
    FakeReflector,
    FakeToolExecutor,
)


def main() -> None:
    events = InMemoryEventSink()
    engine = LoopEngine(
        planner=FakePlanner(),
        actor=FakeActor([ToolCallRecord(name="list_directory", arguments={"path": "."}, call_id="1")]),
        reflector=FakeReflector(Decision.DONE),
        tool_executor=FakeToolExecutor(),
        memory=FakeMemory(),
        checkpoints=FakeCheckpoints(),
        events=events,
        approval=FakeApproval(),
        config=RunConfig(max_iterations=3),
    )
    result = engine.run(goal="List workspace and summarize", goal_id="demo-goal", run_id="demo-run")
    print(f"status={result.status} stop_reason={result.stop_reason.value}")
    print(f"iterations={result.iterations} tool_calls={result.tool_calls_made}")
    print(f"events={len(events.events)}")


if __name__ == "__main__":
    main()
