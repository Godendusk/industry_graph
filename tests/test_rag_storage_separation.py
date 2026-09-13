import importlib
import sqlite3
import sys
import types
import unittest
from pathlib import Path


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
        cls.original_llm_client = sys.modules.get("llm_client")
        sys.modules["llm_client"] = types.SimpleNamespace(llm=object())
        cls.qa_rag = importlib.import_module("RAG.build_vector_db")
        cls.report_rag = importlib.import_module(
            "report_generation.external_rag.vector_store"
        )

    @classmethod
    def tearDownClass(cls):
        if cls.original_llm_client is None:
            sys.modules.pop("llm_client", None)
        else:
            sys.modules["llm_client"] = cls.original_llm_client

    def test_default_directories_are_separate_and_match_existing_data(self):
        self.assertEqual(self.qa_rag.DB_DIR, PROJECT_ROOT / "RAG" / "vector_db1")
        self.assertEqual(
            self.report_rag.VECTOR_DB_DIR,
            PROJECT_ROOT / "RAG" / "vector_db",
        )
        self.assertNotEqual(self.qa_rag.DB_DIR, self.report_rag.VECTOR_DB_DIR)

    def test_default_directories_contain_expected_collections(self):
        qa_collections, qa_embedding_count = _database_stats(self.qa_rag.DB_DIR)
        report_collections, report_embedding_count = _database_stats(
            self.report_rag.VECTOR_DB_DIR
        )
        self.assertIn("knowledge_base", qa_collections)
        self.assertGreater(qa_embedding_count, 0)
        self.assertTrue(
            {
                "report_policy_ai",
                "report_speech_ai",
                "report_expert_view_ai",
                "report_company_case_ai",
                "report_research_report_ai",
            }.issubset(report_collections)
        )
        self.assertGreater(report_embedding_count, 0)


if __name__ == "__main__":
    unittest.main()
