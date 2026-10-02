from pathlib import Path
from tempfile import TemporaryDirectory

from report_generation.task_card_agent import _external_rag_available


def test_news_store_does_not_require_external_column_id():
    with TemporaryDirectory() as tmpdir:
        vector_db_path = Path(tmpdir)
        config = {"rag_type": "news", "vector_db_path": vector_db_path}
        (vector_db_path / "chroma.sqlite3").write_text("", encoding="utf-8")
        assert _external_rag_available(config)


def test_report_store_requires_external_column_id_and_database():
    with TemporaryDirectory() as tmpdir:
        vector_db_path = Path(tmpdir)
        config = {
            "rag_type": "report",
            "external_column_id": "column-1",
            "vector_db_path": vector_db_path,
        }
        assert not _external_rag_available(config)
        (vector_db_path / "chroma.sqlite3").write_text("", encoding="utf-8")
        assert _external_rag_available(config)
        config["external_column_id"] = ""
        assert not _external_rag_available(config)
