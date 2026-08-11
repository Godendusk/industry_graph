import importlib
import json
import math
import tempfile
import threading
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from retrieval_core.lexical_store import LexicalStore
from retrieval_core.schemas import ChunkRecord


v2_index = importlib.import_module("report_generation.external_rag.v2_index")
IndexWriteResult = v2_index.IndexWriteResult
V2IndexWriter = v2_index.V2IndexWriter


def chunk(chunk_id="c1", document_id="m1", index=0, token_count=3):
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=index,
        text="text " + chunk_id,
        embedding_text="embed " + chunk_id,
        search_text="search " + chunk_id,
        token_count=token_count,
        content_hash="hash-" + chunk_id,
        metadata={"library": "policy", "material_id": document_id, "title": "T"},
    )


class FakeLexical:
    def __init__(self):
        self.documents = {}
        self.metadata = {}
        self.calls = []
        self.fail_replace = False
        self.fail_delete = False

    def replace_document(self, document_id, chunks):
        self.calls.append(("replace", document_id))
        if self.fail_replace:
            raise RuntimeError("secret lexical failure")
        self.documents[document_id] = {row.chunk_id: row for row in chunks}

    def delete_document(self, document_id):
        self.calls.append(("delete", document_id))
        if self.fail_delete:
            raise RuntimeError("secret lexical failure")
        self.documents.pop(document_id, None)

    def ids_for_document(self, document_id):
        return set(self.documents.get(document_id, {}))

    def all_chunk_ids(self):
        return {item for rows in self.documents.values() for item in rows}

    def count(self):
        return len(self.all_chunk_ids())

    def set_index_metadata(self, key, value):
        if value is None:
            self.metadata.pop(key, None)
        else:
            self.metadata[key] = value

    def get_index_metadata(self, key):
        return self.metadata.get(key)


class FakeDense:
    def __init__(self, dimension=768):
        self.documents = {}
        self.calls = []
        self.vector_dimension = dimension
        self.fail_upsert = False
        self.fail_delete = False

    def upsert_chunks(self, chunks, embeddings):
        self.calls.append(("upsert", tuple(c.chunk_id for c in chunks), embeddings))
        if self.fail_upsert:
            raise RuntimeError("secret dense failure")
        for row in chunks:
            self.documents.setdefault(row.document_id, set()).add(row.chunk_id)

    def delete_ids(self, ids):
        values = set(ids)
        self.calls.append(("delete_ids", tuple(sorted(values))))
        if self.fail_delete:
            raise RuntimeError("secret dense failure")
        for existing in self.documents.values():
            existing.difference_update(values)

    def delete_document(self, document_id):
        self.calls.append(("delete_document", document_id))
        if self.fail_delete:
            raise RuntimeError("secret dense failure")
        self.documents.pop(document_id, None)

    def ids_for_document(self, document_id):
        return set(self.documents.get(document_id, set()))

    def all_chunk_ids(self):
        return {item for rows in self.documents.values() for item in rows}

    def count(self):
        return len(self.all_chunk_ids())

    def dimension(self):
        return self.vector_dimension


def writer(dense=None, lexical=None, directory=None, **kwargs):
    dense = dense or FakeDense()
    lexical = lexical or FakeLexical()
    return V2IndexWriter(
        dense=dense,
        lexical=lexical,
        ready_path=None if directory is None else Path(directory) / "READY",
        embed_documents=lambda texts: [[float(i), 1.0] for i, _ in enumerate(texts)],
        model_version="model-1",
        chunker_version="chunker-1",
        dictionary_version="dict-1",
        **kwargs,
    )


