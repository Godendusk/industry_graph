import json
from types import SimpleNamespace

import pytest
from scripts.evaluate_agentic_report import CallRecorder


def test_trace_keeps_exact_request_response_and_does_not_record_client_secrets(tmp_path):
    result = SimpleNamespace(content='{"claim_checks": []}', error_message='',
                             finish_reason='stop', prompt_tokens=12, completion_tokens=4)
    client = SimpleNamespace(model='test', api_key='private-key', query_result=lambda **kw: result)
    with CallRecorder(client, trace_dir=tmp_path) as recorder:
        recorder.stage = 'review'
        assert client.query_result(user_prompt='原文', system_prompt='核对', max_tokens=6000) is result
    files = list(tmp_path.glob('*.json'))
    assert len(files) == 1
    saved = json.loads(files[0].read_text())
    assert saved['request'] == {'user_prompt': '原文', 'system_prompt': '核对', 'max_tokens': 6000}
    assert saved['response']['content'] == result.content
    assert saved['stage'] == 'review'
    assert 'private-key' not in files[0].read_text()
    assert recorder.summary()['records'][0]['trace_file'] == files[0].name


def test_trace_records_failure_and_preserves_original_exception(tmp_path):
    def fail(*args, **kwargs):
        raise ValueError('broken response')
    client = SimpleNamespace(model='test', query_result=fail)
    with CallRecorder(client, trace_dir=tmp_path) as recorder:
        with pytest.raises(ValueError, match='broken response'):
            client.query_result('原文', '核对')
    saved = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert saved['request']['user_prompt'] == '原文'
    assert saved['error_type'] == 'ValueError'
    assert saved['status'] == 'failed'


def test_review_retains_concrete_patch_rejection_reason(monkeypatch):
    from report_generation import review_agent
    def query(text, prompt, tokens):
        payload = json.loads(text)
        if 'claim_verification' in payload:
            section = payload['claim_verification'][0]
            return {'claim_checks': [{'claim_id': section['claims'][0]['claim_id'],
                'status': 'conflicting', 'reason': '原文是计划',
                'supports': [{'evidence_id': section['evidence'][0]['evidence_id'], 'quote': '甲公司计划投产。'}]}]}
        if 'editable_spans' in payload:
            return {'outline_id': 'S1.1', 'patches': [{'span_index': 0, 'replacement': '甲公司计划投产。[C999]'}]}
        return {'issues': []}
    monkeypatch.setattr(review_agent, '_query', query)
    result = review_agent.review_report_bodies(body_sections=[{'outline_id': 'S1.1', 'status': 'success',
        'body_text': '甲公司已经投产。[C1]', 'external_evidence_blocks': [{'citation_id': 'C1', 'text': '甲公司计划投产。'}]}],
        writing_tasks=[], report_title='报告', user_prompt='', references=[])
    warning = next(w for w in result['warnings'] if w['reason'] == 'edit_failed')
    assert warning['detail'] == 'invalid_citation'
    assert result['review']['edit_attempts'][0]['status'] == 'rejected'


def test_formal_report_evaluation_can_rely_on_runtime_instead_of_artificial_call_cap():
    result = SimpleNamespace(content='{}', error_message='', finish_reason='stop', prompt_tokens=1, completion_tokens=1)
    client = SimpleNamespace(model='test', query_result=lambda **kw: result)
    with CallRecorder(client, max_calls=None) as recorder:
        for _ in range(181):
            client.query_result(user_prompt='内容')
    assert recorder.summary()['calls'] == 181
    assert not recorder.exhausted


def test_repetition_rejection_retains_span_failure_instead_of_generic_notice(monkeypatch):
    from report_generation import review_agent
    def query(text, prompt, tokens):
        return {'issues': [{'reason': '重复', 'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': '不存在的摘录'}],
            'edits': [{'outline_id': 'S2.1', 'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '独有分析。'}],
                'instruction': '压缩', 'preserve_paragraph_ids': []}]}]}
    monkeypatch.setattr(review_agent, '_query', query)
    result = review_agent.review_report_bodies(body_sections=[{'outline_id': oid,'status': 'success','body_text': '独有分析。'}
        for oid in ['S1.1','S2.1']], writing_tasks=[],report_title='报告',user_prompt='',references=[])
    warning=next(w for w in result['warnings'] if w['reason']=='check_failed')
    assert 'nonunique_span' in warning['detail']
