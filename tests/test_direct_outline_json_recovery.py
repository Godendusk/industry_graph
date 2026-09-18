import unittest
from unittest.mock import patch

from report_generation.outline_agent import generate_report_outline


VALID_OUTLINE = """{
  "chapters": [
    {"level1_title": "产业范围", "chapter_goal": "明确研究对象", "content_requirements": ["上市公司"], "subsections": [{"title": "产业链范围", "writing_focus": "界定范围", "suggested_query": "具身智能产业链"}, {"title": "样本筛选", "writing_focus": "说明标准", "suggested_query": "具身智能上市公司"}]},
    {"level1_title": "企业表现", "chapter_goal": "分析企业", "content_requirements": ["业务布局"], "subsections": [{"title": "业务归类", "writing_focus": "分类企业", "suggested_query": "具身智能业务"}, {"title": "经营进展", "writing_focus": "分析进展", "suggested_query": "具身智能订单"}]},
    {"level1_title": "股价波动", "chapter_goal": "分析市场表现", "content_requirements": ["交易数据"], "subsections": [{"title": "波动区间", "writing_focus": "统计波动", "suggested_query": "具身智能股价"}, {"title": "事件影响", "writing_focus": "关联事件", "suggested_query": "具身智能产业事件"}]}
  ]
}"""


class DirectOutlineJsonRecoveryTest(unittest.TestCase):
    def test_retries_once_with_concise_json_when_initial_output_is_invalid(self):
        with patch(
            "report_generation.outline_agent.llm.query",
            side_effect=['{"chapters": [{"level1_title": "未完成"', VALID_OUTLINE],
        ) as query:
            result = generate_report_outline(
                title="具身智能产业报告",
                user_requirement="分析具身智能上市公司与股价波动",
                industry="embodied",
                industry_confirmed=True,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["outline"]), 3)
        self.assertEqual(query.call_count, 2)
        self.assertEqual(query.call_args_list[1].kwargs["max_tokens"], 3000)
        self.assertIn("重新生成", query.call_args_list[1].kwargs["user_prompt"])