class V2IndexWriterTests(unittest.TestCase):
    def test_result_is_immutable_and_successful_upsert_matches_ids(self):
        dense, lexical = FakeDense(), FakeLexical()
        subject = writer(dense, lexical)
        rows = [chunk("c1", index=0), chunk("c2", index=1)]

        result = subject.upsert_document("m1", rows)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.expected_ids, ("c1", "c2"))
        self.assertEqual(result.dense_ids, result.expected_ids)
        self.assertEqual(result.lexical_ids, result.expected_ids)
        with self.assertRaises(FrozenInstanceError):
            result.status = "error"

    def test_upsert_embeds_before_lexical_then_dense_and_deletes_only_stale_ids(self):
        events = []
        dense, lexical = FakeDense(), FakeLexical()
        dense.documents = {"m1": {"old", "c1"}, "other": {"protected"}}
        lexical.replace_document = lambda doc, rows: (
            events.append("lexical"),
            lexical.documents.__setitem__(doc, {r.chunk_id: r for r in rows}),
        )
        dense.upsert_chunks = lambda rows, vectors: (
            events.append(("dense", vectors)),
            dense.documents.__setitem__("m1", dense.documents["m1"] | {r.chunk_id for r in rows}),
        )
        dense.delete_ids = lambda ids: (
            events.append(("delete", tuple(ids))),
            dense.documents["m1"].difference_update(ids),
        )
        subject = V2IndexWriter(
            dense, lexical, embed_documents=lambda texts: events.append(("embed", tuple(texts))) or [[1.0, 2.0]]
        )

        result = subject.upsert_document("m1", [chunk()])

        self.assertEqual(result.status, "success")
        self.assertEqual(events[0], ("embed", ("embed c1",)))
        self.assertEqual(events[1], "lexical")
        self.assertEqual(events[2][0], "dense")
        self.assertEqual(events[3], ("delete", ("old",)))
        self.assertEqual(dense.documents["other"], {"protected"})

    def test_explicit_embeddings_are_validated_before_any_store_mutation(self):
        dense, lexical = FakeDense(), FakeLexical()
        subject = writer(dense, lexical)
        invalid_vectors = ([], [[1.0], [1.0, 2.0]], [[math.nan, 1.0]])
        for vectors in invalid_vectors:
            with self.subTest(vectors=vectors):
                result = subject.upsert_document("m1", [chunk()], embeddings=vectors)
                self.assertEqual(result.status, "error")
                self.assertEqual(lexical.calls, [])
                self.assertEqual(dense.calls, [])

    def test_embedding_failure_changes_no_store_and_records_safe_inconsistent_state(self):
        dense, lexical = FakeDense(), FakeLexical()
        subject = V2IndexWriter(
            dense, lexical, embed_documents=lambda texts: (_ for _ in ()).throw(RuntimeError("api-key-secret"))
        )

        result = subject.upsert_document("m1", [chunk()])

        self.assertEqual(result.status, "error")
        self.assertNotIn("api-key-secret", result.message)
        self.assertEqual(lexical.calls, [])
        self.assertEqual(dense.calls, [])
        self.assertEqual(json.loads(lexical.metadata[v2_index.INDEX_METADATA_KEY])["documents"]["m1"]["state"], "inconsistent")

    def test_rejects_invalid_duplicate_and_bounded_inputs_without_mutation(self):
        dense, lexical = FakeDense(), FakeLexical()
        subject = writer(dense, lexical, max_chunks=2, max_tokens=4)
        cases = [
            (" ", [chunk()]),
            ("m1", []),
            ("m1", [chunk("c1", index=0), chunk("c1", index=1)]),
            ("m1", [chunk("c1", index=0), chunk("c2", index=0)]),
            ("m1", [chunk(document_id="other")]),
            ("m1", [chunk(token_count=5)]),
            ("m1", (chunk(str(i), index=i) for i in range(3))),
        ]
        for document_id, rows in cases:
            with self.subTest(document_id=document_id, rows=rows):
                self.assertEqual(subject.upsert_document(document_id, rows).status, "error")
        self.assertEqual(lexical.calls, [])
        self.assertEqual(dense.calls, [])

    def test_does_not_mutate_input_sequences_or_chunks(self):
        rows = [chunk()]
        vectors = [[1.0, 2.0]]
        before_rows, before_vectors = list(rows), [list(v) for v in vectors]
        self.assertEqual(writer().upsert_document("m1", rows, vectors).status, "success")
        self.assertEqual(rows, before_rows)
        self.assertEqual(vectors, before_vectors)

    def test_dense_failure_after_lexical_is_inconsistent_and_later_upsert_repairs(self):
        dense, lexical = FakeDense(), FakeLexical()
        subject = writer(dense, lexical)
        dense.fail_upsert = True
        failed = subject.upsert_document("m1", [chunk()])
        self.assertEqual(failed.status, "inconsistent")
        self.assertEqual(lexical.ids_for_document("m1"), {"c1"})
        self.assertEqual(dense.ids_for_document("m1"), set())
        dense.fail_upsert = False
        repaired = subject.upsert_document("m1", [chunk()])
        self.assertEqual(repaired.status, "success")
        state = json.loads(lexical.metadata[v2_index.INDEX_METADATA_KEY])
        self.assertEqual(state["documents"]["m1"]["state"], "success")

    def test_mismatched_sets_are_inconsistent_and_not_ready(self):
        dense, lexical = FakeDense(), FakeLexical()
        subject = writer(dense, lexical)
        dense.upsert_chunks = lambda chunks, embeddings: None
        result = subject.upsert_document("m1", [chunk()])
        self.assertEqual(result.status, "inconsistent")
        self.assertFalse(subject.can_mark_ready(expected_dimension=768))
        self.assertIn("document_ids_mismatch", subject.check_ready(768).failures)

    def test_metadata_persists_across_writer_instances_and_concurrent_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            lexical = LexicalStore(Path(directory) / "lexical.sqlite3")
            dense = FakeDense()
            first = writer(dense, lexical, directory)
            second = writer(dense, lexical, directory)
            barrier = threading.Barrier(2)
            results = []

            def run(subject, document_id):
                barrier.wait()
                results.append(subject.upsert_document(document_id, [chunk(document_id + "-c", document_id)]))

            threads = [threading.Thread(target=run, args=(first, "d1")), threading.Thread(target=run, args=(second, "d2"))]
            for item in threads:
                item.start()
            for item in threads:
                item.join()
            state = json.loads(lexical.get_index_metadata(v2_index.INDEX_METADATA_KEY))
            self.assertEqual({r.status for r in results}, {"success"})
            self.assertEqual(set(state["documents"]), {"d1", "d2"})

    def test_delete_success_and_partial_failure_are_explicit(self):
        dense, lexical = FakeDense(), FakeLexical()
        subject = writer(dense, lexical)
        self.assertEqual(subject.upsert_document("m1", [chunk()]).status, "success")
        dense.fail_delete = True
        partial = subject.delete_document("m1")
        self.assertEqual(partial.status, "inconsistent")
        self.assertEqual(lexical.ids_for_document("m1"), set())
        self.assertEqual(dense.ids_for_document("m1"), {"c1"})
        dense.fail_delete = False
        self.assertEqual(subject.delete_document("m1").status, "success")
        self.assertNotIn("m1", json.loads(lexical.metadata[v2_index.INDEX_METADATA_KEY])["documents"])

    def test_ready_requires_dimension_global_ids_versions_and_valid_success_states(self):
        with tempfile.TemporaryDirectory() as directory:
            dense, lexical = FakeDense(), FakeLexical()
            subject = writer(dense, lexical, directory)
            self.assertEqual(subject.upsert_document("m1", [chunk()]).status, "success")
            self.assertTrue(subject.can_mark_ready(768, "model-1", "chunker-1", "dict-1"))
            dense.vector_dimension = None
            self.assertFalse(subject.can_mark_ready(768))
            dense.vector_dimension = 3
            self.assertFalse(subject.can_mark_ready(768))
            dense.vector_dimension = 768
            dense.documents["other"] = {"dense-only"}
            self.assertFalse(subject.can_mark_ready(768))
            dense.documents.pop("other")
            self.assertFalse(subject.can_mark_ready(768, "wrong", "chunker-1", "dict-1"))

    def test_missing_versions_malformed_metadata_and_malicious_store_iterable_fail_closed(self):
        dense, lexical = FakeDense(), FakeLexical()
        no_versions = V2IndexWriter(dense, lexical, embed_documents=lambda texts: [[1.0, 2.0]])
        self.assertEqual(no_versions.upsert_document("m1", [chunk()]).status, "success")
        self.assertFalse(no_versions.can_mark_ready(768))
        lexical.metadata[v2_index.INDEX_METADATA_KEY] = "{bad"
        self.assertFalse(no_versions.can_mark_ready(768))
        lexical.metadata[v2_index.INDEX_METADATA_KEY] = "[]"
        self.assertFalse(no_versions.can_mark_ready(768))
        dense.all_chunk_ids = lambda: (str(i) for i in range(v2_index.MAX_AUDIT_IDS + 1))
        self.assertFalse(no_versions.can_mark_ready(768))

    def test_malformed_persisted_state_blocks_upsert_before_store_mutation(self):
        dense, lexical = FakeDense(), FakeLexical()
        lexical.metadata[v2_index.INDEX_METADATA_KEY] = "{bad"
        subject = writer(dense, lexical)

        result = subject.upsert_document("m1", [chunk()])

        self.assertEqual(result.status, "error")
        self.assertEqual(lexical.calls, [])
        self.assertEqual(dense.calls, [])

    def test_ready_rejects_impossible_empty_state_and_invalid_store_counts(self):
        dense, lexical = FakeDense(), FakeLexical()
        subject = writer(dense, lexical)
        state = subject._empty_state()
        state["documents"]["m1"] = {
            "state": "success", "expected_ids": [], "max_token_count": 0, "message": "",
        }
        lexical.metadata[v2_index.INDEX_METADATA_KEY] = json.dumps(state)
        self.assertFalse(subject.can_mark_ready(768))
        state["documents"] = {}
        lexical.metadata[v2_index.INDEX_METADATA_KEY] = json.dumps(state)
        dense.count = lambda: True
        self.assertFalse(subject.can_mark_ready(768))

    def test_configured_token_limit_has_a_fixed_safety_ceiling(self):
        with self.assertRaisesRegex(ValueError, "max_tokens"):
            V2IndexWriter(FakeDense(), FakeLexical(), max_tokens=v2_index.MAX_TOKEN_HARD_CAP + 1)

    def test_mark_ready_is_atomic_deterministic_and_validate_helper_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            dense, lexical = FakeDense(), FakeLexical()
            subject = writer(dense, lexical, directory)
            subject.upsert_document("m1", [chunk()])
            payload = subject.mark_ready(768, "model-1", "chunker-1", "dict-1")
            ready_path = Path(directory) / "READY"
            self.assertEqual(json.loads(ready_path.read_text()), payload)
            self.assertEqual(payload["chunk_count"], 1)
            self.assertEqual(len(payload["id_digest"]), 64)
            self.assertTrue(subject.validate_ready_marker())
            self.assertEqual(list(Path(directory).glob(".READY.*.tmp")), [])
            ready_path.write_text("{}")
            self.assertFalse(subject.validate_ready_marker())

    def test_failed_mark_ready_never_creates_or_overwrites_marker_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            dense, lexical = FakeDense(), FakeLexical()
            subject = writer(dense, lexical, directory)
            subject.upsert_document("m1", [chunk()])
            subject.mark_ready(768, "model-1", "chunker-1", "dict-1")
            ready_path = Path(directory) / "READY"
            original = ready_path.read_bytes()
            dense.vector_dimension = 4
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                subject.mark_ready(768)
            self.assertEqual(ready_path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob(".READY.*.tmp")), [])

    def test_real_dense_store_requires_embeddings_but_audit_only_mock_can_use_existing_ids(self):
        from retrieval_core.dense_store import DenseStore

        lexical = FakeLexical()
        real = DenseStore(collection=object())
        result = V2IndexWriter(real, lexical).upsert_document("m1", [chunk()])
        self.assertEqual(result.status, "error")
        dense = FakeDense()
        dense.documents["m1"] = {"c1"}
        audit = V2IndexWriter(dense, lexical, audit_only=True)
        self.assertEqual(audit.upsert_document("m1", [chunk()]).status, "success")

    def test_approved_injected_mock_example_auto_audits_existing_dense_ids(self):
        dense, lexical = FakeDense(), FakeLexical()
        dense.documents["m1"] = {"c1", "c2"}
        subject = V2IndexWriter(dense=dense, lexical=lexical)

        result = subject.upsert_document(
            "m1", [chunk("c1", index=0), chunk("c2", index=1)]
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(dense.calls, [])


if __name__ == "__main__":
    unittest.main()
