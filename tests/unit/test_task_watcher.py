"""Unit tests for task queue behavior."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

# Allow importing task_watcher without redis/watchdog installed locally
if "redis" not in sys.modules:
    sys.modules["redis"] = MagicMock()
if "watchdog" not in sys.modules:
    watchdog = MagicMock()
    sys.modules["watchdog"] = watchdog
    sys.modules["watchdog.events"] = MagicMock()
    sys.modules["watchdog.observers"] = MagicMock()

from task_watcher import Task, _goal_hash, _new_goal_id, enqueue_task


class TestGoalIds:
    def test_unique_ids_for_same_text(self):
        a = _new_goal_id()
        b = _new_goal_id()
        assert a != b

    def test_goal_hash_stable(self):
        assert _goal_hash("hello") == _goal_hash("hello")
        assert _goal_hash("hello") != _goal_hash("world")


class TestEnqueue:
    @patch("task_watcher.get_redis")
    def test_enqueue_preserves_payload(self, mock_redis_fn):
        mock_r = MagicMock()
        mock_redis_fn.return_value = mock_r
        task = enqueue_task("Build tests", source="test")
        assert len(task.goal_id) == 16
        assert task.goal_hash == _goal_hash("Build tests")
        payload = json.loads(mock_r.rpush.call_args[0][1])
        assert payload["goal"] == "Build tests"
        assert payload["source"] == "test"