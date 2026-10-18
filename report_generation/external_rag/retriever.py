"""Hybrid external-material retrieval for report generation."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from ..industry_config import get_industry_config


DEFAULT_TOP_K = 10


def retrieve_external_rag(
    query: str, top_k: int = DEFAULT_TOP_K, industry: str = "ai"
) -> dict:
    """Retrieve external materials through the industry hybrid pipeline."""
    normalized_industry = str(industry or "ai").strip() or "ai"
    normalized_query = str(query or "").strip()
    normalized_top_k = _normalize_top_k(top_k)
    try:
        get_industry_config(normalized_industry)
    except ValueError as exc:
        return _error_response(str(exc), normalized_query, normalized_top_k, normalized_industry)
    if not normalized_query:
        return _error_response("query cannot be empty", normalized_query, normalized_top_k, normalized_industry)
    hybrid_retrieve = _retrieve_hybrid if normalized_industry == "ai" else partial(
        _retrieve_news_hybrid, industry=normalized_industry
    )
    hybrid = hybrid_retrieve(normalized_query, normalized_top_k)
    hybrid["industry"] = normalized_industry
    return hybrid


def _retrieve_news_hybrid(query: str, top_k: int, industry: str) -> dict:
    try:
        from .news_retrieval import retrieve_news_hybrid

        return retrieve_news_hybrid(query, top_k, industry)
    except Exception as error:
        return _error_response(f"news hybrid retrieval failed: {error}", query, top_k, industry)


def _retrieve_hybrid(query: str, top_k: int = DEFAULT_TOP_K) -> dict:
    normalized_query = str(query or "").strip()
    normalized_top_k = _normalize_top_k(top_k)
    if not normalized_query:
        return _error_response("query cannot be empty", normalized_query, normalized_top_k)
    try:
        from report_generation.external_rag.report_adapter import (
            build_rag_context_text, build_report_query, retrieve_with_soft_routing,
            route_libraries, to_evidence_blocks,
        )
        from report_generation.external_rag.v2_index import V2IndexWriter
        from retrieval_core.config import RetrievalConfig
        from retrieval_core.dense_store import DenseStore
        from retrieval_core.lexical_store import LexicalStore
        from retrieval_core.chunker import _search_text
        from retrieval_core.pipeline import HybridRetrievalPipeline
        from retrieval_core.reranker import rerank_candidates

        config = RetrievalConfig.for_project(Path(__file__).resolve().parents[2])
        dense = DenseStore(config.index_root / "chroma")
        lexical = LexicalStore(config.index_root / "lexical.sqlite3",
                               query_tokenizer=lambda text: _search_text(text, None).split())
        ready = V2IndexWriter(dense, lexical, ready_path=config.index_root / "READY",
                              model_version=config.embedding_model_path.name,
                              chunker_version="v2", dictionary_version="v1", audit_only=True)
        if not ready.validate_ready_marker():
            return _error_response("report v2 index is not ready", normalized_query, normalized_top_k)
        from .news_retrieval import local_models

        models = local_models()
        scorer = lambda pairs: models.rerank_pairs(pairs[0][0], [pair[1] for pair in pairs])
        pipeline = HybridRetrievalPipeline(
            embed_query=lambda text: models.embed_queries([text])[0], dense_search=dense.search,
            lexical_search=lexical.search, rerank=partial(rerank_candidates, scorer=scorer),
            dense_limit=config.dense_limit, lexical_limit=config.lexical_limit,
            rerank_limit=config.rerank_limit, rrf_k=config.rrf_k,
        )
        focused = build_report_query(normalized_query)
        routed = retrieve_with_soft_routing(pipeline.retrieve, focused.semantic_query,
                                            route_libraries(focused), normalized_top_k)
        evidence_blocks = to_evidence_blocks(routed.candidates)
        degraded = bool(routed.warnings)
        version = "hybrid_v2_degraded" if degraded else "hybrid_v2"
        for block in evidence_blocks:
            block["retrieval_version"] = version
            block["industry"] = "ai"
        attempts = [attempt.result for attempt in routed.attempts if attempt.result is not None]
        diagnostics = {"attempts": [{"status": result.status, "timings": dict(result.timings),
                                    "candidate_counts": dict(result.candidate_counts),
                                    "warnings": [dict(item) for item in result.warnings]} for result in attempts]}
        if not evidence_blocks and attempts and all(result.status == "error" for result in attempts):
            response = _error_response("all report hybrid recall attempts failed", normalized_query, normalized_top_k)
            response.update(warnings=[dict(item) for item in routed.warnings], diagnostics=diagnostics)
            return response
        warnings = [dict(item) for item in routed.warnings]
        if not evidence_blocks:
            warnings.append({"code": "rag_no_evidence", "message": "No external evidence matched this query."})
        return {"status": "success", "query": normalized_query, "top_k": normalized_top_k,
                "rag_context_text": build_rag_context_text(evidence_blocks),
                "evidence_blocks": evidence_blocks, "warnings": warnings,
                "retrieval_version": version, "retrieval_degraded": degraded, "diagnostics": diagnostics}
    except Exception as error:
        return _error_response(f"hybrid v2 retrieval failed: {error}", normalized_query, normalized_top_k)


def _normalize_top_k(top_k: Any) -> int:
    try:
        value = int(top_k)
    except (TypeError, ValueError):
        return DEFAULT_TOP_K
    return value if value > 0 else DEFAULT_TOP_K


def _error_response(message: str, query: str, top_k: int, industry: str = "ai") -> dict:
    return {
        "status": "error",
        "industry": industry,
        "query": query,
        "message": message,
        "top_k": top_k,
        "rag_context_text": "",
        "evidence_blocks": [],
        "warnings": [],
        "retrieval_version": "unavailable",
        "diagnostics": {},
    }
