"""Industry-isolated adapters for existing 768-dimensional news collections."""

from functools import lru_cache, partial
import math

from ..industry_config import PROJECT_ROOT, get_industry_config
from .news_index import NewsLexicalStore, check_news_index, news_metadata
from .report_adapter import build_rag_context_text, to_evidence_blocks
from .vector_store import get_chroma_client
from retrieval_core.config import RetrievalConfig
from retrieval_core.model_manager import ModelManager
from retrieval_core.pipeline import HybridRetrievalPipeline
from retrieval_core.reranker import rerank_candidates
from retrieval_core.schemas import RetrievalCandidate


@lru_cache(maxsize=1)
def local_models() -> ModelManager:
    config = RetrievalConfig.for_project(PROJECT_ROOT)
    return ModelManager(config.embedding_model_path, config.reranker_model_path)


class NewsDenseStore:
    def __init__(self, industry: str, collection=None):
        self.industry = industry
        config = get_industry_config(industry)
        if config.get("rag_type") != "news":
            raise ValueError("news retrieval requires a news industry")
        self.collection_name = config["collection_name"]
        self._collection = collection

    @property
    def collection(self):
        if self._collection is None:
            self._collection = get_chroma_client(self.industry).get_collection(self.collection_name)
        return self._collection

    def search(self, vector, limit: int, libraries=None) -> list[RetrievalCandidate]:
        if len(vector) != 768 or not all(math.isfinite(float(item)) for item in vector):
            raise ValueError("news query embedding must have 768 finite dimensions")
        if libraries is not None and self.collection_name not in libraries:
            return []
        count = self.collection.count()
        if not count:
            return []
        results = self.collection.query(query_embeddings=[vector], n_results=min(limit, count),
                                        include=["documents", "metadatas", "distances"])
        ids, texts, metadatas, distances = (results[key][0] for key in ("ids", "documents", "metadatas", "distances"))
        rows = []
        for rank, (chunk_id, text, raw, distance) in enumerate(zip(ids, texts, metadatas, distances), 1):
            if not text or not str(text).strip():
                continue
            metadata = news_metadata(self.industry, chunk_id, raw or {})
            rows.append(RetrievalCandidate(
                chunk_id=chunk_id, document_id=metadata["material_id"], text=str(text).strip(), metadata=metadata,
                dense_rank=rank, dense_distance=float(distance), dense_score=-float(distance),
            ))
        return rows


def pipeline_response(industry, query, top_k, result):
    warnings = [dict(row) for row in result.warnings]
    degraded = bool(warnings)
    version = "hybrid_v2_degraded" if degraded else "hybrid_v2"
    blocks = to_evidence_blocks(result.candidates)
    for block in blocks:
        block["retrieval_version"] = version
        block["industry"] = industry
    if not blocks and result.status == "success":
        warnings.append({"code": "rag_no_evidence", "message": "No external evidence matched this query."})
    failed = {row.get("stage") for row in warnings}
    return {"status": result.status, "industry": industry, "query": query, "top_k": top_k,
            "evidence_blocks": blocks, "rag_context_text": build_rag_context_text(blocks),
            "retrieval_version": version, "retrieval_degraded": degraded, "warnings": warnings,
            "message": result.message, "diagnostics": {"timings": dict(result.timings),
                "candidate_counts": dict(result.candidate_counts),
                "stages": {stage: "failed" if stage in failed else (
                    "skipped" if stage == "dense" and "embed" in failed else "success")
                    for stage in ("embed", "dense", "lexical", "fusion", "rerank")}}}


def retrieve_news_hybrid(query: str, top_k: int, industry: str) -> dict:
    state = check_news_index(industry)
    if state["status"] != "ready":
        raise RuntimeError(state["message"])
    config = RetrievalConfig.for_project(PROJECT_ROOT)
    models = local_models()
    dense = NewsDenseStore(industry)
    lexical = NewsLexicalStore(industry)
    scorer = lambda pairs: models.rerank_pairs(pairs[0][0], [pair[1] for pair in pairs])
    pipeline = HybridRetrievalPipeline(
        # Existing news vectors were encoded without the report query instruction.
        embed_query=lambda text: models.embed_documents([text])[0],
        dense_search=dense.search, lexical_search=lexical.search,
        rerank=partial(rerank_candidates, scorer=scorer), dense_limit=config.dense_limit,
        lexical_limit=config.lexical_limit, rerank_limit=config.rerank_limit, rrf_k=config.rrf_k,
    )
    result = pipeline.retrieve(query, (dense.collection_name,), top_k)
    return pipeline_response(industry, query, top_k, result)


def retrieve_news_legacy(query: str, top_k: int, industry: str) -> dict:
    vector = local_models().embed_documents([query])[0]
    rows = NewsDenseStore(industry).search(vector, top_k)
    blocks = to_evidence_blocks(rows)
    for block in blocks:
        block["retrieval_version"] = "legacy_news"
        block["industry"] = industry
    return {"status": "success", "industry": industry, "query": query, "top_k": top_k,
            "evidence_blocks": blocks, "rag_context_text": build_rag_context_text(blocks),
            "retrieval_version": "legacy_news", "warnings": [] if blocks else [
                {"code": "rag_store_empty", "message": "News collection has no usable evidence."}]}
