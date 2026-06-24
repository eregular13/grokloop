"""Unit tests for budget stopping conditions."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))

from budget import BudgetConfig, BudgetManager


class TestBudgetManager:
    def test_continue_when_under_limits(self):
        bm = BudgetManager(BudgetConfig(max_iterations=10))
        bm.state.iteration = 3
        stop, reason = bm.check()
        assert stop is False
        assert reason == "continue"

    def test_stop_at_max_iterations(self):
        bm = BudgetManager(BudgetConfig(max_iterations=5))
        bm.state.iteration = 5
        stop, reason = bm.check()
        assert stop is True
        assert reason == "max_iterations"

    def test_stop_on_completed_decision(self):
        bm = BudgetManager(BudgetConfig())
        stop, reason = bm.check(decision="done")
        assert stop is True
        assert reason == "completed"

    def test_stop_on_ask_human_decision(self):
        bm = BudgetManager(BudgetConfig())
        stop, reason = bm.check(decision="ask_human")
        assert stop is True
        assert reason == "ask_human"

    def test_stop_on_consecutive_failures(self):
        bm = BudgetManager(BudgetConfig(max_consecutive_failures=3))
        bm.state.consecutive_failures = 3
        stop, reason = bm.check()
        assert stop is True
        assert reason == "max_consecutive_failures"

    def test_record_success_resets_failures(self):
        bm = BudgetManager(BudgetConfig())
        bm.record_failure()
        bm.record_failure()
        bm.record_success()
        assert bm.state.consecutive_failures == 0

    def test_remaining_iterations(self):
        bm = BudgetManager(BudgetConfig(max_iterations=10))
        bm.state.iteration = 7
        assert bm.remaining_iterations() == 3
