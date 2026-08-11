import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from enum import Enum
from numbers import Number
from pathlib import Path
from unittest.mock import patch

from retrieval_core import (
    ChunkRecord,
    RetrievalCandidate,
    RetrievalConfig,
    RetrievalResult,
)


class MutableBox:
    def __init__(self, values):
        self.values = list(values)


class ArrayLike:
    def __init__(self, values):
        self.values = values
        self.shape = (len(values),)

    def tolist(self):
        return self.values


class ScalarArrayLike:
    shape = ()

    def __init__(self, value):
        self.value = value

    def tolist(self):
        return self.value


class MutableInt(int):
    def __new__(cls, value):
        instance = super().__new__(cls, value)
        instance.items = []
        return instance


class MutableStr(str):
    def __new__(cls, value):
        instance = super().__new__(cls, value)
        instance.items = []
        return instance


class MutableFloat(float):
    def __new__(cls, value):
        instance = super().__new__(cls, value)
        instance.items = []
        return instance


class MutableNumber(Number):
    def __init__(self, value):
        self.value = value
        self.items = []


class MutableValueEnum(Enum):
    ROW = ["mutable"]


class RetrievalConfigTests(unittest.TestCase):
    def test_for_project_uses_exact_defaults(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            with patch.dict(os.environ, {}, clear=True):
                config = RetrievalConfig.for_project(project_root)

            resolved_root = project_root.resolve()
            self.assertEqual(config.project_root, resolved_root)
            self.assertEqual(config.mode, "legacy")
            self.assertEqual(config.index_root, resolved_root / "RAG/indexes/report_v2")
            self.assertEqual(
                config.embedding_model_path,
                resolved_root / "RAG/model_store/bge-base-zh-v1.5",
            )
            self.assertEqual(
                config.reranker_model_path,
                resolved_root / "RAG/model_store/bge-reranker-base",
            )
            self.assertEqual(config.dense_limit, 40)
            self.assertEqual(config.lexical_limit, 40)
            self.assertEqual(config.rerank_limit, 24)
            self.assertEqual(config.final_limit, 10)
            self.assertEqual(config.rrf_k, 60)
            self.assertTrue(config.allow_legacy_fallback)
            self.assertFalse(config.index_root.exists())

    def test_for_project_accepts_each_supported_mode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            for mode in ("legacy", "compare", "hybrid_v2"):
                with self.subTest(mode=mode):
                    with patch.dict(
                        os.environ, {"REPORT_RETRIEVAL_MODE": mode}, clear=True
                    ):
                        config = RetrievalConfig.for_project(Path(temporary_directory))
                    self.assertEqual(config.mode, mode)

    def test_for_project_strips_supported_mode_from_environment(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {"REPORT_RETRIEVAL_MODE": "  hybrid_v2\t"},
                clear=True,
            ):
                config = RetrievalConfig.for_project(Path(temporary_directory))

        self.assertEqual(config.mode, "hybrid_v2")

    def test_for_project_rejects_invalid_mode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ, {"REPORT_RETRIEVAL_MODE": "experimental"}, clear=True
            ):
                with self.assertRaisesRegex(ValueError, "experimental"):
                    RetrievalConfig.for_project(Path(temporary_directory))


