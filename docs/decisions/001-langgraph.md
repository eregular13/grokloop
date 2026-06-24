# ADR 001: LangGraph for the loop controller

## Status

Accepted

## Context

GrokLoop needs a persistent, restartable agent loop with explicit state transitions,
checkpointing, and human-in-the-loop support.

## Decision

Use **LangGraph** with SQLite checkpointer as the loop controller.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| **LangGraph** | Native state machine, checkpoints, HITL | LangChain ecosystem dependency |
| **CrewAI + LiteLLM** | Multi-agent roles | Weaker cycle control, manual persistence |
| **Single recursive function** | Simple | No checkpointing, hard to test, infinite loop risk |

## Consequences

- Graph nodes map 1:1 to loop phases (observe, plan, act, reflect, store, decide)
- Restart survival via `data/checkpoints/agent_state.db`
- Unit tests target routing and budget logic independently of the graph runtime
- Provider swaps (Ollama → other) require only adapter changes, not controller rewrites