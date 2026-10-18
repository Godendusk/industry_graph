import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from report_generation.external_rag.news_index import (
    NewsLexicalStore, build_news_index, check_news_index, news_metadata,
)
from report_generation.external_rag.news_retrieval import (
    NewsDenseStore, pipeline_response, retrieve_news_hybrid,
)
from report_generation.external_rag.retriever import retrieve_external_rag
from report_generation.industry_config import INDUSTRY_CONFIG
from retrieval_core.schemas import RetrievalCandidate, RetrievalResult


class NewsIndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "source.sqlite3"
        self.root = Path(self.temporary.name) / "index"
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.executescript("""
                CREATE TABLE collections(id TEXT,name TEXT,dimension INTEGER);
                CREATE TABLE segments(id TEXT,collection TEXT,scope TEXT);
                CREATE TABLE embeddings(id INTEGER PRIMARY KEY,segment_id TEXT,embedding_id TEXT);
                CREATE TABLE embedding_metadata(id INTEGER,key TEXT,string_value TEXT,
                    int_value INTEGER,float_value REAL,bool_value INTEGER,PRIMARY KEY(id,key));
                INSERT INTO collections VALUES('c','brain_news',768);
                INSERT INTO segments VALUES('s','c','METADATA');
            """)
        self.add_row(1, "a:0", "a", "脑机接口临床试验，患者通过接口控制机械臂。", 0)
        self.add_row(2, "a:1", "a", "脑机接口推动患者康复。", 1)
        self.add_row(3, "b:0", "b", "神经信号解码技术取得进展。", 0)

    def add_row(self, row_id, chunk_id, source_id, text, index):
        metadata = {"chroma:document": text, "source_id": source_id, "chunk_index": index,
                    "title": "脑机接口研究", "url": "https://example.test/" + source_id,
                    "publish_date": "2026-10-01"}
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?,?)", (row_id, "s", chunk_id))
            for key, value in metadata.items():
                connection.execute("INSERT OR REPLACE INTO embedding_metadata(id,key,string_value,int_value) "
                                   "VALUES(?,?,?,?)", (row_id, key, value if isinstance(value, str) else None,
                                                       value if isinstance(value, int) else None))

    def build(self, action="build", **kwargs):
        return build_news_index("brain", root=self.root, source_path=self.source,
                                action=action, batch_size=1, **kwargs)

    def test_build_preserves_ids_sources_and_chinese_keyword_matches(self):
        result = self.build()
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["documents"], 2)
        self.assertEqual(check_news_index("brain", self.root, self.source)["status"], "ready")
        rows = NewsLexicalStore("brain", self.root, self.source).search("患者康复", 3)
        self.assertTrue(rows)
        self.assertEqual(rows[0].document_id, "a")
        self.assertIn(rows[0].chunk_id, {"a:0", "a:1"})
        self.assertEqual(rows[0].metadata["source_address"], "https://example.test/a")
        self.assertEqual(rows[0].metadata["classification_name"], "脑机接口专题资讯")
        self.assertEqual(NewsLexicalStore("brain", self.root, self.source).search("接口", 3, ["sea_news"]), [])

    def test_resume_committed_checkpoint_and_reject_changed_source(self):
        def interrupt(_):
            raise RuntimeError("interrupted")

        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.build(progress=interrupt)
        self.assertFalse((self.root / "READY").exists())
        result = self.build("resume")
        self.assertEqual(result["count"], 3)
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.build(progress=interrupt)
        self.add_row(4, "d:0", "d", "新的患者康复试验", 0)
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.build("resume")

    def test_keywords_cover_whole_news_but_return_original_chunk_ids(self):
        self.add_row(1, "a:0", "a", "alpha topic", 0)
        self.add_row(2, "a:1", "a", "beta topic beta", 1)
        self.build()
        with closing(sqlite3.connect(self.root / "lexical.sqlite3")) as connection:
            rows = connection.execute(
                "SELECT d.document_id FROM news_document_fts f JOIN news_documents d ON d.rowid=f.rowid "
                "WHERE news_document_fts MATCH ?", ('"alpha" AND "beta"',)
            ).fetchall()
        self.assertEqual(rows, [("a",)])
        candidates = NewsLexicalStore("brain", self.root, self.source).search("alpha beta", 5)
        self.assertEqual([row.chunk_id for row in candidates], ["a:1"])

    def test_sync_updates_deletes_and_reuses_unchanged_rows(self):
        self.build()
        self.add_row(1, "a:0", "a", "脑机接口视觉重建成功。", 0)
        self.add_row(4, "d:0", "d", "新的患者康复试验", 0)
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute("DELETE FROM embeddings WHERE id=3")
            connection.execute("DELETE FROM embedding_metadata WHERE id=3")
        self.assertEqual(check_news_index("brain", self.root, self.source)["status"], "not_ready")
        result = self.build("sync")
        self.assertEqual(result["count"], 3)
        with closing(sqlite3.connect(self.root / "lexical.sqlite3")) as connection:
            self.assertEqual({row[0] for row in connection.execute("SELECT chunk_id FROM chunks")}, {"a:0", "a:1", "d:0"})
        with patch("report_generation.external_rag.news_index._tokenize_record", side_effect=AssertionError("retokenized")):
            self.assertEqual(self.build("sync")["digest"], result["digest"])
        rows = NewsLexicalStore("brain", self.root, self.source).search("视觉重建", 3)
        self.assertEqual(rows[0].chunk_id, "a:0")

    def test_invalid_dimension_empty_text_and_wrong_industry_fail_closed(self):
        self.build()
        marker = json.loads((self.root / "READY").read_text(encoding="utf-8"))
        marker["industry"] = "sea"
        (self.root / "READY").write_text(json.dumps(marker), encoding="utf-8")
        self.assertEqual(check_news_index("brain", self.root, self.source)["status"], "not_ready")
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute("UPDATE collections SET dimension=384")
        with self.assertRaisesRegex(ValueError, "768 dimensions"):
            self.build()
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute("UPDATE collections SET dimension=768")
            connection.execute("DELETE FROM embedding_metadata WHERE key='chroma:document' AND id=1")
        with self.assertRaisesRegex(ValueError, "empty news text"):
            self.build()

    def test_chroma_maintenance_does_not_invalidate_but_new_sequence_does(self):
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.executescript("""
                CREATE TABLE max_seq_id(segment_id TEXT,seq_id INTEGER);
                INSERT INTO max_seq_id VALUES('s',3);
                CREATE TABLE embeddings_queue(seq_id INTEGER);
                INSERT INTO embeddings_queue VALUES(3);
            """)
        self.build()
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute("CREATE TABLE maintenance_noise(value INTEGER)")
            connection.execute("DELETE FROM embeddings_queue")
        self.assertEqual(check_news_index("brain", self.root, self.source)["status"], "ready")
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute("INSERT INTO embeddings_queue VALUES(4)")
        self.assertEqual(check_news_index("brain", self.root, self.source)["status"], "not_ready")

    def test_source_url_alias_is_preserved(self):
        metadata = news_metadata("brain", "s:0", {"source_id": "s", "source_url": "https://example.test/s"})
        self.assertEqual(metadata["source_address"], "https://example.test/s")


