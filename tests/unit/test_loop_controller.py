"""Unit tests for loop controller routing and initial state."""

from __future__ import annotations

from loop_controller import make_initial_state, parse_decision, route_after_decide


class TestRouteAfterDecide:
    def test_continue_routes_to_increment(self):
        state = make_initial_state("abc123", "test goal")
        state["decision"] = "continue"
        assert route_after_decide(state) == "increment"

    def test_done_routes_to_finish(self):
        state = make_initial_state("abc123", "test goal")
        state["decision"] = "done"
        assert route_after_decide(state) == "finish"

    def test_ask_human_routes_to_human_gate(self):
        state = make_initial_state("abc123", "test goal")
        state["decision"] = "ask_human"
        assert route_after_decide(state) == "human_gate"

    def test_missing_decision_defaults_to_increment(self):
        state = make_initial_state("abc123", "test goal")
        assert route_after_decide(state) == "increment"


class TestParseDecision:
    def test_parse_done(self):
        assert parse_decision("done") == "done"
        assert parse_decision("The goal is DONE.") == "done"

    def test_parse_ask_human(self):
        assert parse_decision("ask_human") == "ask_human"
        assert parse_decision("I need human help") == "ask_human"

    def test_parse_continue(self):
        assert parse_decision("continue") == "continue"
        assert parse_decision("more work needed") == "continue"


class TestMakeInitialState:
    def test_initial_fields(self):
        state = make_initial_state("goal1", "Do something")
        assert state["goal_id"] == "goal1"
        assert state["goal"] == "Do something"
        assert state["iteration"] == 0
        assert state["decision"] == "continue"
        assert state["status"] == "initialized"
        assert state["messages"] == []
