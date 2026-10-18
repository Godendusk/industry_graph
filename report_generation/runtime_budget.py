"""Shared wall-clock budget for the active part of a report request.

Restore ``consumed_seconds`` from a previous snapshot when the next request
starts. Time spent waiting for the user between requests is then excluded.
"""

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import partial
from functools import wraps
import inspect
from queue import Queue, Empty
import threading
import time


class BudgetExceeded(TimeoutError):
    """The report or its current stage has used its execution time."""


_active_budget = ContextVar("report_runtime_budget", default=None)
_active_stage = ContextVar("report_runtime_stage", default=None)
DEFAULT_TOTAL_SECONDS = 1200


class RuntimeBudget:
    # Cumulative ceilings let later stages use time saved by earlier stages.
    STAGE_CEILINGS = {
        "coordinator": 560,
        "body": 800,
        "review": 1080,
        "summary": DEFAULT_TOTAL_SECONDS,
        "export": DEFAULT_TOTAL_SECONDS,
    }

    def __init__(self, total_seconds=DEFAULT_TOTAL_SECONDS, consumed_seconds=0, clock=time.monotonic):
        self.total_seconds = float(total_seconds)
        self._consumed_seconds = max(0.0, float(consumed_seconds))
        self._clock = clock
        self._started_at = clock()

    def _elapsed(self):
        return self._consumed_seconds + max(0.0, self._clock() - self._started_at)

    def remaining_seconds(self, stage=None):
        ceiling = self.total_seconds
        if stage is not None:
            ceiling *= self.STAGE_CEILINGS[stage] / DEFAULT_TOTAL_SECONDS
        return max(0.0, ceiling - self._elapsed())

    def stage_remaining_seconds(self, stage):
        return self.remaining_seconds(stage)

    def check(self, stage=None):
        remaining = self.remaining_seconds(stage)
        if remaining <= 0:
            suffix = f" (stage: {stage})" if stage else ""
            raise BudgetExceeded(f"Report runtime budget exhausted{suffix}")
        return remaining

    def snapshot(self):
        consumed = self._elapsed()
        return {
            "total_seconds": self.total_seconds,
            "consumed_seconds": consumed,
            "remaining_seconds": max(0.0, self.total_seconds - consumed),
        }

    @contextmanager
    def activate(self, stage):
        if stage not in self.STAGE_CEILINGS:
            raise ValueError(f"Unknown report stage: {stage}")
        budget_token = _active_budget.set(self)
        stage_token = _active_stage.set(stage)
        try:
            yield self
        finally:
            _active_stage.reset(stage_token)
            _active_budget.reset(budget_token)


def current_budget():
    return _active_budget.get()


def call_remaining(timeout=None):
    """Return the per-call timeout, capped by the active report stage."""
    budget = current_budget()
    remaining = budget.check(_active_stage.get()) if budget else None
    if timeout is not None:
        timeout = float(timeout)
        if timeout <= 0:
            raise BudgetExceeded("LLM call timeout exhausted")
        return min(timeout, remaining) if remaining is not None else timeout
    return remaining


def bind_runtime_context(function, *args, **kwargs):
    """Capture context before constructing a worker thread (one invocation)."""
    context = copy_context()
    return partial(context.run, function, *args, **kwargs)


def submit_with_context(executor, function, *args, **kwargs):
    """ThreadPoolExecutor submission with this report's stage context."""
    return executor.submit(bind_runtime_context(function, *args, **kwargs))


def budgeted_stage(stage):
    """Carry an optional snapshot across synchronous and streaming report APIs.

    Direct library calls keep their existing contract. Production requests pass
    a snapshot (including an empty one for a new run). A daemon boundary also
    bounds local model loading, which an HTTP timeout cannot interrupt.
    """
    def decorate(function):
        streaming = inspect.isgeneratorfunction(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            supplied = kwargs.pop('runtime_budget', None)
            inherited = current_budget()
            if supplied is None and inherited is None:
                return function(*args, **kwargs)
            if isinstance(supplied, RuntimeBudget):
                budget = supplied
            elif supplied is not None:
                budget = RuntimeBudget(total_seconds=min(DEFAULT_TOTAL_SECONDS, float(supplied.get('total_seconds', DEFAULT_TOTAL_SECONDS))),
                                       consumed_seconds=supplied.get('consumed_seconds', 0))
            else:
                budget = inherited

            def failure(exc):
                return {'status': 'error', 'delivery_status': 'incomplete',
                        'message': str(exc), 'runtime_budget': budget.snapshot()}

            def invoke():
                with budget.activate(stage):
                    budget.check(stage)
                    return function(*args, **kwargs)

            # Body generation includes its review, whose ceiling is later.
            end_stage = 'review' if stage == 'body' else stage
            if not streaming:
                if supplied is None:
                    return invoke()
                queue = Queue()
                def produce():
                    try:
                        queue.put((True, invoke()))
                    except Exception as exc:
                        queue.put((False, exc))
                threading.Thread(target=bind_runtime_context(produce), daemon=True).start()
                try:
                    ok, result = queue.get(timeout=max(.001, budget.remaining_seconds(end_stage)))
                except Empty:
                    return failure(BudgetExceeded(f'Report stage deadline exceeded: {stage}'))
                if not ok:
                    if isinstance(result, BudgetExceeded):
                        return failure(result)
                    raise result
                try:
                    budget.check(end_stage)
                except BudgetExceeded as exc:
                    return failure(exc)
                if isinstance(result, dict):
                    result['runtime_budget'] = budget.snapshot()
                return result

            def iterate():
                queue = Queue()
                stop = object()
                def produce():
                    try:
                        with budget.activate(stage):
                            budget.check(stage)
                            for event in function(*args, **kwargs):
                                queue.put(event)
                    except Exception as exc:
                        queue.put({'event': 'error', **failure(exc)})
                    finally:
                        queue.put(stop)
                threading.Thread(target=bind_runtime_context(produce), daemon=True).start()
                while True:
                    try:
                        event = queue.get(timeout=max(.001, budget.remaining_seconds(end_stage)))
                    except Empty:
                        yield {'event': 'error', **failure(BudgetExceeded(f'Report stage deadline exceeded: {stage}'))}
                        return
                    if event is stop:
                        return
                    try:
                        budget.check(end_stage)
                    except BudgetExceeded as exc:
                        yield {'event': 'error', **failure(exc)}
                        return
                    if isinstance(event, dict):
                        event['runtime_budget'] = budget.snapshot()
                    yield event
            return iterate()
        return wrapped
    return decorate
