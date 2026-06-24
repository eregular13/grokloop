# GrokLoop Architecture

## Overview

GrokLoop is a **bounded agent execution loop** implemented as a LangGraph state machine,
backed by persistent memory and a Redis task queue. It is designed for local, offline
operation with explicit stopping conditions and human-in-the-loop gates.

## State machine

```text
Receive goal
      ↓
Validate configuration (config.py / Pydantic)
      ↓
Build context (observe → ChromaDB memory)
      ↓
Plan next actions (planner LLM)
      ↓
Act (tool-calling LLM → tool registry)
      ↓
Authorize (path policy, command blocklist, timeouts)
      ↓
Execute with timeout
      ↓
Record result (store → ChromaDB + structured logs)
      ↓
Evaluate stopping conditions (budget.py + decide node)
      ├── continue → increment → observe
      ├── complete → finish
      └── ask_human → human_inbox gate
```

## Component boundaries

| Component | Module | Responsibility |
|-----------|--------|----------------|
| **Model provider** | `langchain_ollama` | Sends LLM requests, normalizes responses |
| **Loop controller** | `agent_loop.py` | LangGraph nodes, routing, checkpointing |
| **Tool registry** | `tools.py` | Typed tool definitions, argument schemas |
| **Policy layer** | `tools.py` | Path restrictions, blocklists, sandbox |
| **State store** | `memory.py`, SQLite checkpointer | Vector memory + graph checkpoints |
| **Budget manager** | `budget.py` | Iteration, time, failure limits |
| **Observer** | `observability.py` | Run ID, step ID, structured JSONL events |
| **Task intake** | `task_watcher.py` | Redis queue, filesystem watcher |
| **Human gate** | `human_gate.py` | Pause/resume on human input |

The loop controller depends on **interfaces** (LangChain tools, settings) rather than
hard-coding provider clients — enabling unit tests with fakes.

## Stopping conditions

Enforced by `budget.py` and the `decide` graph node:

| Condition | Config / trigger |
|-----------|------------------|
| Maximum iterations | `MAX_ITERATIONS_PER_GOAL` |
| Maximum elapsed time | `MAX_GOAL_ELAPSED_SECONDS` |
| Maximum consecutive failures | `MAX_CONSECUTIVE_FAILURES` |
| User cancellation | SIGTERM / docker stop |
| Successful completion | `decision == done` |
| Policy violation | Tool raises `PermissionError` |
| Human escalation | `ask_human` tool or max iterations |

## Data flow

```text
tasks/*.txt ──┐
CLI submit  ──┼──► Redis queue ──► agent daemon ──► Ollama (host)
Dashboard   ──┘         │                │
                          │                ├──► ChromaDB (memory)
                          │                ├──► workspace/ (files)
                          │                └──► data/logs/ (JSONL)
human_inbox/*.txt ───────► human_gate
```

## Deployment

Single-host Docker Compose:

- `agent` — Python 3.12 daemon
- `chromadb` — persistent vector store
- `redis` — task queue
- `searxng` — optional local search
- `dashboard` — Streamlit UI

Ollama runs on the **host** and is reached via `host.docker.internal:11434`.

## Security model

See [SECURITY.md](../SECURITY.md). Model output is untrusted. Every tool invocation
passes through typed validation and path/command policy before execution.

## Observability

Each goal run receives a `run_id`. Each graph step emits structured events:

```json
{
  "run_id": "14043fd7fd0f",
  "step_id": 4,
  "event": "cycle_step",
  "node": "decide",
  "status": "decided_continue",
  "iteration": 3,
  "duration_ms": 218
}
```

Events are appended to `data/logs/agent_cycles.jsonl`. Full prompts are not logged by default.