"""Reconstruct a run timeline from JSONL engine events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_events(path: Path, *, run_id: str = "") -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if run_id and ev.get("run_id") != run_id:
            continue
        events.append(ev)
    return events


def summarize_run(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"phases": [], "step_count": 0}
    phases = [e.get("phase") for e in events if e.get("event") == "phase_complete"]
    last = events[-1]
    return {
        "run_id": last.get("run_id"),
        "goal_id": last.get("goal_id"),
        "step_count": len(events),
        "phases": phases,
        "final_stop_reason": last.get("stop_reason", ""),
        "final_status": last.get("status", ""),
    }