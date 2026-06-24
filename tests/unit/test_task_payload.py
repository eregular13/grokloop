"""Ensure dashboard and agent task payloads stay compatible."""

from __future__ import annotations

import re

# Dashboard copy lives in dashboard/ — import via path hack for test
import sys
from pathlib import Path

from task_payload import build_task_payload as agent_build
from task_payload import goal_content_hash, new_goal_id

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dashboard"))
from task_submit import build_task_payload as dash_build  # noqa: E402

REQUIRED_KEYS = frozenset(
    {"goal_id", "goal", "source", "goal_hash", "thread_id", "question_id", "created_at"}
)


class TestTaskPayloadParity:
    def test_required_keys(self):
        p = agent_build("hello world", "cli")
        assert REQUIRED_KEYS.issubset(p.keys())

    def test_goal_id_is_uuid_hex_16(self):
        gid = new_goal_id()
        assert re.fullmatch(r"[a-f0-9]{16}", gid)

    def test_unique_ids_same_text(self):
        a = agent_build("same goal", "cli")
        b = agent_build("same goal", "cli")
        assert a["goal_id"] != b["goal_id"]
        assert a["goal_hash"] == b["goal_hash"] == goal_content_hash("same goal")

    def test_dashboard_matches_agent_schema(self):
        a = agent_build("dashboard goal", "dashboard")
        d = dash_build("dashboard goal", "dashboard", goal_id=a["goal_id"])
        assert set(a.keys()) == set(d.keys())
        for k in REQUIRED_KEYS:
            if k == "created_at":
                continue
            assert a[k] == d[k]

    def test_thread_id_format(self):
        p = agent_build("x", "cli")
        assert p["thread_id"] == f"goal_{p['goal_id']}"
