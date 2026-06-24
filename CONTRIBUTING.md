# Contributing to GrokLoop

Thank you for your interest in contributing.

## Getting started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USER/grokloop.git`
3. Copy `.env.example` to `.env`
4. Install dev dependencies:

   ```bash
   pip install -r agent/requirements.txt pytest
   ```

5. Run tests:

   ```bash
   PYTHONPATH=agent pytest tests/ -v
   ```

## Pull request guidelines

- One logical change per PR
- Include tests for controller, budget, or policy changes
- Do not commit `.env`, runtime `data/`, or secrets
- Update `CHANGELOG.md` for user-visible changes
- Ensure CI passes

## Code organization

| Module | Responsibility |
|--------|----------------|
| `agent/agent_loop.py` | LangGraph state machine |
| `agent/budget.py` | Stopping conditions |
| `agent/observability.py` | Structured run/step events |
| `agent/tools.py` | Tool registry + sandbox policy |
| `agent/memory.py` | ChromaDB persistence |
| `agent/config.py` | Typed configuration |

Keep the loop controller independent of concrete providers where possible — use interfaces and fakes in tests.

## Commit messages

Use clear, imperative subjects:

```text
Add budget check for max consecutive failures
Fix path traversal in read_file tool
Document Ollama split-brain setup in README
```

## Questions

Open a GitHub issue for bugs, features, or design discussion.