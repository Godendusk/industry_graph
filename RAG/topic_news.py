"""Query the six local industry news collections with their original BGE model."""

from __future__ import annotations

from pathlib import Path

from report_generation.industry_config import INDUSTRY_CONFIG


TOPIC_NEWS_COLLECTIONS = {
    industry: (config["vector_db_path"], config["collection_name"])
    for industry, config in INDUSTRY_CONFIG.items()
    if config.get("rag_type") == "news" and industry != "embodied"
}


def query_topic_news(query: str, industry: str, top_k: int = 5) -> dict:
    if industry not in TOPIC_NEWS_COLLECTIONS:
        raise ValueError(f"unsupported news industry: {industry}")
    db_dir, collection_name = TOPIC_NEWS_COLLECTIONS[industry]
    if not db_dir.is_dir():
        raise FileNotFoundError(f"news vector database not found: {db_dir}")

    import chromadb
    from report_generation.external_rag.embodied_store import _encode_with_fallback, _get_model

    collection = chromadb.PersistentClient(path=str(db_dir)).get_collection(collection_name)
    count = collection.count()
    if not count:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    vector = _encode_with_fallback(_get_model(), [str(query)])[0]
    embedding = vector.tolist() if hasattr(vector, "tolist") else list(vector)
    return collection.query(
        query_embeddings=[embedding],
        n_results=min(max(1, int(top_k)), count),
        include=["documents", "metadatas", "distances"],
    )
