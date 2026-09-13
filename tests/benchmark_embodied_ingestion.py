"""Benchmark embodied-news embedding and Chroma writes on a local sample.

This is an executable benchmark, not a pytest test. It reads up to 1000 existing
embodied-news chunks and writes only to a temporary Chroma directory.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from report_generation.external_rag.embodied_store import MODEL_PATH, VECTOR_DB_DIR, _device


def _load_sample(source_db: Path, limit: int) -> tuple[list[str], list[dict]]:
    import chromadb

    client = chromadb.PersistentClient(path=str(source_db))
    collection = client.get_collection("embodied_news")
    rows = collection.get(limit=limit, include=["documents", "metadatas"])
    documents = [str(value) for value in rows.get("documents") or []]
    metadatas = [dict(value or {}) for value in rows.get("metadatas") or []]
    if len(documents) != len(metadatas):
        raise RuntimeError("sample documents and metadata have different lengths")
    if not documents:
        raise RuntimeError("source collection has no documents")
    return documents, metadatas


def run_benchmark(
    documents: list[str],
    metadatas: list[dict],
    device: str,
    batch_size: int,
    model_path: Path = MODEL_PATH,
) -> dict:
    import chromadb
    from sentence_transformers import SentenceTransformer

    started = time.perf_counter()
    model = SentenceTransformer(str(model_path), device=device)
    model_loaded = time.perf_counter()

    embeddings = []
    for start in range(0, len(documents), batch_size):
        vectors = model.encode(
            documents[start : start + batch_size],
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        embeddings.extend(vector.tolist() for vector in vectors)
    encoded = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="embodied-benchmark-") as temporary:
        client = chromadb.PersistentClient(path=temporary)
        collection = client.get_or_create_collection(name="benchmark_embodied_news")
        collection.upsert(
            ids=[f"benchmark:{index}" for index in range(len(documents))],
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        written = collection.count()
    written_at = time.perf_counter()

    return {
        "device": device,
        "batch_size": batch_size,
        "documents": len(documents),
        "embedding_dimension": len(embeddings[0]),
        "written": written,
        "model_load_seconds": round(model_loaded - started, 3),
        "embedding_seconds": round(encoded - model_loaded, 3),
        "chroma_upsert_seconds": round(written_at - encoded, 3),
        "total_seconds": round(written_at - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, default=VECTOR_DB_DIR)
    parser.add_argument("--model-path", type=Path, default=MODEL_PATH)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda", "auto"), default="auto")
    args = parser.parse_args()
    if args.limit <= 0 or args.batch_size <= 0:
        parser.error("--limit and --batch-size must be positive")
    device = _device() if args.device == "auto" else args.device
    documents, metadatas = _load_sample(args.source_db, args.limit)
    print(json.dumps(
        run_benchmark(documents, metadatas, device, args.batch_size, args.model_path),
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
