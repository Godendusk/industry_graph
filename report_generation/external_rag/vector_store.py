"""Chroma vector store wrapper for external report materials."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Dict, List

from .client import get_external_libraries
from ..industry_config import get_vector_db_path


REPORT_GENERATION_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPORT_GENERATION_DIR.parent
VECTOR_DB_DIR = REPORT_GENERATION_DIR / "vector_db"
MODEL_PATH = PROJECT_ROOT / "RAG" / "models"
BATCH_SIZE = 128
# 限制嵌入模型使用的 CPU 线程数，避免编码时 CPU 占用过高（默认 4 线程）
MAX_ENCODE_THREADS = 4

_embedding_model: Any = None
_embedding_model_lock = Lock()
_chroma_clients: Dict[str, Any] = {}
_chroma_client_lock = Lock()


def _device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def get_embedding_model():
    global _embedding_model

    if _embedding_model is None:
        with _embedding_model_lock:
            if _embedding_model is None:
                try:
                    import torch

                    torch.set_num_threads(MAX_ENCODE_THREADS)
                except Exception:
                    pass
                from sentence_transformers import SentenceTransformer

                _embedding_model = SentenceTransformer(str(MODEL_PATH), device=_device())
    return _embedding_model


def get_chroma_client(industry: str = "ai"):
    normalized_industry = str(industry or "").strip()
    if normalized_industry not in _chroma_clients:
        with _chroma_client_lock:
            if normalized_industry not in _chroma_clients:
                import chromadb

                vector_db_path = get_vector_db_path(normalized_industry)
                vector_db_path.mkdir(parents=True, exist_ok=True)
                try:
                    chroma_path = vector_db_path.relative_to(Path.cwd())
                except ValueError:
                    chroma_path = vector_db_path
                _chroma_clients[normalized_industry] = chromadb.PersistentClient(
                    path=str(chroma_path)
                )
    return _chroma_clients[normalized_industry]


def has_vector_store(industry: str) -> bool:
    return (get_vector_db_path(industry) / "chroma.sqlite3").is_file()


def get_collection(library: str, industry: str = "ai"):
    libraries = get_external_libraries(industry)
    if library not in libraries:
        raise ValueError(f"Unknown external library: {library}")
    collection_name = libraries[library]["collection"]
    return get_chroma_client(industry).get_or_create_collection(name=collection_name)


def build_paragraph_ids(library: str, material_id: str, paragraph_count: int) -> List[str]:
    return [
        f"external:{library}:{material_id}:p:{index}"
        for index in range(paragraph_count)
    ]


def delete_existing_material(library: str, material_id: str, old_chunk_count: int, industry: str = "ai") -> None:
    if old_chunk_count <= 0:
        return
    collection = get_collection(library, industry=industry)
    old_ids = build_paragraph_ids(library, material_id, old_chunk_count)
    try:
        collection.delete(ids=old_ids)
    except Exception:
        # Missing ids are harmless for idempotent ingestion.
        return


def upsert_paragraphs(
    library: str,
    material_id: str,
    paragraphs: List[str],
    metadatas: List[Dict[str, Any]],
    industry: str = "ai",
) -> List[str]:
    if not paragraphs:
        return []
    if len(paragraphs) != len(metadatas):
        raise ValueError("paragraphs and metadatas length mismatch")

    collection = get_collection(library, industry=industry)
    ids = build_paragraph_ids(library, material_id, len(paragraphs))
    model = get_embedding_model()

    # 分批编码，避免一次性处理大量段落导致 CPU/内存峰值
    all_embeddings = []
    for start in range(0, len(paragraphs), BATCH_SIZE):
        batch = paragraphs[start:start + BATCH_SIZE]
        batch_embeddings = model.encode(
            batch,
            show_progress_bar=False,
            batch_size=BATCH_SIZE,
            device=_device(),
        )
        all_embeddings.extend(batch_embeddings)

    collection.upsert(
        ids=ids,
        documents=paragraphs,
        metadatas=metadatas,
        embeddings=[e.tolist() if hasattr(e, "tolist") else list(e) for e in all_embeddings],
    )
    return ids
