"""Chroma vector store wrapper for external report materials."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List

from .client import EXTERNAL_LIBRARIES


REPORT_GENERATION_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPORT_GENERATION_DIR.parent
VECTOR_DB_DIR = PROJECT_ROOT / "RAG" / "vector_db"  # 报告五库：report_*_ai
MODEL_PATH = PROJECT_ROOT / "RAG" / "models"
BATCH_SIZE = 128
# 限制嵌入模型使用的 CPU 线程数，避免编码时 CPU 占用过高（默认 4 线程）
MAX_ENCODE_THREADS = 4

# 在模块导入时立即设置线程限制，确保在 numpy/torch 等库加载前生效
# Docker 环境中若未设置这些变量，BLAS 后端会使用全部 CPU 核心
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_var] = os.environ.get(_var, str(MAX_ENCODE_THREADS))

_embedding_model: Any = None
_embedding_model_lock = Lock()
_chroma_client: Any = None
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
                from sentence_transformers import SentenceTransformer

                _embedding_model = SentenceTransformer(str(MODEL_PATH), device=_device())
    return _embedding_model


def get_chroma_client():
    global _chroma_client

    if _chroma_client is None:
        with _chroma_client_lock:
            if _chroma_client is None:
                import chromadb

                VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
                _chroma_client = chromadb.PersistentClient(path=str(VECTOR_DB_DIR))
    return _chroma_client


def get_collection(library: str):
    if library not in EXTERNAL_LIBRARIES:
        raise ValueError(f"Unknown external library: {library}")
    collection_name = EXTERNAL_LIBRARIES[library]["collection"]
    return get_chroma_client().get_or_create_collection(name=collection_name)


def build_paragraph_ids(library: str, material_id: str, paragraph_count: int) -> List[str]:
    return [
        f"external:{library}:{material_id}:p:{index}"
        for index in range(paragraph_count)
    ]


def delete_existing_material(library: str, material_id: str, old_chunk_count: int) -> None:
    if old_chunk_count <= 0:
        return
    collection = get_collection(library)
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
) -> List[str]:
    if not paragraphs:
        return []
    if len(paragraphs) != len(metadatas):
        raise ValueError("paragraphs and metadatas length mismatch")

    collection = get_collection(library)
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
