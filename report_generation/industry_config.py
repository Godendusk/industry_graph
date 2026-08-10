"""Shared industry configuration for report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VECTOR_DB_ROOT = PROJECT_ROOT / "report_generation" / "vector_db"

INDUSTRY_CONFIG: Dict[str, dict] = {
    "ai": {
        "name": "人工智能",
        "graph_path": PROJECT_ROOT / "static" / "data" / "ai" / "graph_data.json",
        "vector_db_path": VECTOR_DB_ROOT / "ai",
        "external_column_id": "2008715487928750081",
    },
    "embodied": {
        "name": "具身智能",
        "graph_path": PROJECT_ROOT / "static" / "data" / "embodied" / "graph_data.json",
        "vector_db_path": VECTOR_DB_ROOT / "embodied",
        "external_column_id": None,
    },
    "low_altitude": {
        "name": "低空经济",
        "graph_path": PROJECT_ROOT / "static" / "data" / "low_altitude" / "graph_data.json",
        "vector_db_path": VECTOR_DB_ROOT / "low_altitude",
        "external_column_id": None,
    },
    "sea": {
        "name": "海洋经济",
        "graph_path": PROJECT_ROOT / "static" / "data" / "sea" / "graph_data.json",
        "vector_db_path": VECTOR_DB_ROOT / "sea",
        "external_column_id": None,
    },
    "quantum": {
        "name": "量子科技",
        "graph_path": PROJECT_ROOT / "static" / "data" / "quantum" / "graph_data.json",
        "vector_db_path": VECTOR_DB_ROOT / "quantum",
        "external_column_id": None,
    },
    "biology": {
        "name": "生物制造",
        "graph_path": PROJECT_ROOT / "static" / "data" / "biology" / "graph_data.json",
        "vector_db_path": VECTOR_DB_ROOT / "biology",
        "external_column_id": None,
    },
    "brain": {
        "name": "脑机接口",
        "graph_path": PROJECT_ROOT / "static" / "data" / "brain" / "graph_data.json",
        "vector_db_path": VECTOR_DB_ROOT / "brain",
        "external_column_id": None,
    },
    "material": {
        "name": "新材料",
        "graph_path": PROJECT_ROOT / "static" / "data" / "material" / "graph_data.json",
        "vector_db_path": VECTOR_DB_ROOT / "material",
        "external_column_id": None,
    },
}

SUPPORTED_INDUSTRIES = {
    industry: config["name"] for industry, config in INDUSTRY_CONFIG.items()
}


def get_industry_config(industry: str) -> dict:
    normalized = str(industry or "").strip()
    config = INDUSTRY_CONFIG.get(normalized)
    if config is None:
        raise ValueError(f"unsupported industry: {normalized or '(empty)'}")
    return config


def get_vector_db_path(industry: str) -> Path:
    return Path(get_industry_config(industry)["vector_db_path"])
