"""Configuration for report retrieval."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RetrievalConfig:
    project_root: Path
    index_root: Path
    embedding_model_path: Path
    reranker_model_path: Path
    dense_limit: int = 40
    lexical_limit: int = 40
    rerank_limit: int = 24
    final_limit: int = 10
    rrf_k: int = 60

    @classmethod
    def for_project(cls, project_root: Path) -> "RetrievalConfig":
        root = Path(project_root).resolve()
        return cls(
            project_root=root,
            index_root=root / "RAG" / "indexes" / "report_v2",
            embedding_model_path=root
            / "RAG"
            / "model_store"
            / "bge-base-zh-v1.5",
            reranker_model_path=root
            / "RAG"
            / "model_store"
            / "bge-reranker-base",
        )
