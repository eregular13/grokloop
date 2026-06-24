"""Factory for LoopEngine with production or fake adapters."""

from __future__ import annotations

from typing import Any

from loop_engine.engine import LoopEngine
from loop_engine.events import InMemoryEventSink
from loop_engine.models import RunConfig
from loop_engine.testing import (
    FakeActor,
    FakeApproval,
    FakeCheckpoints,
    FakeMemory,
    FakePlanner,
    FakeReflector,
    FakeToolExecutor,
)

from config import settings

RUNTIME_LANGGRAPH = "langgraph"
RUNTIME_LOOP_ENGINE = "loop_engine"


def resolve_runtime_backend(*, use_loop_engine: bool | None = None) -> str:
    """Return runtime backend id based on feature flag."""
    flag = settings.use_loop_engine if use_loop_engine is None else use_loop_engine
    return RUNTIME_LOOP_ENGINE if flag else RUNTIME_LANGGRAPH


def _run_config_from_settings() -> RunConfig:
    return RunConfig(
        max_iterations=settings.max_iterations_per_goal,
        max_elapsed_seconds=float(settings.max_goal_elapsed_seconds)
        if settings.max_goal_elapsed_seconds
        else None,
        max_consecutive_failures=settings.max_consecutive_failures,
        step_timeout_seconds=float(settings.tool_timeout_seconds),
    )


def build_loop_engine(
    *,
    use_fakes: bool = False,
    fake_reflector_decision: Any = None,
    overrides: dict[str, Any] | None = None,
) -> LoopEngine:
    """Build a LoopEngine with production adapters or in-memory fakes."""
    overrides = overrides or {}

    if use_fakes:
        from loop_engine.models import Decision

        dec = fake_reflector_decision if fake_reflector_decision is not None else Decision.DONE
        return LoopEngine(
            planner=overrides.get("planner", FakePlanner()),
            actor=overrides.get("actor", FakeActor()),
            reflector=overrides.get("reflector", FakeReflector(dec)),
            tool_executor=overrides.get("tool_executor", FakeToolExecutor()),
            memory=overrides.get("memory", FakeMemory()),
            checkpoints=overrides.get("checkpoints", FakeCheckpoints()),
            events=overrides.get("events", InMemoryEventSink()),
            approval=overrides.get("approval", FakeApproval()),
            config=overrides.get("config", _run_config_from_settings()),
        )

    from runtime.adapters import (
        ChromaMemoryAdapter,
        HumanApprovalGateAdapter,
        OllamaActorAdapter,
        OllamaPlannerAdapter,
        OllamaReflectorAdapter,
        ProductionEventSinkAdapter,
        ProductionToolExecutorAdapter,
        SqliteCheckpointStore,
    )

    return LoopEngine(
        planner=overrides.get("planner", OllamaPlannerAdapter()),
        actor=overrides.get("actor", OllamaActorAdapter()),
        reflector=overrides.get("reflector", OllamaReflectorAdapter()),
        tool_executor=overrides.get("tool_executor", ProductionToolExecutorAdapter()),
        memory=overrides.get("memory", ChromaMemoryAdapter()),
        checkpoints=overrides.get(
            "checkpoints",
            SqliteCheckpointStore(settings.loop_engine_checkpoint_db),
        ),
        events=overrides.get("events", ProductionEventSinkAdapter()),
        approval=overrides.get("approval", HumanApprovalGateAdapter()),
        config=overrides.get("config", _run_config_from_settings()),
    )
