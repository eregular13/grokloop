"""Daemon goal routing — LangGraph (default) vs LoopEngine (experimental)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from config import settings

if TYPE_CHECKING:
    from task_watcher import Task


def run_goal_for_task(agent, task: Task) -> str:
    """Route a dequeued task to the configured runtime backend."""
    if settings.use_loop_engine:
        from runtime.loop_engine_runtime import run_goal_loop_engine

        return run_goal_loop_engine(task)

    thread_id = task.thread_id or f"goal_{task.goal_id}"
    from main import run_goal_langgraph

    return run_goal_langgraph(agent, task, thread_id)
