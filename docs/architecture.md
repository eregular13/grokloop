# GrokLoop Architecture

## Overview

GrokLoop has three loop layers:

1. **`agent/loop_engine/`** — pure, deterministic orchestration over Protocol interfaces.
   Fully testable with fakes. No LangGraph/Ollama/Redis/Chroma imports.
2. **`agent/runtime/`** — production adapters implementing those interfaces (Ollama planner/actor/reflector,
   `tools.py` executor, Chroma memory, SQLite checkpoints, JSONL events, human gate).
   Enabled when `USE_LOOP_ENGINE=true` (experimental, not production-ready).
3. **`agent/agent_loop.py`** — LangGraph production path (default when `USE_LOOP_ENGINE=false`).

The daemon uses layer 3 by default. Layer 2 bridges layer 1 to live services without polluting the engine core.

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
| **Loop engine (core)** | `loop_engine/engine.py` | Deterministic phase orchestration |
| **Runtime adapters** | `runtime/adapters.py`, `runtime/factory.py` | Bridge engine to Ollama/tools/Chroma/Redis |
| **Loop controller (LangGraph)** | `agent_loop.py` | Default production path (`USE_LOOP_ENGINE=false`) |
| **Loop runtime** | `runtime/loop_engine_runtime.py` | Experimental daemon path (`USE_LOOP_ENGINE=true`) |
| **Tool registry** | `tools.py` | Typed tool definitions, argument schemas |
| **Policy layer** | `tools.py` | Path restrictions, blocklists, sandbox |
| **State store** | `memory.py`, SQLite checkpointer | Vector memory + graph checkpoints |
| **Budget manager** | `loop_engine/budget.py`, `budget.py` | Iteration, time, tool-call limits |
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

Events append to `data/logs/agent_cycles.jsonl`. Two formats coexist:

**LangGraph path** (legacy wrapper events):

```json
{"timestamp": "...", "goal_id": "...", "event": "goal_started", "data": {...}}
```

**LoopEngine path** (normalized phase events via `loop_engine.events.JsonlEventSink`):

```json
{
  "timestamp": "...",
  "run_id": "...",
  "goal_id": "...",
  "step_id": 4,
  "phase": "decide",
  "event": "continue",
  "status": "decided_continue",
  "decision": "continue",
  "duration_ms": 218
}
```

The Streamlit dashboard loads JSONL generically (both formats display in the activity table).
Full prompts are not logged by default.

## Loop engine interfaces

```text
LoopEngine
  ├── Planner.plan(state) -> str
  ├── Actor.act(state) -> (summary, tool_calls)
  ├── ToolExecutor.execute(state, call) -> ToolResultRecord
  ├── Reflector.reflect(state) -> (reflection, decision?)
  ├── MemoryStore.observe/store
  ├── CheckpointStore.save/load  # resume support
  ├── EventSink.emit             # ordered step_id
  └── ApprovalGate.park          # ask_human without blocking worker
```

## Run replay (stub)

`loop_engine/replay.py` loads JSONL events and summarizes phase order. Full step replay UI
is deferred; use `data/logs/agent_cycles.jsonl` for inspection today.