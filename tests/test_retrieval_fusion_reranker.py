import math
from types import MappingProxyType
import unittest

from retrieval_core.fusion import reciprocal_rank_fusion
from retrieval_core.reranker import rerank_candidates
from retrieval_core.schemas import RetrievalCandidate


def candidate(chunk_id, document_id=None, **overrides):
    values = {
        "chunk_id": chunk_id,
        "document_id": document_id or f"doc-{chunk_id}",
        "text": f"text-{chunk_id}",
        "metadata": {"source": f"{chunk_id}.pdf"},
    }
    values.update(overrides)
    return RetrievalCandidate(**values)


class AmbiguousArrayLike:
    def __init__(self, values):
        self.values = list(values)
        self.shape = (len(self.values),)

    def tolist(self):
        return list(self.values)

    def __eq__(self, other):
        class AmbiguousTruth:
            def __bool__(self):
                raise ValueError("truth value is ambiguous")

        return AmbiguousTruth()


class ReciprocalRankFusionTests(unittest.TestCase):
    def test_shared_chunk_is_merged_with_both_route_values_and_exact_score(self):
        dense = candidate(
            "shared",
            "doc-1",
            dense_rank=2,
            dense_score=0.8,
            dense_distance=0.2,
            diagnostics={"dense_probe": 7},
        )
        lexical = candidate(
            "shared",
            "doc-1",
            bm25_rank=3,
            bm25_score=-1.4,
            diagnostics={"lexical_probe": 9},
        )

        result = reciprocal_rank_fusion(
            [dense], [lexical], rrf_k=60, limit=10, per_document_limit=3
        )

        self.assertEqual(len(result), 1)
        fused = result[0]
        self.assertEqual(fused.dense_rank, 2)
        self.assertEqual(fused.dense_score, 0.8)
        self.assertEqual(fused.dense_distance, 0.2)
        self.assertEqual(fused.bm25_rank, 3)
        self.assertEqual(fused.bm25_score, -1.4)
        self.assertEqual(fused.diagnostics, {"dense_probe": 7, "lexical_probe": 9})
        self.assertEqual(fused.rrf_score, 1 / 62 + 1 / 63)
        self.assertEqual(fused.rrf_rank, 1)

    def test_document_cap_is_applied_before_global_limit_without_backfill(self):
        dense = [
            candidate("a", "doc-1", dense_rank=1),
            candidate("b", "doc-1", dense_rank=2),
            candidate("c", "doc-2", dense_rank=3),
        ]

        result = reciprocal_rank_fusion(
            dense, [], rrf_k=60, limit=3, per_document_limit=1
        )

        self.assertEqual([row.chunk_id for row in result], ["a", "c"])
        self.assertEqual([row.rrf_rank for row in result], [1, 3])

    def test_rrf_counts_only_routes_that_returned_the_chunk(self):
        dense = candidate("a", dense_rank=1, bm25_rank=1, bm25_score=-0.5)

        result = reciprocal_rank_fusion(
            [dense], [], rrf_k=60, limit=1, per_document_limit=1
        )

        self.assertEqual(result[0].rrf_score, 1 / 61)

    def test_equal_scores_are_ordered_by_chunk_id_not_input_order(self):
        dense = [
            candidate("z", dense_rank=1),
            candidate("a", dense_rank=1),
        ]

        first = reciprocal_rank_fusion(
            dense, [], rrf_k=60, limit=10, per_document_limit=2
        )
        second = reciprocal_rank_fusion(
            list(reversed(dense)), [], rrf_k=60, limit=10, per_document_limit=2
        )

        self.assertEqual([row.chunk_id for row in first], ["a", "z"])
        self.assertEqual([row.chunk_id for row in second], ["a", "z"])

    def test_empty_and_zero_limit_return_empty(self):
        self.assertEqual(
            reciprocal_rank_fusion(
                [], [], rrf_k=60, limit=5, per_document_limit=1
            ),
            [],
        )
        self.assertEqual(
            reciprocal_rank_fusion(
                [candidate("a", dense_rank=1)],
                [],
                rrf_k=60,
                limit=0,
                per_document_limit=1,
            ),
            [],
        )

    def test_invalid_limits_and_route_ranks_are_rejected(self):
        calls = [
            lambda: reciprocal_rank_fusion(
                [], [], rrf_k=-1, limit=1, per_document_limit=1
            ),
            lambda: reciprocal_rank_fusion(
                [], [], rrf_k=60, limit=-1, per_document_limit=1
            ),
            lambda: reciprocal_rank_fusion(
                [], [], rrf_k=60, limit=1, per_document_limit=0
            ),
            lambda: reciprocal_rank_fusion(
                [candidate("a", dense_rank=0)],
                [],
                rrf_k=60,
                limit=1,
                per_document_limit=1,
            ),
            lambda: reciprocal_rank_fusion(
                [],
                [candidate("a", bm25_rank=None)],
                rrf_k=60,
                limit=1,
                per_document_limit=1,
            ),
        ]
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(ValueError):
                    call()

    def test_equal_array_like_nested_values_merge_without_ambiguous_truth(self):
        dense = candidate(
            "a",
            dense_rank=1,
            metadata={"nested": {"vector": AmbiguousArrayLike([1, 2])}},
        )
        lexical = candidate(
            "a",
            bm25_rank=1,
            metadata={"nested": {"vector": AmbiguousArrayLike([1, 2])}},
        )

        result = reciprocal_rank_fusion(
            [dense], [lexical], rrf_k=60, limit=1, per_document_limit=1
        )

        self.assertEqual(result[0].chunk_id, "a")

    def test_conflicting_array_like_nested_values_are_rejected(self):
        dense = candidate(
            "a", dense_rank=1, metadata={"vector": AmbiguousArrayLike([1, 2])}
        )
        lexical = candidate(
            "a", bm25_rank=1, metadata={"vector": AmbiguousArrayLike([1, 3])}
        )

        with self.assertRaisesRegex(ValueError, "conflicting metadata"):
            reciprocal_rank_fusion(
                [dense], [lexical], rrf_k=60, limit=1, per_document_limit=1
            )

    def test_duplicate_route_chunk_and_conflicting_identity_are_rejected(self):
        duplicate = candidate("a", dense_rank=1)
        with self.assertRaisesRegex(ValueError, "duplicate chunk_id"):
            reciprocal_rank_fusion(
                [duplicate, duplicate],
                [],
                rrf_k=60,
                limit=1,
                per_document_limit=1,
            )

        dense = candidate("a", "doc-1", dense_rank=1)
        lexical = candidate("a", "doc-2", bm25_rank=1)
        with self.assertRaisesRegex(ValueError, "conflicting identity"):
            reciprocal_rank_fusion(
                [dense], [lexical], rrf_k=60, limit=1, per_document_limit=1
            )

    def test_fusion_does_not_mutate_input_candidates(self):
        dense = candidate(
            "a", dense_rank=1, dense_score=0.5, diagnostics={"route": "dense"}
        )

        result = reciprocal_rank_fusion(
            [dense], [], rrf_k=60, limit=1, per_document_limit=1
        )

        self.assertIsNot(result[0], dense)
        self.assertIsNone(dense.rrf_rank)
        self.assertIsNone(dense.rrf_score)
        self.assertEqual(dense.diagnostics, {"route": "dense"})

    def test_fusion_deeply_isolates_nested_output_values(self):
        original = candidate(
            "a",
            dense_rank=1,
            metadata={
                "nested": MappingProxyType({"items": [1]}),
                "vector": AmbiguousArrayLike([1, 2]),
            },
            diagnostics={"trace": {"steps": ["dense"]}},
        )

        result = reciprocal_rank_fusion(
            [original], [], rrf_k=60, limit=1, per_document_limit=1
        )[0]
        with self.assertRaises(AttributeError):
            result.metadata["nested"]["items"].append(2)
        with self.assertRaises(TypeError):
            result.metadata["vector"] += (9,)
        with self.assertRaises(AttributeError):
            result.diagnostics["trace"]["steps"].append("fusion")

        self.assertEqual(original.metadata["nested"]["items"], (1,))
        self.assertEqual(original.metadata["vector"], (1, 2))
        self.assertEqual(original.diagnostics["trace"]["steps"], ("dense",))
        with self.assertRaises(TypeError):
            result.metadata["new"] = "value"


