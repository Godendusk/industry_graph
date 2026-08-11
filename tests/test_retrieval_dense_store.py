import copy
import importlib.util
import tempfile
import threading
import time
import unittest
from pathlib import Path

from retrieval_core.dense_store import COLLECTION_NAME, DenseStore
from retrieval_core.schemas import ChunkRecord


def chunk(chunk_id="c1", document_id="d1", index=0, **metadata):
    values = {
        "library": "policy",
        "material_id": "m1",
        "title": "材料",
        "section_path": ("第一章", "进展"),
        "nested": {"b": 2, "a": [1, True]},
        "nullable": None,
    }
    values.update(metadata)
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=index,
        text=f"正文 {chunk_id}",
        embedding_text=f"嵌入 {chunk_id}",
        search_text=f"检索 {chunk_id}",
        token_count=3,
        content_hash=f"hash-{chunk_id}",
        metadata=values,
    )


class FakeCollection:
    def __init__(self, *, metadata_marker=False, metadata=None, configuration=None):
        self.upsert_calls = []
        self.delete_calls = []
        self.query_calls = []
        self.get_calls = []
        self.query_result = {}
        self.get_handler = None
        self.item_count = 0
        if metadata_marker:
            self.metadata = metadata
        if configuration is not None:
            self.configuration = configuration

    def upsert(self, **kwargs):
        self.upsert_calls.append(copy.deepcopy(kwargs))

    def delete(self, **kwargs):
        self.delete_calls.append(copy.deepcopy(kwargs))

    def query(self, **kwargs):
        self.query_calls.append(copy.deepcopy(kwargs))
        return copy.deepcopy(self.query_result)

    def get(self, **kwargs):
        self.get_calls.append(copy.deepcopy(kwargs))
        if self.get_handler is not None:
            return self.get_handler(**kwargs)
        return {"ids": []}

    def count(self):
        return self.item_count


