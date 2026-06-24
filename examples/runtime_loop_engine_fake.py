#!/usr/bin/env python3
"""Run LoopEngine via runtime factory with fake adapters — no external services."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from loop_engine.events import InMemoryEventSink
from loop_engine.models import Decision, RunConfig
from runtime.factory import build_loop_engine


def main() -> None:
    events = InMemoryEventSink()
    engine = build_loop_engine(
        use_fakes=True,
        fake_reflector_decision=Decision.DONE,
        overrides={
            "events": events,
            "config": RunConfig(max_iterations=2),
        },
    )
    result = engine.run(goal="Summarize workspace layout", goal_id="fake-goal", run_id="fake-run")
    print(f"status={result.status}")
    print(f"stop_reason={result.stop_reason.value}")
    print(f"iterations={result.iterations}")
    print(f"events={len(events.events)}")


if __name__ == "__main__":
    main()
