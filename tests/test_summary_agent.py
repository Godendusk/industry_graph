from unittest.mock import patch

from llm_client import LLMQueryResult
from report_generation.summary_agent import generate_report_summary


def _inputs():
    return {
        "report_title": "测试产业报告",
        "outline": [{
            "section_type": "body",
            "level1_id": "S1",
            "level1_title": "产业现状",
            "subsections": [{"outline_id": "S1.1", "title": "发展情况"}],
        }],
        "body_sections": [{
            "outline_id": "S1.1",
            "body_text": "产业已经形成若干应用场景，仍需验证商业化能力。",
        }],
        "industry": "ai",
    }


def test_summary_keeps_reasoning_and_reserves_budget_for_visible_abstract():
    with patch(
        "report_generation.summary_agent.llm.query_result",
        side_effect=[
            LLMQueryResult(content="产业形成了应用基础，并面临商业化验证要求。", finish_reason="stop"),
            LLMQueryResult(content='{"issues": []}', finish_reason="stop"),
        ],
    ) as query:
        result = generate_report_summary(**_inputs())

    assert result["status"] == "success"
    request = query.call_args_list[0].kwargs
    assert request["reasoning_effort"] == "high"
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request["max_tokens"] >= 12000


def test_summary_retries_once_with_more_budget_after_reasoning_exhausts_output():
    with patch(
        "report_generation.summary_agent.llm.query_result",
        side_effect=[
            LLMQueryResult(content="", finish_reason="length"),
            LLMQueryResult(content="产业形成了应用基础，并面临商业化验证要求。", finish_reason="stop"),
            LLMQueryResult(content='{"issues": []}', finish_reason="stop"),
        ],
    ) as query:
        result = generate_report_summary(**_inputs())

    assert result["status"] == "success"
    assert query.call_count == 3
    assert query.call_args_list[1].kwargs["max_tokens"] > query.call_args_list[0].kwargs["max_tokens"]
    assert query.call_args_list[1].kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_summary_rejects_truncated_retry_instead_of_exporting_partial_abstract():
    with patch(
        'report_generation.summary_agent.llm.query_result',
        side_effect=[
            LLMQueryResult(content='', finish_reason='length'),
            LLMQueryResult(content='尚未完成的摘要', finish_reason='length'),
        ],
    ) as query:
        result = generate_report_summary(**_inputs())
    assert query.call_count == 2
    assert result['status'] == 'error'
    assert result['abstract_text'] == ''
    assert 'length' in result['message']


def test_summary_consistency_warning_is_returned_without_discarding_abstract():
    with patch(
        'report_generation.summary_agent.llm.query_result',
        side_effect=[
            LLMQueryResult(content='摘要加入了正文没有的结论。', finish_reason='stop'),
            LLMQueryResult(content='{"issues": [{"reason": "摘要新增正文未支持的结论"}]}', finish_reason='stop'),
        ],
    ):
        result = generate_report_summary(**_inputs())
    assert result['status'] == 'success'
    assert result['abstract_text']
    assert result['summary_review']['status'] == 'partial'
    assert result['summary_review']['issue_count'] == 1


def test_summary_applies_consistency_correction_with_deep_thinking():
    with patch('report_generation.summary_agent.llm.query_result', side_effect=[
        LLMQueryResult(content='数据治理尚不健全。', finish_reason='stop'),
        LLMQueryResult(content='{"issues":[{"reason":"条件被改写为缺陷"}],"corrected_abstract_text":"数据治理是能力转化所需条件，当前成效仍待验证。"}', finish_reason='stop'),
    ]) as query:
        result = generate_report_summary(**_inputs())
    assert result['abstract_text'] == '数据治理是能力转化所需条件，当前成效仍待验证。'
    assert result['summary_review']['changed'] is True
    assert query.call_args.kwargs['extra_body'] == {'thinking': {'type': 'enabled'}}


def test_summary_review_failure_keeps_generated_abstract_and_final_note():
    with patch('report_generation.summary_agent.llm.query_result', side_effect=[
        LLMQueryResult(content='可保留摘要。', finish_reason='stop'),
        LLMQueryResult(content='', finish_reason='length'),
    ]):
        result = generate_report_summary(**_inputs())
    assert result['abstract_text'] == '可保留摘要。'
    assert result['summary_review']['status'] == 'failed'
    assert result['adjustment_notes']


def test_summary_review_retries_truncated_thinking_before_applying_correction():
    with patch('report_generation.summary_agent.llm.query_result', side_effect=[
        LLMQueryResult(content='商业化能力已验证。', finish_reason='stop'),
        LLMQueryResult(content='', finish_reason='length'),
        LLMQueryResult(content='{"issues":[{"reason":"将待验证写成已验证"}],"corrected_abstract_text":"商业化能力仍需验证。"}', finish_reason='stop'),
    ]) as query:
        result = generate_report_summary(**_inputs())
    assert result['abstract_text'] == '商业化能力仍需验证。'
    assert result['summary_review']['status'] == 'completed'
    first, retry = [call.kwargs for call in query.call_args_list[1:]]
    assert retry['max_tokens'] > first['max_tokens']
    assert retry['user_prompt'] == first['user_prompt']
    assert retry['reasoning_effort'] == 'high'
    assert retry['extra_body'] == {'thinking': {'type': 'enabled'}}


def test_summary_review_stops_after_one_budget_retry_and_keeps_original():
    with patch('report_generation.summary_agent.llm.query_result', side_effect=[
        LLMQueryResult(content='保留这份摘要。', finish_reason='stop'),
        LLMQueryResult(content='', finish_reason='length'),
        LLMQueryResult(content='{"issues":[', finish_reason='length'),
    ]) as query:
        result = generate_report_summary(**_inputs())
    assert query.call_count == 3
    assert result['abstract_text'] == '保留这份摘要。'
    assert result['summary_review']['status'] == 'failed'
    assert any('核对未完成' in note['reason'] for note in result['adjustment_notes'])


def test_summary_review_does_not_retry_connection_errors():
    with patch('report_generation.summary_agent.llm.query_result', side_effect=[
        LLMQueryResult(content='保留这份摘要。', finish_reason='stop'),
        LLMQueryResult(error_message='Request timed out.'),
    ]) as query:
        result = generate_report_summary(**_inputs())
    assert query.call_count == 2
    assert result['abstract_text'] == '保留这份摘要。'
    assert result['summary_review']['status'] == 'failed'


def test_summary_correction_does_not_export_source_markers():
    with patch('report_generation.summary_agent.llm.query_result', side_effect=[
        LLMQueryResult(content='原摘要。', finish_reason='stop'),
        LLMQueryResult(content='{"issues":[{"reason":"范围限定遗漏"}],"corrected_abstract_text":"仅适用于所列样本。[C1]"}', finish_reason='stop'),
    ]):
        result = generate_report_summary(**_inputs())
    assert result['abstract_text'] == '仅适用于所列样本。'
