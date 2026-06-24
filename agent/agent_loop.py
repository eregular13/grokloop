"""LangGraph-based autonomous agent loop with checkpointing."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from config import DecisionType, load_system_prompt, settings
from memory import memory_store
from tools import get_tools, tools_by_name

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    goal_id: str
    goal: str
    messages: Annotated[list, add_messages]
    memory_context: str
    plan: str
    reflection: str
    decision: DecisionType
    iteration: int
    tool_calls_made: int
    last_action_summary: str
    human_question: str
    status: str


def _get_llm(*, for_planning: bool = False) -> ChatOllama:
    model = settings.planner_model if for_planning else settings.ollama_model
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=model,
        temperature=0.3 if for_planning else 0.2,
        num_ctx=16384,
    )


def _bind_tools_llm() -> Any:
    return _get_llm().bind_tools(get_tools())


# ── Graph nodes ────────────────────────────────────────────────────


def observe(state: AgentState) -> dict:
    """Load relevant memories for the current goal."""
    logger.info("[%s] OBSERVE (iter %d)", state["goal_id"], state["iteration"])
    ctx = memory_store.format_context(state["goal"], goal_id=state["goal_id"])
    recent = memory_store.search(state["goal"], goal_id=state["goal_id"], top_k=3)
    summary = state.get("last_action_summary", "Starting fresh iteration.")
    return {
        "memory_context": ctx,
        "messages": [
            SystemMessage(
                content=(
                    f"## Memory context\n{ctx}\n\n"
                    f"## Last action\n{summary}\n\n"
                    f"## Iteration {state['iteration'] + 1}"
                )
            )
        ],
        "status": "observed",
    }


def plan(state: AgentState) -> dict:
    """Generate a plan for this iteration."""
    logger.info("[%s] PLAN", state["goal_id"])
    llm = _get_llm(for_planning=True)
    prompt = f"""Goal: {state['goal']}

Relevant memory:
{state.get('memory_context', 'None')}

Previous reflection:
{state.get('reflection', 'None')}

Iteration: {state['iteration'] + 1} / {settings.max_iterations_per_goal}

Create a concise plan for THIS iteration only (1-3 concrete actions).
Respond with JSON: {{"plan": "...", "rationale": "..."}}"""
    resp = llm.invoke([HumanMessage(content=prompt)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)

    plan_text = text
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            plan_text = parsed.get("plan", text)
    except json.JSONDecodeError:
        pass

    return {
        "plan": plan_text,
        "messages": [HumanMessage(content=f"Plan for this iteration:\n{plan_text}")],
        "status": "planned",
    }


def act(state: AgentState) -> dict:
    """LLM decides and invokes tools."""
    logger.info("[%s] ACT", state["goal_id"])
    llm = _bind_tools_llm()
    system = load_system_prompt()
    msgs = [
        SystemMessage(content=system),
        HumanMessage(content=f"Goal: {state['goal']}\n\nCurrent plan:\n{state.get('plan', '')}"),
        *state.get("messages", []),
    ]
    response = llm.invoke(msgs)
    return {"messages": [response], "status": "acted"}


def reflect(state: AgentState) -> dict:
    """Evaluate what happened this iteration."""
    logger.info("[%s] REFLECT", state["goal_id"])
    llm = _get_llm(for_planning=True)

    recent_msgs = state.get("messages", [])[-6:]
    transcript = []
    for m in recent_msgs:
        if isinstance(m, AIMessage):
            transcript.append(f"AI: {m.content}")
            if m.tool_calls:
                for tc in m.tool_calls:
                    transcript.append(f"  tool_call: {tc['name']}({tc['args']})")
        elif isinstance(m, ToolMessage):
            transcript.append(f"Tool[{m.name}]: {str(m.content)[:500]}")

    prompt = f"""Goal: {state['goal']}
Plan: {state.get('plan', '')}

Recent actions:
{chr(10).join(transcript) or 'No actions yet.'}

Reflect briefly:
1. What was accomplished?
2. What failed or needs follow-up?
3. Is the goal complete, should we continue, or ask human?

Respond JSON: {{"reflection": "...", "progress_pct": 0-100, "blockers": "..."}}"""

    resp = llm.invoke([HumanMessage(content=prompt)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    reflection = text
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            reflection = parsed.get("reflection", text)
    except json.JSONDecodeError:
        pass

    return {"reflection": reflection, "status": "reflected"}


def store(state: AgentState) -> dict:
    """Persist iteration results to vector memory."""
    logger.info("[%s] STORE", state["goal_id"])
    summary = (
        f"Goal: {state['goal']}\n"
        f"Iteration: {state['iteration']}\n"
        f"Plan: {state.get('plan', '')}\n"
        f"Reflection: {state.get('reflection', '')}\n"
        f"Last action: {state.get('last_action_summary', '')}"
    )
    memory_store.store(
        summary,
        goal_id=state["goal_id"],
        memory_type="iteration_log",
        tags=["loop", f"iter_{state['iteration']}"],
    )
    if state.get("reflection"):
        memory_store.store(
            state["reflection"],
            goal_id=state["goal_id"],
            memory_type="reflection",
        )
    return {"status": "stored"}


def decide(state: AgentState) -> dict:
    """Determine next step: continue, done, or ask_human."""
    logger.info("[%s] DECIDE", state["goal_id"])
    llm = _get_llm(for_planning=True)

    # Check if ask_human was called this iteration
    for m in reversed(state.get("messages", [])):
        if isinstance(m, ToolMessage) and m.name == "ask_human":
            return {
                "decision": "ask_human",
                "human_question": str(m.content),
                "status": "awaiting_human",
            }

    prompt = f"""Goal: {state['goal']}
