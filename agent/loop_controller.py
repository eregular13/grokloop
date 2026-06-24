"""Loop controller — state model and routing (no provider imports)."""

from __future__ import annotations

from typing import Literal, TypedDict

DecisionType = Literal["continue", "done", "ask_human"]


class AgentState(TypedDict):
    goal_id: str
    goal: str
    messages: list
    memory_context: str
    plan: str
    reflection: str
    decision: DecisionType
    iteration: int
    tool_calls_made: int
    last_action_summary: str
    human_question: str
    status: str


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


def route_after_decide(state: AgentState) -> str:
    decision = state.get("decision", "continue")
    if decision == "done":
        return "finish"
    if decision == "ask_human":
        return "human_gate"
    return "increment"


def parse_decision(raw: str) -> DecisionType:
    """Parse LLM decision text into a typed decision."""
    text = raw.strip().lower()
    if "done" in text:
        return "done"
    if "ask" in text or "human" in text:
        return "ask_human"
    return "continue"
