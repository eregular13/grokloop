"""Unit tests for task queue behavior."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

if "redis" not in sys.modules:
    sys.modules["redis"] = MagicMock()
if "watchdog" not in sys.modules:
    watchdog = MagicMock()
    sys.modules["watchdog"] = watchdog
    sys.modules["watchdog.events"] = MagicMock()
    sys.modules["watchdog.observers"] = MagicMock()

from task_payload import goal_content_hash, new_goal_id
from task_watcher import enqueue_task


class TestGoalIds:
    def test_unique_ids_for_same_text(self):
        assert new_goal_id() != new_goal_id()

    def test_goal_hash_stable(self):
        assert goal_content_hash("hello") == goal_content_hash("hello")


class TestEnqueue:
    @patch("task_watcher.get_redis")
    def test_enqueue_preserves_payload(self, mock_redis_fn):
        mock_r = MagicMock()
        mock_redis_fn.return_value = mock_r
        task = enqueue_task("Build tests", source="test")
        assert len(task.goal_id) == 16
        assert task.goal_hash == goal_content_hash("Build tests")
        payload = json.loads(mock_r.rpush.call_args[0][1])
        assert payload["goal"] == "Build tests"
        assert payload["thread_id"] == f"goal_{task.goal_id}"
        assert "goal_hash" in payload