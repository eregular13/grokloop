# Changelog

All notable changes to GrokLoop are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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