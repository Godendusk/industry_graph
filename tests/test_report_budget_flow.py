"""The production stage boundary carries time across separate requests."""
from report_generation import runtime_budget as runtime
import time


def test_sync_stage_restores_consumed_time_and_exposes_snapshot():
    @runtime.budgeted_stage('body')
    def body():
        assert runtime.current_budget() is not None
        return {'status': 'success'}

    result = body(runtime_budget={'total_seconds': 900, 'consumed_seconds': 200})
    assert result['runtime_budget']['consumed_seconds'] >= 200
    assert runtime.current_budget() is None


def test_expired_stage_cannot_start_call_or_look_completed():
    calls = []
    @runtime.budgeted_stage('body')
    def body():
        calls.append(True)
        return {'status': 'success'}

    result = body(runtime_budget={'consumed_seconds': 900})
    assert not calls
    assert result['status'] == 'error'
    assert result['delivery_status'] == 'incomplete'


def test_stream_restores_context_and_snapshots_each_result():
    @runtime.budgeted_stage('coordinator')
    def coordinate():
        yield {'event': 'started'}
        assert runtime.current_budget() is not None
        yield {'event': 'completed', 'status': 'success'}

    result = list(coordinate(runtime_budget={'consumed_seconds': 80}))
    assert result[-1]['runtime_budget']['consumed_seconds'] >= 80
    assert runtime.current_budget() is None


def test_no_budget_argument_keeps_existing_direct_call_contract():
    @runtime.budgeted_stage('body')
    def body():
        return {'status': 'success'}
    assert body() == {'status': 'success'}


def test_blocked_local_work_returns_at_deadline():
    @runtime.budgeted_stage('coordinator')
    def blocked():
        time.sleep(.3)
        return {'status': 'success'}
    start = time.monotonic()
    result = blocked(runtime_budget={'total_seconds': .09})
    assert time.monotonic() - start < .2
    assert result['delivery_status'] == 'incomplete'


def test_stream_worker_receives_report_context():
    from report_generation import body_agent
    from unittest.mock import patch
    contexts = []
    def section(**kwargs):
        contexts.append(runtime.current_budget())
        return {'outline_id': 'S1.1', 'status': 'success', 'body_text': 'text'}
    with patch.object(body_agent, 'generate_body_section', side_effect=section), \
         patch.object(body_agent, 'review_report_bodies', return_value=None):
        list(body_agent.stream_report_bodies('需求', '标题', [{'outline_id': 'S1.1'}],
                                            runtime_budget={}))
    assert contexts and all(contexts)


def test_queued_late_completion_is_not_accepted():
    now = [0.0]
    budget = runtime.RuntimeBudget(clock=lambda: now[0])
    @runtime.budgeted_stage('coordinator')
    def late():
        now[0] = 561
        yield {'event': 'completed', 'status': 'success'}
    result = list(late(runtime_budget=budget))
    assert result[-1]['event'] == 'error'
    assert result[-1]['delivery_status'] == 'incomplete'


def test_coordinator_reserves_time_for_global_scope_instead_of_per_section_planning():
    from report_generation.coordinator_agent import _build_writing_task_from_retrieval
    from report_generation.runtime_budget import RuntimeBudget
    from unittest.mock import patch
    subsection = {'outline_id': 'S1.1', 'parent_level1_id': 'L1',
                  'parent_level1_title': '比较', 'title': '业务差异'}
    budget = RuntimeBudget(consumed_seconds=520)
    with budget.activate('coordinator'), patch('report_generation.coordinator_agent.request_decision') as request:
        task, warnings = _build_writing_task_from_retrieval(subsection, {}, {}, '比较业务', '报告', [])
    request.assert_not_called()
    assert task['writing_decision']
    assert any(w.get('reason') == 'scope_time_reserved' for w in warnings)
