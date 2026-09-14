"""Local, credential-free state for resumable embodied-news ingestion."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable


class EmbodiedIngestionManifest:
    """Persist page progress without storing credentials or response bodies."""

    VERSION = 1

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _write(self, state: Dict[str, Any]) -> Dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return state

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            raise ValueError(f"manifest must contain an object: {self.path}")
        return state

    def start(self, total: int, page_size: int, status: int = 1) -> Dict[str, Any]:
        state = {
            "version": self.VERSION,
            "status": "running",
            "snapshot_complete": False,
            "subject_id": "2043590589800853505",
            "data_status": int(status),
            "page_size": int(page_size),
            "total": int(total),
            "total_pages": 0,
            "next_page": 1,
            "records_seen": 0,
            "details_succeeded": 0,
            "detail_fallbacks": 0,
            "skipped": 0,
            "failed": 0,
            "chunks_written": 0,
            "collection_count": 0,
            "stale_chunks_removed": 0,
            "skipped_pages": [],
            "skipped_page_errors": [],
            "source_ids": [],
            "errors": [],
            "error_count": 0,
        }
        return self._write(state)

    def mark_page_skipped(
        self,
        page_no: int,
        records: int,
        error: Dict[str, Any],
    ) -> Dict[str, Any]:
        state = self.load()
        if not state:
            raise ValueError("cannot skip a page before starting a manifest")
        skipped_pages = [int(value) for value in state.get("skipped_pages", [])]
        if int(page_no) not in skipped_pages:
            skipped_pages.append(int(page_no))
        skipped_errors = list(state.get("skipped_page_errors", []))
        skipped_errors.append(dict(error))
        state["status"] = "running"
        state["snapshot_complete"] = False
        state["next_page"] = int(page_no) + 1
        state["records_seen"] = int(state.get("records_seen", 0)) + int(records)
        state["failed"] = int(state.get("failed", 0)) + 1
        state["skipped_pages"] = sorted(set(skipped_pages))
        state["skipped_page_errors"] = skipped_errors[:100]
        return self._write(state)

    def mark_page_complete(
        self,
        page_no: int,
        records: int,
        chunks: int,
        source_ids: Iterable[str] = (),
        **counters: int,
    ) -> Dict[str, Any]:
        state = self.load()
        if not state:
            raise ValueError("cannot complete a page before starting a manifest")
        known_ids = set(str(value) for value in state.get("source_ids", []))
        known_ids.update(str(value) for value in source_ids if str(value))
        state["next_page"] = int(page_no) + 1
        state["records_seen"] = int(state.get("records_seen", 0)) + int(records)
        state["chunks_written"] = int(state.get("chunks_written", 0)) + int(chunks)
        state["source_ids"] = sorted(known_ids)
        for key, value in counters.items():
            state[key] = int(state.get(key, 0)) + int(value)
        return self._write(state)

    def set_snapshot_info(self, total: int, total_pages: int) -> Dict[str, Any]:
        state = self.load()
        state["total"] = int(total)
        state["total_pages"] = int(total_pages)
        return self._write(state)

    def append_errors(self, errors: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        state = self.load()
        incoming = list(errors)
        existing = list(state.get("errors", []))
        state["error_count"] = int(state.get("error_count", 0)) + len(incoming)
        state["errors"] = (existing + incoming)[:100]
        return self._write(state)

    def save_runtime_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        state = self.load()
        for key in (
            "details_succeeded",
            "detail_fallbacks",
            "skipped",
            "failed",
            "error_count",
            "collection_count",
            "stale_chunks_removed",
        ):
            if key in stats:
                state[key] = int(stats[key])
        if "errors" in stats:
            state["errors"] = list(stats["errors"])[:100]
        return self._write(state)

    def finish(
        self,
        collection_count: int,
        stale_chunks_removed: int = 0,
        snapshot_complete: bool = True,
    ) -> Dict[str, Any]:
        state = self.load()
        if snapshot_complete:
            state["status"] = "completed"
        elif state.get("skipped_pages"):
            state["status"] = "completed_with_skips"
        else:
            state["status"] = "running"
        state["snapshot_complete"] = bool(snapshot_complete)
        state["collection_count"] = int(collection_count)
        state["stale_chunks_removed"] = int(stale_chunks_removed)
        return self._write(state)

    def fail(self, error: Dict[str, Any]) -> Dict[str, Any]:
        state = self.load()
        state["status"] = "failed"
        state["snapshot_complete"] = False
        existing = list(state.get("errors", []))
        state["error_count"] = int(state.get("error_count", 0)) + 1
        state["errors"] = (existing + [error])[:100]
        return self._write(state)
