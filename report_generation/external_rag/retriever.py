"""External material RAG retrieval for report generation."""

from __future__ import annotations

import math
import os
from functools import partial
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from .client import get_external_libraries
from .vector_store import get_chroma_client, get_embedding_model, has_vector_store
from ..industry_config import get_industry_config


DEFAULT_TOP_K = 10
_QUERY_EMBEDDING_LOCK = Lock()


def _mode() -> str:
    value = os.environ.get("REPORT_RETRIEVAL_MODE", "hybrid_v2").strip()
    return value if value in {"legacy", "compare", "hybrid_v2"} else "legacy"


def retrieve_external_rag(
    query: str, top_k: int = DEFAULT_TOP_K, industry: str = "ai"
) -> dict:
    """Dispatch legacy, shadow-compare, or hybrid-v2 report retrieval."""
    normalized_industry = str(industry or "ai").strip() or "ai"
    normalized_query = str(query or "").strip()
    normalized_top_k = _normalize_top_k(top_k)
    if normalized_industry == "embodied":
        return retrieve_embodied_news(normalized_query, normalized_top_k)
    try:
        get_industry_config(normalized_industry)
    except ValueError as exc:
        return _error_response(str(exc), normalized_query, normalized_top_k, normalized_industry)
    if normalized_industry != "ai":
        return _retrieve_legacy(query, normalized_top_k, industry=normalized_industry)
    mode = _mode()
    if mode == "legacy":
        return _retrieve_legacy(query, top_k, industry=normalized_industry)
    if mode == "compare":
        legacy = _retrieve_legacy(query, top_k, industry=normalized_industry)
        try:
            hybrid = _retrieve_hybrid(query, top_k)
        except Exception as error:
            hybrid = _error_response("hybrid shadow failed", str(query or ""), _normalize_top_k(top_k))
            hybrid["comparison_error"] = type(error).__name__
        _log_comparison(query, legacy, hybrid)
        return legacy
    hybrid = _retrieve_hybrid(query, top_k)
    if hybrid.get("status") == "error" and os.environ.get("REPORT_RETRIEVAL_ALLOW_LEGACY_FALLBACK", "1") != "0":
        legacy = _retrieve_legacy(query, top_k, industry=normalized_industry)
        legacy["retrieval_fallback"] = "legacy"
        legacy["hybrid_error"] = hybrid.get("message", "hybrid retrieval failed")
        return legacy
    return hybrid


