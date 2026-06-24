"""Run goals through LoopEngine runtime (experimental path)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from loop_engine.engine import new_run_state
from loop_engine.models import StopReason
from observability import log_cycle_event

from runtime.factory import build_loop_engine

if TYPE_CHECKING:
    from task_watcher import Task

logger = logging.getLogger("localgrokloop.runtime")


def _status_from_stop_reason(reason: StopReason) -> str:
    mapping = {
        StopReason.COMPLETED: "completed",
        StopReason.ASK_HUMAN: "awaiting_human",
        StopReason.MAX_ITERATIONS: "max_iterations",
        StopReason.MAX_ELAPSED_TIME: "max_elapsed_time",
        StopReason.MAX_CONSECUTIVE_FAILURES: "max_consecutive_failures",
        StopReason.MAX_TOOL_CALLS: "max_tool_calls",
        StopReason.POLICY_VIOLATION: "policy_violation",
        StopReason.ERROR: "error",
    }
    return mapping.get(reason, reason.value)


def run_goal_loop_engine(task: Task, engine=None) -> str:
    """Execute one goal via LoopEngine runtime adapters."""
    from task_watcher import set_active_goal

    engine = engine or build_loop_engine(use_fakes=False)
    run_id = task.goal_id

    log_cycle_event(run_id, "goal_started", {**task.to_dict(), "runtime": "loop_engine"})
    set_active_goal(task)

    final_status = "unknown"
    try:
        initial = new_run_state(run_id, task.goal_id, task.goal)
        initial.metadata["task_dict"] = task.to_dict()
        result = engine.run(state=initial)
        final_status = _status_from_stop_reason(result.stop_reason)
        log_cycle_event(
            run_id,
            "goal_finished",
            {
                "status": final_status,
                "stop_reason": result.stop_reason.value,
                "runtime": "loop_engine",
            },
        )
    except Exception as exc:
        logger.exception("LoopEngine goal failed: %s", exc)
        log_cycle_event(run_id, "goal_error", {"error": str(exc), "runtime": "loop_engine"})
        final_status = "error"
    finally:
        set_active_goal(None)

    return final_status
