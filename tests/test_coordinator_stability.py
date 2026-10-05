import threading
import unittest
from unittest.mock import patch

from report_generation import coordinator_agent


def _twenty_subsection_outline():
    return [
        {
            "section_type": "body",
            "level1_id": f"S{section_index}",
            "level1_title": f"一级标题{section_index}",
            "subsections": [
                {
                    "outline_id": f"S{section_index}.{subsection_index}",
                    "title": f"二级标题{section_index}-{subsection_index}",
                }
                for subsection_index in range(1, 6)
            ],
        }
        for section_index in range(1, 5)
    ]


class CoordinatorStabilityTest(unittest.TestCase):
    def test_flatten_body_subsections_preserves_outline_retrieval_fields(self):
        outline = [{
            "section_type": "body",
            "level1_id": "S1",
            "level1_title": "产业发展",
            "chapter_goal": "明确产业发展阶段",
            "content_requirements": ["市场规模", "企业布局"],
            "subsections": [{
                "outline_id": "S1.1",
                "title": "核心企业布局现状",
                "writing_focus": "分析央企与头部企业布局",
                "suggested_query": "人工智能 核心企业 布局",
            }],
        }]

        flattened = coordinator_agent._flatten_body_subsections(outline)

        self.assertEqual(flattened[0]["chapter_goal"], "明确产业发展阶段")
        self.assertEqual(flattened[0]["content_requirements"], ["市场规模", "企业布局"])
        self.assertEqual(flattened[0]["writing_focus"], "分析央企与头部企业布局")
        self.assertEqual(flattened[0]["suggested_query"], "人工智能 核心企业 布局")

    def test_enhanced_retrieval_query_includes_outline_fields_and_multi_goals(self):
        query = coordinator_agent._build_subsection_retrieval_query(
            user_prompt="分析人工智能产业",
            report_title="人工智能产业报告",
            parent_level1_title="应用落地",
            chapter_goal="回答应用落地路径",
            content_requirements=["企业案例", "政策建议"],
            subsection_title="标杆案例与推进建议",
            writing_focus="结合项目落地提出实践路径",
            suggested_query="人工智能 企业案例 项目落地 政策建议",
        )

        self.assertIn("用户需求：分析人工智能产业", query)
        self.assertIn("报告标题：人工智能产业报告", query)
        self.assertIn("当前一级标题：应用落地", query)
        self.assertIn("章节目标：回答应用落地路径", query)
        self.assertIn("内容边界：企业案例；政策建议", query)
        self.assertIn("当前二级标题：标杆案例与推进建议", query)
        self.assertIn("二级写作重点：结合项目落地提出实践路径", query)
        self.assertIn("建议检索 query：人工智能 企业案例 项目落地 政策建议", query)
        self.assertIn("政策建议、实践路径、推进措施、标杆经验和可操作对策", query)
        self.assertIn("企业案例、项目落地、应用场景、标杆实践和商业化进展", query)

    def test_legacy_outline_still_builds_compatible_retrieval_query(self):
        query = coordinator_agent._build_subsection_retrieval_query(
            user_prompt="生成报告",
            report_title="测试报告",
            parent_level1_title="产业现状",
            subsection_title="市场格局",
        )

        self.assertIn("用户需求：生成报告", query)
        self.assertIn("报告标题：测试报告", query)
        self.assertIn("当前一级标题：产业现状", query)
        self.assertIn("当前二级标题：市场格局", query)
        self.assertIn("检索目标：", query)

    def test_retrieval_calls_receive_enhanced_query_and_task_records_it(self):
        graph_queries = []
        rag_queries = []
        outline = [{
            "section_type": "body",
            "level1_id": "S1",
            "level1_title": "问题研判",
            "chapter_goal": "识别产业落地约束",
            "content_requirements": ["风险挑战", "能力短板"],
            "subsections": [{
                "outline_id": "S1.1",
                "title": "算力供给瓶颈与约束",
                "writing_focus": "分析算力成本、供给不足和落地障碍",
                "suggested_query": "人工智能 算力瓶颈 风险 约束",
            }],
        }]

        def graph(query, *, industry):
            graph_queries.append(query)
            return {"status": "success", "graph_context_text": "", "evidence_blocks": []}

        def rag(query, *, industry, top_k):
            rag_queries.append(query)
            return {"status": "success", "evidence_blocks": [], "warnings": []}

        with patch.object(coordinator_agent, "retrieve_industry_graph", side_effect=graph), patch.object(
            coordinator_agent,
            "retrieve_external_rag",
            side_effect=rag,
        ), patch.object(
            coordinator_agent.llm,
            "query",
            return_value='{"writing_system_prompt": "本地模拟的正文任务书"}',
        ):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成人工智能报告",
                report_title="人工智能产业报告",
                outline=outline,
                industry="embodied",
            )

        query = result["writing_tasks"][0]["section_retrieval_query"]
        self.assertEqual(graph_queries[0], query)
        self.assertEqual(rag_queries[0], query)
        self.assertIn("章节目标：识别产业落地约束", query)
        self.assertIn("内容边界：风险挑战；能力短板", query)
        self.assertIn("二级写作重点：分析算力成本、供给不足和落地障碍", query)
        self.assertIn("建议检索 query：人工智能 算力瓶颈 风险 约束", query)
        self.assertIn("产业瓶颈、风险挑战、能力短板、资源约束和落地障碍", query)

    def test_embodied_coordinator_flow_uses_local_boundaries_for_twenty_subsections(self):
        graph_calls = []
        rag_calls = []
        llm_calls = []
        calls_lock = threading.Lock()

        def local_graph_retrieval(query, *, industry):
            with calls_lock:
                graph_calls.append((query, industry))
            return {
                "status": "success",
                "query": query,
                "graph_context_text": "本地模拟图谱材料",
                "evidence_blocks": [],
            }

        def local_rag_retrieval(query, *, industry, top_k):
            with calls_lock:
                rag_calls.append((query, industry, top_k))
            return {
                "status": "success",
                "query": query,
                "top_k": top_k,
                "rag_context_text": "本地模拟 RAG 材料",
                "evidence_blocks": [],
                "warnings": [],
            }

        def local_llm_query(**kwargs):
            with calls_lock:
                llm_calls.append(kwargs)
            return '{"writing_system_prompt": "本地模拟的正文任务书"}'

        outline = _twenty_subsection_outline()
        expected_ids = [
            f"S{section_index}.{subsection_index}"
            for section_index in range(1, 5)
            for subsection_index in range(1, 6)
        ]
        with patch.object(
            coordinator_agent,
            "retrieve_industry_graph",
            side_effect=local_graph_retrieval,
        ), patch.object(
            coordinator_agent,
            "retrieve_external_rag",
            side_effect=local_rag_retrieval,
        ), patch.object(coordinator_agent.llm, "query", side_effect=local_llm_query):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成具身智能报告",
                report_title="具身智能报告",
                outline=outline,
                industry="embodied",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            [task["outline_id"] for task in result["writing_tasks"]], expected_ids
        )
        self.assertEqual(len(graph_calls), 20)
        self.assertTrue(all(industry == "embodied" for _, industry in graph_calls))
        self.assertEqual(len(rag_calls), 40)
        self.assertTrue(
            all(industry == "embodied" and top_k == 20 for _, industry, top_k in rag_calls)
        )
        self.assertEqual(len(llm_calls), 20)
        self.assertTrue(
            all(
                call["extra_log_info"].startswith(
                    "report_generation.coordinator_agent outline="
                )
                for call in llm_calls
            )
        )

    def test_twenty_subsections_use_three_workers_and_keep_outline_order(self):
        configured_worker_counts = []
        completion_order = []
        completion_lock = threading.Lock()
        second_task_completed = threading.Event()
        original_executor = coordinator_agent.ThreadPoolExecutor

        def generate_task(*, subsection, **_kwargs):
            outline_id = subsection["outline_id"]
            if outline_id == "S1.1":
                if not second_task_completed.wait(timeout=1):
                    self.fail("S1.1 did not receive the S1.2 completion event")
            with completion_lock:
                completion_order.append(outline_id)
            if outline_id == "S1.2":
                second_task_completed.set()
            return ({"outline_id": subsection["outline_id"], "warnings": []}, [])

        def record_executor(*args, **kwargs):
            configured_worker_counts.append(kwargs["max_workers"])
            return original_executor(*args, **kwargs)

        def build_task(*, subsection, **_kwargs):
            return ({
                "outline_id": subsection["outline_id"],
                "parent_level1_id": subsection["parent_level1_id"],
                "parent_level1_title": subsection["parent_level1_title"],
                "title": subsection["title"],
                "writing_system_prompt": "本地模拟的正文任务书",
                "warnings": [],
            }, [])

        with patch.object(coordinator_agent, "ThreadPoolExecutor", side_effect=record_executor), patch.object(
            coordinator_agent,
            "_generate_writing_task_for_subsection",
            side_effect=generate_task,
        ), patch.object(
            coordinator_agent,
            "_build_writing_task_from_retrieval",
            side_effect=build_task,
        ):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告",
                report_title="具身智能报告",
                outline=_twenty_subsection_outline(),
                industry="embodied",
            )

        self.assertEqual(configured_worker_counts, [3, 3])
        self.assertLess(
            completion_order.index("S1.2"),
            completion_order.index("S1.1"),
        )
        self.assertEqual(
            [task["outline_id"] for task in result["writing_tasks"]],
            [f"S{section_index}.{subsection_index}" for section_index in range(1, 5) for subsection_index in range(1, 6)],
        )

    def test_custom_max_workers_is_used_for_coordinator_generation(self):
        configured_worker_counts = []
        original_executor = coordinator_agent.ThreadPoolExecutor

        def record_executor(*args, **kwargs):
            configured_worker_counts.append(kwargs["max_workers"])
            return original_executor(*args, **kwargs)

        def build_task(*, subsection, **_kwargs):
            return ({
                "outline_id": subsection["outline_id"],
                "parent_level1_id": subsection["parent_level1_id"],
                "parent_level1_title": subsection["parent_level1_title"],
                "title": subsection["title"],
                "writing_system_prompt": "本地模拟的正文任务书",
                "warnings": [],
            }, [])

        with patch.object(coordinator_agent, "ThreadPoolExecutor", side_effect=record_executor), patch.object(
            coordinator_agent,
            "_generate_writing_task_for_subsection",
            side_effect=lambda *, subsection, **_kwargs: ({"outline_id": subsection["outline_id"]}, []),
        ), patch.object(
            coordinator_agent,
            "_build_writing_task_from_retrieval",
            side_effect=build_task,
        ):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告",
                report_title="具身智能报告",
                outline=_twenty_subsection_outline(),
                industry="embodied",
                max_workers=5,
            )

        self.assertEqual(configured_worker_counts, [5, 5])
        self.assertEqual(result["max_workers"], 5)

    def test_max_workers_is_capped_and_limited_by_task_count(self):
        configured_worker_counts = []
        original_executor = coordinator_agent.ThreadPoolExecutor

        def record_executor(*args, **kwargs):
            configured_worker_counts.append(kwargs["max_workers"])
            return original_executor(*args, **kwargs)

        def build_task(*, subsection, **_kwargs):
            return ({
                "outline_id": subsection["outline_id"],
                "parent_level1_id": subsection["parent_level1_id"],
                "parent_level1_title": subsection["parent_level1_title"],
                "title": subsection["title"],
                "writing_system_prompt": "本地模拟的正文任务书",
                "warnings": [],
            }, [])

        with patch.object(coordinator_agent, "ThreadPoolExecutor", side_effect=record_executor), patch.object(
            coordinator_agent,
            "_generate_writing_task_for_subsection",
            side_effect=lambda *, subsection, **_kwargs: ({"outline_id": subsection["outline_id"]}, []),
        ), patch.object(
            coordinator_agent,
            "_build_writing_task_from_retrieval",
            side_effect=build_task,
        ):
            capped = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告",
                report_title="具身智能报告",
                outline=_twenty_subsection_outline(),
                industry="embodied",
                max_workers=20,
            )
            limited = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告",
                report_title="具身智能报告",
                outline=_twenty_subsection_outline()[:1],
                industry="embodied",
                max_workers=6,
            )

        self.assertEqual(configured_worker_counts, [6, 6, 5, 5])
        self.assertEqual(capped["max_workers"], 6)
        self.assertEqual(limited["max_workers"], 5)

    def test_prompt_generation_uses_coordinator_workers_and_keeps_outline_order(self):
        prompt_order = []
        prompt_lock = threading.Lock()
        second_prompt_completed = threading.Event()

        def generate_task(*, subsection, **_kwargs):
            return ({
                "outline_id": subsection["outline_id"],
                "parent_level1_id": subsection["parent_level1_id"],
                "parent_level1_title": subsection["parent_level1_title"],
                "title": subsection["title"],
                "graph_retrieval": {"status": "skipped", "evidence_blocks": []},
                "external_rag_retrieval": {"status": "skipped", "evidence_blocks": []},
            }, [])

        def build_task(*, subsection, **_kwargs):
            outline_id = subsection["outline_id"]
            if outline_id == "S1.1":
                if not second_prompt_completed.wait(timeout=1):
                    self.fail("S1.1 did not receive the S1.2 prompt completion event")
            with prompt_lock:
                prompt_order.append(outline_id)
            if outline_id == "S1.2":
                second_prompt_completed.set()
            return ({
                "outline_id": subsection["outline_id"],
                "parent_level1_id": subsection["parent_level1_id"],
                "parent_level1_title": subsection["parent_level1_title"],
                "title": subsection["title"],
                "writing_system_prompt": "本地模拟的正文任务书",
                "warnings": [],
            }, [])

        with patch.object(
            coordinator_agent,
            "_generate_writing_task_for_subsection",
            side_effect=generate_task,
        ), patch.object(
            coordinator_agent,
            "_build_writing_task_from_retrieval",
            side_effect=build_task,
        ):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告",
                report_title="具身智能报告",
                outline=_twenty_subsection_outline(),
                industry="embodied",
                max_workers=3,
            )

        self.assertLess(
            prompt_order.index("S1.2"),
            prompt_order.index("S1.1"),
        )
        self.assertEqual(
            [task["outline_id"] for task in result["writing_tasks"]],
            [f"S{section_index}.{subsection_index}" for section_index in range(1, 5) for subsection_index in range(1, 6)],
        )

    def test_stream_started_event_reports_normalized_max_workers(self):
        first_event = next(coordinator_agent.stream_writing_tasks(
            user_prompt="生成报告",
            report_title="具身智能报告",
            outline=_twenty_subsection_outline(),
            industry="embodied",
            max_workers="bad",
        ))

        self.assertEqual(first_event["event"], "started")
        self.assertEqual(first_event["max_workers"], 3)

    def test_source_switches_skip_graph_and_external_rag_retrieval(self):
        graph_calls = []
        rag_calls = []

        with patch.object(
            coordinator_agent,
            "retrieve_industry_graph",
            side_effect=lambda *args, **kwargs: graph_calls.append((args, kwargs)),
        ), patch.object(
            coordinator_agent,
            "retrieve_external_rag",
            side_effect=lambda *args, **kwargs: rag_calls.append((args, kwargs)),
        ), patch.object(
            coordinator_agent.llm,
            "query",
            return_value='{"writing_system_prompt": "本地模拟的正文任务书"}',
        ):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成具身智能报告",
                report_title="具身智能报告",
                outline=_twenty_subsection_outline()[:1],
                industry="embodied",
                use_graph=False,
                use_external_rag=False,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(graph_calls, [])
        self.assertEqual(rag_calls, [])
        self.assertTrue(all(
            task["graph_retrieval"]["status"] == "skipped"
            and task["external_rag_retrieval"]["status"] == "skipped"
            for task in result["writing_tasks"]
        ))

    def test_unhandled_worker_errors_return_ordered_fallback_tasks_and_warnings(self):
        with patch.object(
            coordinator_agent,
            "_generate_writing_task_for_subsection",
            side_effect=RuntimeError("mocked worker failure"),
        ):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告",
                report_title="具身智能报告",
                outline=_twenty_subsection_outline(),
                industry="embodied",
            )

        expected_ids = [
            f"S{section_index}.{subsection_index}"
            for section_index in range(1, 5)
            for subsection_index in range(1, 6)
        ]
        self.assertEqual([task["outline_id"] for task in result["writing_tasks"]], expected_ids)
        self.assertEqual(len(result["warnings"]), 20)
        for task, warning in zip(result["writing_tasks"], result["warnings"]):
            self.assertEqual(task["warnings"], [warning])
            self.assertEqual(warning["stage"], "coordinator_task_generation")
            self.assertIn("mocked worker failure", warning["message"])

    def test_stream_writing_tasks_emits_per_task_progress_and_completion(self):
        def generate_task(*, subsection, **_kwargs):
            return (
                {
                    "outline_id": subsection["outline_id"],
                    "parent_level1_title": subsection["parent_level1_title"],
                    "title": subsection["title"],
                    "external_rag_retrieval": {"evidence_blocks": []},
                    "warnings": [],
                },
                [],
            )

        with patch.object(
            coordinator_agent,
            "_generate_writing_task_for_subsection",
            side_effect=generate_task,
        ), patch.object(
            coordinator_agent,
            "_build_writing_task_from_retrieval",
            side_effect=lambda *, subsection, **_kwargs: ({
                "outline_id": subsection["outline_id"],
                "parent_level1_id": subsection["parent_level1_id"],
                "parent_level1_title": subsection["parent_level1_title"],
                "title": subsection["title"],
                "writing_system_prompt": "本地模拟的正文任务书",
                "warnings": [],
            }, []),
        ):
            events = list(coordinator_agent.stream_writing_tasks(
                user_prompt="生成报告",
                report_title="具身智能报告",
                outline=_twenty_subsection_outline()[:1],
                industry="embodied",
            ))

        event_names = [event["event"] for event in events]
        self.assertEqual(events[0]["event"], "started")
        self.assertIn("task_started", event_names)
        self.assertIn("task_completed", event_names)
        self.assertEqual(events[-1]["event"], "completed")
        self.assertEqual(events[-1]["status"], "success")
        self.assertEqual(len(events[-1]["writing_tasks"]), 5)


if __name__ == "__main__":
    unittest.main()
