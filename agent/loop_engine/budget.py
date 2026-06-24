"""Budget enforcement for the loop engine — injectable clock for tests."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from loop_engine.models import Decision, RunConfig, RunState, StopReason

Clock = Callable[[], float]


@dataclass
class BudgetState:
    started_at: float = field(default_factory=time.monotonic)

    def elapsed(self, clock: Clock) -> float:
        return clock() - self.started_at


class LoopBudget:
    """Checks stopping conditions against RunState + RunConfig."""

    def __init__(self, config: RunConfig, clock: Clock | None = None) -> None:
        self.config = config
        self.clock: Clock = clock or time.monotonic
        self._started_at = self.clock()

    def elapsed_seconds(self) -> float:
        return self.clock() - self._started_at

    def check(self, state: RunState, *, decision: Decision | None = None) -> StopReason:
        if decision == Decision.DONE:
            return StopReason.COMPLETED
        if decision == Decision.ASK_HUMAN:
            return StopReason.ASK_HUMAN

        if state.iteration >= self.config.max_iterations:
            return StopReason.MAX_ITERATIONS

        if (
            self.config.max_elapsed_seconds is not None
            and self.elapsed_seconds() >= self.config.max_elapsed_seconds
        ):
            return StopReason.MAX_ELAPSED_TIME

        if state.consecutive_failures >= self.config.max_consecutive_failures:
            return StopReason.MAX_CONSECUTIVE_FAILURES

        if state.tool_calls_made >= self.config.max_tool_calls:
            return StopReason.MAX_TOOL_CALLS

        return StopReason.CONTINUE

    def should_stop(self, reason: StopReason) -> bool:
        return reason != StopReason.CONTINUE