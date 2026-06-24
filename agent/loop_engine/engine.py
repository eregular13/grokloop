"""Deterministic loop engine — pure orchestration over injected interfaces."""

from __future__ import annotations

import time

from loop_engine.budget import LoopBudget
from loop_engine.interfaces import (
    Actor,
    ApprovalGate,
    CheckpointStore,
    EventSink,
    MemoryStore,
    Planner,
    Reflector,
    ToolExecutor,
)
from loop_engine.models import (
    Decision,
    LoopPhase,
    RunConfig,
    RunResult,
    RunState,
    StopReason,
    ToolResultRecord,
)


def parse_decision_text(raw: str) -> Decision:
    text = raw.strip().lower()
    if "done" in text:
        return Decision.DONE
    if "ask" in text or "human" in text:
        return Decision.ASK_HUMAN
    return Decision.CONTINUE


def new_run_state(run_id: str, goal_id: str, goal: str) -> RunState:
    return RunState(run_id=run_id, goal_id=goal_id, goal=goal)


class LoopEngine:
    """Runs one goal through observe → plan → act → tools → reflect → store → decide."""

    def __init__(
        self,
        *,
        planner: Planner,
        actor: Actor,
        reflector: Reflector,
        tool_executor: ToolExecutor,
        memory: MemoryStore,
        checkpoints: CheckpointStore,
        events: EventSink,
        approval: ApprovalGate,
        config: RunConfig | None = None,
    ) -> None:
        self.planner = planner
        self.actor = actor
        self.reflector = reflector
        self.tool_executor = tool_executor
        self.memory = memory
        self.checkpoints = checkpoints
        self.events = events
        self.approval = approval
        self.config = config or RunConfig()
        self._step = 0

    def run(self, state: RunState | None = None, *, goal: str = "", goal_id: str = "", run_id: str = "") -> RunResult:
        if state is None:
            if not goal or not goal_id or not run_id:
                raise ValueError("run() requires state or goal+goal_id+run_id")
            state = new_run_state(run_id, goal_id, goal)
        return self._run_loop(state)

    def resume(self, run_id: str) -> RunResult:
        loaded = self.checkpoints.load(run_id)
        if loaded is None:
            raise KeyError(f"No checkpoint for run_id={run_id}")
        return self._run_loop(loaded)

    def _run_loop(self, state: RunState) -> RunResult:
        budget = LoopBudget(self.config)
        self._step = int(state.metadata.get("last_step_id", 0))

        while True:
            # Budget gate before each iteration
            pre_reason = budget.check(state)
            if budget.should_stop(pre_reason) and pre_reason not in (StopReason.CONTINUE,):
                return self._finish(state, pre_reason, budget)

            try:
                state = self._phase_observe(state, budget)
                state = self._phase_plan(state, budget)
                state = self._phase_act(state, budget)
                state = self._phase_tools(state, budget)
                state = self._phase_reflect(state, budget)
                state = self._phase_store(state, budget)
                state, stop = self._phase_decide(state, budget)
                if stop:
                    return self._finish(state, state.stop_reason, budget)
            except BudgetStop as exc:
                return self._finish(state, exc.reason, budget)
            except PolicyViolation as exc:
                state.stop_reason = StopReason.POLICY_VIOLATION
                state.status = "policy_violation"
                self._emit(state, LoopPhase.DECIDE, "policy_violation", stop_reason=StopReason.POLICY_VIOLATION, data={"error": str(exc)})
                self._checkpoint(state)
                return self._finish(state, StopReason.POLICY_VIOLATION, budget)
            except Exception as exc:
                state.stop_reason = StopReason.ERROR
                state.status = "error"
                self._emit(state, state.phase, "error", stop_reason=StopReason.ERROR, data={"error": str(exc)})
                self._checkpoint(state)
                return self._finish(state, StopReason.ERROR, budget)

            # continue — next iteration
            state.iteration += 1
            state.decision = Decision.CONTINUE
            state.pending_tool_calls = []
            state.tool_results = []
            state.phase = LoopPhase.OBSERVE
            state.touch()
            self._checkpoint(state)

    def _phase_observe(self, state: RunState, budget: LoopBudget) -> RunState:
        t0 = time.monotonic()
        state.phase = LoopPhase.OBSERVE
        state.memory_context = self.memory.observe(state)
        state.status = "observed"
        state.touch()
        self._emit(state, LoopPhase.OBSERVE, "phase_complete", status=state.status, duration_ms=_ms(t0))
        self._checkpoint(state)
        return state

    def _phase_plan(self, state: RunState, budget: LoopBudget) -> RunState:
        t0 = time.monotonic()
        state.phase = LoopPhase.PLAN
        state.plan = self.planner.plan(state)
        state.status = "planned"
        state.touch()
        self._emit(state, LoopPhase.PLAN, "phase_complete", status=state.status, duration_ms=_ms(t0))
        self._checkpoint(state)
        return state

    def _phase_act(self, state: RunState, budget: LoopBudget) -> RunState:
        t0 = time.monotonic()
        state.phase = LoopPhase.ACT
        summary, tool_calls = self.actor.act(state)
        state.last_action_summary = summary
        state.pending_tool_calls = tool_calls
        state.status = "acted"
        state.touch()
        self._emit(
            state,
            LoopPhase.ACT,
            "phase_complete",
            status=state.status,
            duration_ms=_ms(t0),
            data={"tool_calls": len(tool_calls)},
        )
        self._checkpoint(state)
        return state

    def _phase_tools(self, state: RunState, budget: LoopBudget) -> RunState:
        if not state.pending_tool_calls:
            return state
        t0 = time.monotonic()
        state.phase = LoopPhase.TOOLS
        results: list[ToolResultRecord] = []
        for call in state.pending_tool_calls:
            result = self.tool_executor.execute(state, call)
            results.append(result)
            state.tool_calls_made += 1
            if not result.success:
                state.consecutive_failures += 1
            else:
                state.consecutive_failures = 0
            tool_stop = budget.check(state)
            if tool_stop == StopReason.MAX_TOOL_CALLS:
                state.stop_reason = tool_stop
                state.status = "max_tool_calls"
                self._emit(state, LoopPhase.TOOLS, "budget_stop", stop_reason=tool_stop)
                self._checkpoint(state)
                raise BudgetStop(tool_stop)
        state.tool_results = results
        state.status = "tools_executed"
        state.touch()
        self._emit(state, LoopPhase.TOOLS, "phase_complete", status=state.status, duration_ms=_ms(t0), data={"count": len(results)})
        self._checkpoint(state)
        return state

    def _phase_reflect(self, state: RunState, budget: LoopBudget) -> RunState:
        t0 = time.monotonic()
        state.phase = LoopPhase.REFLECT
        reflection, suggested = self.reflector.reflect(state)
        state.reflection = reflection
        if suggested is not None:
            state.metadata["suggested_decision"] = suggested.value
        state.status = "reflected"
        state.touch()
        self._emit(state, LoopPhase.REFLECT, "phase_complete", status=state.status, duration_ms=_ms(t0))
        self._checkpoint(state)
        return state

    def _phase_store(self, state: RunState, budget: LoopBudget) -> RunState:
        t0 = time.monotonic()
        state.phase = LoopPhase.STORE
        self.memory.store(state)
        state.status = "stored"
        state.touch()
        self._emit(state, LoopPhase.STORE, "phase_complete", status=state.status, duration_ms=_ms(t0))
        self._checkpoint(state)
        return state

    def _phase_decide(self, state: RunState, budget: LoopBudget) -> tuple[RunState, bool]:
        t0 = time.monotonic()
        state.phase = LoopPhase.DECIDE

        suggested = state.metadata.get("suggested_decision")
        if suggested:
            decision = Decision(suggested)
        else:
            decision = parse_decision_text(state.reflection)

        if state.iteration >= self.config.max_iterations and decision == Decision.CONTINUE:
            decision = Decision.ASK_HUMAN
            state.human_question = f"Reached max iterations ({self.config.max_iterations}). Continue?"

        state.decision = decision
        stop_reason = budget.check(state, decision=decision)

        if decision == Decision.ASK_HUMAN:
            question = state.human_question or state.reflection or "Human input required."
            qid = self.approval.park(state, question)
            state.human_question = question
            state.metadata["question_id"] = qid
            state.stop_reason = StopReason.ASK_HUMAN
            state.status = "awaiting_human"
            self._emit(state, LoopPhase.DECIDE, "ask_human", decision=decision, stop_reason=StopReason.ASK_HUMAN, duration_ms=_ms(t0), data={"question_id": qid})
            self._checkpoint(state)
            return state, True

        if decision == Decision.DONE:
            state.stop_reason = StopReason.COMPLETED
            state.status = "completed"
            self._emit(state, LoopPhase.DECIDE, "done", decision=decision, stop_reason=StopReason.COMPLETED, duration_ms=_ms(t0))
            self._checkpoint(state)
            return state, True

        if budget.should_stop(stop_reason):
            state.stop_reason = stop_reason
            state.status = stop_reason.value
            self._emit(state, LoopPhase.DECIDE, "budget_stop", stop_reason=stop_reason, duration_ms=_ms(t0))
            self._checkpoint(state)
            return state, True

        state.status = "decided_continue"
        state.touch()
        self._emit(state, LoopPhase.DECIDE, "continue", decision=Decision.CONTINUE, duration_ms=_ms(t0))
        self._checkpoint(state)
        return state, False

    def _finish(self, state: RunState, reason: StopReason, budget: LoopBudget) -> RunResult:
        state.phase = LoopPhase.FINISH
        state.stop_reason = reason
        state.status = reason.value if reason != StopReason.CONTINUE else state.status
        state.touch()
        self._emit(state, LoopPhase.FINISH, "run_finished", stop_reason=reason)
        self._checkpoint(state)
        return RunResult(
            run_id=state.run_id,
            goal_id=state.goal_id,
            status=state.status,
            stop_reason=reason,
            iterations=state.iteration,
            tool_calls_made=state.tool_calls_made,
            final_state=state,
        )

    def _emit(self, state: RunState, phase: LoopPhase, event: str, **kwargs) -> None:
        self._step += 1
        state.metadata["last_step_id"] = self._step
        self.events.emit(state, self._step, phase, event, **kwargs)

    def _checkpoint(self, state: RunState) -> None:
        self.checkpoints.save(state)


class PolicyViolation(Exception):
    pass


class BudgetStop(Exception):
    def __init__(self, reason: StopReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
