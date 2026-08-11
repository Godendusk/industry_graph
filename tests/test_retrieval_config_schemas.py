import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retrieval_core import (
    ChunkRecord,
    RetrievalCandidate,
    RetrievalConfig,
    RetrievalResult,
)


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


if __name__ == "__main__":
    unittest.main()