def retrieve_embodied_news(query: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """Retrieve embodied news chunks from the isolated Chroma collection."""
    normalized_query = str(query or "").strip()
    normalized_top_k = _normalize_top_k(top_k)
    if not normalized_query:
        return _error_response("query cannot be empty", normalized_query, normalized_top_k)
    try:
        from .embodied_store import query_embodied_news

        results = query_embodied_news(normalized_query, normalized_top_k)
    except Exception as exc:
        return _error_response(
            f"embodied RAG initialization failed: {exc}",
            normalized_query,
            normalized_top_k,
        )

    ids = _first_result_list(results.get("ids"))
    documents = _first_result_list(results.get("documents"))
    metadatas = _first_result_list(results.get("metadatas"))
    distances = _first_result_list(results.get("distances"))
    evidence_blocks = []
    for index, vector_id in enumerate(ids):
        text = _safe_text(_list_get(documents, index))
        if not text:
            continue
        metadata = _list_get(metadatas, index)
        metadata = metadata if isinstance(metadata, dict) else {}
        evidence_blocks.append(
            {
                "citation_id": f"外部资料{len(evidence_blocks) + 1}",
                "rank": len(evidence_blocks) + 1,
                "library": "embodied_news",
                "classification_type": "",
                "classification_name": "具身智能专题资讯",
                "material_id": _metadata_value(metadata, "source_id", ""),
                "title": _metadata_value(metadata, "title", ""),
                "publish_date": _metadata_value(metadata, "publish_date", ""),
                "source_address": _metadata_value(metadata, "url", ""),
                "paragraph_index": _coerce_int(metadata.get("chunk_index")),
                "vector_id": _safe_text(vector_id),
                "distance": _coerce_float(_list_get(distances, index)),
                "text": text,
            }
        )
    return {
        "status": "success",
        "query": normalized_query,
        "top_k": normalized_top_k,
        "rag_context_text": _build_rag_context_text(evidence_blocks),
        "evidence_blocks": evidence_blocks,
        "retrieval_version": "embodied_chroma",
    }


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
        from retrieval_core.model_manager import ModelManager
        from retrieval_core.pipeline import HybridRetrievalPipeline
        from retrieval_core.reranker import rerank_candidates

        config = RetrievalConfig.for_project(Path(__file__).resolve().parents[2])
        dense = DenseStore(config.index_root / "chroma")
        lexical = LexicalStore(config.index_root / "lexical.sqlite3")
        ready = V2IndexWriter(dense, lexical, ready_path=config.index_root / "READY",
                              model_version=config.embedding_model_path.name,
                              chunker_version="v2", dictionary_version="v1", audit_only=True)
        if not ready.validate_ready_marker():
            return _error_response("report v2 index is not ready", normalized_query, normalized_top_k)
        models = ModelManager(config.embedding_model_path, config.reranker_model_path)
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
        return {"status": "success", "query": normalized_query, "top_k": normalized_top_k,
                "rag_context_text": build_rag_context_text(evidence_blocks),
                "evidence_blocks": evidence_blocks, "warnings": list(routed.warnings),
                "retrieval_version": "hybrid_v2"}
    except Exception as error:
        return _error_response(f"hybrid v2 retrieval failed: {type(error).__name__}", normalized_query, normalized_top_k)


def _log_comparison(query: str, legacy: dict, hybrid: dict) -> None:
    """Comparison hook kept side-effect free until application logging is wired."""
    return None


def _retrieve_legacy(
    query: str, top_k: int = DEFAULT_TOP_K, industry: str = "ai"
) -> dict:
    """Retrieve the globally most relevant external material paragraphs."""
    normalized_query = str(query or "").strip()
    normalized_industry = str(industry or "ai").strip() or "ai"
    normalized_top_k = _normalize_top_k(top_k)
    if not normalized_query:
        return _error_response("query cannot be empty", normalized_query, normalized_top_k, normalized_industry)

    try:
        industry_config = get_industry_config(normalized_industry)
        libraries = get_external_libraries(normalized_industry)
    except ValueError as exc:
        return _error_response(str(exc), normalized_query, normalized_top_k, normalized_industry)

    if not has_vector_store(normalized_industry):
        message = f"{industry_config['name']}产业 RAG 向量库暂无资料，本次主要参考知识图谱生成"
        return {
            "status": "success",
            "industry": normalized_industry,
            "query": normalized_query,
            "top_k": normalized_top_k,
            "rag_context_text": "",
            "evidence_blocks": [],
            "warnings": [{"code": "rag_store_empty", "message": message}],
        }

    try:
        client = get_chroma_client(normalized_industry)
        query_embedding = _embed_query(normalized_query)
    except Exception as exc:
        return _error_response(
            f"external RAG initialization failed: {exc}",
            normalized_query,
            normalized_top_k,
            normalized_industry,
        )

    warnings: List[dict] = []
    candidates: List[dict] = []
    for library, config in libraries.items():
        candidates.extend(
            _query_library(
                client=client,
                library=library,
                config=config,
                query_embedding=query_embedding,
                n_results=normalized_top_k,
                warnings=warnings,
            )
        )

    top_candidates = _select_top_candidates(candidates, normalized_top_k, libraries)
    evidence_blocks = _build_evidence_blocks(top_candidates)
    return {
        "status": "success",
        "industry": normalized_industry,
        "query": normalized_query,
        "top_k": normalized_top_k,
        "rag_context_text": _build_rag_context_text(evidence_blocks),
        "evidence_blocks": evidence_blocks,
        "warnings": warnings,
    }


def _embed_query(query: str) -> List[float]:
    model = get_embedding_model()
    with _QUERY_EMBEDDING_LOCK:
        embeddings = model.encode(
            [query],
            show_progress_bar=False,
            batch_size=1,
        )
    embedding = embeddings[0]
    if hasattr(embedding, "tolist"):
        return embedding.tolist()
    return list(embedding)


def _query_library(
    client: Any,
    library: str,
    config: Dict[str, str],
    query_embedding: List[float],
    n_results: int,
    warnings: List[dict],
) -> List[dict]:
    collection_name = config["collection"]
    try:
        collection = client.get_collection(name=collection_name)
    except Exception as exc:
        _record_warning(warnings, library, collection_name, f"collection unavailable: {exc}")
        return []

    try:
        item_count = collection.count()
    except Exception as exc:
        item_count = None
        _record_warning(warnings, library, collection_name, f"collection count failed: {exc}")

    if item_count == 0:
        _record_warning(warnings, library, collection_name, "collection is empty")
        return []

    effective_n_results = min(n_results, item_count) if item_count else n_results
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=effective_n_results,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        _record_warning(warnings, library, collection_name, f"collection query failed: {exc}")
        return []

    return _parse_query_results(results, library, config)


def _parse_query_results(results: Dict[str, Any], library: str, config: Dict[str, str]) -> List[dict]:
    ids = _first_result_list(results.get("ids"))
    documents = _first_result_list(results.get("documents"))
    metadatas = _first_result_list(results.get("metadatas"))
    distances = _first_result_list(results.get("distances"))

    candidates = []
    for index, vector_id in enumerate(ids):
        text = _safe_text(_list_get(documents, index))
        if not text:
            continue
        metadata = _list_get(metadatas, index)
        if not isinstance(metadata, dict):
            metadata = {}
        candidates.append(
            {
                "library": library,
                "config": config,
                "vector_id": _safe_text(vector_id),
                "distance": _coerce_float(_list_get(distances, index)),
                "text": text,
                "metadata": metadata,
            }
        )
    return candidates


def _select_top_candidates(candidates: List[dict], top_k: int, libraries: Dict[str, dict]) -> List[dict]:
    library_order = {library: index for index, library in enumerate(libraries)}
    selected = []
    seen = set()
    for candidate in sorted(
        candidates,
        key=lambda item: (
            _sort_distance(item.get("distance")),
            library_order.get(item.get("library"), len(library_order)),
            item.get("vector_id") or "",
        ),
    ):
        key = _candidate_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) >= top_k:
            break
    return selected


