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
        return_value=LLMQueryResult(
            content="产业形成了应用基础，并面临商业化验证要求。",
            finish_reason="stop",
        ),
    ) as query:
        result = generate_report_summary(**_inputs())

    assert result["status"] == "success"
    request = query.call_args.kwargs
    assert request["reasoning_effort"] == "high"
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request["max_tokens"] >= 12000


def test_summary_retries_once_with_more_budget_after_reasoning_exhausts_output():
    with patch(
        "report_generation.summary_agent.llm.query_result",
        side_effect=[
            LLMQueryResult(content="", finish_reason="length"),
            LLMQueryResult(content="产业形成了应用基础，并面临商业化验证要求。", finish_reason="stop"),
        ],
    ) as query:
        result = generate_report_summary(**_inputs())

    assert result["status"] == "success"
    assert query.call_count == 2
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
