"""Production adapters implementing loop_engine Protocol interfaces."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from loop_engine.events import JsonlEventSink
from loop_engine.models import Decision, RunState, ToolCallRecord, ToolResultRecord

from config import load_system_prompt, settings
from runtime.serde import run_state_from_json, run_state_to_json

logger = logging.getLogger(__name__)


def _parse_json_field(text: str, field: str, default: str = "") -> str:
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            return str(parsed.get(field, default or text))
    except json.JSONDecodeError:
        pass
    return default or text


class OllamaPlannerAdapter:
    """Planner using Ollama via LangChain (production only)."""

    def plan(self, state: RunState) -> str:
        from langchain_core.messages import HumanMessage
        from langchain_ollama import ChatOllama

        llm = ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.planner_model,
            temperature=0.3,
            num_ctx=16384,
        )
        prompt = f"""Goal: {state.goal}

Relevant memory:
{state.memory_context or 'None'}

Previous reflection:
{state.reflection or 'None'}

Iteration: {state.iteration + 1} / {settings.max_iterations_per_goal}

Create a concise plan for THIS iteration only (1-3 concrete actions).
Respond with JSON: {{"plan": "...", "rationale": "..."}}"""
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        return _parse_json_field(text, "plan", text)


class OllamaActorAdapter:
    """Actor using tool-bound Ollama. Parses tool_calls when present.

    Limitation: tool-call quality depends on model; falls back to text-only summary.
    """

    def act(self, state: RunState) -> tuple[str, list[ToolCallRecord]]:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_ollama import ChatOllama
        from tools import get_tools

        llm = ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=0.2,
            num_ctx=16384,
        ).bind_tools(get_tools())

        msgs = [
            SystemMessage(content=load_system_prompt()),
            HumanMessage(content=f"Goal: {state.goal}\n\nCurrent plan:\n{state.plan}"),
        ]
        response = llm.invoke(msgs)
        summary = response.content if isinstance(response.content, str) else str(response.content or "")

        tool_calls: list[ToolCallRecord] = []
        if hasattr(response, "tool_calls") and response.tool_calls:
            for i, tc in enumerate(response.tool_calls):
                tool_calls.append(
                    ToolCallRecord(
                        name=tc.get("name", "unknown"),
                        arguments=tc.get("args", {}),
                        call_id=tc.get("id", f"call_{i}"),
                    )
                )
        elif not summary:
            summary = "No tool calls requested."

        return summary[:2000], tool_calls


class OllamaReflectorAdapter:
    """Reflector using planning model; suggests decision via metadata when parseable."""

    def reflect(self, state: RunState) -> tuple[str, Decision | None]:
        from langchain_core.messages import HumanMessage
        from langchain_ollama import ChatOllama

        llm = ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.planner_model,
            temperature=0.3,
            num_ctx=16384,
        )
        tool_lines = [f"- {r.name}: {r.output[:200]}" for r in state.tool_results]
        prompt = f"""Goal: {state.goal}
Plan: {state.plan}
Last action: {state.last_action_summary}
Tool results:
{chr(10).join(tool_lines) or 'No tool results.'}

Reflect briefly and indicate if goal is done, needs human, or should continue.
Respond JSON: {{"reflection": "...", "suggested_decision": "continue|done|ask_human"}}"""
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        reflection = _parse_json_field(text, "reflection", text)

        suggested: Decision | None = None
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                raw = json.loads(match.group()).get("suggested_decision", "")
                if raw:
                    from loop_engine.engine import parse_decision_text
                    suggested = parse_decision_text(str(raw))
        except (json.JSONDecodeError, ValueError):
            suggested = None

        return reflection, suggested


class ProductionToolExecutorAdapter:
    """Bridges tools.py into loop engine with policy gates intact."""

    def execute(self, state: RunState, call: ToolCallRecord) -> ToolResultRecord:
        from tools import tools_by_name

        registry = tools_by_name()
        tool = registry.get(call.name)
        if tool is None:
            return ToolResultRecord(
                call_id=call.call_id,
                name=call.name,
                success=False,
                output="",
                error=f"Unknown tool: {call.name}",
            )
        try:
            output = tool.invoke(call.arguments)
            blocked = isinstance(output, str) and output.startswith("BLOCKED:")
            return ToolResultRecord(
                call_id=call.call_id,
                name=call.name,
                success=not blocked,
                output=str(output)[:12000],
                error=str(output) if blocked else "",
            )
        except Exception as exc:
            return ToolResultRecord(
                call_id=call.call_id,
                name=call.name,
                success=False,
                output="",
                error=str(exc),
            )


class ChromaMemoryAdapter:
    """Chroma-backed observe/store. Fails clearly if Chroma unavailable."""

    def observe(self, state: RunState) -> str:
        from memory import get_memory_store

        store = get_memory_store()
        return store.format_context(state.goal, goal_id=state.goal_id, include_global=True)

    def store(self, state: RunState) -> None:
        from memory import get_memory_store

        store = get_memory_store()
        summary = (
            f"Goal: {state.goal}\n"
            f"Iteration: {state.iteration}\n"
            f"Plan: {state.plan}\n"
            f"Reflection: {state.reflection}\n"
            f"Last action: {state.last_action_summary}"
        )
        store.store(
            summary,
            goal_id=state.goal_id,
            memory_type="iteration_log",
            tags=["loop", f"iter_{state.iteration}"],
        )
        if state.reflection:
            store.store(
                state.reflection,
                goal_id=state.goal_id,
                memory_type="reflection",
            )


class SqliteCheckpointStore:
    """Persist RunState as JSON in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS loop_engine_checkpoints (
                    run_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save(self, state: RunState) -> None:
        payload = run_state_to_json(state)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO loop_engine_checkpoints (run_id, goal_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    goal_id=excluded.goal_id,
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (state.run_id, state.goal_id, payload, state.updated_at),
            )

    def load(self, run_id: str) -> RunState | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM loop_engine_checkpoints WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return run_state_from_json(row[0])

    def load_by_goal_id(self, goal_id: str) -> RunState | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM loop_engine_checkpoints WHERE goal_id = ? ORDER BY updated_at DESC LIMIT 1",
                (goal_id,),
            ).fetchone()
        if not row:
            return None
        return run_state_from_json(row[0])


class ProductionEventSinkAdapter:
    """Writes normalized events to agent_cycles.jsonl."""

    def __init__(self, path: Path | None = None) -> None:
        self._sink = JsonlEventSink(path or (settings.log_dir / "agent_cycles.jsonl"))

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
    ) -> None:
        from loop_engine.models import LoopPhase, StopReason

        phase_enum = phase if isinstance(phase, LoopPhase) else LoopPhase(str(phase))
        stop_enum = None
        if stop_reason is not None:
            stop_enum = stop_reason if isinstance(stop_reason, StopReason) else StopReason(str(stop_reason))
        self._sink.emit(
            state,
            step,
            phase_enum,
            event,
            status=status,
            decision=decision,
            stop_reason=stop_enum,
            duration_ms=duration_ms,
            data=data,
        )


class HumanApprovalGateAdapter:
    """Non-blocking human gate via Redis park + outbox question file."""

    def park(self, state: RunState, question: str) -> str:
        from human_gate import new_question_id, write_question
        from task_watcher import Task, park_awaiting_human

        qid = new_question_id()
        write_question(question, context=state.plan[:500], question_id=qid)
        task_data = state.metadata.get("task_dict")
        if task_data:
            task = Task.from_dict(task_data)
            park_awaiting_human(task, question, qid)
        state.human_question = question
        return qid
