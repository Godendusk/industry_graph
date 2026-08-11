import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from retrieval_core import RetrievalCandidate, RetrievalResult
from report_generation.external_rag.report_adapter import (
    INDUSTRY_DICTIONARY_VERSION,
    LibraryRoute,
    build_rag_context_text,
    build_report_query,
    retrieve_with_soft_routing,
    route_libraries,
    to_evidence_blocks,
)


ALL_LIBRARIES = {
    "policy", "speech", "expert_view", "company_case", "research_report"
}


def candidate(chunk_id, text=None, **overrides):
    values = {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "text": text if text is not None else f"text-{chunk_id}",
        "metadata": {},
    }
    values.update(overrides)
    return RetrievalCandidate(**values)


def result(query, rows=(), status="success", warnings=()):
    return RetrievalResult(
        status=status, query=query, candidates=tuple(rows), warnings=tuple(warnings)
    )


class ReportQueryTests(unittest.TestCase):
    def test_focuses_labeled_fields_by_priority_and_drops_generic_tail(self):
        raw = """用户需求：分析国资央企数字化转型
        报告标题: 人工智能产业发展报告
        当前一级标题：算力基础设施
        当前二级标题: 央企智算中心布局
        检索目标：检索产业链结构、竞争格局、问题、政策、案例和建议依据"""

        focused = build_report_query(raw)

        self.assertTrue(focused.semantic_query.startswith("央企智算中心布局"))
        self.assertIn("算力基础设施", focused.semantic_query)
        self.assertIn("人工智能产业发展报告", focused.semantic_query)
        self.assertIn("分析国资央企数字化转型", focused.semantic_query)
        self.assertNotIn("问题、政策、案例和建议", focused.semantic_query)
        self.assertEqual(focused.current_subsection, "央企智算中心布局")
        self.assertEqual(focused.dictionary_version, INDUSTRY_DICTIONARY_VERSION)
        with self.assertRaises(Exception):
            focused.current_subsection = "changed"

    def test_budget_uses_injected_counter_and_preserves_higher_priority_text(self):
        raw = """用户需求：UUUU
        报告标题：TTTT
        当前一级标题：PPPP
        当前二级标题：SSSSSS"""

        focused = build_report_query(raw, max_tokens=11, token_counter=len)

        self.assertLessEqual(len(focused.semantic_query), 11)
        self.assertEqual(focused.semantic_query, "SSSSSS PPPP")
        self.assertNotIn("TTTT", focused.semantic_query)

    def test_duplicate_labels_are_stable_and_unlabeled_input_is_supported(self):
        duplicate = build_report_query("当前二级标题：首值\n当前二级标题: 次值")
        unlabeled = build_report_query("  央企智算中心布局与建设路径  ")

        self.assertEqual(duplicate.current_subsection, "首值")
        self.assertEqual(duplicate.semantic_query, "首值")
        self.assertEqual(unlabeled.semantic_query, "央企智算中心布局与建设路径")
        self.assertEqual(unlabeled.unlabeled_text, "央企智算中心布局与建设路径")

    def test_empty_label_accepts_a_wrapped_continuation_line(self):
        focused = build_report_query("当前二级标题：\n央企智算中心布局")

        self.assertEqual(focused.current_subsection, "央企智算中心布局")
        self.assertEqual(focused.semantic_query, "央企智算中心布局")

    def test_bm25_normalizes_deduplicates_and_uses_injected_tokenizer(self):
        seen = []

        def tokenize(text):
            seen.append(text)
            return ["央企智算中心", "布局", "的", "央企智算中心", "，", "政策法规"]

        focused = build_report_query(
            "当前二级标题：央企智算中心布局", bm25_tokenizer=tokenize
        )

        self.assertEqual(focused.bm25_terms, ("央企智算中心", "布局", "政策法规"))
        self.assertEqual(seen, [focused.semantic_query])

    def test_default_dictionary_keeps_versioned_industry_term_together(self):
        focused = build_report_query("当前二级标题：央企智算中心布局")

        self.assertIn("央企智算中心", focused.bm25_terms)

    def test_default_dictionary_preserves_focused_intent_order(self):
        focused = build_report_query("当前二级标题：人工智能与国资央企")

        self.assertEqual(focused.bm25_terms[:2], ("人工智能", "国资央企"))

    def test_default_bm25_does_not_mutate_jieba_global_tokenizer(self):
        try:
            import jieba
        except ImportError:
            self.skipTest("jieba not installed")
        before = dict(jieba.dt.FREQ)
        build_report_query("当前二级标题：央企智算中心布局")
        self.assertEqual(jieba.dt.FREQ, before)

    def test_local_jieba_tokenizer_is_constructed_and_customized(self):
        instances = []

        class FakeTokenizer:
            def __init__(self):
                self.words = []
                instances.append(self)

            def add_word(self, word):
                self.words.append(word)

            def cut(self, text, HMM=False):
                return ["央企智算中心", "布局"]

        fake_jieba = SimpleNamespace(Tokenizer=FakeTokenizer)
        with patch.dict(sys.modules, {"jieba": fake_jieba}):
            focused = build_report_query("当前二级标题：央企智算中心布局")

        self.assertEqual(focused.bm25_terms, ("央企智算中心", "布局"))
        self.assertEqual(len(instances), 1)
        self.assertIn("央企智算中心", instances[0].words)

    def test_bm25_tokenizer_output_consumption_is_bounded(self):
        terms = [f"term{index}" for index in range(600)]

        focused = build_report_query(
            "当前二级标题：央企智算中心布局",
            bm25_tokenizer=lambda _: iter(terms),
        )

        self.assertEqual(len(focused.bm25_terms), 512)
        self.assertEqual(focused.bm25_terms[-1], "term511")

    def test_query_validation_is_clear(self):
        for invalid in (None, 3, "   "):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    build_report_query(invalid)
        for invalid in (0, -1, True, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    build_report_query("query", max_tokens=invalid)


class LibraryRouteTests(unittest.TestCase):
    def test_routes_all_categories(self):
        policy = route_libraries("政策环境与监管要求")
        company = route_libraries("企业实践案例与应用")
        research = route_libraries("专家研判与行业趋势研究")
        general = route_libraries("产业发展概况")

        self.assertEqual(policy.preferred, {"policy", "speech"})
        self.assertEqual(company.preferred, {"company_case"})
        self.assertEqual(research.preferred, {"expert_view", "research_report"})
        self.assertEqual(general.preferred, ALL_LIBRARIES)
        self.assertFalse(policy.search_all_immediately)
        self.assertTrue(general.search_all_immediately)
        self.assertEqual(set(general.all_libraries), ALL_LIBRARIES)

    def test_route_record_is_isolated_from_mutable_constructor_input(self):
        preferred = {"policy"}
        route = LibraryRoute(preferred=preferred)
        preferred.add("speech")

        self.assertEqual(route.preferred, {"policy"})
        with self.assertRaises(AttributeError):
            route.preferred.add("speech")

    def test_route_canonicalizes_all_library_order_and_rejects_unbounded_inputs(self):
        route = LibraryRoute(preferred={"policy"}, all_libraries=set(ALL_LIBRARIES))

        self.assertEqual(
            route.all_libraries,
            ("policy", "speech", "expert_view", "company_case", "research_report"),
        )
        with self.assertRaises(TypeError):
            LibraryRoute(preferred=(name for name in ("policy",)))

    def test_route_rejects_blank_or_non_string_input(self):
        for invalid in (None, " ", 1):
            with self.assertRaises((TypeError, ValueError)):
                route_libraries(invalid)


class SoftRoutingTests(unittest.TestCase):
    def test_does_not_fallback_when_preferred_has_enough_viable_unique_rows(self):
        calls = []

        def retrieve(query, libraries, top_k):
            calls.append((query, tuple(libraries), top_k))
            return result(query, [candidate("c1"), candidate("c2")])

        routed = retrieve_with_soft_routing(
            retrieve, "监管要求", route_libraries("政策环境"), 2
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(set(calls[0][1]), {"policy", "speech"})
        self.assertEqual([row.chunk_id for row in routed.candidates], ["c1", "c2"])
        self.assertEqual(len(routed.attempts), 1)
        self.assertIsInstance(routed.attempts[0].result, RetrievalResult)

    def test_falls_back_once_when_short_and_merges_first_scope_order(self):
        calls = []

        def retrieve(query, libraries, top_k):
            calls.append(tuple(libraries))
            if len(calls) == 1:
                return result(query, [candidate("c1")])
            return result(query, [candidate("c2"), candidate("c1"), candidate("c3")])

        routed = retrieve_with_soft_routing(
            retrieve, "监管要求", route_libraries("政策环境"), 3
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(set(calls[1]), ALL_LIBRARIES)
        self.assertEqual([row.chunk_id for row in routed.candidates], ["c1", "c2", "c3"])

    def test_preferred_exception_falls_back_and_preserves_warning(self):
        calls = []

        def retrieve(query, libraries, top_k):
            calls.append(tuple(libraries))
            if len(calls) == 1:
                raise RuntimeError("private details")
            return result(query, [candidate("c2")], warnings=[{"stage": "dense"}])

        routed = retrieve_with_soft_routing(
            retrieve, "监管要求", route_libraries("政策环境"), 2
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(routed.attempts[0].status, "error")
        self.assertEqual(routed.attempts[0].error_type, "RuntimeError")
        self.assertNotIn("private details", repr(routed))
        self.assertEqual(routed.attempts[1].warnings[0]["stage"], "dense")

    def test_error_result_is_allowed_to_expand_even_if_it_contains_rows(self):
        calls = []

        def retrieve(query, libraries, top_k):
            calls.append(tuple(libraries))
            if len(calls) == 1:
                return result(query, [candidate("c1"), candidate("c2")], status="error")
            return result(query, [candidate("c3")])

        routed = retrieve_with_soft_routing(
            retrieve, "监管要求", route_libraries("政策环境"), 2
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual([row.chunk_id for row in routed.candidates], ["c1", "c2"])

    def test_general_route_searches_all_once_even_when_short(self):
        calls = []

        def retrieve(query, libraries, top_k):
            calls.append(tuple(libraries))
            return result(query, [candidate("c1")])

        routed = retrieve_with_soft_routing(
            retrieve, "产业概况", route_libraries("产业概况"), 5
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(set(calls[0]), ALL_LIBRARIES)
        self.assertEqual(len(routed.candidates), 1)

    def test_blank_candidates_do_not_count_and_inputs_are_not_mutated(self):
        source_rows = [candidate("c1", ""), candidate("c2")]
        original = list(source_rows)
        calls = []

        def retrieve(query, libraries, top_k):
            calls.append(tuple(libraries))
            return result(query, source_rows)

        routed = retrieve_with_soft_routing(
            retrieve, "企业案例", route_libraries("企业案例"), 2
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(source_rows, original)
        self.assertEqual([row.chunk_id for row in routed.candidates], ["c2"])

    def test_soft_routing_validates_inputs_and_result_type(self):
        route = route_libraries("产业概况")
        bad_cases = [
            (None, "q", route, 1),
            (lambda *_: result("q"), " ", route, 1),
            (lambda *_: result("q"), "q", route, 0),
            (lambda *_: [], "q", route, 1),
        ]
        for args in bad_cases:
            with self.subTest(args=args):
                with self.assertRaises((TypeError, ValueError)):
                    retrieve_with_soft_routing(*args)


class EvidenceAdapterTests(unittest.TestCase):
    def test_converts_candidate_to_legacy_shape_with_fallbacks(self):
        row = candidate(
            "c1",
            "政策正文",
            dense_distance=0.25,
            metadata={
                "library": "policy",
                "classification_type": 1,
                "classification_name": "政策法规",
                "material_id": 88,
                "title": "算力政策",
                "publish_date": 20260102,
                "source_address": Path("policy.pdf"),
                "paragraph_index": "",
                "chunk_index": "2",
            },
        )

        block = to_evidence_blocks([row])[0]

        self.assertEqual(block["citation_id"], "外部资料1")
        self.assertEqual(block["rank"], 1)
        self.assertEqual(block["paragraph_index"], 2)
        self.assertEqual(block["vector_id"], "c1")
        self.assertEqual(block["distance"], 0.25)
        self.assertEqual(block["text"], "政策正文")
        self.assertEqual(block["retrieval_version"], "hybrid_v2")
        self.assertEqual(block["classification_type"], "1")
        self.assertEqual(block["material_id"], "88")
        self.assertEqual(block["source_address"], "policy.pdf")

    def test_diagnostics_are_copied_json_safe_and_can_be_omitted(self):
        row = candidate(
            "c1",
            dense_rank=1,
            rrf_score=0.8,
            diagnostics={"nested": {"values": [1, Path("x")]}, "labels": {"a"}},
        )

        included = to_evidence_blocks((row,))[0]
        omitted = to_evidence_blocks((row,), include_diagnostics=False)[0]

        json.dumps(included, ensure_ascii=False)
        self.assertEqual(included["diagnostics"]["nested"]["values"], [1, "x"])
        self.assertEqual(included["dense_rank"], 1)
        self.assertNotIn("diagnostics", omitted)
        self.assertNotIn("dense_rank", omitted)

    def test_preserves_order_rejects_invalid_or_blank_and_unbounded_iterables(self):
        rows = (candidate("b"), candidate("a"))
        self.assertEqual(
            [block["vector_id"] for block in to_evidence_blocks(rows)], ["b", "a"]
        )
        with self.assertRaises(TypeError):
            to_evidence_blocks((row for row in rows))
        with self.assertRaises(TypeError):
            to_evidence_blocks([object()])
        with self.assertRaises(ValueError):
            to_evidence_blocks([candidate("blank", " ")])

    def test_context_formatter_matches_legacy_layout_and_empty_message(self):
        empty = build_rag_context_text([])
        text = build_rag_context_text(
            [{
                "citation_id": "外部资料1",
                "classification_name": "政策法规",
                "title": "算力政策",
                "publish_date": "2026-01-02",
                "source_address": "https://example.test/policy",
                "paragraph_index": 2,
                "text": "政策正文",
            }]
        )

        self.assertEqual(empty, "【外部资料库检索结果】\n\n未检索到匹配内容。")
        self.assertIn("[外部资料1]", text)
        self.assertIn("资料类型：政策法规", text)
        self.assertIn("标题：算力政策", text)
        self.assertIn("段落序号：2", text)
        self.assertIn("内容：政策正文", text)


if __name__ == "__main__":
    unittest.main()
