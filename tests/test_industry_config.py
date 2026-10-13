from pathlib import Path

from report_generation.industry_config import INDUSTRY_CONFIG
from RAG.topic_news import TOPIC_NEWS_COLLECTIONS


def test_report_industries_use_rag_vector_db_root():
    expected = {
        "ai": "ai",
        "embodied": "embodied",
        "low_altitude": "low_altitude",
        "sea": "sea",
        "quantum": "quantum",
        "biology": "biology",
        "brain": "brain",
        "material": "material",
    }
    for industry, dirname in expected.items():
        config = INDUSTRY_CONFIG[industry]
        assert Path(config["vector_db_path"]).name == dirname
        assert Path(config["vector_db_path"]).parent.name == "vector_db"
        assert Path(config["vector_db_path"]).parent.parent.name == "report_generation"


def test_qa_database_is_not_report_industry():
    assert "QA" not in INDUSTRY_CONFIG
    assert "qa" not in INDUSTRY_CONFIG


def test_news_collections_are_configured_once():
    for industry in ("embodied", "low_altitude", "sea", "quantum", "biology", "brain", "material"):
        config = INDUSTRY_CONFIG[industry]
        assert config["rag_type"] == "news"
        assert config["collection_name"] == f"{industry}_news"
        assert "news_vector_db_path" not in config


def test_topic_news_mapping_uses_industry_configuration():
    for industry in ("low_altitude", "sea", "quantum", "biology", "brain", "material"):
        path, collection_name = TOPIC_NEWS_COLLECTIONS[industry]
        assert path == INDUSTRY_CONFIG[industry]["vector_db_path"]
        assert collection_name == INDUSTRY_CONFIG[industry]["collection_name"]
