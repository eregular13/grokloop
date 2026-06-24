"""Structured observability — run IDs, step IDs, JSONL events."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings


def new_run_id(goal_id: str = "") -> str:
    """Stable run identifier; prefers goal_id when available."""
    return goal_id or uuid.uuid4().hex[:12]


class RunObserver:
    """Emits structured events for a single goal run."""

    def __init__(self, run_id: str, log_path: Path | None = None) -> None:
        self.run_id = run_id
        self.step_id = 0
        self.log_path = log_path or (settings.log_dir / "agent_cycles.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event: str,
        *,
        node: str = "",
        status: str = "",
        iteration: int = 0,
        duration_ms: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.step_id += 1
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "step_id": self.step_id,
            "event": event,
        }
        if node:
            entry["node"] = node
        if status:
            entry["status"] = status
        if iteration:
            entry["iteration"] = iteration
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        if extra:
            entry["data"] = extra

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry
