from concurrent.futures import ThreadPoolExecutor

import pytest

from report_generation.runtime_budget import (
    BudgetExceeded,
    RuntimeBudget,
    bind_runtime_context,
    call_remaining,
    current_budget,
    submit_with_context,
)


def test_budget_survives_stage_transition_and_restores_snapshot():
    now = [0.0]
    budget = RuntimeBudget(total_seconds=900, consumed_seconds=120, clock=lambda: now[0])
    now[0] = 80.0
    assert budget.remaining_seconds() == 700
    snapshot = budget.snapshot()
    assert snapshot["consumed_seconds"] == 200
    # A new request starts a new clock: user waiting between requests is excluded.
    now[0] = 500.0
    resumed = RuntimeBudget(total_seconds=snapshot["total_seconds"], consumed_seconds=snapshot["consumed_seconds"], clock=lambda: now[0])
    assert resumed.remaining_seconds() == 700
    now[0] += 20
    assert resumed.remaining_seconds() == 680


def test_stage_ceilings_carry_unused_time_to_later_stages():
    now = [0.0]
    budget = RuntimeBudget(clock=lambda: now[0])
    now[0] = 120.0
    assert budget.stage_remaining_seconds("coordinator") == 440
    assert budget.stage_remaining_seconds("body") == 680
    assert budget.stage_remaining_seconds("review") == 960
    assert budget.stage_remaining_seconds("summary") == 1080
    assert budget.stage_remaining_seconds("export") == 1080
    now[0] = 800.0
    with pytest.raises(BudgetExceeded, match="body"):
        budget.check("body")
    assert budget.check("review") == 280


def test_active_stage_caps_call_and_resets_after_context():
    now = [0.0]
    budget = RuntimeBudget(clock=lambda: now[0])
    assert current_budget() is None
    assert call_remaining() is None
    with budget.activate("coordinator"):
        assert current_budget() is budget
        assert call_remaining() == 560
        assert call_remaining(40) == 40
        now[0] = 250
        assert call_remaining(100) == 100
        with budget.activate("body"):
            assert call_remaining() == 550
        assert call_remaining() == 310
    assert current_budget() is None
    assert call_remaining(100) == 100


def test_failed_work_and_elapsed_retries_use_same_budget():
    now = [0.0]
    budget = RuntimeBudget(clock=lambda: now[0])
    with pytest.raises(RuntimeError), budget.activate("coordinator"):
        now[0] += 200
        raise RuntimeError("provider failed")
    with budget.activate("coordinator"):
        assert call_remaining() == 360
        now[0] += 360
        with pytest.raises(BudgetExceeded, match="coordinator"):
            call_remaining()
    assert budget.remaining_seconds() == 640


def test_expired_total_is_clamped_and_rejected():
    budget = RuntimeBudget(consumed_seconds=1250)
    assert budget.remaining_seconds() == 0
    assert budget.snapshot()["remaining_seconds"] == 0
    with pytest.raises(BudgetExceeded, match="runtime budget"):
        budget.check()


def test_explicit_worker_helpers_propagate_budget_and_stage():
    budget = RuntimeBudget(consumed_seconds=100, clock=lambda: 0)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with budget.activate("review"):
            bound = bind_runtime_context(lambda value: (current_budget(), call_remaining(), value), "thread")
            submitted = submit_with_context(executor, lambda: (current_budget(), call_remaining()))
        assert executor.submit(bound).result() == (budget, 980, "thread")
        assert submitted.result() == (budget, 980)
        assert executor.submit(current_budget).result() is None


def test_long_report_coordination_can_use_seven_minutes_without_extending_total_budget():
    budget = RuntimeBudget(total_seconds=900, consumed_seconds=305, clock=lambda: 0)
    assert budget.stage_remaining_seconds('coordinator') == 115
    assert budget.remaining_seconds() == 595
    assert budget.stage_remaining_seconds('body') == 295


def test_expensive_initial_retrieval_keeps_time_for_report_scope_within_twenty_minutes():
    budget=RuntimeBudget(consumed_seconds=361,clock=lambda:0)
    assert budget.stage_remaining_seconds('coordinator') == 199
    assert budget.remaining_seconds() == 839
    assert budget.stage_remaining_seconds('body') == 439


@pytest.mark.parametrize('snapshot', [{}, {'total_seconds': 1200}, {'total_seconds': 1800}])
def test_production_budget_defaults_and_caps_at_twenty_minutes(snapshot):
    from report_generation.runtime_budget import budgeted_stage

    @budgeted_stage('export')
    def export():
        return {'status': 'success'}

    result = export(runtime_budget=snapshot)
    assert result['runtime_budget']['total_seconds'] == 1200


def test_production_stream_restores_elapsed_time_with_twenty_minute_budget():
    from report_generation.runtime_budget import budgeted_stage

    @budgeted_stage('review')
    def review():
        yield {'event': 'completed', 'status': 'success'}

    result = list(review(runtime_budget={'total_seconds': 1200, 'consumed_seconds': 950}))
    assert result[-1]['status'] == 'success'
    assert result[-1]['runtime_budget']['total_seconds'] == 1200
    assert result[-1]['runtime_budget']['consumed_seconds'] >= 950
