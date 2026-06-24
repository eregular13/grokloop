# Changelog

All notable changes to GrokLoop are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Security

- Remove Docker socket and `/project` mount from default Compose
- Add `docker-compose.operator.yml` explicit opt-in overlay
- Bind ChromaDB, SearXNG, dashboard to `127.0.0.1` only
- Fix path containment with `Path.relative_to()` (prefix-attack safe)
- Replace shell denylist-only with mode-gated risk tiers
- Gate `docker_command` behind `AGENT_MODE=operator` + `ENABLE_DOCKER_TOOL`
- Optional `DASHBOARD_PASSWORD` auth gate

### Reliability

- Unique UUID goal IDs (dedupe hash separate)
- Non-blocking human gate — park goal in Redis, worker continues
- Correlated `question_id` for human responses
- `SEED_DEFAULT_GOAL=false` by default; only seed when queue empty
- Global + goal-specific memory in observe phase

### Added

- README with product contract (problem, audience, loop definition, quick start)
- Architecture documentation and ADR for LangGraph
- `budget.py` — explicit stopping conditions
- `observability.py` — structured run/step event logging
- Unit tests for loop routing, budget, and path policy
- GitHub Actions CI workflow
- CONTRIBUTING, SECURITY, LICENSE, CHANGELOG
- Dependabot and issue/PR templates

## [0.1.0] - 2026-06-24

### Added

- Initial LocalGrokLoop implementation
- LangGraph agent daemon with SQLite checkpointing
- ChromaDB vector memory, Redis task queue
- Tool suite: files, shell, Python, git, docker, search, memory, human gate
- SearXNG local search service
- Streamlit dashboard on port 8501
- Docker Compose stack with Ollama via `host.docker.internal`
- Goal intake: CLI, `tasks/*.txt` file drop, web UI