def _build_evidence_blocks(candidates: List[dict]) -> List[dict]:
    evidence_blocks = []
    for rank, candidate in enumerate(candidates, 1):
        metadata = candidate.get("metadata") or {}
        config = candidate.get("config") or {}
        evidence_blocks.append(
            {
                "citation_id": f"外部资料{rank}",
                "rank": rank,
                "library": _metadata_value(metadata, "library", candidate.get("library")),
                "classification_type": _metadata_value(
                    metadata,
                    "classification_type",
                    config.get("classification_type"),
                ),
                "classification_name": _metadata_value(
                    metadata,
                    "classification_name",
                    config.get("classification_name"),
                ),
                "material_id": _metadata_value(metadata, "material_id", ""),
                "title": _metadata_value(metadata, "title", ""),
                "publish_date": _metadata_value(metadata, "publish_date", ""),
                "source_address": _metadata_value(metadata, "source_address", ""),
                "paragraph_index": _coerce_int(metadata.get("paragraph_index")),
                "vector_id": candidate.get("vector_id") or "",
                "distance": candidate.get("distance"),
                "text": candidate.get("text") or "",
            }
        )
    return evidence_blocks


def _build_rag_context_text(evidence_blocks: List[dict]) -> str:
    lines = ["【外部资料库检索结果】"]
    if not evidence_blocks:
        lines.extend(["", "未检索到匹配内容。"])
        return "\n".join(lines)

    for block in evidence_blocks:
        paragraph_index = block.get("paragraph_index")
        lines.extend(
            [
                "",
                f"[{block['citation_id']}]",
                f"资料类型：{_display_value(block.get('classification_name'))}",
                f"标题：{_display_value(block.get('title'))}",
                f"发布日期：{_display_value(block.get('publish_date'))}",
                f"来源：{_display_value(block.get('source_address'))}",
                f"段落序号：{paragraph_index if paragraph_index is not None else '未提供'}",
                f"内容：{_display_value(block.get('text'))}",
            ]
        )
    return "\n".join(lines)


def _first_result_list(value: Any) -> List[Any]:
    if isinstance(value, list) and value and isinstance(value[0], list):
        return value[0]
    if isinstance(value, list):
        return value
    return []


def _list_get(items: List[Any], index: int) -> Any:
    if index < len(items):
        return items[index]
    return None


def _metadata_value(metadata: Dict[str, Any], key: str, default: Any) -> str:
    value = metadata.get(key)
    if value is None or value == "":
        value = default
    return _safe_text(value)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _display_value(value: Any) -> str:
    text = _safe_text(value)
    return text if text else "未提供"


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sort_distance(value: Any) -> float:
    distance = _coerce_float(value)
    if distance is None or math.isnan(distance):
        return math.inf
    return distance


def _candidate_key(candidate: dict) -> Any:
    if candidate.get("vector_id"):
        return candidate["vector_id"]
    metadata = candidate.get("metadata") or {}
    return (
        candidate.get("library"),
        metadata.get("material_id"),
        metadata.get("paragraph_index"),
        candidate.get("text"),
    )


def _normalize_top_k(top_k: Any) -> int:
    try:
        value = int(top_k)
    except (TypeError, ValueError):
        return DEFAULT_TOP_K
    return value if value > 0 else DEFAULT_TOP_K


def _record_warning(warnings: List[dict], library: str, collection: str, message: str) -> None:
    warnings.append(
        {
            "library": library,
            "collection": collection,
            "message": message,
        }
    )


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
    }
