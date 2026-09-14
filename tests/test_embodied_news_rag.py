import importlib
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def fake_response(payload, status_code=200):
    response = SimpleNamespace(status_code=status_code, text=str(payload))
    response.raise_for_status = lambda: None
    response.json = lambda: payload
    return response


def load_module(test_case, name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        test_case.fail(f"feature module is missing: {exc}")


class EmbodiedNewsClientTest(unittest.TestCase):
    def test_list_news_uses_embodied_subject_payload(self):
        module = load_module(self, "report_generation.external_rag.embodied_client")
        with patch.object(module.requests, "post") as post:
            post.return_value = fake_response(
                {"code": 200, "result": {"records": [], "total": 0}}
            )
            client = module.EmbodiedNewsClient(
                access_token="access", x_access_token="x-access"
            )

            result = client.list_news(page_no=1, page_size=100)

        payload = post.call_args.kwargs["json"]
        self.assertEqual(result["total"], 0)
        self.assertEqual(payload["subjectId"], "2043590589800853505")
        self.assertEqual(payload["pageNo"], 1)
        self.assertEqual(payload["pageSize"], 100)
        self.assertEqual(payload["status"], 1)
        self.assertIn("content", payload["fetchFields"])
        self.assertEqual(payload["column"], "publishDate")
        self.assertEqual(payload["order"], "desc")

    def test_detail_uses_source_id_and_subject_index(self):
        module = load_module(self, "report_generation.external_rag.embodied_client")
        with patch.object(module.requests, "get") as get:
            get.return_value = fake_response(
                {"code": 200, "result": {"id": "source-id", "content": "正文"}}
            )
            result = module.EmbodiedNewsClient(
                access_token="access", x_access_token="x-access"
            ).get_detail("source-id")

        self.assertEqual(result["id"], "source-id")
        self.assertEqual(get.call_args.kwargs["params"], {
            "id": "source-id",
            "index": "subjectdatabase_2026",
        })

    def test_business_failure_raises_client_error(self):
        module = load_module(self, "report_generation.external_rag.embodied_client")
        with patch.object(module.requests, "post") as post:
            post.return_value = fake_response(
                {"code": 401, "message": "Token失效，请重新登录"}
            )
            client = module.EmbodiedNewsClient(
                access_token="access", x_access_token="x-access"
            )

            with self.assertRaises(module.EmbodiedNewsClientError) as raised:
                client.list_news(page_no=1, page_size=100)

        self.assertIn("Token失效", str(raised.exception))

    def test_missing_environment_tokens_fail_before_request(self):
        module = load_module(self, "report_generation.external_rag.embodied_client")
        with patch.dict(os.environ, {}, clear=True), patch.object(module.requests, "post") as post:
            with self.assertRaises(module.EmbodiedNewsClientError):
                module.EmbodiedNewsClient()
            post.assert_not_called()


class EmbodiedIngestionTest(unittest.TestCase):
    def test_ingestion_falls_back_to_list_record_when_detail_is_empty(self):
        module = load_module(self, "report_generation.external_rag.embodied_ingestion")

        class FakeClient:
            def list_news(self, page_no, page_size):
                return {
                    "records": [
                        {
                            "id": "list-only",
                            "title": "列表标题",
                            "summary": "列表摘要可以用于检索。",
                            "content": "",
                        }
                    ],
                    "total": 1,
                }

            def get_detail(self, source_id):
                raise module.EmbodiedNewsClientError("queryById returned empty body")

        class FakeStore:
            def __init__(self):
                self.chunks = []

            def upsert(self, chunks):
                self.chunks.extend(chunks)
                return len(chunks)

            def count(self):
                return len(self.chunks)

        store = FakeStore()
        stats = module.ingest_latest_news(client=FakeClient(), store=store, limit=1)

        self.assertEqual(stats["chunks_written"], 1)
        self.assertEqual(stats["detail_fallbacks"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["status"], "partial_success")
        self.assertIn("列表摘要可以用于检索", store.chunks[0]["document"])

    def test_ingestion_skips_empty_detail_and_upserts_stable_chunks(self):
        module = load_module(self, "report_generation.external_rag.embodied_ingestion")

        class FakeClient:
            def list_news(self, page_no, page_size):
                return {
                    "records": [
                        {"id": "a", "title": "标题", "summary": "摘要"},
                        {"id": "b", "title": "空正文", "summary": ""},
                    ],
                    "total": 2,
                }

            def get_detail(self, source_id):
                return {
                    "a": {"id": "a", "title": "标题", "content": "第一段。第二段。"},
                    "b": {"id": "b", "title": "空正文", "content": ""},
                }[source_id]

        class FakeStore:
            def __init__(self):
                self.ids = []

            def upsert(self, chunks):
                self.ids.extend(chunk["id"] for chunk in chunks)
                return len(chunks)

            def count(self):
                return len(self.ids)

            def prune_sources(self, source_ids):
                return 0

        store = FakeStore()
        stats = module.ingest_latest_news(client=FakeClient(), store=store, limit=2)

        self.assertEqual(stats["records_seen"], 2)
        self.assertEqual(stats["details_succeeded"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertGreater(stats["chunks_written"], 0)
        self.assertEqual(store.ids, ["a:0"])

    def test_chunking_removes_html_and_keeps_chunk_ids_stable(self):
        module = load_module(self, "report_generation.external_rag.embodied_ingestion")
        raw = "<p>第一段内容</p><p>第二段内容</p>"

        chunks = module.build_chunks(
            {"id": "source-id", "title": "标题", "content": raw},
            subject_id="2043590589800853505",
        )

        self.assertEqual(chunks[0]["id"], "source-id:0")
        self.assertNotIn("<p>", chunks[0]["document"])
        self.assertEqual(chunks[0]["metadata"]["subject_id"], "2043590589800853505")

    def test_chunking_repairs_surrogate_pair_emojis_for_tokenizer(self):
        module = load_module(self, "report_generation.external_rag.embodied_ingestion")
        raw = "机器人\ud83e\udd16完成测试。"

        chunks = module.build_chunks(
            {"id": "emoji-source", "title": "标题", "content": raw},
            subject_id="2043590589800853505",
        )

        document = chunks[0]["document"]
        self.assertNotRegex(document, r"[\ud800-\udfff]")
        self.assertIn("🤖", document)


class EmbodiedRoutingTest(unittest.TestCase):
    def test_embodied_route_queries_only_embodied_collection(self):
        module = load_module(self, "report_generation.external_rag.retriever")
        with patch.object(
            module,
            "retrieve_embodied_news",
            return_value={"status": "success", "evidence_blocks": []},
        ) as embodied:
            result = module.retrieve_external_rag(
                "具身智能机器人进展", top_k=5, industry="embodied"
            )

        self.assertEqual(result["status"], "success")
        embodied.assert_called_once_with("具身智能机器人进展", 5)

    def test_unknown_industry_returns_error_without_ai_fallback(self):
        module = load_module(self, "report_generation.external_rag.retriever")
        result = module.retrieve_external_rag("查询", industry="unknown")

        self.assertEqual(result["status"], "error")
        self.assertIn("unsupported industry", result["message"])


class EmbodiedStoreTest(unittest.TestCase):
    def test_store_uses_isolated_path_and_768_dimension_model(self):
        module = load_module(self, "report_generation.external_rag.embodied_store")
        self.assertEqual(module.COLLECTION_NAME, "embodied_news")
        self.assertEqual(module.MODEL_PATH.name, "bge-base-zh-v1.5")
        self.assertEqual(module.VECTOR_DB_DIR.name, "vector_db_embodied")

    def test_device_prefers_mps_when_cuda_is_unavailable(self):
        module = load_module(self, "report_generation.external_rag.embodied_store")
        import torch

        with patch.object(torch.cuda, "is_available", return_value=False), patch.object(
            torch.backends.mps, "is_available", return_value=True
        ):
            self.assertEqual(module._device(), "mps")

    def test_device_falls_back_to_cpu_when_accelerators_are_unavailable(self):
        module = load_module(self, "report_generation.external_rag.embodied_store")
        import torch

        with patch.object(torch.cuda, "is_available", return_value=False), patch.object(
            torch.backends.mps, "is_available", return_value=False
        ):
            self.assertEqual(module._device(), "cpu")

    def test_device_prefers_cuda_over_mps(self):
        module = load_module(self, "report_generation.external_rag.embodied_store")
        import torch

        with patch.object(torch.cuda, "is_available", return_value=True), patch.object(
            torch.backends.mps, "is_available", return_value=True
        ):
            self.assertEqual(module._device(), "cuda")

    def test_store_encodes_configured_batch_size_and_writes_once(self):
        module = load_module(self, "report_generation.external_rag.embodied_store")
        encode_batch_sizes = []

        class FakeModel:
            def encode(self, documents, **kwargs):
                encode_batch_sizes.append(len(documents))
                return [[float(index)] for index, _ in enumerate(documents)]

        class FakeCollection:
            def __init__(self):
                self.upsert_calls = []

            def upsert(self, **kwargs):
                self.upsert_calls.append(kwargs)

        store = module.EmbodiedNewsStore.__new__(module.EmbodiedNewsStore)
        store.model_path = module.MODEL_PATH
        store.embedding_batch_size = 2
        store.collection = FakeCollection()

        with patch.object(module, "_get_model", return_value=FakeModel()):
            written = store.upsert([
                {"id": "a:0", "document": "甲", "metadata": {"source_id": "a"}},
                {"id": "b:0", "document": "乙", "metadata": {"source_id": "b"}},
                {"id": "c:0", "document": "丙", "metadata": {"source_id": "c"}},
            ])

        self.assertEqual(written, 3)
        self.assertEqual(encode_batch_sizes, [2, 1])
        self.assertEqual(len(store.collection.upsert_calls), 1)


class EmbodiedReportRoutingTest(unittest.TestCase):
    def test_graph_route_selects_embodied_graph_file(self):
        module = load_module(self, "report_generation.graph_retriever")
        fake_graph = object()
        with patch.object(module, "_AIGraph", return_value=fake_graph) as graph_loader, patch.object(
            module,
            "_select_level3_with_llm",
            return_value={"status": "error", "message": "test stop"},
        ):
            result = module.retrieve_graph("查询", industry="embodied")

        graph_loader.assert_called_once_with(module.GRAPH_PATHS["embodied"])
        self.assertEqual(result["industry"], "embodied")

    def test_all_report_agents_accept_embodied_industry(self):
        for module_name in (
            "report_generation.outline_agent",
            "report_generation.coordinator_agent",
            "report_generation.body_agent",
            "report_generation.summary_agent",
            "report_generation.rewrite_agent",
            "report_generation.word_export_agent",
        ):
            module = load_module(self, module_name)
            self.assertEqual(module.SUPPORTED_INDUSTRIES["embodied"], "具身智能")

    def test_outline_external_retrieval_passes_industry(self):
        module = load_module(self, "report_generation.outline_agent")
        with patch.object(
            module,
            "retrieve_external_rag",
            return_value={"status": "success", "evidence_blocks": []},
        ) as retrieve:
            module._retrieve_external_rag_for_section(
                "查询", "S1", [], [], industry="embodied"
            )
        retrieve.assert_called_once_with("查询", top_k=10, industry="embodied")

    def test_coordinator_external_retrieval_passes_industry(self):
        module = load_module(self, "report_generation.coordinator_agent")
        with patch.object(
            module,
            "retrieve_external_rag",
            return_value={"status": "success", "evidence_blocks": []},
        ) as retrieve:
            module._retrieve_external_rag_for_subsection(
                "查询", 5, "S1", [], [], industry="embodied"
            )
        retrieve.assert_called_once_with("查询", top_k=5, industry="embodied")

    def test_rewrite_external_retrieval_passes_industry(self):
        module = load_module(self, "report_generation.rewrite_agent")
        with patch.object(
            module,
            "retrieve_external_rag",
            return_value={"status": "success", "evidence_blocks": []},
        ) as retrieve:
            module._retrieve_external_rag_for_rewrite(
                "查询", 5, [], industry="embodied"
            )
        retrieve.assert_called_once_with("查询", top_k=5, industry="embodied")


if __name__ == "__main__":
    unittest.main()
