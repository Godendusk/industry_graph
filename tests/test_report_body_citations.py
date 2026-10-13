import unittest
from unittest.mock import patch

from llm_client import LLMQueryResult
from report_generation import body_agent


def _task(outline_id, evidence_blocks):
    return {
        "outline_id": outline_id,
        "parent_level1_id": outline_id.split(".")[0],
        "parent_level1_title": f"一级标题 {outline_id.split('.')[0]}",
        "title": f"小节 {outline_id}",
        "writing_system_prompt": "只写当前小节正文。",
        "graph_retrieval": {"status": "error", "graph_context_text": ""},
        "external_rag_retrieval": {
            "status": "success",
            "rag_context_text": "[C1]\n政策材料",
            "evidence_blocks": evidence_blocks,
        },
    }


class ReportBodyCitationsTest(unittest.TestCase):
    def test_budget_omission_is_retained_as_section_warning(self):
        context = {'text':'相关已写表述', 'omitted_fact_count':2}
        with patch.object(body_agent, 'build_prior_context', return_value=context), \
             patch.object(body_agent.llm, 'query_result', return_value=LLMQueryResult(content='正文[C1]。', finish_reason='stop')):
            result = body_agent.generate_body_section(_task('S1.1', [{'citation_id':'C1'}]), '报告', '测试')
        assert any(w.get('omitted_fact_count') == 2 for w in result['warnings'])

    def test_body_generation_passes_prior_sections_across_level1_groups(self):
        tasks = [
            _task("S1.1", [{"citation_id": "C1", "title": "材料一"}]),
            _task("S2.1", [{"citation_id": "C2", "title": "材料二"}]),
            _task("S3.1", [{"citation_id": "C3", "title": "材料三"}]),
        ]
        prompts = []

        def query_result(**kwargs):
            if kwargs.get("extra_log_info") == "report_generation.review_agent":
                return LLMQueryResult(content='{"issues":[]}', finish_reason="stop")
            prompts.append(kwargs["user_prompt"])
            index = len(prompts)
            return LLMQueryResult(content=f"第{index}节首句。第{index}节补充。", finish_reason="stop")

        with patch.object(body_agent.llm, "query_result", side_effect=query_result):
            result = body_agent.generate_report_bodies(
                user_prompt="生成报告",
                report_title="测试报告",
                writing_tasks=tasks,
                max_workers=3,
                references=[],
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(prompts), 3)
        self.assertIn("小节 S1.1", prompts[1])
        self.assertIn("第1节首句", prompts[1])
        self.assertIn("小节 S1.1", prompts[2])
        self.assertIn("小节 S2.1", prompts[2])

    def test_failed_section_is_not_added_to_prior_report_facts(self):
        tasks = [
            _task("S1.1", [{"citation_id": "C1", "title": "材料一"}]),
            _task("S2.1", [{"citation_id": "C2", "title": "材料二"}]),
            _task("S3.1", [{"citation_id": "C3", "title": "材料三"}]),
        ]
        prompts = []

        def query_result(**kwargs):
            prompts.append(kwargs["user_prompt"])
            if "小节 S2.1" in kwargs["user_prompt"]:
                return LLMQueryResult(content="", finish_reason="length")
            return LLMQueryResult(content="成功小节正文。", finish_reason="stop")

        with patch.object(body_agent.llm, "query_result", side_effect=query_result):
            result = body_agent.generate_report_bodies(
                user_prompt="生成报告",
                report_title="测试报告",
                writing_tasks=tasks,
                max_workers=3,
                references=[],
            )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["body_sections"][1]["status"], "error")
        third_prompt = prompts[-1]
        self.assertIn("小节 S1.1", third_prompt)
        self.assertNotIn("小节 S2.1", third_prompt)

    def test_format_prior_report_facts_uses_current_evidence(self):
        prior_sections = [
            {
                "status": "success",
                "title": "前文一",
                "body_text": "首句内容。使用当前材料[C2]的事实。其他事实[C9]。",
            },
            {
                "status": "error",
                "title": "失败小节",
                "body_text": "不应出现。",
            },
        ]
        current_task = _task("S2.1", [{"citation_id": "C2", "title": "材料二"}])

        facts = body_agent._format_prior_report_facts(prior_sections, current_task)

        self.assertIn("前文一", facts)
        self.assertIn("首句内容。", facts)
        self.assertIn("使用当前材料[C2]的事实。", facts)
        self.assertNotIn("其他事实[C9]", facts)
        self.assertNotIn("失败小节", facts)

    def test_removes_unknown_marker_and_records_used_ids(self):
        evidence = [{"citation_id": "C1", "title": "政策甲"}]
        with patch.object(
            body_agent.llm,
            "query_result",
            return_value=LLMQueryResult(
                content="政策提出扩大应用范围[C1]，市场规模达到百亿元[C8]。",
                finish_reason="stop",
            ),
        ):
            result = body_agent.generate_body_section(
                writing_task=_task("S1.1", evidence),
                user_prompt="生成报告",
                report_title="测试报告",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["body_text"], "政策提出扩大应用范围[C1]，市场规模达到百亿元。")
        self.assertEqual(result["citation_ids"], ["C1"])
        self.assertEqual(result["warnings"][-1]["invalid_citation_ids"], ["C8"])

    def test_returns_only_references_used_by_successful_sections(self):
        tasks = [
            _task("S1.1", [{"citation_id": "C2", "title": "案例乙"}]),
            _task("S1.2", [{"citation_id": "C1", "title": "政策甲"}]),
        ]
        responses = [
            LLMQueryResult(content="案例说明[C2]。", finish_reason="stop"),
            LLMQueryResult(content="政策说明[C1]。", finish_reason="stop"),
        ]
        references = [
            {"citation_id": "C1", "title": "政策甲"},
            {"citation_id": "C2", "title": "案例乙"},
            {"citation_id": "C3", "title": "未使用"},
        ]
        with patch.object(body_agent.llm, "query_result", side_effect=responses):
            result = body_agent.generate_report_bodies(
                user_prompt="生成报告",
                report_title="测试报告",
                writing_tasks=tasks,
                industry="embodied",
                max_workers=1,
                references=references,
            )

        self.assertEqual([row["citation_id"] for row in result["references"]], ["C1", "C2"])


if __name__ == "__main__":
    unittest.main()


def test_cross_source_body_context_never_authorizes_prior_citation():
    current = _task('S2.1', [{'citation_id':'C17','text':'中国移动牵头成立具身智能产业联盟'}])
    current['repetition_focus_terms'] = ['中国移动', '具身智能产业联盟']
    prior = [{'outline_id':'S1.1','title':'布局','status':'success',
              'body_text':'背景。中国移动牵头成立具身智能产业联盟[C14]。'}]
    with patch.object(body_agent.llm,'query_result',return_value=LLMQueryResult(
        content='承接[C14]，新分析[C17]。',finish_reason='stop')) as query:
        result=body_agent.generate_body_section(current,'报告','测试',prior)
    assert '中国移动牵头成立具身智能产业联盟[C14]' in query.call_args.kwargs['user_prompt']
    assert '允许小节变短' in query.call_args.kwargs['system_prompt']
    assert '待验证条件' in query.call_args.kwargs['system_prompt']
    assert '同一一级标题下已有前文' not in query.call_args.kwargs['user_prompt']
    assert result['citation_ids'] == ['C17']
    assert result['repetition_focus_terms'] == ['中国移动','具身智能产业联盟']
