"""Isolated Chroma storage for embodied-intelligence news chunks."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VECTOR_DB_DIR = PROJECT_ROOT / "RAG" / "vector_db_embodied"
MODEL_PATH = PROJECT_ROOT / "RAG" / "model_store" / "bge-base-zh-v1.5"
COLLECTION_NAME = "embodied_news"
BATCH_SIZE = 64

_MODEL: Any = None
_MODEL_LOCK = Lock()


def _device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _get_model() -> Any:
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                from sentence_transformers import SentenceTransformer

                if not MODEL_PATH.is_dir():
                    raise FileNotFoundError(f"embedding model not found: {MODEL_PATH}")
                _MODEL = SentenceTransformer(str(MODEL_PATH), device=_device())
    return _MODEL


class EmbodiedNewsStore:
    """Persistent Chroma collection using the 768-dimensional local BGE model."""

    def __init__(
        self,
        db_dir: Path | str = VECTOR_DB_DIR,
        model_path: Path | str = MODEL_PATH,
        embedding_batch_size: int = BATCH_SIZE,
    ):
        self.db_dir = Path(db_dir)
        self.model_path = Path(model_path)
        self.embedding_batch_size = max(1, int(embedding_batch_size))
        self.db_dir.mkdir(parents=True, exist_ok=True)
        import chromadb

        self.client = chromadb.PersistentClient(path=str(self.db_dir))
        self.collection = self.client.get_or_create_collection(name=COLLECTION_NAME)

    def upsert(self, chunks: Iterable[Dict[str, Any]]) -> int:
        records = list(chunks)
        if not records:
            return 0
        model = _get_model() if self.model_path == MODEL_PATH else self._load_custom_model()
        ids = [str(item["id"]) for item in records]
        documents = [str(item["document"]) for item in records]
        metadatas = [dict(item["metadata"]) for item in records]
        embeddings: List[Any] = []
        for start in range(0, len(documents), self.embedding_batch_size):
            embeddings.extend(
                model.encode(
                    documents[start : start + self.embedding_batch_size],
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            )
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=[vector.tolist() if hasattr(vector, "tolist") else list(vector) for vector in embeddings],
        )
        return len(records)

    def _load_custom_model(self) -> Any:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(str(self.model_path), device=_device())

    def query(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        model = _get_model() if self.model_path == MODEL_PATH else self._load_custom_model()
        vector = model.encode(
            [str(query)], normalize_embeddings=True, show_progress_bar=False
        )
        count = self.collection.count()
        if not count:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        return self.collection.query(
            query_embeddings=[vector[0].tolist() if hasattr(vector[0], "tolist") else list(vector[0])],
            n_results=min(max(1, int(top_k)), count),
            include=["documents", "metadatas", "distances"],
        )

    def count(self) -> int:
        return self.collection.count()

    def prune_sources(self, source_ids: set[str]) -> int:
        """Remove chunks belonging to sources outside the current feed snapshot."""
        existing = self.collection.get(include=["metadatas"])
        stale_ids = [
            vector_id
            for vector_id, metadata in zip(
                existing.get("ids") or [], existing.get("metadatas") or []
            )
            if not isinstance(metadata, dict) or str(metadata.get("source_id", "")) not in source_ids
        ]
        if stale_ids:
            self.collection.delete(ids=stale_ids)
        return len(stale_ids)


def query_embodied_news(query: str, top_k: int = 10) -> Dict[str, Any]:
    return EmbodiedNewsStore().query(query, top_k=top_k)
