"""Ingestion pipeline for the authorized embodied-intelligence subject news feed."""

from __future__ import annotations

import argparse
import html
import math
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .embodied_client import EmbodiedNewsClient
from .embodied_manifest import EmbodiedIngestionManifest
from .embodied_store import EmbodiedNewsStore, MODEL_PATH, VECTOR_DB_DIR


SUBJECT_ID = "2043590589800853505"
DEFAULT_LIMIT = 100
DEFAULT_PAGE_SIZE = 100
MAX_CHUNK_CHARS = 500
DEFAULT_FULL_MANIFEST = VECTOR_DB_DIR / "embodied_full_manifest.json"
MAX_RECORDED_ERRORS = 100


def _repair_unicode_surrogates(text: str) -> str:
    """Convert escaped UTF-16 surrogate pairs into Unicode code points."""
    try:
        return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    except UnicodeError:
        return text.encode("utf-8", "replace").decode("utf-8")


def _clean_body(value: object) -> str:
    text = _repair_unicode_surrogates(str(value or ""))
    text = html.unescape(text)
    text = _repair_unicode_surrogates(text)
    if "<" in text and ">" in text:
        try:
            from bs4 import BeautifulSoup

            text = BeautifulSoup(text, "html.parser").get_text("\n")
        except ImportError:
            text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _split_body(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    paragraphs = [part.strip() for part in re.split(r"\n+", text) if part.strip()]
    if not paragraphs:
        return []
    chunks: List[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = re.split(r"(?<=[。！？!?；;])", paragraph)
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            if current and len(current) + len(piece) > max_chars:
                chunks.append(current)
                current = ""
            if len(piece) > max_chars:
                for start in range(0, len(piece), max_chars):
                    part = piece[start : start + max_chars]
                    if len(part) == max_chars:
                        chunks.append(part)
                    else:
                        current = part
            else:
                current += piece
    if current:
        chunks.append(current)
    return chunks


def build_chunks(detail: Dict[str, Any], subject_id: str = SUBJECT_ID) -> List[Dict[str, Any]]:
    source_id = str(detail.get("id") or detail.get("infoId") or "").strip()
    title = _clean_body(detail.get("title"))
    summary = _clean_body(detail.get("summary"))
    body = _clean_body(
        detail.get("contentWithTag") or detail.get("content") or detail.get("summary")
    )
    if not source_id or not body:
        return []
    body_chunks = _split_body(body)
    if not body_chunks:
        return []
    total_chunks = len(body_chunks)
    metadata_base = {
        "source_id": source_id,
        "subject_id": subject_id,
        "title": title,
        "publish_date": _clean_body(detail.get("publishDate")),
        "source": _clean_body(detail.get("source") or detail.get("origin")),
        "url": _clean_body(detail.get("sourceAddress")),
    }
    chunks = []
    for index, body_chunk in enumerate(body_chunks):
        prefix = "\n".join(value for value in (title, summary) if value)
        document = f"{prefix}\n{body_chunk}" if prefix else body_chunk
        chunks.append(
            {
                "id": f"{source_id}:{index}",
                "document": document,
                "metadata": {
                    **metadata_base,
                    "chunk_index": index,
                    "total_chunks": total_chunks,
                },
            }
        )
    return chunks


def _has_usable_list_text(record: Dict[str, Any]) -> bool:
    for field in ("contentWithTag", "content", "summary"):
        if _clean_body(record.get(field)):
            return True
    return False


def _append_error(stats: Dict[str, Any], error: Dict[str, Any]) -> None:
    stats["error_count"] = int(stats.get("error_count", 0)) + 1
    if len(stats["errors"]) < MAX_RECORDED_ERRORS:
        stats["errors"].append(error)


def _base_stats() -> Dict[str, Any]:
    return {
        "status": "error",
        "subject_id": SUBJECT_ID,
        "records_seen": 0,
        "details_succeeded": 0,
        "detail_fallbacks": 0,
        "skipped": 0,
        "failed": 0,
        "chunks_written": 0,
        "errors": [],
        "error_count": 0,
        "collection_count": 0,
        "stale_chunks_removed": 0,
        "skipped_pages": [],
        "skipped_page_errors": [],
    }


def ingest_latest_news(
    client: Any | None = None,
    store: Any | None = None,
    limit: int = DEFAULT_LIMIT,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    client = client or EmbodiedNewsClient()
    store = store or EmbodiedNewsStore()
    stats = _base_stats()
    try:
        result = client.list_news(page_no=1, page_size=min(page_size, limit))
    except Exception as exc:
        _append_error(stats, {"stage": "list", "error": str(exc)})
        return stats
    records = list(result.get("records") or [])[:limit]
    stats["records_seen"] = len(records)
    current_source_ids = set()
    for record in records:
        source_id = str(record.get("id") or record.get("infoId") or "").strip()
        if not source_id:
            stats["skipped"] += 1
            _append_error(stats, {"stage": "record", "error": "missing source ID"})
            continue
        current_source_ids.add(source_id)
        try:
            detail = client.get_detail(source_id)
        except Exception as exc:
            detail = {}
            stats["detail_fallbacks"] += 1
            _append_error(stats, {
                "stage": "detail",
                "id": source_id,
                "error": str(exc),
                "fallback": "list_record",
            })
        merged = dict(record)
        if isinstance(detail, dict):
            merged.update({key: value for key, value in detail.items() if value not in (None, "")})
        chunks = build_chunks(merged, SUBJECT_ID)
        if not chunks:
            stats["skipped"] += 1
            continue
        if detail:
            stats["details_succeeded"] += 1
        try:
            stats["chunks_written"] += int(store.upsert(chunks))
        except Exception as exc:
            stats["failed"] += 1
            _append_error(stats, {"stage": "upsert", "id": source_id, "error": str(exc)})
    if current_source_ids and hasattr(store, "prune_sources"):
        try:
            stats["stale_chunks_removed"] = int(store.prune_sources(current_source_ids))
        except Exception as exc:
            _append_error(stats, {"stage": "prune", "error": str(exc)})
    try:
        stats["collection_count"] = int(store.count())
    except Exception as exc:
        _append_error(stats, {"stage": "count", "error": str(exc)})
    if stats["chunks_written"] > 0:
        stats["status"] = "partial_success" if stats["failed"] or len(stats["errors"]) else "success"
    return stats


def _stats_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    stats = _base_stats()
    for key in (
        "records_seen",
        "details_succeeded",
        "detail_fallbacks",
        "skipped",
        "failed",
        "chunks_written",
        "collection_count",
        "stale_chunks_removed",
        "error_count",
    ):
        stats[key] = int(state.get(key, 0))
    stats["errors"] = list(state.get("errors", []))[:MAX_RECORDED_ERRORS]
    stats["skipped_pages"] = [int(value) for value in state.get("skipped_pages", [])]
    stats["skipped_page_errors"] = list(state.get("skipped_page_errors", []))[:MAX_RECORDED_ERRORS]
    return stats


def _merge_nonempty(base: Dict[str, Any], extra: Any) -> Dict[str, Any]:
    merged = dict(base)
    if isinstance(extra, dict):
        merged.update({key: value for key, value in extra.items() if value not in (None, "")})
    return merged


def _process_full_record(
    client: Any,
    record: Dict[str, Any],
    stats: Dict[str, Any],
) -> tuple[str, List[Dict[str, Any]]]:
    source_id = str(record.get("id") or record.get("infoId") or "").strip()
    if not source_id:
        stats["skipped"] += 1
        _append_error(stats, {"stage": "record", "error": "missing source ID"})
        return "", []

    detail: Dict[str, Any] = {}
    if not _has_usable_list_text(record):
        try:
            detail = client.get_detail(source_id)
            if isinstance(detail, dict) and detail:
                stats["details_succeeded"] += 1
            else:
                detail = {}
        except Exception as exc:
            stats["detail_fallbacks"] += 1
            _append_error(stats, {
                "stage": "detail",
                "id": source_id,
                "error": str(exc),
                "fallback": "list_record",
            })

    chunks = build_chunks(_merge_nonempty(record, detail), SUBJECT_ID)
    if not chunks:
        stats["skipped"] += 1
    return source_id, chunks


def ingest_all_news(
    client: Any | None = None,
    store: Any | None = None,
    manifest_path: Path | str = DEFAULT_FULL_MANIFEST,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    resume: bool = True,
    retry_count: int = 3,
    sleep_seconds: float = 0.2,
    limit_records: int | None = None,
    skip_failed_pages: bool = False,
) -> Dict[str, Any]:
    """Build a resumable full snapshot of the status=1 embodied feed."""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if retry_count < 0:
        raise ValueError("retry_count cannot be negative")
    if max_pages is not None and max_pages <= 0:
        raise ValueError("max_pages must be positive")
    if limit_records is not None and limit_records <= 0:
        raise ValueError("limit_records must be positive")

    client = client or EmbodiedNewsClient()
    store = store or EmbodiedNewsStore()
    manifest = EmbodiedIngestionManifest(manifest_path)
    existing = manifest.load() if resume else {}
    resumable = (
        existing
        and existing.get("status") in {"running", "failed"}
        and existing.get("subject_id") == SUBJECT_ID
        and int(existing.get("data_status", 1)) == 1
        and int(existing.get("page_size", page_size)) == page_size
    )
    state = existing if resumable else manifest.start(total=0, page_size=page_size, status=1)
    stats = _stats_from_state(state)
    if resumable:
        # Historical failures remain in the manifest, but a recovered invocation
        # should report only errors from the current attempt.
        stats["errors"] = []
        stats["error_count"] = 0
    current_source_ids = set(str(value) for value in state.get("source_ids", []))
    next_page = max(1, int(state.get("next_page", 1)))
    total_pages = int(state.get("total_pages", 0))
    pages_processed = 0
    limited = False

    while True:
        if max_pages is not None and pages_processed >= max_pages:
            limited = True
            break
        if total_pages and next_page > total_pages:
            break

        result = None
        last_error = None
        for attempt in range(retry_count + 1):
            try:
                result = client.list_news(page_no=next_page, page_size=page_size)
                break
            except Exception as exc:
                last_error = exc
                if attempt < retry_count and sleep_seconds > 0:
                    time.sleep(sleep_seconds)
        if result is None:
            error = {"stage": "list", "page": next_page, "error": str(last_error)}
            manifest.fail(error)
            _append_error(stats, error)
            try:
                stats["collection_count"] = int(store.count())
                manifest.save_runtime_stats(stats)
            except Exception as exc:
                _append_error(stats, {"stage": "count", "error": str(exc)})
            stats["status"] = "failed"
            return stats

        total = int(result.get("total") or 0)
        reported_pages = int(result.get("pages") or 0)
        calculated_pages = math.ceil(total / page_size) if total else 0
        total_pages = reported_pages or calculated_pages or total_pages
        manifest.set_snapshot_info(total=total, total_pages=total_pages)
        records = list(result.get("records") or [])
        if not records:
            if next_page == 1 or (total_pages and next_page <= total_pages):
                error = {"stage": "list", "page": next_page, "error": "empty page before snapshot completed"}
                manifest.fail(error)
                _append_error(stats, error)
                stats["status"] = "failed"
                return stats
            break

        if limit_records is not None:
            remaining = limit_records - stats["records_seen"]
            if remaining <= 0:
                limited = True
                break
            if len(records) > remaining:
                records = records[:remaining]
                limited = True

        page_source_ids = set()
        page_chunks: List[Dict[str, Any]] = []
        page_failed = False
        for record in records:
            if not isinstance(record, dict):
                stats["skipped"] += 1
                _append_error(stats, {"stage": "record", "page": next_page, "error": "record is not an object"})
                continue
            source_id = str(record.get("id") or record.get("infoId") or "").strip()
            if source_id:
                page_source_ids.add(source_id)
            try:
                _, chunks = _process_full_record(client, record, stats)
                page_chunks.extend(chunks)
            except Exception as exc:
                page_failed = True
                stats["failed"] += 1
                _append_error(stats, {"stage": "upsert", "page": next_page, "id": source_id, "error": str(exc)})

        if page_failed:
            error = {"stage": "page", "page": next_page, "error": "page processing failed"}
            if skip_failed_pages:
                stats["records_seen"] += len(records)
                stats["skipped_pages"].append(next_page)
                stats["skipped_pages"] = sorted(set(stats["skipped_pages"]))
                stats["skipped_page_errors"].append(error)
                manifest.mark_page_skipped(next_page, len(records), error)
                pages_processed += 1
                next_page += 1
                continue
            manifest.fail({"stage": "page", "page": next_page, "error": "page processing failed"})
            stats["status"] = "failed"
            return stats

        try:
            if page_chunks:
                page_written = int(store.upsert(page_chunks))
            else:
                page_written = 0
        except Exception as exc:
            stats["failed"] += 1
            error = {"stage": "upsert", "page": next_page, "error": str(exc)}
            _append_error(stats, error)
            if skip_failed_pages:
                stats["records_seen"] += len(records)
                stats["skipped_pages"].append(next_page)
                stats["skipped_pages"] = sorted(set(stats["skipped_pages"]))
                stats["skipped_page_errors"].append(error)
                manifest.mark_page_skipped(next_page, len(records), error)
                manifest.save_runtime_stats(stats)
                pages_processed += 1
                next_page += 1
                continue
            manifest.fail({"stage": "page", "page": next_page, "error": "page processing failed"})
            stats["status"] = "failed"
            return stats

        current_source_ids.update(page_source_ids)
        stats["records_seen"] += len(records)
        stats["chunks_written"] += page_written
        manifest.mark_page_complete(
            page_no=next_page,
            records=len(records),
            chunks=page_written,
            source_ids=page_source_ids,
            details_succeeded=0,
            detail_fallbacks=0,
            skipped=0,
            failed=0,
        )
        # Counters that may have been incremented while processing this page are
        # persisted separately so a resume does not lose them.
        manifest.save_runtime_stats(stats)
        pages_processed += 1
        next_page += 1
        if limited or (limit_records is not None and stats["records_seen"] >= limit_records):
            limited = True
            break
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    traversal_complete = not limited and stats["records_seen"] > 0
    snapshot_complete = traversal_complete and not stats["skipped_pages"]
    stale_removed = 0
    if snapshot_complete and current_source_ids and hasattr(store, "prune_sources"):
        try:
            stale_removed = int(store.prune_sources(current_source_ids))
            stats["stale_chunks_removed"] = stale_removed
        except Exception as exc:
            _append_error(stats, {"stage": "prune", "error": str(exc)})
            snapshot_complete = False
    try:
        stats["collection_count"] = int(store.count())
    except Exception as exc:
        _append_error(stats, {"stage": "count", "error": str(exc)})

    stats["status"] = "success" if snapshot_complete and stats["error_count"] == 0 else "partial_success"
    if stats["records_seen"] == 0:
        stats["status"] = "error"
    final_state = manifest.finish(
        collection_count=stats["collection_count"],
        stale_chunks_removed=stale_removed,
        snapshot_complete=snapshot_complete,
    )
    final_state["details_succeeded"] = stats["details_succeeded"]
    final_state["detail_fallbacks"] = stats["detail_fallbacks"]
    final_state["skipped"] = stats["skipped"]
    final_state["failed"] = stats["failed"]
    final_state["error_count"] = stats["error_count"]
    final_state["errors"] = stats["errors"][:MAX_RECORDED_ERRORS]
    final_state["skipped_pages"] = stats["skipped_pages"]
    final_state["skipped_page_errors"] = stats["skipped_page_errors"][:MAX_RECORDED_ERRORS]
    manifest._write(final_state)
    return stats


def validate_embodied_collection(store: Any | None = None) -> Dict[str, Any]:
    store = store or EmbodiedNewsStore()
    rows = store.collection.get(include=["metadatas"])
    source_ids = {
        str(metadata.get("source_id"))
        for metadata in rows.get("metadatas", [])
        if isinstance(metadata, dict) and metadata.get("source_id")
    }
    return {
        "collection": "embodied_news",
        "count": int(store.count()),
        "unique_source_ids": len(source_ids),
        "embedding_dimension": 768,
        "model_path": str(MODEL_PATH),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest latest embodied subject news")
    parser.add_argument("--all", action="store_true", dest="full_run")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--limit-records", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_FULL_MANIFEST)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--retry-count", type=int, default=3)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--skip-failed-pages", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        print(validate_embodied_collection())
        return 0
    if args.full_run:
        stats = ingest_all_news(
            page_size=args.page_size,
            max_pages=args.max_pages,
            resume=args.resume,
            retry_count=args.retry_count,
            sleep_seconds=args.sleep_seconds,
            limit_records=args.limit_records,
            manifest_path=args.manifest,
            skip_failed_pages=args.skip_failed_pages,
        )
    else:
        stats = ingest_latest_news(limit=args.limit, page_size=args.page_size)
    print(stats)
    return 0 if stats["status"] in {"success", "partial_success"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
