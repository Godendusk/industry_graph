import unittest
from unittest.mock import patch

from report_generation import coordinator_agent


class ReportCoordinatorCitationsTest(unittest.TestCase):
    def test_registers_sources_in_outline_order_and_rebuilds_context(self):
        outline = [{
            "section_type": "body",
            "level1_id": "S1",
            "level1_title": "现状",
            "subsections": [
                {"outline_id": "S1.1", "title": "政策"},
                {"outline_id": "S1.2", "title": "案例"},
            ],
        }]

        def task_for_subsection(*, subsection, **_kwargs):
            blocks = [{
                "library": "policy" if subsection["outline_id"] == "S1.1" else "company_case",
                "material_id": "m1" if subsection["outline_id"] == "S1.1" else "m2",
                "vector_id": f"v-{subsection['outline_id']}",
                "title": "政策甲" if subsection["outline_id"] == "S1.1" else "案例乙",
                "text": "证据片段",
            }]
            if subsection["outline_id"] == "S1.2":
                blocks.insert(0, {
                    "library": "policy",
                    "material_id": "m1",
                    "vector_id": "v-S1.2-policy",
                    "title": "政策甲",
                    "text": "第二个片段",
                })
            return ({
                "outline_id": subsection["outline_id"],
                "parent_level1_id": subsection["parent_level1_id"],
                "parent_level1_title": subsection["parent_level1_title"],
                "title": subsection["title"],
                "external_rag_retrieval": {
                    "status": "success",
                    "evidence_blocks": blocks,
                    "rag_context_text": "旧上下文",
                },
                "writing_system_prompt": "prompt",
                "warnings": [],
            }, [])

        def retrieval_for_subsection(*, subsection, **kwargs):
            task, warnings = task_for_subsection(subsection=subsection, **kwargs)
            return ({
                "outline_id": task["outline_id"],
                "parent_level1_id": task["parent_level1_id"],
                "parent_level1_title": task["parent_level1_title"],
                "title": task["title"],
                "section_retrieval_query": "q",
                "graph_retrieval": {"status": "skipped", "graph_context_text": ""},
                "external_rag_retrieval": task["external_rag_retrieval"],
            }, warnings)

        with patch.object(coordinator_agent, "_retrieve_candidates_for_subsection", side_effect=retrieval_for_subsection):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告",
                report_title="测试报告",
                outline=outline,
                industry="embodied",
            )

        tasks = result["writing_tasks"]
        self.assertEqual(tasks[0]["external_rag_retrieval"]["evidence_blocks"][0]["citation_id"], "C1")
        self.assertEqual(
            [row["citation_id"] for row in tasks[1]["external_rag_retrieval"]["evidence_blocks"]],
            ["C2", "C1"],
        )
        self.assertEqual([row["citation_id"] for row in result["references"]], ["C1", "C2"])
        self.assertIn("[C1]", tasks[0]["external_rag_retrieval"]["rag_context_text"])
        self.assertIn("[C2]", tasks[1]["external_rag_retrieval"]["rag_context_text"])


    def test_task_prompt_uses_allocated_materials_before_prompt_generation(self):
        outline = [{
            "section_type": "body", "level1_id": "S1", "level1_title": "现状",
            "subsections": [
                {"outline_id": "S1.1", "title": "政策"},
                {"outline_id": "S1.2", "title": "案例"},
            ],
        }]

        def retrieval_for(subsection):
            blocks = []
            if subsection["outline_id"] == "S1.1":
                blocks = [
                    {"library": "policy", "material_id": "m1", "vector_id": "v1", "rank": 1, "title": "甲", "text": "甲"},
                    {"library": "policy", "material_id": "m2", "vector_id": "v2", "rank": 2, "title": "乙", "text": "乙"},
                ]
            else:
                blocks = [
                    {"library": "policy", "material_id": "m1", "vector_id": "v3", "rank": 1, "title": "甲", "text": "甲2"},
                    {"library": "policy", "material_id": "m3", "vector_id": "v4", "rank": 2, "title": "丙", "text": "丙"},
                ]
            return ({
                "section_retrieval_query": "q",
                "graph_retrieval": {"status": "skipped", "graph_context_text": ""},
                "external_rag_retrieval": {"status": "success", "evidence_blocks": blocks},
            }, [])

        with patch.object(coordinator_agent, "_retrieve_candidates_for_subsection", side_effect=[retrieval_for({"outline_id": "S1.1"}), retrieval_for({"outline_id": "S1.2"})]), \
             patch.object(coordinator_agent, "_generate_writing_system_prompt", return_value={"status": "success", "writing_system_prompt": "prompt"}) as prompt:
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告", report_title="测试报告", outline=outline,
                industry="embodied", top_k=2,
            )

        self.assertEqual(result["status"], "success")
        second_blocks = result["writing_tasks"][1]["external_rag_retrieval"]["evidence_blocks"]
        self.assertEqual([row["material_id"] for row in second_blocks], ["m3", "m1"])
        prompt_contexts = [call.kwargs["rag_context_text"] for call in prompt.call_args_list]
        self.assertIn("[C", prompt_contexts[0])
        self.assertIn("丙", prompt_contexts[1])
        self.assertNotIn("乙", prompt_contexts[1])

    def test_focused_retry_backend_warning_is_emitted_once(self):
        subsection = {
            "outline_id": "S1.1",
            "parent_level1_title": "现状",
            "title": "政策",
        }
        retrieval = {
            "status": "success",
            "evidence_blocks": [
                {"library": "policy", "material_id": "m1", "vector_id": "v1", "text": "甲"},
            ],
        }
        warnings = []
        task_warnings = []
        backend_warning = {"outline_id": "S1.1", "stage": "external_rag_retrieval", "code": "x", "message": "backend warning"}

        def retry(*, warnings, task_warnings, **_kwargs):
            warnings.append(backend_warning)
            task_warnings.append(backend_warning)
            return {
                "status": "success",
                "evidence_blocks": [
                    {"library": "policy", "material_id": "m2", "vector_id": "v2", "text": "乙"},
                ],
                "warnings": [backend_warning],
            }

        with patch.object(coordinator_agent, "_retrieve_external_rag_for_subsection", side_effect=retry):
            coordinator_agent._expand_external_candidates_if_needed(
                external_rag_retrieval=retrieval,
                query="q",
                subsection=subsection,
                industry="embodied",
                candidate_top_k=20,
                warnings=warnings,
                task_warnings=task_warnings,
            )

        self.assertEqual([item["message"] for item in warnings], ["backend warning"])
        self.assertEqual([item["message"] for item in task_warnings], ["backend warning"])

    def test_focused_retry_success_clears_initial_error_status(self):
        subsection = {"outline_id": "S1.1", "parent_level1_title": "现状", "title": "政策"}
        retrieval = {"status": "error", "message": "initial unavailable", "evidence_blocks": []}
        with patch.object(
            coordinator_agent,
            "_retrieve_external_rag_for_subsection",
            return_value={
                "status": "success",
                "retrieval_version": "retry-v1",
                "evidence_blocks": [{"library": "policy", "material_id": "m2", "vector_id": "v2", "text": "乙"}],
                "warnings": [],
            },
        ):
            coordinator_agent._expand_external_candidates_if_needed(
                external_rag_retrieval=retrieval,
                query="q",
                subsection=subsection,
                industry="embodied",
                candidate_top_k=20,
                warnings=[],
                task_warnings=[],
            )
        self.assertEqual(retrieval["status"], "success")
        self.assertEqual(retrieval["retrieval_version"], "retry-v1")
        self.assertEqual(retrieval["evidence_blocks"][0]["material_id"], "m2")

    def test_stream_completion_uses_same_allocated_tasks_and_references(self):
        outline = [{
            "section_type": "body", "level1_id": "S1", "level1_title": "现状",
            "subsections": [{"outline_id": "S1.1", "title": "政策"}],
        }]
        retrieval = ({
            "section_retrieval_query": "q",
            "graph_retrieval": {"status": "skipped", "graph_context_text": ""},
            "external_rag_retrieval": {"status": "success", "evidence_blocks": [
                {"library": "policy", "material_id": "m1", "vector_id": "v1", "title": "甲", "text": "甲"},
            ]},
        }, [])
        kwargs = dict(user_prompt="生成报告", report_title="测试报告", outline=outline, industry="embodied")
        with patch.object(coordinator_agent, "_retrieve_candidates_for_subsection", return_value=retrieval), \
             patch.object(coordinator_agent, "_generate_writing_system_prompt", return_value={"status": "success", "writing_system_prompt": "prompt"}):
            ordinary = coordinator_agent.generate_writing_tasks(**kwargs)
            streamed = list(coordinator_agent.stream_writing_tasks(**kwargs))

        completed = streamed[-1]
        self.assertEqual(completed["event"], "completed")
        self.assertEqual(completed["writing_tasks"], ordinary["writing_tasks"])
        self.assertEqual(completed["references"], ordinary["references"])


if __name__ == "__main__":
    unittest.main()
