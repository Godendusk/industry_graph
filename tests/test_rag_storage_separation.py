import importlib
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
from docx import Document

from report_generation.industry_config import get_vector_db_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _database_stats(directory: Path) -> tuple[set[str], int]:
    database_path = directory / "chroma.sqlite3"
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        collections = {
            row[0]
            for row in connection.execute("SELECT name FROM collections")
        }
        embedding_count = connection.execute(
            "SELECT COUNT(*) FROM embeddings"
        ).fetchone()[0]
    finally:
        connection.close()
    return collections, embedding_count


class RagStorageSeparationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qa_rag = importlib.import_module("RAG.build_vector_db")
        cls.report_rag = importlib.import_module(
            "report_generation.external_rag.vector_store"
        )

    def test_default_directories_are_separate_and_follow_industry_configuration(self):
        self.assertEqual(self.qa_rag.DB_DIR, PROJECT_ROOT / "RAG" / "vector_db_QA")
        self.assertEqual(
            self.report_rag.VECTOR_DB_DIR,
            PROJECT_ROOT / "report_generation" / "vector_db" / "ai",
        )
        self.assertNotEqual(self.qa_rag.DB_DIR, self.report_rag.VECTOR_DB_DIR)

    def test_building_stores_keeps_qa_and_report_collections_separate(self):
        # 实际构建两个小型持久库，验证路由隔离；仅替换嵌入模型，不依赖本机语料。
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            qa_dir, report_dir = root / "qa", root / "report"
            knowledge_dir = root / "docs"
            knowledge_dir.mkdir()
            document = Document()
            document.add_paragraph("这是一条用于验证问答库与产业报告库隔离的测试资料。")
            document.save(knowledge_dir / "sample.docx")
            with patch.object(self.qa_rag, "DB_DIR", qa_dir), \
                 patch.object(self.qa_rag, "KNOWLEDGE_DIR", knowledge_dir), \
                 patch.object(self.qa_rag, "PROGRESS_FILE", root / "progress.json"), \
                 patch.object(self.qa_rag, "SentenceTransformer") as model:
                model.return_value.encode.side_effect = lambda chunks, **kwargs: np.array(
                    [[1.0, 0.0, 0.0] for _ in chunks]
                )
                self.qa_rag.build_vector_db()

            with patch.object(self.report_rag, "get_vector_db_path", return_value=report_dir), \
                 patch.dict(self.report_rag._chroma_clients, {}, clear=True):
                for library in ("policy", "speech", "expert_view", "company_case", "research_report"):
                    collection = self.report_rag.get_collection(library, industry="ai")
                    collection.add(
                        ids=[f"test-{library}"],
                        documents=[f"用于验证{library}集合隔离的测试资料。"],
                        embeddings=[[1.0, 0.0, 0.0]],
                    )

            qa_collections, qa_count = _database_stats(qa_dir)
            report_collections, report_count = _database_stats(report_dir)
            self.assertEqual(qa_collections, {"knowledge_base"})
            self.assertEqual(report_collections, {
                "report_policy_ai", "report_speech_ai", "report_expert_view_ai",
                "report_company_case_ai", "report_research_report_ai",
            })
            self.assertEqual(qa_count, 1)
            self.assertEqual(report_count, 5)
            self.assertTrue(qa_collections.isdisjoint(report_collections))


if __name__ == "__main__":
    unittest.main()
