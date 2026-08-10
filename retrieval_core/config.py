"""Configuration for report retrieval."""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class RetrievalConfig:
    project_root: Path
    mode: str
    index_root: Path
    embedding_model_path: Path
    reranker_model_path: Path
    dense_limit: int = 40
    lexical_limit: int = 40
    rerank_limit: int = 24
    final_limit: int = 10
    rrf_k: int = 60
    allow_legacy_fallback: bool = True

    @classmethod
    def for_project(cls, project_root: Path) -> "RetrievalConfig":
        root = Path(project_root).resolve()
        mode = os.environ.get("REPORT_RETRIEVAL_MODE", "legacy")
        supported_modes = {"legacy", "compare", "hybrid_v2"}
        if mode not in supported_modes:
            raise ValueError(
                f"Unsupported REPORT_RETRIEVAL_MODE {mode!r}; "
                f"expected one of {sorted(supported_modes)}"
            )

        return cls(
            project_root=root,
            mode=mode,
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
