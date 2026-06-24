"""Tests for the LoopEngine runtime bridge (no live services)."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

if "redis" not in sys.modules:
    sys.modules["redis"] = MagicMock()
if "watchdog" not in sys.modules:
    watchdog = MagicMock()
    sys.modules["watchdog"] = watchdog
    sys.modules["watchdog.events"] = MagicMock()
    sys.modules["watchdog.observers"] = MagicMock()

from loop_engine.engine import LoopEngine, new_run_state
from loop_engine.events import InMemoryEventSink
from loop_engine.models import Decision, RunConfig, RunState, StopReason, ToolCallRecord
from loop_engine.testing import FakeApproval
from runtime.adapters import (
    ProductionEventSinkAdapter,
    ProductionToolExecutorAdapter,
    SqliteCheckpointStore,
)
from runtime.factory import (
    RUNTIME_LANGGRAPH,
    RUNTIME_LOOP_ENGINE,
    build_loop_engine,
    resolve_runtime_backend,
)
from runtime.loop_engine_runtime import run_goal_loop_engine

from config import Settings


class TestFeatureFlag:
    def test_use_loop_engine_defaults_false(self):
        s = Settings(_env_file=None)
        assert s.use_loop_engine is False

    def test_resolve_runtime_backend_default_langgraph(self):
        assert resolve_runtime_backend(use_loop_engine=False) == RUNTIME_LANGGRAPH

    def test_resolve_runtime_backend_loop_engine_when_enabled(self):
        assert resolve_runtime_backend(use_loop_engine=True) == RUNTIME_LOOP_ENGINE


class TestRuntimeFactory:
    def test_build_loop_engine_with_fakes(self):
        engine = build_loop_engine(use_fakes=True)
        assert isinstance(engine, LoopEngine)

    def test_fake_runtime_completes(self):
        engine = build_loop_engine(
            use_fakes=True,
            fake_reflector_decision=Decision.DONE,
            overrides={"config": RunConfig(max_iterations=2)},
        )
        result = engine.run(goal="demo goal", goal_id="g-demo", run_id="r-demo")
        assert result.stop_reason == StopReason.COMPLETED

    def test_fake_runtime_parks_on_ask_human(self):
        approval = FakeApproval()
        engine = build_loop_engine(
            use_fakes=True,
            fake_reflector_decision=Decision.ASK_HUMAN,
            overrides={"approval": approval},
        )
        result = engine.run(goal="need human", goal_id="g-human", run_id="r-human")
        assert result.stop_reason == StopReason.ASK_HUMAN
        assert approval.parked


class TestMainRouting:
    def test_run_goal_for_task_uses_langgraph_when_flag_false(self, monkeypatch):
        from task_watcher import Task

        monkeypatch.setattr("runtime.routing.settings.use_loop_engine", False)
        task = Task(goal_id="g1", goal="test goal", source="test")
        agent = MagicMock()
        mock_langgraph = MagicMock(return_value="completed")
        mock_main = MagicMock()
        mock_main.run_goal_langgraph = mock_langgraph
        with (
            patch.dict(sys.modules, {"main": mock_main}),
            patch("runtime.loop_engine_runtime.run_goal_loop_engine") as loop_engine,
        ):
            from runtime.routing import run_goal_for_task

            status = run_goal_for_task(agent, task)
        mock_langgraph.assert_called_once_with(agent, task, task.thread_id)
        loop_engine.assert_not_called()
        assert status == "completed"

    def test_run_goal_for_task_uses_loop_engine_when_flag_true(self, monkeypatch):
        from task_watcher import Task

        monkeypatch.setattr("runtime.routing.settings.use_loop_engine", True)
        task = Task(goal_id="g2", goal="loop goal", source="test")
        with patch(
            "runtime.loop_engine_runtime.run_goal_loop_engine",
            return_value="completed",
        ) as loop_engine:
            from runtime.routing import run_goal_for_task

            status = run_goal_for_task(None, task)
        loop_engine.assert_called_once_with(task)
        assert status == "completed"


class TestLoopEngineRuntime:
    def test_run_goal_loop_engine_with_injected_fake_engine(self):
        from task_watcher import Task

        events = InMemoryEventSink()
        engine = build_loop_engine(
            use_fakes=True,
            fake_reflector_decision=Decision.DONE,
            overrides={"events": events, "config": RunConfig(max_iterations=1)},
        )
        task = Task(goal_id="g-runtime", goal="runtime test", source="test")
        status = run_goal_loop_engine(task, engine=engine)
        assert status == "completed"
        assert any(e.event == "run_finished" for e in events.events)


class TestSqliteCheckpointStore:
    def test_save_and_load_run_state(self, tmp_path):
        db = tmp_path / "checkpoints.db"
        store = SqliteCheckpointStore(db)
        state = new_run_state("run-1", "goal-1", "checkpoint test")
        state.plan = "step one"
        state.iteration = 2
        store.save(state)

        loaded = store.load("run-1")
        assert loaded is not None
        assert loaded.goal_id == "goal-1"
        assert loaded.plan == "step one"
        assert loaded.iteration == 2

    def test_load_by_goal_id_returns_latest(self, tmp_path):
        db = tmp_path / "checkpoints.db"
        store = SqliteCheckpointStore(db)
        older = new_run_state("run-a", "shared-goal", "older")
        older.updated_at = "2020-01-01T00:00:00+00:00"
        newer = new_run_state("run-b", "shared-goal", "newer")
        newer.updated_at = "2026-01-01T00:00:00+00:00"
        store.save(older)
        store.save(newer)

        loaded = store.load_by_goal_id("shared-goal")
        assert loaded is not None
        assert loaded.run_id == "run-b"
        assert loaded.goal == "newer"


class TestProductionEventSink:
    def test_writes_normalized_fields(self, tmp_path):
        log_path = tmp_path / "agent_cycles.jsonl"
        sink = ProductionEventSinkAdapter(path=log_path)
        state = new_run_state("run-ev", "goal-ev", "event test")
        sink.emit(state, 1, "observe", "phase_complete", status="observed", duration_ms=12)

        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["run_id"] == "run-ev"
        assert entry["goal_id"] == "goal-ev"
        assert entry["step_id"] == 1
        assert entry["phase"] == "observe"
        assert entry["event"] == "phase_complete"
        assert entry["status"] == "observed"
        assert entry["duration_ms"] == 12
        assert "prompt" not in entry.get("data", {})


class TestProductionToolExecutor:
    def test_unknown_tool_fails(self):
        adapter = ProductionToolExecutorAdapter()
        state = RunState(run_id="r", goal_id="g", goal="test")
        fake_tools = MagicMock()
        fake_tools.tools_by_name.return_value = {}
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = adapter.execute(
                state,
                ToolCallRecord(name="nonexistent_tool", arguments={}, call_id="c1"),
            )
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_docker_tool_blocked_in_edit_mode(self):
        adapter = ProductionToolExecutorAdapter()
        state = RunState(run_id="r", goal_id="g", goal="test")
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = "BLOCKED: docker_command requires AGENT_MODE=operator"
        fake_tools = MagicMock()
        fake_tools.tools_by_name.return_value = {"docker_command": mock_tool}
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = adapter.execute(
                state,
                ToolCallRecord(name="docker_command", arguments={"args": "ps"}, call_id="c2"),
            )
        assert result.success is False
        assert "BLOCKED" in (result.error or result.output)


class TestDashboardEventCompatibility:
    def test_dashboard_loads_legacy_and_engine_events(self, tmp_path):
        log_path = tmp_path / "agent_cycles.jsonl"
        legacy = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "goal_id": "legacy-goal",
            "event": "goal_started",
            "data": {"source": "cli"},
        }
        engine_event = {
            "timestamp": "2026-01-01T00:01:00+00:00",
            "run_id": "run-1",
            "goal_id": "engine-goal",
            "step_id": 3,
            "phase": "plan",
            "event": "phase_complete",
            "status": "planned",
        }
        log_path.write_text(
            json.dumps(legacy) + "\n" + json.dumps(engine_event) + "\n",
            encoding="utf-8",
        )

        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        records = [json.loads(line) for line in lines]
        assert len(records) == 2
        assert records[0]["event"] == "goal_started"
        assert records[1]["phase"] == "plan"
        assert records[1]["step_id"] == 3