class FakeClient:
    def __init__(self, collection):
        self.collection = collection
        self.calls = []

    def get_or_create_collection(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return self.collection


class DenseStoreTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("chromadb"), "chromadb is not installed")
    def test_temporary_chroma_roundtrip_is_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "chroma"
            store = DenseStore(path=path, batch_size=2, page_size=1)
            self.assertFalse(path.exists())

            store.upsert_chunks(
                [chunk("c1", index=0), chunk("c2", index=1, library="expert_view")],
                [[1.0, 0.0], [0.0, 1.0]],
            )

            self.assertTrue(path.exists())
            self.assertEqual(store.count(), 2)
            self.assertEqual(store.dimension(), 2)
            self.assertEqual(store.all_chunk_ids(), {"c1", "c2"})
            self.assertEqual(
                [result.chunk_id for result in store.search([1.0, 0.0], 2)],
                ["c1", "c2"],
            )
            store.delete_ids(["c1", "not-present"])
            self.assertEqual(store.all_chunk_ids(), {"c2"})

    def test_collection_is_lazy_and_configured_for_cosine(self):
        collection = FakeCollection(
            metadata_marker=True, metadata={"hnsw:space": "cosine"}
        )
        client = FakeClient(collection)
        paths = []
        store = DenseStore(
            path=Path("/virtual/chroma"), client_factory=lambda path: paths.append(path) or client
        )
        self.assertEqual(paths, [])

        self.assertEqual(store.count(), 0)

        self.assertEqual(paths, [Path("/virtual/chroma")])
        self.assertEqual(
            client.calls,
            [{"name": COLLECTION_NAME, "metadata": {"hnsw:space": "cosine"}}],
        )
        self.assertEqual(COLLECTION_NAME, "report_external_v2")

    def test_lazy_collection_rejects_explicit_non_cosine_metadata(self):
        collection = FakeCollection(
            metadata_marker=True, metadata={"hnsw:space": "l2"}
        )
        store = DenseStore(
            path=Path("/virtual/chroma"),
            client_factory=lambda path: FakeClient(collection),
        )

        with self.assertRaisesRegex(ValueError, "report_external_v2.*l2.*cosine"):
            store.count()

    def test_injected_collection_rejects_explicit_non_cosine_metadata(self):
        collection = FakeCollection(
            metadata_marker=True, metadata={"hnsw:space": "l2"}
        )

        with self.assertRaisesRegex(ValueError, "report_external_v2.*l2.*cosine"):
            DenseStore(collection=collection)

    def test_lazy_collection_validates_modern_configuration_and_allows_opaque_fake(self):
        cosine = FakeCollection(configuration={"hnsw": {"space": "cosine"}})
        cosine_store = DenseStore(
            path=Path("/virtual/cosine"),
            client_factory=lambda path: FakeClient(cosine),
        )
        self.assertEqual(cosine_store.count(), 0)

        inner_product = FakeCollection(
            configuration={"hnsw_configuration": {"space": "ip"}}
        )
        ip_store = DenseStore(
            path=Path("/virtual/ip"),
            client_factory=lambda path: FakeClient(inner_product),
        )
        with self.assertRaisesRegex(ValueError, "report_external_v2.*ip.*cosine"):
            ip_store.count()

        opaque_store = DenseStore(
            path=Path("/virtual/opaque"),
            client_factory=lambda path: FakeClient(FakeCollection()),
        )
        self.assertEqual(opaque_store.count(), 0)

    def test_lazy_collection_rejects_non_cosine_configuration_despite_metadata(self):
        collection = FakeCollection(
            metadata_marker=True,
            metadata={"hnsw:space": "cosine"},
            configuration={"hnsw_configuration": {"space": "l2"}},
        )
        store = DenseStore(
            path=Path("/virtual/chroma"),
            client_factory=lambda path: FakeClient(collection),
        )

        with self.assertRaisesRegex(ValueError, "report_external_v2.*l2.*cosine"):
            store.count()

    def test_lazy_collection_rejects_non_cosine_spann_configuration(self):
        collection = FakeCollection(configuration={"spann": {"space": "l2"}})
        store = DenseStore(
            path=Path("/virtual/chroma"),
            client_factory=lambda path: FakeClient(collection),
        )

        with self.assertRaisesRegex(ValueError, "report_external_v2.*l2.*cosine"):
            store.count()

    def test_concurrent_first_access_initializes_one_client_and_collection(self):
        collection = FakeCollection(
            metadata_marker=True, metadata={"hnsw:space": "cosine"}
        )
        client = FakeClient(collection)
        factory_calls = []
        errors = []

        def factory(path):
            factory_calls.append(path)
            time.sleep(0.03)
            return client

        store = DenseStore(path=Path("/virtual/chroma"), client_factory=factory)
        barrier = threading.Barrier(8)

        def access():
            try:
                barrier.wait()
                self.assertEqual(store.count(), 0)
            except BaseException as error:  # assertion below reports worker failures
                errors.append(error)

        threads = [threading.Thread(target=access) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(factory_calls, [Path("/virtual/chroma")])
        self.assertEqual(len(client.calls), 1)
        self.assertIs(store._client, client)
        self.assertIs(store._collection_value, collection)

    def test_collection_retry_reuses_client_after_acquisition_failure(self):
        collection = FakeCollection(
            metadata_marker=True, metadata={"hnsw:space": "cosine"}
        )

        class FlakyClient:
            def __init__(self):
                self.calls = 0

            def get_or_create_collection(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("temporary collection failure")
                return collection

        client = FlakyClient()
        factory_calls = []
        store = DenseStore(
            path=Path("/virtual/chroma"),
            client_factory=lambda path: factory_calls.append(path) or client,
        )

        with self.assertRaisesRegex(RuntimeError, "temporary collection failure"):
            store.count()
        self.assertEqual(store.count(), 0)
        self.assertEqual(factory_calls, [Path("/virtual/chroma")])
        self.assertEqual(client.calls, 2)
        self.assertIs(store._client, client)

    def test_upsert_writes_explicit_vectors_text_and_safe_metadata_in_batches(self):
        collection = FakeCollection()
        store = DenseStore(collection=collection, batch_size=2)
        chunks = [chunk("c1", index=0), chunk("c2", index=1), chunk("c3", index=2)]
        embeddings = [[1, 0], [0.5, 0.5], [0, 1]]
        metadata_before = [dict(item.metadata) for item in chunks]
        embeddings_before = copy.deepcopy(embeddings)

        store.upsert_chunks(chunks, embeddings)

        self.assertEqual([call["ids"] for call in collection.upsert_calls], [["c1", "c2"], ["c3"]])
        self.assertEqual(collection.upsert_calls[0]["documents"], ["正文 c1", "正文 c2"])
        self.assertEqual(collection.upsert_calls[0]["embeddings"], [[1.0, 0.0], [0.5, 0.5]])
        first_metadata = collection.upsert_calls[0]["metadatas"][0]
        self.assertEqual(first_metadata["document_id"], "d1")
        self.assertEqual(first_metadata["chunk_index"], 0)
        self.assertEqual(first_metadata["library"], "policy")
        self.assertIsInstance(first_metadata["section_path"], str)
        self.assertIsInstance(first_metadata["nested"], str)
        self.assertIsInstance(first_metadata["nullable"], str)
        self.assertEqual([dict(item.metadata) for item in chunks], metadata_before)
        self.assertEqual(embeddings, embeddings_before)

    def test_upsert_validates_lengths_dimensions_values_and_batch_size(self):
        store = DenseStore(collection=FakeCollection())
        invalid_cases = [
            ([], [], "nonempty"),
            ([chunk()], [], "same length"),
            ([chunk()], [[]], "nonempty vector"),
            ([chunk("a"), chunk("b")], [[1, 2], [3]], "dimension"),
            ([chunk()], [[1, True]], "numeric"),
        ]
        for chunks, embeddings, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    store.upsert_chunks(chunks, embeddings)
        with self.assertRaisesRegex(ValueError, "batch_size"):
            DenseStore(collection=FakeCollection(), batch_size=0)

    def test_search_passes_exact_query_arguments_and_single_library_filter(self):
        collection = FakeCollection()
        collection.query_result = {
            "ids": [["c1"]],
            "documents": [["正文"]],
            "metadatas": [[{"document_id": "d1", "material_id": "m1", "library": "policy"}]],
            "distances": [[0.2]],
        }
        store = DenseStore(collection=collection)

        result = store.search([0.1, 0.2], 4, libraries={"policy"})

        self.assertEqual(
            collection.query_calls,
            [{
                "query_embeddings": [[0.1, 0.2]],
                "n_results": 4,
                "where": {"library": "policy"},
                "include": ["documents", "metadatas", "distances"],
            }],
        )
        self.assertEqual(result[0].chunk_id, "c1")
        self.assertEqual(result[0].document_id, "d1")
        self.assertEqual(result[0].dense_rank, 1)
        self.assertAlmostEqual(result[0].dense_distance, 0.2)
        self.assertAlmostEqual(result[0].dense_score, 0.8)
        self.assertEqual(result[0].diagnostics["dense_distance"], 0.2)

    def test_search_sorts_multi_library_filter_and_restores_complex_metadata(self):
        collection = FakeCollection()
        source = chunk()
        store = DenseStore(collection=collection)
        store.upsert_chunks([source], [[1.0, 0.0]])
        encoded = collection.upsert_calls[0]["metadatas"][0]
        collection.query_result = {
            "ids": [["c1", "c2"]],
            "documents": [["one", "two"]],
            "metadatas": [[encoded, {"material_id": "fallback-doc"}]],
            "distances": [[0.1, 0.4]],
        }

        results = store.search([1, 0], 3, libraries=["z", "a", "z"])

        self.assertEqual(
            collection.query_calls[0]["where"], {"library": {"$in": ["a", "z"]}}
        )
        self.assertEqual([item.chunk_id for item in results], ["c1", "c2"])
        self.assertEqual(results[0].metadata["section_path"], ("第一章", "进展"))
        self.assertEqual(results[0].metadata["nested"], {"a": [1, True], "b": 2})
        self.assertIsNone(results[0].metadata["nullable"])
        self.assertEqual(results[1].document_id, "fallback-doc")

    def test_metadata_prefix_string_cannot_collide_with_encoded_values(self):
        collection = FakeCollection()
        store = DenseStore(collection=collection)
        original = '__retrieval_core_json_v1__:["scalar","not-original"]'
        store.upsert_chunks([chunk(marker=original)], [[1.0]])
        encoded = collection.upsert_calls[0]["metadatas"][0]
        collection.query_result = {
            "ids": [["c1"]],
            "documents": [["正文"]],
            "metadatas": [[encoded]],
            "distances": [[0.0]],
        }

        self.assertEqual(store.search([1.0], 1)[0].metadata["marker"], original)

    def test_search_handles_empty_and_malformed_results_without_reordering(self):
        collection = FakeCollection()
        store = DenseStore(collection=collection)
        for malformed in ({}, {"ids": None}, {"ids": []}, {"ids": [[]]}):
            collection.query_result = malformed
            with self.subTest(malformed=malformed):
                self.assertEqual(store.search([1.0], 2), [])

        collection.query_result = {
            "ids": [["good", None, "missing-distance"]],
            "documents": [["text", "ignored"]],
            "metadatas": [[{"document_id": "d"}, {}]],
            "distances": [[0.5]],
        }
        results = store.search([1.0], 5)
        self.assertEqual([item.chunk_id for item in results], ["good"])

    def test_search_validates_vector_limit_and_libraries(self):
        collection = FakeCollection()
        store = DenseStore(collection=collection)
        cases = [([], 1, None, "nonempty"), ([1.0], 0, None, "limit"), ([True], 1, None, "numeric")]
        for vector, limit, libraries, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    store.search(vector, limit, libraries)
        with self.assertRaisesRegex(ValueError, "libraries"):
            store.search([1.0], 1, libraries=[1])
        self.assertEqual(store.search([1.0], 1, libraries=[]), [])
        self.assertEqual(collection.query_calls, [])

    def test_delete_ids_is_batched_and_empty_or_missing_is_harmless(self):
        collection = FakeCollection()
        store = DenseStore(collection=collection, batch_size=2)
        store.delete_ids([])
        store.delete_ids(["missing", "c2", "c3"])
        self.assertEqual(collection.delete_calls, [{"ids": ["missing", "c2"]}, {"ids": ["c3"]}])

    def test_delete_document_uses_an_exact_document_filter(self):
        collection = FakeCollection()
        store = DenseStore(collection=collection)

        store.delete_document("d1")

        self.assertEqual(collection.delete_calls, [{"where": {"document_id": "d1"}}])

    def test_delete_document_rejects_blank_or_non_string_ids(self):
        collection = FakeCollection()
        store = DenseStore(collection=collection)

        for document_id in ("", "   ", None, 1):
            with self.subTest(document_id=document_id):
                with self.assertRaisesRegex(ValueError, "document_id"):
                    store.delete_document(document_id)

        self.assertEqual(collection.delete_calls, [])

    def test_ids_queries_paginate_and_document_filter_is_exact(self):
        collection = FakeCollection()
        store = DenseStore(collection=collection, page_size=2)

        def get_handler(**kwargs):
            pages = {0: ["c1", "c2"], 2: ["c3"], 4: []}
            return {"ids": pages.get(kwargs.get("offset", 0), [])}

        collection.get_handler = get_handler
        self.assertEqual(store.all_chunk_ids(), {"c1", "c2", "c3"})
        self.assertEqual(
            collection.get_calls,
            [{"limit": 2, "offset": 0, "include": []}, {"limit": 2, "offset": 2, "include": []}],
        )
        collection.get_calls.clear()
        self.assertEqual(store.ids_for_document("d1"), {"c1", "c2", "c3"})
        self.assertEqual(collection.get_calls[0]["where"], {"document_id": "d1"})

    def test_count_and_dimension_are_robust_for_empty_and_vector_results(self):
        collection = FakeCollection()
        store = DenseStore(collection=collection)
        self.assertEqual(store.count(), 0)
        self.assertIsNone(store.dimension())

        collection.item_count = 1
        collection.get_handler = lambda **kwargs: {"ids": ["c1"], "embeddings": [[1.0, 2.0, 3.0]]}
        self.assertEqual(store.count(), 1)
        self.assertEqual(store.dimension(), 3)


if __name__ == "__main__":
    unittest.main()
