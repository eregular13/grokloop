# GrokLoop

GrokLoop is a **local, persistent agent daemon** that helps developers and power users
**accomplish multi-step goals** (coding, research, automation) by running an explicit
**observe → plan → act → reflect → store → decide** loop against tools and memory.

It runs 100% on your machine via Docker + Ollama. No cloud API keys required.

## Who is it for?

- Developers who want a **24/7 local coding/research assistant**
- Users who want **persistent memory** across restarts
- Anyone building **offline, self-hosted agent workflows** with human-in-the-loop

## What does “loop” mean?

A **loop** is one bounded iteration toward a goal:

1. **Observe** — load relevant vector memory
2. **Plan** — decide the next 1–3 actions
3. **Act** — call tools (files, shell, Python, git, search, …)
4. **Reflect** — evaluate progress and blockers
5. **Store** — persist results to ChromaDB
6. **Decide** — `continue`, `done`, or `ask_human`

The daemon repeats until a stopping condition is met (success, max iterations, human gate, or budget).

## Example

**Input** (CLI, file drop, or dashboard):

```text
List files in /workspace, identify one improvement, and implement it.
```

**Output**:

- Tool results written to workspace files
- Iteration logs in `data/logs/agent_cycles.jsonl`
- Vector memories in ChromaDB (survives restart)
- Human questions in `human_outbox/` when blocked

**Success condition:** Agent marks goal `done` after verifiable workspace changes, or escalates via `ask_human`.

## How it works

```text
Goal intake (CLI / tasks/*.txt / dashboard)
        ↓
Redis task queue
        ↓
LangGraph state machine (default) OR LoopEngine runtime (experimental)
        ↓
Ollama (local LLM) + tools + ChromaDB memory
        ↓
Structured logs + optional human response
```

See [docs/architecture.md](docs/architecture.md) for component boundaries.

## External dependencies

| Service | Purpose | Required? |
|---------|---------|-----------|
| **Ollama** (host) | Local LLM inference | Yes |
| **ChromaDB** | Vector memory | Yes |
| **Redis** | Task queue / active goal | Yes |
| **SearXNG** | Local web search | Optional |
| **Streamlit dashboard** | Web UI | Optional |

## Quick start

### Prerequisites

- Docker Compose v2
- Ollama running (`ollama pull qwen3:14b`)

### Run

```bash
git clone https://github.com/eregular13/grokloop.git
cd grokloop
cp .env.example .env          # Linux/macOS
# copy .env.example .env      # Windows
docker compose up --build -d
```

**Operator mode (dangerous — docker socket + project write):**
```bash
docker compose -f docker-compose.yml -f docker-compose.operator.yml up -d
```

### Submit one goal

```bash
docker compose exec agent python -m main submit "List /workspace and summarize contents"
```

Or drop a `.txt` file in `tasks/`, or open http://localhost:8501

### Verify it ran

```bash
docker compose logs -f agent
cat data/logs/agent_cycles.jsonl | tail -5
```

## Loop engine (testable core)

`agent/loop_engine/` is a **pure Python loop engine** testable without Ollama, LangGraph,
Redis, ChromaDB, Docker, or live web search. It orchestrates:

```text
observe → plan → act → tools → reflect → store → decide → (continue | finish)
```

via narrow Protocol interfaces (`Planner`, `Actor`, `Reflector`, `ToolExecutor`, etc.).

| Layer | Module | Role |
|-------|--------|------|
| **Loop engine (core)** | `agent/loop_engine/` | Pure orchestration + budget + events (no framework deps) |
| **Runtime adapters** | `agent/runtime/` | Bridges engine interfaces to Ollama, tools, Chroma, Redis |
| **LangGraph daemon** | `agent/agent_loop.py` | Default production path (`USE_LOOP_ENGINE=false`) |
| **Policy** | `agent/policy.py` | Path + shell mode gating |

Run engine tests (no external services):