Iteration: {state['iteration']} / {settings.max_iterations_per_goal}
Reflection: {state.get('reflection', '')}

Decide: "continue", "done", or "ask_human"
- done: goal fully achieved with evidence
- ask_human: blocked, ambiguous, or needs approval
- continue: more work needed

Respond with ONLY one word: continue, done, or ask_human"""

    resp = llm.invoke([HumanMessage(content=prompt)])
    raw = (resp.content if isinstance(resp.content, str) else str(resp.content)).strip().lower()
    decision: DecisionType = "continue"
    if "done" in raw:
        decision = "done"
    elif "ask" in raw or "human" in raw:
        decision = "ask_human"
    elif state["iteration"] >= settings.max_iterations_per_goal:
        decision = "ask_human"
        return {
            "decision": decision,
            "human_question": f"Reached max iterations ({settings.max_iterations_per_goal}). Continue?",
            "status": "max_iterations",
        }

    return {"decision": decision, "status": f"decided_{decision}"}


def increment(state: AgentState) -> dict:
    """Bump iteration counter and summarize last tool activity."""
    tool_summary = ""
    tool_count = 0
    for m in reversed(state.get("messages", [])):
        if isinstance(m, ToolMessage):
            tool_count += 1
            if not tool_summary:
                tool_summary = f"{m.name}: {str(m.content)[:300]}"
    return {
        "iteration": state["iteration"] + 1,
        "tool_calls_made": state.get("tool_calls_made", 0) + tool_count,
        "last_action_summary": tool_summary or state.get("last_action_summary", ""),
        "status": "incremented",
    }


def route_after_decide(state: AgentState) -> str:
    decision = state.get("decision", "continue")
    if decision == "done":
        return "finish"
    if decision == "ask_human":
        return "human_gate"
    return "increment"


def finish(state: AgentState) -> dict:
    """Mark goal complete."""
    logger.info("[%s] DONE", state["goal_id"])
    memory_store.store(
        f"Goal COMPLETED: {state['goal']}\nFinal reflection: {state.get('reflection', '')}",
        goal_id=state["goal_id"],
        memory_type="completion",
        tags=["done"],
    )
    return {"status": "completed"}


# ── Graph assembly ─────────────────────────────────────────────────


def build_agent_graph() -> StateGraph:
    tool_node = ToolNode(get_tools())

    graph = StateGraph(AgentState)

    graph.add_node("observe", observe)
    graph.add_node("plan", plan)
    graph.add_node("act", act)
    graph.add_node("tools", tool_node)
    graph.add_node("reflect", reflect)
    graph.add_node("store", store)
    graph.add_node("decide", decide)
    graph.add_node("increment", increment)
    graph.add_node("finish", finish)

    graph.set_entry_point("observe")
    graph.add_edge("observe", "plan")
    graph.add_edge("plan", "act")

    def should_use_tools(state: AgentState) -> str:
        last = state["messages"][-1] if state.get("messages") else None
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "reflect"

    graph.add_conditional_edges("act", should_use_tools, {"tools": "tools", "reflect": "reflect"})
    graph.add_edge("tools", "reflect")
    graph.add_edge("reflect", "store")
    graph.add_edge("store", "decide")

    graph.add_conditional_edges(
        "decide",
        route_after_decide,
        {"increment": "increment", "finish": "finish", "human_gate": "finish"},
    )
    graph.add_edge("increment", "observe")
    graph.add_edge("finish", END)

    return graph


def compile_agent(checkpointer: SqliteSaver | None = None):
    """Compile graph with optional SQLite checkpointer for restart survival."""
    graph = build_agent_graph()
    if checkpointer:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


def make_initial_state(goal_id: str, goal: str) -> AgentState:
    return AgentState(
        goal_id=goal_id,
        goal=goal,
        messages=[],
        memory_context="",
        plan="",
        reflection="",
        decision="continue",
        iteration=0,
        tool_calls_made=0,
        last_action_summary="",
        human_question="",
        status="initialized",
    )


def log_cycle_event(goal_id: str, event: str, data: dict | None = None) -> None:
    """Append structured log line for monitoring."""
    log_file = settings.log_dir / "agent_cycles.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "goal_id": goal_id,
        "event": event,
        "data": data or {},
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")