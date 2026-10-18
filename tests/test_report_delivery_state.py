from report_generation import delivery


def test_partial_body_never_becomes_completed():
    state = delivery.delivery_state([{'status': 'success', 'body_text': 'text'},
                                     {'status': 'error', 'body_text': ''}],
                                    {'status': 'completed'}, {'status': 'completed'})
    assert state['delivery_status'] == 'incomplete'


def test_successful_generation_is_not_successful_review():
    state = delivery.delivery_state([{'status': 'success', 'body_text': 'text'}],
                                    {'status': 'failed'}, {'status': 'completed'})
    assert state['delivery_status'] == 'incomplete'


def test_brief_type_does_not_mean_failed_execution():
    state = delivery.delivery_state([{'status': 'success', 'body_text': 'text'}],
                                    {'status': 'completed'}, {'status': 'completed'},
                                    {'deliverable_type': 'brief', 'status': 'completed'})
    assert state == {'delivery_status': 'completed', 'deliverable_type': 'brief',
                     'delivery_reasons': []}


def test_unfinished_summary_and_scope_cannot_be_hidden():
    state = delivery.delivery_state([{'status': 'success', 'body_text': 'text'}],
                                    {'status': 'completed'}, {'status': 'failed'},
                                    {'status': 'failed'})
    assert state['delivery_status'] == 'incomplete'
    assert len(state['delivery_reasons']) == 2


def test_body_only_success_cannot_certify_whole_delivery():
    state = delivery.delivery_state([{'status': 'success', 'body_text': 'text'}],
                                    {'status': 'completed'})
    assert state['delivery_status'] == 'incomplete'


def test_manual_body_edit_cannot_reuse_old_review_after_new_summary():
    state = delivery.delivery_state([{'status': 'success', 'body_text': 'new',
                                      'claim_verification': {'body_text': 'old', 'invalidated': True}}],
                                    {'status': 'completed'}, {'status': 'completed'})
    assert state['delivery_status'] == 'incomplete'


def test_unvalidated_scope_does_not_expand_original_outline():
    from report_generation import body_agent
    from unittest.mock import patch
    tasks = [{'outline_id': 'S1.1', 'report_scope': {'status': 'incomplete'}}]
    with patch.object(body_agent, 'generate_body_section') as call:
        result = body_agent.generate_report_bodies('研究', '原题目', tasks)
        events = list(body_agent.stream_report_bodies('研究', '原题目', tasks))
    assert not call.called
    assert result['status'] == 'error'
    assert events[-1]['event'] == 'error'
