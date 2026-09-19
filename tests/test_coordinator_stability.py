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
        self.assertEqual(len(rag_calls), 20)
        self.assertTrue(
            all(industry == "embodied" and top_k == 10 for _, industry, top_k in rag_calls)
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

        with patch.object(coordinator_agent, "ThreadPoolExecutor", side_effect=record_executor), patch.object(
            coordinator_agent,
            "_generate_writing_task_for_subsection",
            side_effect=generate_task,
        ):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告",
                report_title="具身智能报告",
                outline=_twenty_subsection_outline(),
                industry="embodied",
            )

        self.assertEqual(configured_worker_counts, [3])
        self.assertLess(
            completion_order.index("S1.2"),
            completion_order.index("S1.1"),
        )
        self.assertEqual(
            [task["outline_id"] for task in result["writing_tasks"]],
            [f"S{section_index}.{subsection_index}" for section_index in range(1, 5) for subsection_index in range(1, 6)],
        )

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


if __name__ == "__main__":
    unittest.main()
