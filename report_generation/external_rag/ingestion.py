"""Initial and incremental ingestion for external report-generation materials."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .client import ExternalMaterialClient, get_external_libraries
from .text_utils import (
    content_hash,
    html_to_paragraphs,
    normalize_text,
    normalized_title,
    split_plain_paragraphs,
)
from .vector_store import (
    delete_existing_material,
    upsert_paragraphs,
)
from ..industry_config import get_industry_config, get_vector_db_path


def _v2_enabled() -> bool:
    """Keep v2 dual-write opt-in until the staged index is operationally ready."""
    return os.environ.get("REPORT_RAG_V2_DUAL_WRITE", "0").strip() == "1"


def _upsert_v2_material(library: str, material_id: str, title: str, metadata: Dict[str, Any], raw_content: str) -> List[str]:
    """Write the same source material to v2; callers record, rather than hide, failures."""
    from .v2_index import V2IndexWriter
    from retrieval_core.chunker import build_report_chunks
    from retrieval_core.config import RetrievalConfig
    from retrieval_core.dense_store import DenseStore
    from retrieval_core.lexical_store import LexicalStore
    from retrieval_core.model_manager import ModelManager

    config = RetrievalConfig.for_project(Path(__file__).resolve().parents[2])
    from .text_utils import html_to_structured_blocks
    blocks = html_to_structured_blocks(raw_content) or [
        {"kind": "paragraph", "text": paragraph} for paragraph in split_plain_paragraphs(raw_content, min_len=1)
    ]
    if not blocks:
        raise ValueError("material has no structured v2 blocks")
    if not config.embedding_model_path.is_dir():
        raise RuntimeError("local v2 embedding model is missing")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(config.embedding_model_path), local_files_only=True)
    manager = ModelManager(config.embedding_model_path, config.reranker_model_path)
    chunks = build_report_chunks(blocks, library, material_id, title, metadata, tokenizer)
    writer = V2IndexWriter(
        DenseStore(config.index_root / "chroma"), LexicalStore(config.index_root / "lexical.sqlite3"),
        ready_path=config.index_root / "READY", embed_documents=manager.embed_documents,
        model_version=config.embedding_model_path.name, chunker_version="v2", dictionary_version="v1",
    )
    result = writer.upsert_document(chunks[0].document_id, chunks)
    if result.status != "success":
        raise RuntimeError(result.message)
    return list(result.expected_ids)


INDUSTRY = "ai"
DEFAULT_PAGE_SIZE = 100
# 安全限制：最大拉取页数，防止 API 分页元数据异常导致无限循环
MAX_PAGES_SAFETY_LIMIT = 500
# 每条记录处理后的短暂休眠（秒），降低 CPU 持续负载
RECORD_THROTTLE_SECONDS = 0.05

# 日志配置：同时输出到控制台和文件
_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "external_rag_ingestion.log"

logger = logging.getLogger("report_generation.external_rag.ingestion")
if not logger.handlers:
    _handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    _handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(_handler)
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)


def initial_ingest_external_library(
    library: str,
    access_token: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    industry: str = "ai",
) -> Dict[str, Any]:
    return _ingest_library(
        library=library,
        access_token=access_token,
        page_size=page_size,
        mode="initial",
        max_pages=None,
        industry=industry,
    )


def update_external_library(
    library: str,
    access_token: str,
    today: Optional[date] = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    industry: str = "ai",
) -> Dict[str, Any]:
    _ = today
    latest_state = _load_latest_publish_date(library, industry)
    if not latest_state.get("latest_publish_date"):
        return _ingest_library(
            library=library,
            access_token=access_token,
            page_size=page_size,
            mode="initial_fallback",
            max_pages=None,
            industry=industry,
        )
    return _ingest_library(
        library=library,
        access_token=access_token,
        page_size=page_size,
        mode="update",
        max_pages=None,
        industry=industry,
    )


def initial_ingest_all_external_libraries(
    access_token: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    industry: str = "ai",
) -> Dict[str, Any]:
    return _run_all_libraries(
        access_token=access_token,
        page_size=page_size,
        runner=initial_ingest_external_library,
        industry=industry,
    )


def update_all_external_libraries(
    access_token: str,
    today: Optional[date] = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    industry: str = "ai",
) -> Dict[str, Any]:
    libraries = get_external_libraries(industry)
    total_libs = len(libraries)
    logger.info("=" * 60)
    logger.info("开始增量更新所有外部资料库（共 %d 个库）", total_libs)
    results: Dict[str, Any] = {}
    for idx, library in enumerate(libraries, 1):
        logger.info("-" * 40)
        logger.info("[%d/%d] 开始更新资料库: %s", idx, total_libs, library)
        try:
            results[library] = update_external_library(
                library=library,
                access_token=access_token,
                today=today,
                page_size=page_size,
                industry=industry,
            )
        except Exception as exc:
            logger.exception("[%d/%d] 资料库 %s 更新异常: %s", idx, total_libs, library, exc)
            results[library] = _library_error_result(library, "update", exc, industry)
    logger.info("=" * 60)
    summary = _summarize_all_results("update_all", results, industry)
    _log_summary("增量更新", summary)
    return summary


def debug_ingest_external_library(
    library: str,
    access_token: str,
    page_size: int = 2,
    max_pages: int = 1,
    industry: str = "ai",
) -> Dict[str, Any]:
    return _ingest_library(
        library=library,
        access_token=access_token,
        page_size=page_size,
        mode="debug",
        max_pages=max_pages,
        industry=industry,
    )


def _run_all_libraries(access_token: str, page_size: int, runner, industry: str) -> Dict[str, Any]:
    libraries = get_external_libraries(industry)
    total_libs = len(libraries)
    logger.info("=" * 60)
    logger.info("开始全量摄入所有外部资料库（共 %d 个库）", total_libs)
    results: Dict[str, Any] = {}
    for idx, library in enumerate(libraries, 1):
        logger.info("-" * 40)
        logger.info("[%d/%d] 开始处理资料库: %s", idx, total_libs, library)
        try:
            results[library] = runner(
                library=library,
                access_token=access_token,
                page_size=page_size,
                industry=industry,
            )
        except Exception as exc:
            logger.exception("[%d/%d] 资料库 %s 摄入异常: %s", idx, total_libs, library, exc)
            results[library] = _library_error_result(library, "initial", exc, industry)
    logger.info("=" * 60)
    summary = _summarize_all_results("initial_all", results, industry)
    _log_summary("全量摄入", summary)
    return summary


def _summarize_all_results(mode: str, results: Dict[str, Any], industry: str) -> Dict[str, Any]:
    failed_libraries = [
        library
        for library, result in results.items()
        if result.get("status") != "success"
    ]
    return {
        "status": "success" if not failed_libraries else "partial_success",
        "industry": industry,
        "mode": mode,
        "libraries": results,
        "failed_libraries": failed_libraries,
    }


def _ingest_library(
    library: str,
    access_token: str,
    page_size: int,
    mode: str,
    max_pages: Optional[int],
    industry: str,
) -> Dict[str, Any]:
    get_industry_config(industry)
    config = _validate_library(library, industry)
    _validate_page_size(page_size)

    manifest = _load_manifest(library, industry)
    latest_state = _load_latest_publish_date(library, industry)
    latest_publish_date = latest_state.get("latest_publish_date") if mode == "update" else None
    client = ExternalMaterialClient(access_token, industry=industry)

    logger.info(
        "资料库 [%s] 开始摄入 | 模式=%s | 分类=%s | 每页=%d | 已有manifest记录=%d | 增量基准日期=%s",
        library, mode, config["classification_name"], page_size, len(manifest),
        latest_publish_date or "无",
    )

    stats: Dict[str, Any] = {
        "status": "success",
        "industry": industry,
        "library": library,
        "classification_type": config["classification_type"],
        "classification_name": config["classification_name"],
        "mode": mode,
        "page_size": page_size,
        "pages_seen": 0,
        "records_seen": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    page_no = 1
    stop_for_old_date = False
    while True:
        if max_pages is not None and page_no > max_pages:
            logger.info("资料库 [%s] 达到最大页数限制 %d，停止拉取", library, max_pages)
            break

        # 安全限制：防止 API 分页元数据异常导致无限循环
        if max_pages is None and page_no > MAX_PAGES_SAFETY_LIMIT:
            logger.warning(
                "资料库 [%s] 已达到安全页数上限 %d，强制停止拉取（可能 API 分页元数据异常）",
                library, MAX_PAGES_SAFETY_LIMIT,
            )
            stats["status"] = "partial_success"
            break

        try:
            result = client.query_info_list(
                classification_type=config["classification_type"],
                page_no=page_no,
                page_size=page_size,
            )
        except Exception as exc:
            stats["status"] = "error" if stats["records_seen"] == 0 else "partial_success"
            stats["failed"] += 1
            _record_error(stats, f"page:{page_no}", str(exc))
            logger.error("资料库 [%s] 第 %d 页拉取失败: %s", library, page_no, exc)
            break
        records = result.get("records") or []
        pages = _safe_int(result.get("pages"))
        total = _safe_int(result.get("total"))
        stats["pages_seen"] += 1

        logger.info(
            "资料库 [%s] 第 %d 页拉取完成 | 本页记录=%d | 总页数=%s | 总记录数=%d | 累计已处理=%d",
            library, page_no, len(records), pages or "未知", total,
            stats["records_seen"] + len(records),
        )

        if not records:
            logger.info("资料库 [%s] 第 %d 页无记录，停止拉取", library, page_no)
            break

        for record in records:
            stats["records_seen"] += 1
            material_id = str(record.get("id") or "").strip()
            title = normalized_title(record.get("title"))
            publish_date = _normalize_publish_date(record.get("publishDate"))

            if not material_id:
                stats["failed"] += 1
                _record_error(stats, "unknown", "missing material id")
                logger.warning("资料库 [%s] 第 %d 页第 %d 条记录缺少 material_id，跳过",
                               library, page_no, stats["records_seen"])
                continue

            if mode == "update" and latest_publish_date:
                compare = _compare_dates(publish_date, latest_publish_date)
                if compare < 0:
                    stop_for_old_date = True
                    logger.info("资料库 [%s] 遇到旧日期记录（%s < %s），停止增量拉取",
                                library, publish_date, latest_publish_date)
                    break
                if compare == 0 and _manifest_has_title_on_date(manifest, publish_date, title):
                    stats["skipped"] += 1
                    continue

            existing_record = _find_manifest_record(manifest, material_id)
            if mode in ("initial", "initial_fallback", "debug") and _is_success_record(existing_record):
                stats["skipped"] += 1
                continue

            try:
                ingest_result = _ingest_record(
                    library=library,
                    config=config,
                    client=client,
                    source_record=record,
                    existing_record=existing_record,
                    industry=industry,
                )
                _upsert_manifest_record(manifest, ingest_result["manifest_record"])
                if existing_record and _is_success_record(existing_record):
                    stats["updated"] += 1
                    logger.info("资料库 [%s] 更新材料: id=%s, 标题=%s, 段落数=%d",
                                library, material_id, title,
                                ingest_result["manifest_record"]["chunk_count"])
                else:
                    stats["inserted"] += 1
                    logger.info("资料库 [%s] 新增材料: id=%s, 标题=%s, 段落数=%d",
                                library, material_id, title,
                                ingest_result["manifest_record"]["chunk_count"])
            except Exception as exc:
                stats["failed"] += 1
                error_message = str(exc)
                _record_error(stats, material_id, error_message)
                logger.error("资料库 [%s] 摄入失败: id=%s, 标题=%s, 错误=%s",
                             library, material_id, title, error_message)
                _upsert_manifest_record(
                    manifest,
                    _build_error_manifest_record(
                        library=library,
                        config=config,
                        source_record=record,
                        error=error_message,
                    ),
                )

        _save_manifest(library, manifest, industry)
        _save_latest_publish_date(library, _compute_latest_publish_date(manifest), industry)

        logger.info(
            "资料库 [%s] 第 %d 页处理完成 | 累计: 已处理=%d, 新增=%d, 更新=%d, 跳过=%d, 失败=%d",
            library, page_no, stats["records_seen"],
            stats["inserted"], stats["updated"], stats["skipped"], stats["failed"],
        )

        if stop_for_old_date:
            break
        if pages and page_no >= pages:
            logger.info("资料库 [%s] 已到最后一页（第 %d 页），拉取完成", library, page_no)
            break
        if not pages and total and page_no * page_size >= total:
            logger.info("资料库 [%s] 已拉取全部记录（共 %d 条），拉取完成", library, total)
            break
        page_no += 1

        # 页间短暂休眠，降低持续 CPU 负载
        time.sleep(0.5)

    latest = _compute_latest_publish_date(manifest)
    _save_manifest(library, manifest, industry)
    _save_latest_publish_date(library, latest, industry)
    stats["latest_publish_date"] = latest
    if stats["status"] == "success" and stats["failed"]:
        stats["status"] = "partial_success"
    logger.info(
        "资料库 [%s] 摄入完成 | 状态=%s | 总页数=%d | 总记录=%d | 新增=%d | 更新=%d | 跳过=%d | 失败=%d | 最新发布日期=%s",
        library, stats["status"], stats["pages_seen"], stats["records_seen"],
        stats["inserted"], stats["updated"], stats["skipped"], stats["failed"], latest,
    )
    return stats


def _library_error_result(library: str, mode: str, exc: Exception, industry: str) -> Dict[str, Any]:
    config = get_external_libraries(industry).get(library, {})
    return {
        "status": "error",
        "industry": industry,
        "library": library,
        "classification_type": config.get("classification_type"),
        "classification_name": config.get("classification_name"),
        "mode": mode,
        "message": str(exc),
        "pages_seen": 0,
        "records_seen": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 1,
        "errors": [{"id": "library", "error": str(exc)}],
    }


def _ingest_record(
    library: str,
    config: Dict[str, str],
    client: ExternalMaterialClient,
    source_record: Dict[str, Any],
    existing_record: Optional[Dict[str, Any]],
    industry: str,
) -> Dict[str, Any]:
    material_id = str(source_record.get("id") or "").strip()
    title = normalized_title(source_record.get("title"))
    publish_date = _normalize_publish_date(source_record.get("publishDate"))
    source_address = normalize_text(source_record.get("sourceAddress"))

    if library == "research_report":
        raw_text = source_record.get("summary") or ""
        paragraphs = split_plain_paragraphs(raw_text)
        raw_content = raw_text
    else:
        detail = client.query_by_id(material_id)
        title = normalized_title(detail.get("title") or title)
        publish_date = _normalize_publish_date(detail.get("publishDate") or publish_date)
        source_address = normalize_text(detail.get("sourceAddress") or source_address)
        raw_html = detail.get("contentWithTag") or detail.get("content") or detail.get("summary") or source_record.get("summary") or ""
        paragraphs = html_to_paragraphs(raw_html)
        raw_content = raw_html

    if not paragraphs:
        raise ValueError("material has no usable paragraphs")

    c_hash = content_hash(paragraphs)
    old_chunk_count = _safe_int((existing_record or {}).get("chunk_count"))
    old_content_hash = (existing_record or {}).get("content_hash")
    if old_chunk_count and old_content_hash != c_hash:
        delete_existing_material(library, material_id, old_chunk_count, industry=industry)
        logger.info("资料库 [%s] 材料内容变更，已删除旧向量: id=%s, 旧段落数=%d", library, material_id, old_chunk_count)

    metadatas = [
        {
            "library": library,
            "classification_type": config["classification_type"],
            "classification_name": config["classification_name"],
            "material_id": material_id,
            "title": title,
            "publish_date": publish_date,
            "source_address": source_address,
            "paragraph_index": index,
            "content_hash": c_hash,
        }
        for index in range(len(paragraphs))
    ]
    upsert_paragraphs(
        library=library,
        material_id=material_id,
        paragraphs=paragraphs,
        metadatas=metadatas,
        industry=industry,
    )

    v2_status, v2_chunk_ids, v2_error = "disabled", [], None
    if _v2_enabled():
        try:
            v2_chunk_ids = _upsert_v2_material(
                library, material_id, title, metadatas[0], raw_content
            )
            v2_status = "success"
        except Exception as exc:
            v2_status, v2_error = "error", str(exc)

    now = _now_iso()
    return {
        "manifest_record": {
            "id": material_id,
            "library": library,
            "classification_type": config["classification_type"],
            "classification_name": config["classification_name"],
            "title": title,
            "publish_date": publish_date,
            "source_address": source_address,
            "content_hash": c_hash,
            "chunk_count": len(paragraphs),
            "status": "success",
            "error": None,
            "fetched_at": now,
            "vectorized_at": now,
            "v2_status": v2_status,
            "v2_chunk_ids": v2_chunk_ids,
            "v2_error": v2_error,
            "chunker_version": "v2" if v2_status == "success" else None,
            "embedding_model": "bge-base-zh-v1.5" if v2_status == "success" else None,
        }
    }


def _build_error_manifest_record(
    library: str,
    config: Dict[str, str],
    source_record: Dict[str, Any],
    error: str,
) -> Dict[str, Any]:
    material_id = str(source_record.get("id") or "").strip()
    return {
        "id": material_id,
        "library": library,
        "classification_type": config["classification_type"],
        "classification_name": config["classification_name"],
        "title": normalized_title(source_record.get("title")),
        "publish_date": _normalize_publish_date(source_record.get("publishDate")),
        "source_address": normalize_text(source_record.get("sourceAddress")),
        "content_hash": "",
        "chunk_count": 0,
        "status": "error",
        "error": error,
        "fetched_at": _now_iso(),
        "vectorized_at": None,
    }


def _manifest_path(library: str, industry: str) -> Path:
    return get_vector_db_path(industry) / f"{library}_manifest.json"


def _latest_path(library: str, industry: str) -> Path:
    return get_vector_db_path(industry) / f"{library}_latest_publish_date.json"


def _load_manifest(library: str, industry: str) -> List[Dict[str, Any]]:
    path = _manifest_path(library, industry)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    materials = data.get("materials") if isinstance(data, dict) else []
    return materials if isinstance(materials, list) else []


def _save_manifest(library: str, manifest: List[Dict[str, Any]], industry: str) -> None:
    vector_db_path = get_vector_db_path(industry)
    vector_db_path.mkdir(parents=True, exist_ok=True)
    config = get_external_libraries(industry)[library]
    manifest.sort(
        key=lambda item: (
            item.get("publish_date") or "",
            item.get("title") or "",
            item.get("id") or "",
        ),
        reverse=True,
    )
    payload = {
        "industry": industry,
        "library": library,
        "classification_type": config["classification_type"],
        "classification_name": config["classification_name"],
        "updated_at": _now_iso(),
        "materials": manifest,
    }
    _manifest_path(library, industry).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_latest_publish_date(library: str, industry: str) -> Dict[str, Any]:
    path = _latest_path(library, industry)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_latest_publish_date(library: str, latest_publish_date: str, industry: str) -> None:
    get_vector_db_path(industry).mkdir(parents=True, exist_ok=True)
    config = get_external_libraries(industry)[library]
    payload = {
        "industry": industry,
        "library": library,
        "classification_type": config["classification_type"],
        "latest_publish_date": latest_publish_date,
        "updated_at": _now_iso(),
    }
    _latest_path(library, industry).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _find_manifest_record(manifest: List[Dict[str, Any]], material_id: str) -> Optional[Dict[str, Any]]:
    for record in manifest:
        if str(record.get("id")) == material_id:
            return record
    return None


def _upsert_manifest_record(manifest: List[Dict[str, Any]], record: Dict[str, Any]) -> None:
    material_id = str(record.get("id") or "")
    for index, existing in enumerate(manifest):
        if str(existing.get("id") or "") == material_id:
            manifest[index] = record
            return
    manifest.append(record)


def _manifest_has_title_on_date(
    manifest: List[Dict[str, Any]],
    publish_date: str,
    title: str,
) -> bool:
    for record in manifest:
        if record.get("status") != "success":
            continue
        if record.get("publish_date") != publish_date:
            continue
        if normalized_title(record.get("title")) == title:
            return True
    return False


def _compute_latest_publish_date(manifest: List[Dict[str, Any]]) -> str:
    dates = [
        str(record.get("publish_date") or "")
        for record in manifest
        if record.get("status") == "success" and record.get("publish_date")
    ]
    return max(dates) if dates else ""


def _normalize_publish_date(value: object) -> str:
    raw = normalize_text(value)
    if not raw:
        return ""
    return raw[:10]


def _compare_dates(left: str, right: str) -> int:
    if not left and not right:
        return 0
    if not left:
        return -1
    if not right:
        return 1
    if left > right:
        return 1
    if left < right:
        return -1
    return 0


def _safe_int(value: object) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _validate_library(library: str, industry: str) -> Dict[str, str]:
    libraries = get_external_libraries(industry)
    if library not in libraries:
        raise ValueError(
            f"Unknown external library: {library}. "
            f"Allowed values: {', '.join(libraries)}"
        )
    return libraries[library]


def _validate_page_size(page_size: int) -> None:
    if page_size <= 0:
        raise ValueError("page_size must be positive")


def _is_success_record(record: Optional[Dict[str, Any]]) -> bool:
    return bool(record and record.get("status") == "success")


def _record_error(stats: Dict[str, Any], material_id: str, error: str) -> None:
    stats["errors"].append({"id": material_id, "error": error})


def _log_summary(action: str, summary: Dict[str, Any]) -> None:
    """输出所有资料库摄入的汇总日志。"""
    libraries = summary.get("libraries") or {}
    failed_libraries = summary.get("failed_libraries") or []
    total_inserted = sum(r.get("inserted", 0) for r in libraries.values())
    total_updated = sum(r.get("updated", 0) for r in libraries.values())
    total_skipped = sum(r.get("skipped", 0) for r in libraries.values())
    total_failed = sum(r.get("failed", 0) for r in libraries.values())
    total_records = sum(r.get("records_seen", 0) for r in libraries.values())
    logger.info("=" * 60)
    logger.info("%s汇总 | 状态=%s | 资料库数=%d | 失败库数=%d",
                action, summary.get("status"), len(libraries), len(failed_libraries))
    logger.info("总记录数=%d | 总新增=%d | 总更新=%d | 总跳过=%d | 总失败=%d",
                total_records, total_inserted, total_updated, total_skipped, total_failed)
    for lib_name, lib_result in libraries.items():
        logger.info(
            "  - %s: 状态=%s, 记录=%d, 新增=%d, 更新=%d, 跳过=%d, 失败=%d",
            lib_name,
            lib_result.get("status"),
            lib_result.get("records_seen", 0),
            lib_result.get("inserted", 0),
            lib_result.get("updated", 0),
            lib_result.get("skipped", 0),
            lib_result.get("failed", 0),
        )
    if failed_libraries:
        logger.warning("失败的资料库: %s", ", ".join(failed_libraries))
    logger.info("=" * 60)