class RerankerTests(unittest.TestCase):
    def make_fused(self):
        return [
            candidate("a", rrf_rank=1, rrf_score=0.3),
            candidate("b", rrf_rank=2, rrf_score=0.2),
            candidate("c", rrf_rank=3, rrf_score=0.1),
        ]

    def test_scores_reorder_candidates_and_assign_ranks(self):
        result = rerank_candidates(
            "query",
            self.make_fused()[:2],
            scorer=lambda pairs: [0.1, 0.9],
            final_limit=2,
        )

        self.assertEqual([row.chunk_id for row in result], ["b", "a"])
        self.assertEqual([row.rerank_score for row in result], [0.9, 0.1])
        self.assertEqual([row.rerank_rank for row in result], [1, 2])

    def test_scorer_exception_falls_back_in_original_order_with_diagnostics(self):
        def fail(_pairs):
            raise RuntimeError("model unavailable")

        result = rerank_candidates(
            "query", self.make_fused(), scorer=fail, final_limit=2
        )

        self.assertEqual([row.chunk_id for row in result], ["a", "b"])
        self.assertTrue(all(row.diagnostics["reranker_fallback"] for row in result))

    def test_scorer_work_is_bounded_separately_from_final_output(self):
        received = []

        def score(pairs):
            received.extend(pairs)
            return [0.2, 0.8]

        result = rerank_candidates(
            "steel", self.make_fused(), scorer=score, final_limit=3, rerank_limit=2
        )

        self.assertEqual(received, [("steel", "text-a"), ("steel", "text-b")])
        self.assertEqual([row.chunk_id for row in result], ["b", "a", "c"])
        self.assertIsNone(result[2].rerank_score)
        self.assertIsNone(result[2].rerank_rank)

    def test_equal_rerank_scores_preserve_input_rrf_order(self):
        result = rerank_candidates(
            "query", self.make_fused(), scorer=lambda pairs: [1, 1, 1], final_limit=3
        )

        self.assertEqual([row.chunk_id for row in result], ["a", "b", "c"])

    def test_wrong_length_and_nonfinite_scores_each_fall_back(self):
        scorers = [lambda pairs: [0.1], lambda pairs: [0.1, math.inf, 0.2]]
        for scorer in scorers:
            with self.subTest(scorer=scorer):
                result = rerank_candidates(
                    "query", self.make_fused(), scorer=scorer, final_limit=2
                )
                self.assertEqual([row.chunk_id for row in result], ["a", "b"])
                self.assertTrue(
                    all(row.diagnostics["reranker_fallback"] for row in result)
                )

    def test_string_and_boolean_scores_each_fall_back(self):
        scorers = [lambda pairs: ["0.9", 0.1], lambda pairs: [True, 0.1]]
        for scorer in scorers:
            with self.subTest(scorer=scorer):
                result = rerank_candidates(
                    "query", self.make_fused()[:2], scorer=scorer, final_limit=2
                )
                self.assertEqual([row.chunk_id for row in result], ["a", "b"])
                self.assertTrue(
                    all(row.diagnostics["reranker_fallback"] for row in result)
                )

    def test_overlong_scorer_generator_is_consumed_only_to_length_boundary(self):
        pulls = []

        def scores():
            for value in range(10):
                pulls.append(value)
                yield float(value)

        result = rerank_candidates(
            "query",
            self.make_fused()[:2],
            scorer=lambda pairs: scores(),
            final_limit=2,
        )

        self.assertEqual(len(pulls), 3)
        self.assertEqual([row.chunk_id for row in result], ["a", "b"])
        self.assertTrue(all(row.diagnostics["reranker_fallback"] for row in result))

    def test_endless_scorer_iterator_returns_after_length_boundary(self):
        class GuardedEndlessScores:
            def __init__(self):
                self.pulls = 0

            def __iter__(self):
                return self

            def __next__(self):
                self.pulls += 1
                if self.pulls > 3:
                    raise AssertionError("score iterator was consumed without a bound")
                return 0.5

        scores = GuardedEndlessScores()
        result = rerank_candidates(
            "query",
            self.make_fused()[:2],
            scorer=lambda pairs: scores,
            final_limit=2,
        )

        self.assertEqual(scores.pulls, 3)
        self.assertEqual([row.chunk_id for row in result], ["a", "b"])
        self.assertTrue(all(row.diagnostics["reranker_fallback"] for row in result))

    def test_scalar_scorer_output_falls_back(self):
        result = rerank_candidates(
            "query", self.make_fused()[:2], scorer=lambda pairs: 0.5, final_limit=2
        )

        self.assertEqual([row.chunk_id for row in result], ["a", "b"])
        self.assertTrue(all(row.diagnostics["reranker_fallback"] for row in result))

    def test_empty_input_and_zero_final_limit_do_not_call_scorer(self):
        def unexpected(_pairs):
            raise AssertionError("scorer should not be called")

        self.assertEqual(
            rerank_candidates("query", [], scorer=unexpected, final_limit=2), []
        )
        self.assertEqual(
            rerank_candidates(
                "query", self.make_fused(), scorer=unexpected, final_limit=0
            ),
            [],
        )

    def test_blank_query_and_invalid_limits_are_rejected(self):
        cases = [
            lambda: rerank_candidates("", [], scorer=lambda pairs: [], final_limit=1),
            lambda: rerank_candidates(7, [], scorer=lambda pairs: [], final_limit=1),
            lambda: rerank_candidates(
                "query", [], scorer=lambda pairs: [], final_limit=-1
            ),
            lambda: rerank_candidates(
                "query", [], scorer=lambda pairs: [], final_limit=1, rerank_limit=0
            ),
        ]
        for call in cases:
            with self.subTest(call=call):
                with self.assertRaises(ValueError):
                    call()

    def test_reranking_does_not_mutate_input_candidates(self):
        original = candidate(
            "a",
            rrf_rank=1,
            rrf_score=0.3,
            diagnostics={"fusion": "ok"},
        )

        result = rerank_candidates(
            "query", [original], scorer=lambda pairs: [0.7], final_limit=1
        )

        self.assertIsNot(result[0], original)
        self.assertIsNone(original.rerank_rank)
        self.assertIsNone(original.rerank_score)
        self.assertEqual(original.diagnostics, {"fusion": "ok"})

    def test_reranking_deeply_isolates_nested_output_values(self):
        original = candidate(
            "a",
            rrf_rank=1,
            rrf_score=0.3,
            metadata={
                "nested": MappingProxyType({"items": [1]}),
                "vector": AmbiguousArrayLike([1, 2]),
            },
            diagnostics={"trace": {"steps": ["fusion"]}},
        )

        result = rerank_candidates(
            "query", [original], scorer=lambda pairs: [0.7], final_limit=1
        )[0]
        with self.assertRaises(AttributeError):
            result.metadata["nested"]["items"].append(2)
        with self.assertRaises(TypeError):
            result.metadata["vector"] += (9,)
        with self.assertRaises(AttributeError):
            result.diagnostics["trace"]["steps"].append("rerank")

        self.assertEqual(original.metadata["nested"]["items"], (1,))
        self.assertEqual(original.metadata["vector"], (1, 2))
        self.assertEqual(original.diagnostics["trace"]["steps"], ("fusion",))
        with self.assertRaises(TypeError):
            result.diagnostics["new"] = "value"

    def test_reranker_fallback_deeply_isolates_nested_diagnostics(self):
        original = candidate(
            "a",
            rrf_rank=1,
            rrf_score=0.3,
            diagnostics={"trace": {"steps": ["fusion"]}},
        )

        result = rerank_candidates(
            "query",
            [original],
            scorer=lambda pairs: (_ for _ in ()).throw(RuntimeError("failure")),
            final_limit=1,
        )[0]
        with self.assertRaises(AttributeError):
            result.diagnostics["trace"]["steps"].append("fallback")

        self.assertEqual(original.diagnostics["trace"]["steps"], ("fusion",))
        self.assertTrue(result.diagnostics["reranker_fallback"])


if __name__ == "__main__":
    unittest.main()