```bash
pip install -r agent/requirements.txt -r requirements-dev.txt
pytest tests/unit/test_loop_engine.py tests/unit/test_runtime.py -v
python examples/minimal_loop_engine.py
python examples/runtime_loop_engine_fake.py
```

Inspect a run (stub replay):

```python
from loop_engine.replay import load_events, summarize_run
```

### Experimental runtime bridge

Set `USE_LOOP_ENGINE=true` in `.env` to route goals through `agent/runtime/` adapters
instead of LangGraph. **Default is `false`** — LangGraph remains the production path.

```bash
# .env
USE_LOOP_ENGINE=true
docker compose up -d agent
```

Known limitations (not production-ready):

- Actor tool-call quality depends on Ollama model support for structured tool calls
- Resume from human gate is wired but minimally exercised in production
- LangGraph path is unchanged and remains the safe default

Test the runtime bridge without live services:

```bash
python examples/runtime_loop_engine_fake.py
pytest tests/unit/test_runtime.py -v
```

## Project layout

```text
grokloop/
├── agent/
│   ├── loop_engine/ # Deterministic testable loop core
│   ├── runtime/     # Production adapters (Ollama, tools, Chroma, SQLite)
│   ├── agent_loop.py # LangGraph production daemon (default)
├── dashboard/       # Streamlit UI
├── config/          # SearXNG settings
├── tasks/           # Drop goal .txt files here
├── workspace/       # Agent sandbox (read/write)
├── tests/           # Unit tests (controller, budget, policy)
├── docs/            # Architecture & decisions
├── examples/        # Minimal examples
└── docker-compose.yml
```

## Configuration

Copy `.env.example` to `.env`. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `qwen3:14b` | Primary tool-calling model |
| `OLLAMA_PLANNER_MODEL` | _(empty)_ | Separate planner model |
| `USE_LOOP_ENGINE` | `false` | Experimental LoopEngine runtime (LangGraph default) |
| `MAX_ITERATIONS_PER_GOAL` | `50` | Hard iteration cap |
| `LOOP_SLEEP_SECONDS` | `30` | Pause between queued goals |
| `SELF_EDIT_MODE` | `false` | Allow edits to project source |

## Agent modes (safety tiers)

| Mode | File writes | Shell | Python | Git commit | Docker |
|------|-------------|-------|--------|------------|--------|
| `observe` | No | read-only | No | No | No |
| `edit` | workspace | low-risk only | Yes | read-only | No |
| `build` | workspace | + pip/npm/make | Yes | yes | No |
| `operator` | workspace + project* | all tiers | Yes | yes | Yes* |

\* Requires `docker compose -f docker-compose.yml -f docker-compose.operator.yml up` and `ENABLE_DOCKER_TOOL=true`.

**Default is `edit` mode** — no Docker socket, no project-root mount.

## Threat model

GrokLoop executes **model-proposed actions** on your machine. Treat model output as **untrusted**.

| Risk | Default | Operator overlay |
|------|---------|------------------|
| Docker socket escape | Disabled | Explicit opt-in |
| Project source modification | Blocked | `SELF_EDIT_MODE=true` |
| LAN exposure | Ports bound to `127.0.0.1` | Same |
| Dashboard queue injection | Localhost + optional password | Set `DASHBOARD_PASSWORD` |
| Path traversal | `Path.relative_to()` containment | Same |
| Shell injection | Mode-gated allowlist, not denylist-only | Same |

**Do not run operator mode overnight unattended.**

## Out of scope (deliberately)

- Cloud LLM providers (OpenAI, Anthropic, etc.) — use Ollama locally
- Multi-tenant SaaS hosting
- Unsandboxed arbitrary internet access from tools
- Guaranteed correctness of model output — model suggestions are **untrusted**
- Production Kubernetes / cloud deployment guides (Docker Compose only for now)

## Development

```bash
pip install -r agent/requirements.txt -r requirements-dev.txt
ruff check agent dashboard tests
python -m compileall agent dashboard
PYTHONPATH=agent:dashboard pytest tests/ -v
docker compose config --quiet
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities privately via GitHub Security Advisories.