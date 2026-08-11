import math
from functools import partial
from itertools import repeat
import unittest

from retrieval_core import HybridRetrievalPipeline, RetrievalCandidate
from retrieval_core.reranker import rerank_candidates


def candidate(chunk_id, document_id=None, **overrides):
    values = {
        "chunk_id": chunk_id,
        "document_id": document_id or f"doc-{chunk_id}",
        "text": f"text-{chunk_id}",
        "metadata": {"source": f"{chunk_id}.pdf", "nested": {"items": [1]}},
    }
    values.update(overrides)
    return RetrievalCandidate(**values)


class HybridRetrievalPipelineTests(unittest.TestCase):
    def make_pipeline(self, events=None, **overrides):
        events = events if events is not None else []

        def embed(query):
            events.append(("embed", query))
            return [0.1, 0.2]

        def dense(vector, limit, libraries):
            events.append(("dense", vector, limit, libraries))
            return []

        def lexical(query, limit, libraries):
            events.append(("bm25", query, limit, libraries))
            return []

        def rerank(query, rows, limit):
            events.append(("rerank", query, [row.chunk_id for row in rows], limit))
            return list(rows)

        dependencies = {
            "embed_query": embed,
            "dense_search": dense,
            "lexical_search": lexical,
            "rerank": rerank,
        }
        dependencies.update(overrides)
        return HybridRetrievalPipeline(**dependencies)

    def test_empty_success_runs_deterministic_recall_and_rerank_order(self):
        events = []
        result = self.make_pipeline(events).retrieve("steel", ["reports"], 5)

        self.assertEqual(result.status, "success")
        self.assertEqual(
            [event[0] for event in events], ["embed", "dense", "bm25", "rerank"]
        )
        self.assertEqual(result.candidates, ())

    def test_dense_exception_warns_and_lexical_route_recovers(self):
        lexical_row = candidate("c1", bm25_rank=1, bm25_score=2.0)

        def fail_dense(vector, limit, libraries):
            raise RuntimeError("secret vector details")

        result = self.make_pipeline(
            dense_search=fail_dense,
            lexical_search=lambda query, limit, libraries: [lexical_row],
        ).retrieve("steel demand", None, 5)

        self.assertEqual(result.status, "success")
        self.assertEqual([row.chunk_id for row in result.candidates], ["c1"])
        self.assertEqual(result.warnings[0]["stage"], "dense")
        self.assertEqual(result.warnings[0]["error_type"], "RuntimeError")
        self.assertNotIn("secret vector details", repr(result.warnings))

    def test_embedding_exception_warns_and_lexical_route_recovers(self):
        events = []

        def fail_embed(query):
            events.append("embed")
            raise ValueError("query leaked")

        def lexical(query, limit, libraries):
            events.append("lexical")
            return [candidate("c1", bm25_rank=1)]

        result = self.make_pipeline(
            events,
            embed_query=fail_embed,
            dense_search=lambda vector, limit, libraries: self.fail("dense called"),
            lexical_search=lexical,
        ).retrieve("sensitive query", None, 1)

        self.assertEqual(events[:2], ["embed", "lexical"])
        self.assertNotIn("dense", events)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.warnings[0]["stage"], "embed")
        self.assertNotIn("sensitive query", repr(result.warnings))

    def test_both_recall_routes_raising_returns_complete_error_result(self):
        def fail(*args):
            raise OSError("private path")

        result = self.make_pipeline(
            dense_search=fail, lexical_search=fail
        ).retrieve("steel", ["a"], 2)

        self.assertEqual(result.status, "error")
        self.assertEqual(result.candidates, ())
        self.assertTrue(result.message)
        self.assertEqual(
            [warning["stage"] for warning in result.warnings],
            ["dense", "lexical"],
        )
        self.assertEqual(
            set(result.candidate_counts),
            {
                "dense",
                "lexical",
                "fused",
                "reranked",
                "business",
                "expanded",
                "final",
            },
        )
        self.assertTrue(all(value == 0 for value in result.candidate_counts.values()))
        self.assertEqual(result.retrieval_version, "hybrid_v2")

    def test_rerank_exception_preserves_rrf_order_and_warns(self):
        dense = [candidate("b", dense_rank=1), candidate("a", dense_rank=2)]
        lexical = [candidate("a", bm25_rank=1), candidate("b", bm25_rank=2)]
        calls = []

        def fail_rerank(query, rows, limit):
            calls.append((query, len(rows), limit))
            raise TypeError("internal model detail")

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: dense,
            lexical_search=lambda query, limit, libraries: lexical,
            rerank=fail_rerank,
        ).retrieve("steel", None, 10)

        self.assertEqual([row.chunk_id for row in result.candidates], ["a", "b"])
        self.assertEqual(result.warnings[0]["stage"], "rerank")
        self.assertEqual(calls, [("steel", 2, 24)])

    def test_limits_counts_timings_hooks_and_final_ranks_are_structured(self):
        seen = {}
        dense = [
            candidate("a", "doc-a", dense_rank=1),
            candidate("b", "doc-b", dense_rank=2),
        ]
        lexical = [candidate("c", "doc-c", bm25_rank=1)]

        def rerank(query, rows, limit):
            seen["rerank"] = (len(rows), limit)
            return list(reversed(rows))

        def business(rows):
            seen["business"] = [row.chunk_id for row in rows]
            return rows

        def expand(rows):
            seen["expand"] = [row.chunk_id for row in rows]
            return list(rows) + [candidate("neighbor")]

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: dense,
            lexical_search=lambda query, limit, libraries: lexical,
            rerank=rerank,
            business_adjust=business,
            neighbor_expand=expand,
            dense_limit=7,
            lexical_limit=8,
            rerank_limit=2,
            per_document_limit=2,
        ).retrieve("steel", ("reports",), 2)

        self.assertEqual(seen["rerank"], (2, 2))
        self.assertEqual(seen["business"], ["c", "a"])
        self.assertEqual(seen["expand"], ["c", "a"])
        self.assertEqual([row.chunk_id for row in result.candidates], ["c", "a"])
        self.assertEqual([row.final_rank for row in result.candidates], [1, 2])
        self.assertEqual(
            result.candidate_counts,
            {
                "dense": 2,
                "lexical": 1,
                "fused": 2,
                "reranked": 2,
                "business": 2,
                "expanded": 2,
                "final": 2,
            },
        )
        self.assertEqual(
            set(result.timings),
            {"embed", "dense", "lexical", "fusion", "rerank", "business", "neighbor"},
        )
        self.assertTrue(all(value >= 0 for value in result.timings.values()))
        self.assertEqual(result.retrieval_version, "hybrid_v2")

    def test_hook_failures_degrade_without_mutating_prior_candidates(self):
        source = candidate("a", dense_rank=1)

        def bad_business(rows):
            rows[0].metadata["nested"]["items"].append(2)
            raise LookupError("private")

        def bad_expand(rows):
            rows.reverse()
            raise RuntimeError("private")

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: [source],
            business_adjust=bad_business,
            neighbor_expand=bad_expand,
        ).retrieve("steel", None, 1)

        self.assertEqual(
            [warning["stage"] for warning in result.warnings],
            ["business", "neighbor"],
        )
        self.assertEqual([row.chunk_id for row in result.candidates], ["a"])
        self.assertEqual(source.metadata["nested"]["items"], (1,))
        self.assertEqual(result.candidates[0].metadata["nested"]["items"], (1,))

    def test_inputs_and_lower_stage_candidates_are_not_mutated(self):
        libraries = ["reports"]
        source = candidate("a", dense_rank=1)

        result = self.make_pipeline(
            dense_search=lambda vector, limit, route_libraries: [source]
        ).retrieve("steel", libraries, 1)

        self.assertEqual(libraries, ["reports"])
        self.assertIsNone(source.rrf_rank)
        self.assertIsNone(source.final_rank)
        self.assertIsNot(result.candidates[0], source)

    def test_validation_rejects_invalid_query_top_k_and_libraries_before_calls(self):
        events = []
        pipeline = self.make_pipeline(events)
        invalid_calls = [
            lambda: pipeline.retrieve(" ", None, 1),
            lambda: pipeline.retrieve(4, None, 1),
            lambda: pipeline.retrieve("steel", None, 0),
            lambda: pipeline.retrieve("steel", None, True),
            lambda: pipeline.retrieve("steel", ["ok", ""], 1),
            lambda: pipeline.retrieve("steel", "reports", 1),
        ]
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(ValueError):
                    call()
        self.assertEqual(events, [])

    def test_constructor_rejects_nonfinite_rrf_constant(self):
        for invalid in (math.inf, math.nan):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.make_pipeline(rrf_k=invalid)

    def test_lexical_exception_allows_dense_recovery(self):
        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: [
                candidate("dense", dense_rank=1)
            ],
            lexical_search=lambda query, limit, libraries: (_ for _ in ()).throw(
                RuntimeError("index details")
            ),
        ).retrieve("steel", [], 1)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.candidates[0].chunk_id, "dense")
        self.assertEqual(result.warnings[0]["stage"], "lexical")

    def test_internal_fusion_exception_returns_clear_error(self):
        result = self.make_pipeline(
            fusion=lambda *args, **kwargs: (_ for _ in ()).throw(
                ValueError("candidate contents")
            )
        ).retrieve("steel", None, 1)

        self.assertEqual(result.status, "error")
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.warnings[0]["stage"], "fusion")
        self.assertTrue(result.message)

    def test_zero_embedding_duration_is_not_remeasured_after_dense_failure(self):
        ticks = iter([0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: (_ for _ in ()).throw(
                RuntimeError("dense unavailable")
            ),
            clock=lambda: next(ticks),
        ).retrieve("steel", None, 1)

        self.assertEqual(result.timings["embed"], 0.0)

    def test_task5_reranker_partial_uses_keyword_limits_and_reorders(self):
        scorer_calls = []

        def score(pairs):
            scorer_calls.append(list(pairs))
            return [0.1, 0.9]

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: [
                candidate("a", dense_rank=1),
                candidate("b", dense_rank=2),
            ],
            rerank=partial(rerank_candidates, scorer=score),
            rerank_limit=2,
        ).retrieve("steel", None, 2)

        self.assertEqual([row.chunk_id for row in result.candidates], ["b", "a"])
        self.assertEqual(
            scorer_calls,
            [[("steel", "text-a"), ("steel", "text-b")]],
        )
        self.assertEqual(result.warnings, ())

    def test_task5_internal_fallback_adds_one_structured_rerank_warning(self):
        scorer_calls = []

        def fail(pairs):
            scorer_calls.append(list(pairs))
            raise RuntimeError("model internals")

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: [
                candidate("a", dense_rank=1),
                candidate("b", dense_rank=2),
            ],
            rerank=partial(rerank_candidates, scorer=fail),
            rerank_limit=2,
        ).retrieve("steel", None, 2)

        self.assertEqual([row.chunk_id for row in result.candidates], ["a", "b"])
        self.assertEqual(len(scorer_calls), 1)
        self.assertEqual([warning["stage"] for warning in result.warnings], ["rerank"])
        self.assertTrue(
            all(row.diagnostics["reranker_fallback"] for row in result.candidates)
        )

    def test_modern_kwargs_reranker_shape_is_bound_without_trial_execution(self):
        calls = []

        def modern(query, rows, **kwargs):
            calls.append((query, len(rows), kwargs))
            return rows

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: [
                candidate("a", dense_rank=1)
            ],
            rerank=modern,
            rerank_limit=3,
        ).retrieve("steel", None, 1)

        self.assertEqual(result.status, "success")
        self.assertEqual(
            calls,
            [("steel", 1, {"final_limit": 3, "rerank_limit": 3})],
        )
        self.assertEqual(result.warnings, ())

    def test_positional_only_modern_reranker_shape_is_bound_once(self):
        calls = []

        def modern(query, rows, final_limit, rerank_limit, /):
            calls.append((query, len(rows), final_limit, rerank_limit))
            return rows

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: [
                candidate("a", dense_rank=1)
            ],
            rerank=modern,
            rerank_limit=3,
        ).retrieve("steel", None, 1)

        self.assertEqual(result.status, "success")
        self.assertEqual(calls, [("steel", 1, 3, 3)])
        self.assertEqual(result.warnings, ())

    def test_noncompliant_fusion_is_bounded_before_rerank_and_hooks(self):
        seen = {}

        def rerank(query, rows, limit):
            seen["rerank_count"] = len(rows)
            return rows

        result = self.make_pipeline(
            fusion=lambda *args, **kwargs: [
                candidate(f"c{index}") for index in range(100)
            ],
            rerank=rerank,
            rerank_limit=3,
        ).retrieve("steel", None, 10)

        self.assertEqual(seen["rerank_count"], 3)
        self.assertEqual(result.candidate_counts["fused"], 3)
        self.assertLessEqual(result.candidate_counts["reranked"], 3)
        self.assertLessEqual(result.candidate_counts["business"], 3)
        self.assertLessEqual(result.candidate_counts["expanded"], 3)

    def test_each_iterable_dependency_is_consumed_only_to_its_stage_limit(self):
        pulls = {}

        def guarded(stage, allowed, **overrides):
            for index in range(allowed):
                pulls[stage] = pulls.get(stage, 0) + 1
                yield candidate(f"{stage}-{index}", **overrides)
            raise AssertionError(f"{stage} was over-consumed")

        def fusion(*args, **kwargs):
            return guarded("fusion", 4)

        def rerank(query, rows, limit):
            return guarded("rerank", 4)

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: guarded(
                "dense", 2, dense_rank=1
            ),
            lexical_search=lambda query, limit, libraries: guarded(
                "lexical", 3, bm25_rank=1
            ),
            fusion=fusion,
            rerank=rerank,
            business_adjust=lambda rows: guarded("business", 4),
            neighbor_expand=lambda rows: guarded("neighbor", 2),
            dense_limit=2,
            lexical_limit=3,
            rerank_limit=4,
        ).retrieve("steel", None, 2)

        self.assertEqual(result.status, "success")
        self.assertEqual(
            pulls,
            {
                "dense": 2,
                "lexical": 3,
                "fusion": 4,
                "rerank": 4,
                "business": 4,
                "neighbor": 2,
            },
        )
        self.assertEqual(result.candidate_counts["final"], 2)

    def test_infinite_iterable_dependencies_are_bounded(self):
        row = candidate("repeated")

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: repeat(row),
            lexical_search=lambda query, limit, libraries: repeat(row),
            fusion=lambda *args, **kwargs: repeat(row),
            rerank=lambda query, rows, limit: repeat(row),
            business_adjust=lambda rows: repeat(row),
            neighbor_expand=lambda rows: repeat(row),
            dense_limit=2,
            lexical_limit=3,
            rerank_limit=4,
        ).retrieve("steel", None, 2)

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.candidate_counts,
            {
                "dense": 2,
                "lexical": 3,
                "fused": 4,
                "reranked": 4,
                "business": 4,
                "expanded": 2,
                "final": 2,
            },
        )

    def test_stale_fallback_diagnostic_does_not_warn_for_current_rerank(self):
        stale = candidate(
            "a",
            dense_rank=1,
            diagnostics={"reranker_fallback": True, "source": "previous-stage"},
        )

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: [stale],
            rerank=lambda query, rows, limit: rows,
        ).retrieve("steel", None, 1)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.warnings, ())
        self.assertNotIn("reranker_fallback", result.candidates[0].diagnostics)
        self.assertEqual(
            result.candidates[0].diagnostics["source"], "previous-stage"
        )

    def test_clock_failure_does_not_override_dense_failure_or_lexical_recovery(self):
        clock_calls = []

        def failing_clock():
            clock_calls.append(len(clock_calls) + 1)
            if len(clock_calls) <= 3:
                return float(len(clock_calls))
            raise RuntimeError("clock unavailable")

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: (_ for _ in ()).throw(
                RuntimeError("dense unavailable")
            ),
            lexical_search=lambda query, limit, libraries: [
                candidate("lexical", bm25_rank=1)
            ],
            clock=failing_clock,
        ).retrieve("steel", None, 1)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.candidates[0].chunk_id, "lexical")
        self.assertEqual([warning["stage"] for warning in result.warnings], ["dense"])
        self.assertEqual(result.timings["dense"], 0.0)
        self.assertTrue(all(value >= 0 for value in result.timings.values()))

    def test_nonfinite_clock_values_degrade_to_zero_timings(self):
        clock_values = [0.0]

        def nonfinite_clock():
            return clock_values.pop() if clock_values else math.inf

        result = self.make_pipeline(clock=nonfinite_clock).retrieve("steel", None, 1)

        self.assertEqual(result.status, "success")
        self.assertTrue(all(value == 0.0 for value in result.timings.values()))

    def test_invalid_dependency_outputs_follow_stage_degradation_rules(self):
        lexical = candidate("lexical", bm25_rank=1)

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: None,
            lexical_search=lambda query, limit, libraries: [lexical],
            rerank=lambda query, rows, limit: 7,
            business_adjust=lambda rows: None,
            neighbor_expand=lambda rows: lexical,
        ).retrieve("steel", None, 1)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.candidates[0].chunk_id, "lexical")
        self.assertEqual(
            [warning["stage"] for warning in result.warnings],
            ["dense", "rerank", "business", "neighbor"],
        )

    def test_signature_unavailable_callable_uses_documented_legacy_shape(self):
        calls = []

        class LegacyCallable:
            @property
            def __signature__(self):
                raise ValueError("signature unavailable")

            def __call__(self, query, rows, limit):
                calls.append((query, len(rows), limit))
                return rows

        result = self.make_pipeline(
            dense_search=lambda vector, limit, libraries: [
                candidate("a", dense_rank=1)
            ],
            rerank=LegacyCallable(),
            rerank_limit=3,
        ).retrieve("steel", None, 1)

        self.assertEqual(result.status, "success")
        self.assertEqual(calls, [("steel", 1, 3)])


if __name__ == "__main__":
    unittest.main()
