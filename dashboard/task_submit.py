"""Dashboard task submission — mirrors agent/task_payload.py semantics."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone


def new_goal_id() -> str:
    return uuid.uuid4().hex[:16]


def goal_content_hash(goal: str) -> str:
    return hashlib.sha256(goal.encode()).hexdigest()[:16]


def build_task_payload(goal: str, source: str = "dashboard", *, goal_id: str = "") -> dict:
    gid = goal_id or new_goal_id()
    return {
        "goal_id": gid,
        "goal": goal.strip(),
        "source": source,
        "goal_hash": goal_content_hash(goal),
        "thread_id": f"goal_{gid}",
        "question_id": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }