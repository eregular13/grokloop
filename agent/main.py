"""LocalGrokLoop daemon — 24/7 autonomous agent entry point."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone

from langgraph.checkpoint.sqlite import SqliteSaver

from agent_loop import compile_agent, log_cycle_event, make_initial_state
from budget import BudgetConfig, BudgetManager
from observability import RunObserver
from config import load_system_prompt, settings
from human_gate import wait_for_human
from task_watcher import (
    dequeue_task,
    enqueue_task,
    get_active_goal,
    scan_pending_files,
    set_active_goal,
    start_task_watcher,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(settings.log_dir / "agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("localgrokloop")

_running = True


def _handle_signal(signum, frame):
    global _running
    logger.info("Shutdown signal received (%s)", signum)
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


DEFAULT_GOAL = (
    "You are a coding + research + automation super-agent. "
    "Help Reid build better tools and optimize his projects. "
    "Proactively scan the workspace, identify improvements, implement them, "
    "run tests, and document what you learn in memory."
)


def run_goal(agent, task, thread_id: str) -> str:
    """Execute one full goal through the LangGraph loop."""
    config = {"configurable": {"thread_id": thread_id}}
    state = make_initial_state(task.goal_id, task.goal)

    observer = RunObserver(task.goal_id)
    budget = BudgetManager(
        BudgetConfig(
            max_iterations=settings.max_iterations_per_goal,
            max_elapsed_seconds=settings.max_goal_elapsed_seconds,
            max_consecutive_failures=settings.max_consecutive_failures,
        )
    )
    observer.emit("goal_started", extra=task.to_dict())
    log_cycle_event(task.goal_id, "goal_started", task.to_dict())
    set_active_goal(task)

    final_status = "unknown"
    try:
        for step_output in agent.stream(state, config, stream_mode="values"):
            status = step_output.get("status", "")
            decision = step_output.get("decision", "")
            iteration = step_output.get("iteration", 0)
            observer.emit(
                "cycle_step",
                status=status,
                iteration=iteration,
                extra={"decision": decision},
            )
            log_cycle_event(
                task.goal_id,
                "cycle_step",
                {"status": status, "decision": decision, "iteration": iteration},
            )

            stop, stop_reason = budget.check(decision=decision or "continue")
            if stop and stop_reason in ("max_iterations", "max_elapsed_time", "max_consecutive_failures"):
                log_cycle_event(task.goal_id, "budget_exhausted", {"reason": stop_reason})
                observer.emit("budget_exhausted", status=stop_reason)
                final_status = stop_reason
                break

            if decision == "ask_human":
                question = step_output.get("human_question", "Need human input.")
                log_cycle_event(task.goal_id, "human_requested", {"question": question})
                response = wait_for_human(question, timeout_seconds=86400)
                if response:
                    # Re-queue with human guidance
                    new_goal = f"{task.goal}\n\nHuman guidance: {response}"
                    enqueue_task(new_goal, source="human_resume")
                    final_status = "human_resumed"
                else:
                    final_status = "human_timeout"
                break

            if status == "completed":
                final_status = "completed"
                break

        if final_status == "unknown":
            snapshot = agent.get_state(config)
            if snapshot.values.get("decision") == "done":
                final_status = "completed"
            else:
                final_status = "paused"

    except Exception as exc:
        logger.exception("Goal execution failed: %s", exc)
        log_cycle_event(task.goal_id, "goal_error", {"error": str(exc)})
        final_status = "error"
    finally:
        set_active_goal(None)
        log_cycle_event(task.goal_id, "goal_finished", {"status": final_status})

    return final_status


def heartbeat():
    """Write periodic heartbeat for monitoring."""
    hb_file = settings.log_dir / "heartbeat.json"
    hb_file.write_text(
        f'{{"timestamp": "{datetime.now(timezone.utc).isoformat()}", "status": "alive"}}',
        encoding="utf-8",
    )


def daemon_loop(agent) -> None:
    """Main 24/7 loop: dequeue tasks, run goals, sleep."""
    observer = start_task_watcher()
    scan_pending_files()

    # Seed default standing goal if queue empty and no active work
    enqueue_task(DEFAULT_GOAL, source="default_standing")

    last_heartbeat = 0.0
    logger.info("LocalGrokLoop daemon started. Model=%s", settings.ollama_model)
    logger.info("System prompt loaded (%d chars)", len(load_system_prompt()))

    try:
        while _running:
            now = time.time()
            if now - last_heartbeat >= settings.heartbeat_seconds:
                heartbeat()
                last_heartbeat = now

            task = dequeue_task(block=True, timeout=settings.loop_sleep_seconds)
            if not task:
                continue

            logger.info("Processing goal %s: %s", task.goal_id, task.goal[:80])
            thread_id = f"goal_{task.goal_id}"
            status = run_goal(agent, task, thread_id)
            logger.info("Goal %s finished: %s", task.goal_id, status)

            time.sleep(settings.loop_sleep_seconds)

    finally:
        observer.stop()
        observer.join()
        logger.info("LocalGrokLoop daemon stopped.")


def cli_submit(goal: str) -> None:
    task = enqueue_task(goal, source="cli")
    print(f"Queued goal {task.goal_id}: {goal[:80]}...")


def cli_status() -> None:
    active = get_active_goal()
    if active:
        print(f"Active: [{active.goal_id}] {active.goal[:100]}")
    else:
        print("No active goal.")


def wait_for_services(max_wait: int = 120) -> None:
    """Block until ChromaDB and Redis are reachable."""
    import httpx

    from memory import get_memory_store

    deadline = time.time() + max_wait
    while time.time() < deadline and _running:
        try:
            get_memory_store().count()
            get_redis = __import__("task_watcher", fromlist=["get_redis"]).get_redis
            get_redis().ping()
            with httpx.Client(timeout=5) as client:
                client.get(f"{settings.ollama_base_url}/api/tags")
            logger.info("All services reachable (ChromaDB, Redis, Ollama)")
            return
        except Exception as exc:
            logger.warning("Waiting for services: %s", exc)
            time.sleep(5)
    logger.warning("Service wait timed out after %ds — starting anyway", max_wait)


def main():
    parser = argparse.ArgumentParser(description="LocalGrokLoop autonomous agent")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Start the 24/7 daemon (default)")
    p_submit = sub.add_parser("submit", help="Submit a goal to the queue")
    p_submit.add_argument("goal", nargs="+", help="Goal text")
    sub.add_parser("status", help="Show active goal")

    args = parser.parse_args()
    command = args.command or "run"

    if command == "submit":
        cli_submit(" ".join(args.goal))
        return

    if command == "status":
        cli_status()
        return

    wait_for_services()

    # Compile agent with SQLite checkpointer
    with SqliteSaver.from_conn_string(str(settings.checkpoint_db)) as checkpointer:
        agent = compile_agent(checkpointer)
        daemon_loop(agent)


if __name__ == "__main__":
    main()