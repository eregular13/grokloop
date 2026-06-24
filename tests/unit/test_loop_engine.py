"""Tests for the deterministic loop engine (no live services)."""

from __future__ import annotations

import pytest

from loop_engine.budget import LoopBudget
from loop_engine.engine import LoopEngine, parse_decision_text
from loop_engine.events import InMemoryEventSink
from loop_engine.models import Decision, LoopPhase, RunConfig, RunState, StopReason, ToolCallRecord
from loop_engine.replay import load_events, summarize_run
from loop_engine.testing import (
    FakeActor,
    FakeApproval,
    FakeCheckpoints,
    FakeMemory,
    FakePlanner,
    FakeReflector,
    FakeToolExecutor,
)


def make_engine(
    *,
    reflector: FakeReflector | None = None,
    actor: FakeActor | None = None,
    config: RunConfig | None = None,
) -> tuple[LoopEngine, InMemoryEventSink, FakeCheckpoints, FakeMemory, FakeApproval]:
    events = InMemoryEventSink()
    checkpoints = FakeCheckpoints()
    memory = FakeMemory()
    approval = FakeApproval()
    engine = LoopEngine(
        planner=FakePlanner(),
        actor=actor or FakeActor(),
        reflector=reflector or FakeReflector(Decision.DONE),
        tool_executor=FakeToolExecutor(),
        memory=memory,
        checkpoints=checkpoints,
        events=events,
        approval=approval,
        config=config or RunConfig(max_iterations=5),
    )
    return engine, events, checkpoints, memory, approval


class TestParseDecision:
    def test_done(self):
        assert parse_decision_text("done") == Decision.DONE

    def test_ask_human(self):
        assert parse_decision_text("ask human") == Decision.ASK_HUMAN

    def test_continue(self):
        assert parse_decision_text("more work") == Decision.CONTINUE


class TestLoopBudget:
    def test_max_iterations(self):
        budget = LoopBudget(RunConfig(max_iterations=3), clock=lambda: 0.0)
        state = RunState(run_id="r1", goal_id="g1", goal="test", iteration=3)
        assert budget.check(state) == StopReason.MAX_ITERATIONS

    def test_max_elapsed_fake_clock(self):
        t = {"now": 100.0}
        budget = LoopBudget(RunConfig(max_elapsed_seconds=10.0), clock=lambda: t["now"])
        t["now"] = 111.0
        state = RunState(run_id="r1", goal_id="g1", goal="test")
        assert budget.check(state) == StopReason.MAX_ELAPSED_TIME

    def test_max_tool_calls(self):
        budget = LoopBudget(RunConfig(max_tool_calls=2), clock=lambda: 0.0)
        state = RunState(run_id="r1", goal_id="g1", goal="test", tool_calls_made=2)
        assert budget.check(state) == StopReason.MAX_TOOL_CALLS


class TestLoopEngineRun:
    def test_successful_run_completes(self):
        engine, events, _, memory, _ = make_engine(reflector=FakeReflector(Decision.DONE))
        result = engine.run(goal="List workspace", goal_id="g1", run_id="r1")
        assert result.stop_reason == StopReason.COMPLETED
        assert memory.observed and memory.stored
        assert any(e.event == "run_finished" for e in events.events)

    def test_ask_human_parks(self):
        engine, _, _, _, approval = make_engine(reflector=FakeReflector(Decision.ASK_HUMAN))
        result = engine.run(goal="Need approval", goal_id="g2", run_id="r2")
        assert result.stop_reason == StopReason.ASK_HUMAN
        assert approval.parked
        assert result.final_state.metadata.get("question_id")

    def test_checkpoints_after_each_phase(self):
        engine, _, checkpoints, _, _ = make_engine(reflector=FakeReflector(Decision.DONE))
        engine.run(goal="test", goal_id="g3", run_id="r3")
        phases = [s.phase for s in checkpoints.saves]
        assert LoopPhase.OBSERVE in phases
        assert LoopPhase.FINISH in phases
        assert len(checkpoints.saves) >= 6

    def test_ordered_step_ids(self):
        engine, events, _, _, _ = make_engine(reflector=FakeReflector(Decision.DONE))
        engine.run(goal="test", goal_id="g4", run_id="r4")
        ids = [e.step_id for e in events.events]
        assert ids == list(range(1, len(ids) + 1))

    def test_resume_from_checkpoint(self):
        engine, _, checkpoints, _, _ = make_engine(config=RunConfig(max_iterations=10))
        partial = RunState(
            run_id="r5",
            goal_id="g5",
            goal="resume me",
            iteration=1,
            phase=LoopPhase.OBSERVE,
            metadata={"last_step_id": 7},
        )
        checkpoints.save(partial)
        engine.reflector = FakeReflector(Decision.DONE)
        result = engine.resume("r5")
        assert result.stop_reason == StopReason.COMPLETED

    def test_max_iterations_stops(self):
        engine, _, _, _, _ = make_engine(
            reflector=FakeReflector(Decision.CONTINUE),
            config=RunConfig(max_iterations=1),
        )
        result = engine.run(goal="loop", goal_id="g6", run_id="r6")
        assert result.stop_reason in (StopReason.ASK_HUMAN, StopReason.MAX_ITERATIONS)

    def test_max_tool_calls_stops(self):
        calls = [ToolCallRecord(name="t", arguments={}, call_id="c1")]
        engine, _, _, _, _ = make_engine(
            reflector=FakeReflector(Decision.CONTINUE),
            actor=FakeActor(tool_calls=calls),
            config=RunConfig(max_iterations=10, max_tool_calls=0),
        )
        result = engine.run(goal="tools", goal_id="g7", run_id="r7")
        assert result.stop_reason == StopReason.MAX_TOOL_CALLS

    def test_replay_summarize(self, tmp_path):
        from loop_engine.events import JsonlEventSink

        state = RunState(run_id="rx", goal_id="gx", goal="g")
        sink = JsonlEventSink(tmp_path / "events.jsonl")
        sink.emit(state, 1, LoopPhase.OBSERVE, "phase_complete", status="observed")
        sink.emit(state, 2, LoopPhase.FINISH, "run_finished", stop_reason=StopReason.COMPLETED)
        events = load_events(tmp_path / "events.jsonl", run_id="rx")
        summary = summarize_run(events)
        assert summary["step_count"] == 2
        assert summary["run_id"] == "rx"