# Minimal example

This example demonstrates one complete, bounded GrokLoop run.

## Prerequisites

- Docker Compose
- Ollama with `qwen3:14b` pulled

## Steps

```bash
# From repository root
cp .env.example .env
docker compose up --build -d

# Wait for services (~30s), then submit a bounded goal
docker compose exec agent python -m main submit "List /workspace and write a one-line summary to summary.txt"

# Watch progress
docker compose logs -f agent
```

## Expected output

1. Agent logs show: `OBSERVE → PLAN → ACT → REFLECT → STORE → DECIDE`
2. `workspace/summary.txt` is created inside the container (visible on host at `./workspace/`)
3. `data/logs/agent_cycles.jsonl` contains structured events with `run_id` and `step_id`
4. Loop stops with `decision: done` or `ask_human` within `MAX_ITERATIONS_PER_GOAL`

## Success condition

`workspace/summary.txt` exists and contains a non-empty summary of the workspace listing.