class ChunkRecordTests(unittest.TestCase):
    def make_chunk(self, **overrides):
        values = {
            "chunk_id": "document-1:0",
            "document_id": "document-1",
            "chunk_index": 0,
            "text": "A useful passage.",
            "embedding_text": "A useful passage.",
            "search_text": "useful passage",
            "token_count": 4,
            "content_hash": "abc123",
            "metadata": {"source": "report.docx"},
        }
        values.update(overrides)
        return ChunkRecord(**values)

    def test_requires_nonempty_identity_and_text(self):
        for field in ("chunk_id", "document_id", "text"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.make_chunk(**{field: ""})

    def test_neighbor_ids_default_to_none(self):
        chunk = self.make_chunk()
        self.assertIsNone(chunk.previous_chunk_id)
        self.assertIsNone(chunk.next_chunk_id)

    def test_metadata_is_immutable_and_isolated_from_source_mapping(self):
        metadata = {"source": "report.docx"}
        chunk = self.make_chunk(metadata=metadata)

        metadata["page"] = 3

        self.assertEqual(chunk.metadata, {"source": "report.docx"})
        with self.assertRaises(TypeError):
            chunk.metadata["page"] = 3


class RetrievalCandidateTests(unittest.TestCase):
    def test_from_chunk_preserves_identity_text_and_metadata(self):
        metadata = {"source": "report.docx", "page": 3}
        chunk = ChunkRecord(
            chunk_id="document-1:2",
            document_id="document-1",
            chunk_index=2,
            text="Market demand increased.",
            embedding_text="Market demand increased.",
            search_text="market demand increased",
            token_count=5,
            content_hash="def456",
            metadata=metadata,
        )

        candidate = RetrievalCandidate.from_chunk(chunk)

        self.assertEqual(candidate.chunk_id, chunk.chunk_id)
        self.assertEqual(candidate.document_id, chunk.document_id)
        self.assertEqual(candidate.text, chunk.text)
        self.assertEqual(candidate.metadata, metadata)
        self.assertIsNot(candidate.metadata, metadata)
        self.assertIsNone(candidate.dense_rank)
        self.assertEqual(candidate.diagnostics, {})

    def test_metadata_and_diagnostics_are_immutable_and_isolated_from_inputs(self):
        metadata = {"source": "report.docx"}
        diagnostics = {"stage": "dense"}
        candidate = RetrievalCandidate(
            chunk_id="document-1:0",
            document_id="document-1",
            text="A useful passage.",
            metadata=metadata,
            diagnostics=diagnostics,
        )

        metadata["page"] = 3
        diagnostics["latency_ms"] = 12.5

        self.assertEqual(candidate.metadata, {"source": "report.docx"})
        self.assertEqual(candidate.diagnostics, {"stage": "dense"})
        with self.assertRaises(TypeError):
            candidate.metadata["page"] = 3
        with self.assertRaises(TypeError):
            candidate.diagnostics["latency_ms"] = 12.5

    def test_fields_and_nested_values_are_immutable_and_isolated(self):
        metadata = {"nested": {"items": [1]}, "labels": {"safe"}}
        diagnostics = {"trace": ["dense"]}
        candidate = RetrievalCandidate(
            chunk_id="document-1:0",
            document_id="document-1",
            text="A useful passage.",
            metadata=metadata,
            diagnostics=diagnostics,
        )

        metadata["nested"]["items"].append(2)
        metadata["labels"].add("changed")
        diagnostics["trace"].append("changed")

        self.assertEqual(candidate.metadata["nested"]["items"], (1,))
        self.assertEqual(candidate.metadata["labels"], frozenset({"safe"}))
        self.assertEqual(candidate.diagnostics["trace"], ("dense",))
        with self.assertRaises(FrozenInstanceError):
            candidate.final_rank = 1
        with self.assertRaises(TypeError):
            candidate.metadata["nested"]["new"] = "value"
        with self.assertRaises(AttributeError):
            candidate.metadata["nested"]["items"].append(2)
        with self.assertRaises(AttributeError):
            candidate.metadata["labels"].add("changed")


class RetrievalResultTests(unittest.TestCase):
    def test_defaults_are_safe_and_independent(self):
        first = RetrievalResult(status="ok", query="steel")
        second = RetrievalResult(status="ok", query="coal")

        self.assertEqual(first.candidates, ())
        self.assertEqual(first.warnings, ())
        self.assertEqual(first.timings, {})
        self.assertEqual(first.candidate_counts, {})
        self.assertEqual(first.retrieval_version, "hybrid_v2")
        self.assertEqual(first.message, "")
        self.assertIsNot(first.timings, second.timings)
        with self.assertRaises(AttributeError):
            first.status = "error"

    def test_container_fields_are_immutable_and_isolated_from_inputs(self):
        candidate = RetrievalCandidate(
            chunk_id="document-1:0",
            document_id="document-1",
            text="A useful passage.",
            metadata={"source": "report.docx"},
        )
        candidates = [candidate]
        warnings = [{"stage": "dense", "error_type": "RuntimeError"}]
        timings = {"retrieve": 0.2}
        candidate_counts = {"dense": 1}
        result = RetrievalResult(
            status="ok",
            query="steel",
            candidates=candidates,
            warnings=warnings,
            timings=timings,
            candidate_counts=candidate_counts,
        )

        candidates.append(candidate)
        warnings[0]["stage"] = "changed"
        timings["rerank"] = 0.1
        candidate_counts["final"] = 1

        self.assertEqual(result.candidates, (candidate,))
        self.assertEqual(
            result.warnings,
            ({"stage": "dense", "error_type": "RuntimeError"},),
        )
        self.assertEqual(result.timings, {"retrieve": 0.2})
        self.assertEqual(result.candidate_counts, {"dense": 1})
        with self.assertRaises(AttributeError):
            result.candidates.append(candidate)
        with self.assertRaises(AttributeError):
            result.warnings.append({"stage": "rerank"})
        with self.assertRaises(TypeError):
            result.warnings[0]["stage"] = "changed"
        with self.assertRaises(TypeError):
            result.timings["rerank"] = 0.1
        with self.assertRaises(TypeError):
            result.candidate_counts["final"] = 1

    def test_warning_values_are_recursively_frozen_and_isolated(self):
        warning = {
            "stage": "dense",
            "context": {
                "attempts": [1, {"labels": {"safe"}}],
                "pair": ([2],),
            },
        }

        result = RetrievalResult(status="success", query="steel", warnings=[warning])
        warning["context"]["attempts"].append(3)
        warning["context"]["attempts"][1]["labels"].add("changed")
        warning["context"]["pair"][0].append(4)

        frozen_context = result.warnings[0]["context"]
        self.assertEqual(
            frozen_context,
            {
                "attempts": (1, {"labels": frozenset({"safe"})}),
                "pair": ((2,),),
            },
        )
        with self.assertRaises(TypeError):
            frozen_context["new"] = "value"
        with self.assertRaises(AttributeError):
            frozen_context["attempts"].append(3)
        with self.assertRaises(AttributeError):
            frozen_context["attempts"][1]["labels"].add("changed")

    def test_candidates_are_snapshotted_with_immutable_values_isolated(self):
        source = [1]
        candidate = RetrievalCandidate(
            chunk_id="document-1:0",
            document_id="document-1",
            text="A useful passage.",
            metadata={"items": source},
        )

        result = RetrievalResult(
            status="success", query="steel", candidates=[candidate]
        )
        source.append(2)

        self.assertIsNot(result.candidates[0], candidate)
        self.assertEqual(result.candidates[0].metadata["items"], (1,))

    def test_self_referential_warning_fails_fast_with_clear_cycle_error(self):
        warning = {"stage": "dense"}
        warning["context"] = warning

        with self.assertRaisesRegex(ValueError, "cycle"):
            RetrievalResult(status="error", query="steel", warnings=[warning])

    def test_array_like_candidate_metadata_becomes_immutable_nested_values(self):
        source = ArrayLike([[1, 2], [3, 4]])

        candidate = RetrievalCandidate(
            chunk_id="document-1:0",
            document_id="document-1",
            text="A useful passage.",
            metadata={"vector": source},
        )
        source.values[0].append(9)

        self.assertEqual(candidate.metadata["vector"], ((1, 2), (3, 4)))
        with self.assertRaises(TypeError):
            candidate.metadata["vector"][0] += (9,)

    def test_opaque_mutable_candidate_metadata_fails_closed(self):
        with self.assertRaisesRegex(TypeError, "immutable"):
            RetrievalCandidate(
                chunk_id="document-1:0",
                document_id="document-1",
                text="A useful passage.",
                metadata={"opaque": MutableBox([1])},
            )

    def test_timings_and_candidate_counts_reject_nested_or_invalid_values(self):
        invalid_results = [
            lambda: RetrievalResult(
                status="success", query="steel", timings={"dense": [0.1]}
            ),
            lambda: RetrievalResult(
                status="success", query="steel", timings={"dense": -0.1}
            ),
            lambda: RetrievalResult(
                status="success", query="steel", candidate_counts={"dense": True}
            ),
            lambda: RetrievalResult(
                status="success", query="steel", candidate_counts={"dense": -1}
            ),
        ]

        for make_result in invalid_results:
            with self.subTest(make_result=make_result):
                with self.assertRaises(ValueError):
                    make_result()

    def test_mutable_builtin_scalar_subclasses_normalize_to_exact_builtins(self):
        integer = MutableInt(3)
        text = MutableStr("steel")
        decimal = MutableFloat(1.5)

        candidate = RetrievalCandidate(
            chunk_id="document-1:0",
            document_id="document-1",
            text="A useful passage.",
            metadata={"integer": integer, "text": text, "decimal": decimal},
        )
        result = RetrievalResult(
            status="success",
            query="steel",
            warnings=[{"stage": "probe", "value": integer}],
            timings={"dense": decimal},
            candidate_counts={"dense": integer},
        )

        self.assertIs(type(candidate.metadata["integer"]), int)
        self.assertIs(type(candidate.metadata["text"]), str)
        self.assertIs(type(candidate.metadata["decimal"]), float)
        self.assertIs(type(result.warnings[0]["value"]), int)
        self.assertIs(type(result.timings["dense"]), float)
        self.assertIs(type(result.candidate_counts["dense"]), int)
        self.assertIsNot(candidate.metadata["integer"], integer)
        self.assertIsNot(candidate.metadata["text"], text)
        self.assertIsNot(candidate.metadata["decimal"], decimal)

    def test_opaque_number_and_mutable_enum_fail_closed(self):
        invalid_values = [MutableNumber(3), MutableValueEnum.ROW]
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(TypeError, "immutable"):
                    RetrievalCandidate(
                        chunk_id="document-1:0",
                        document_id="document-1",
                        text="A useful passage.",
                        metadata={"invalid": invalid},
                    )

    def test_numpy_like_scalars_normalize_before_timing_and_count_validation(self):
        result = RetrievalResult(
            status="success",
            query="steel",
            timings={"dense": ScalarArrayLike(0.25)},
            candidate_counts={"dense": ScalarArrayLike(2)},
        )

        self.assertIs(type(result.timings["dense"]), float)
        self.assertEqual(result.timings["dense"], 0.25)
        self.assertIs(type(result.candidate_counts["dense"]), int)
        self.assertEqual(result.candidate_counts["dense"], 2)


if __name__ == "__main__":
    unittest.main()
