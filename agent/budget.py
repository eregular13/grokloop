"""Budget manager — explicit stopping conditions for the agent loop."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

StopReason = Literal[
    "continue",
    "max_iterations",
    "max_elapsed_time",
    "max_consecutive_failures",
    "completed",
    "ask_human",
    "cancelled",
    "policy_violation",
]


@dataclass
class BudgetConfig:
    max_iterations: int = 50
    max_elapsed_seconds: float | None = None
    max_consecutive_failures: int = 5


@dataclass
class BudgetState:
    iteration: int = 0
    consecutive_failures: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at


class BudgetManager:
    """Enforces iteration, time, and failure budgets before each loop step."""

    def __init__(self, config: BudgetConfig) -> None:
        self.config = config
        self.state = BudgetState()

    def record_success(self) -> None:
        self.state.consecutive_failures = 0

    def record_failure(self) -> None:
        self.state.consecutive_failures += 1

    def increment_iteration(self) -> None:
        self.state.iteration += 1

    def check(self, *, decision: str = "continue") -> tuple[bool, StopReason]:
        """Return (should_stop, reason)."""
        if decision == "done":
            return True, "completed"
        if decision == "ask_human":
            return True, "ask_human"

        if self.state.iteration >= self.config.max_iterations:
            return True, "max_iterations"

        if (
            self.config.max_elapsed_seconds is not None
            and self.state.elapsed_seconds() >= self.config.max_elapsed_seconds
        ):
            return True, "max_elapsed_time"

        if self.state.consecutive_failures >= self.config.max_consecutive_failures:
            return True, "max_consecutive_failures"

        return False, "continue"

    def remaining_iterations(self) -> int:
        return max(0, self.config.max_iterations - self.state.iteration)