class NewsRetrievalTests(unittest.TestCase):
    def test_all_industries_default_to_their_hybrid_adapter(self):
        for industry in INDUSTRY_CONFIG:
            with self.subTest(industry=industry), patch.dict(os.environ, {}, clear=True), patch(
                "report_generation.external_rag.retriever._retrieve_hybrid", return_value={"status": "success"}
            ) as ai, patch("report_generation.external_rag.retriever._retrieve_news_hybrid",
                          return_value={"status": "success"}) as news:
                result = retrieve_external_rag("test", 3, industry)
                self.assertEqual(result["industry"], industry)
                (ai if industry == "ai" else news).assert_called_once()
                (news if industry == "ai" else ai).assert_not_called()

    def test_news_failure_is_returned_without_switching_industry_or_stores(self):
        with patch("report_generation.external_rag.retriever._retrieve_news_hybrid",
                   return_value={"status": "error", "message": "missing index"}):
            result = retrieve_external_rag("test", 3, "sea")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["industry"], "sea")
        self.assertEqual(result["message"], "missing index")
        self.assertNotIn("retrieval_fallback", result)

    def test_dense_validation_mapping_and_library_isolation(self):
        collection = Mock()
        collection.count.return_value = 1
        collection.query.return_value = {"ids": [["s:0"]], "documents": [["新闻正文"]],
            "metadatas": [[{"source_id": "s", "url": "https://example.test/s", "chunk_index": 0}]],
            "distances": [[0.2]]}
        store = NewsDenseStore("sea", collection)
        with self.assertRaisesRegex(ValueError, "768"):
            store.search([0] * 384, 3)
        rows = store.search([1] + [0] * 767, 3, ["sea_news"])
        self.assertEqual(rows[0].chunk_id, "s:0")
        self.assertEqual(rows[0].metadata["source_address"], "https://example.test/s")
        self.assertEqual(store.search([1] + [0] * 767, 3, ["brain_news"]), [])
        collection.query.assert_called_once()

    def test_hybrid_fuses_same_ids_and_exposes_reranker_failure(self):
        metadata = news_metadata("brain", "s:0", {"source_id": "s", "chunk_index": 0, "url": "https://example.test/s"})
        dense = RetrievalCandidate("s:0", "s", "脑机接口临床应用", metadata, dense_rank=1, dense_distance=0.2)
        lexical = RetrievalCandidate("s:0", "s", "脑机接口临床应用", metadata, bm25_rank=1, bm25_score=-2)
        models = Mock()
        models.embed_documents.return_value = [[1] + [0] * 767]
        models.rerank_pairs.return_value = [0.8]
        with patch("report_generation.external_rag.news_retrieval.check_news_index", return_value={"status": "ready"}), patch(
            "report_generation.external_rag.news_retrieval.local_models", return_value=models
        ), patch.object(NewsDenseStore, "search", return_value=[dense]), patch.object(
            NewsLexicalStore, "search", return_value=[lexical]
        ):
            result = retrieve_news_hybrid("脑机接口", 3, "brain")
            self.assertEqual(result["retrieval_version"], "hybrid_v2")
            self.assertEqual(len(result["evidence_blocks"]), 1)
            block = result["evidence_blocks"][0]
            self.assertEqual(block["dense_rank"], 1)
            self.assertEqual(block["bm25_rank"], 1)
            self.assertEqual(block["rerank_score"], 0.8)
            models.embed_documents.assert_called_with(["脑机接口"])
            models.rerank_pairs.side_effect = RuntimeError("missing reranker")
            result = retrieve_news_hybrid("脑机接口", 3, "brain")
            self.assertEqual(result["retrieval_version"], "hybrid_v2_degraded")
            self.assertEqual(result["diagnostics"]["stages"]["rerank"], "failed")
            self.assertTrue(result["evidence_blocks"])

    def test_no_evidence_is_explicit(self):
        result = pipeline_response("brain", "query", 3, RetrievalResult("success", "query"))
        self.assertEqual(result["warnings"][0]["code"], "rag_no_evidence")

    def test_writing_task_reserves_budget_for_visible_json(self):
        from report_generation import writing_decisions
        from llm_client import LLMQueryResult

        task = {"outline_id": "S1.1", "title": "Status", "external_rag_retrieval": {
            "evidence_blocks": [{"citation_id": "C1"}], "rag_context_text": "[C1] Source evidence"}}
        decision = writing_decisions.fallback_decision(task)
        response = LLMQueryResult(content=json.dumps(decision), finish_reason="stop")
        with patch.object(writing_decisions.llm, "query_result", return_value=response) as query:
            result = writing_decisions.request_decision(
                task=task, user_prompt="Write a brief report", report_title="Report",
                outline_context="", previous_tasks=[], outline_ids={"S1.1"},
            )
        self.assertEqual(result["status"], "generated")
        self.assertIsNone(query.call_args.kwargs["reasoning_effort"])
        self.assertEqual(query.call_args.kwargs["extra_body"], {"thinking": {"type": "disabled"}})

    def test_each_industry_evidence_reaches_writing_prompt_and_registered_citation(self):
        from report_generation import coordinator_agent

        outline = [{"section_type": "body", "level1_id": "S1", "level1_title": "现状",
                    "subsections": [{"outline_id": "S1.1", "title": "发展情况"}]}]
        for industry, config in INDUSTRY_CONFIG.items():
            with self.subTest(industry=industry):
                block = {"library": config.get("collection_name", "policy"), "material_id": "s",
                         "vector_id": "s:0", "title": config["name"] + "资料", "text": "真实证据正文",
                         "source_address": "https://example.test/source", "publish_date": "2026-10-01"}

                def prompt(**kwargs):
                    task = kwargs["task"]
                    context = task["external_rag_retrieval"]["rag_context_text"]
                    self.assertIn("真实证据正文", context)
                    self.assertIn("[C1]", context)
                    decision = coordinator_agent.fallback_decision(task)
                    decision["evidence_uses"] = [{"topic": "Source evidence", "basis": "external",
                        "citation_ids": ["C1"], "use": "Support this section", "support_limit": ""}]
                    return {"status": "generated", "decision": decision, "warnings": []}

                with patch.object(coordinator_agent, "retrieve_external_rag", return_value={
                    "status": "success", "industry": industry, "retrieval_version": "hybrid_v2",
                    "evidence_blocks": [block], "rag_context_text": "真实证据正文", "warnings": []
                }), patch.object(coordinator_agent, "request_decision", side_effect=prompt), patch.object(
                    coordinator_agent, "coordinate_writing_tasks",
                    side_effect=lambda tasks, **kwargs: (tasks, {"status": "completed", "outline_operations": []}, []),
                ):
                    result = coordinator_agent.generate_writing_tasks(
                        "生成产业报告", config["name"] + "报告", outline, industry=industry,
                        top_k=1, use_graph=False, max_workers=1,
                    )
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["references"][0]["source_address"], "https://example.test/source")
                task = result["writing_tasks"][0]
                self.assertIn("C1", task["writing_system_prompt"])
                self.assertEqual(task["writing_decision"]["evidence_uses"][0]["citation_ids"], ["C1"])


if __name__ == "__main__":
    unittest.main()
