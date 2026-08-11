"""Fail-closed coordination for the report v2 lexical and dense indexes.

``audit_only`` exists only for injected test/audit stores whose dense rows are
already present.  A production :class:`DenseStore` always requires real,
validated embeddings and never receives generated placeholder vectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
from threading import RLock
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple

from retrieval_core.dense_store import DenseStore
from retrieval_core._copying import deep_freeze_mapping
from retrieval_core.schemas import ChunkRecord


INDEX_METADATA_KEY = "report_v2_index_state"
COLLECTION_VERSION = "report_v2"
STATE_SCHEMA_VERSION = 2
MAX_AUDIT_IDS = 1_000_000
DEFAULT_MAX_CHUNKS = 100_000
DEFAULT_MAX_TOKENS = 8192
MAX_TOKEN_HARD_CAP = 1_000_000
MAX_EMBEDDING_DIMENSION = 65_536
SUPPORTED_DIMENSION = 768
MAX_READY_BYTES = 1_000_000

_TRANSITION_LOCK = RLock()


@dataclass(frozen=True)
class IndexWriteResult:
    status: str
    document_id: str
    expected_ids: Tuple[str, ...] = ()
    dense_ids: Tuple[str, ...] = ()
    lexical_ids: Tuple[str, ...] = ()
    message: str = ""
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {"success", "inconsistent", "error"}:
            raise ValueError("invalid index write status")
        if type(self.document_id) is not str or type(self.message) is not str:
            raise ValueError("document_id and message must be exact strings")
        for name in ("expected_ids", "dense_ids", "lexical_ids"):
            values = tuple(getattr(self, name))
            if any(type(value) is not str or not value for value in values):
                raise ValueError(f"{name} must contain exact nonempty strings")
            object.__setattr__(self, name, values)
        object.__setattr__(self, "diagnostics", deep_freeze_mapping(self.diagnostics))


@dataclass(frozen=True)
class ReadyCheckResult:
    ready: bool
    failures: Tuple[str, ...]
    facts: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.ready) is not bool:
            raise ValueError("ready must be an exact boolean")
        failures = tuple(self.failures)
        if any(type(value) is not str or not value for value in failures):
            raise ValueError("failures must contain exact nonempty strings")
        object.__setattr__(self, "failures", failures)
        object.__setattr__(self, "facts", deep_freeze_mapping(self.facts))


class V2IndexWriter:
    def __init__(
        self,
        dense: Any,
        lexical: Any,
        *,
        ready_path: Optional[Path] = None,
        index_root: Optional[Path] = None,
        embed_documents: Optional[Callable[[Sequence[str]], Iterable[Sequence[float]]]] = None,
        model_version: Optional[str] = None,
        chunker_version: Optional[str] = None,
        dictionary_version: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
        audit_only: Optional[bool] = None,
    ) -> None:
        if ready_path is not None and index_root is not None:
            raise ValueError("provide ready_path or index_root, not both")
        for name, value in (("max_tokens", max_tokens), ("max_chunks", max_chunks)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if max_tokens > MAX_TOKEN_HARD_CAP:
            raise ValueError("max_tokens exceeds the hard safety limit")
        if audit_only is not None and not isinstance(audit_only, bool):
            raise ValueError("audit_only must be a boolean or None")
        for name, value in (
            ("model_version", model_version),
            ("chunker_version", chunker_version),
            ("dictionary_version", dictionary_version),
        ):
            if value is not None and type(value) is not str:
                raise ValueError(f"{name} must be an exact string or None")
        self.dense = dense
        self.lexical = lexical
        self.ready_path = (
            Path(ready_path)
            if ready_path is not None
            else (Path(index_root) / "READY" if index_root is not None else None)
        )
        self.embed_documents = embed_documents
        self.model_version = model_version
        self.chunker_version = chunker_version
        self.dictionary_version = dictionary_version
        self.max_tokens = max_tokens
        self.max_chunks = max_chunks
        # Non-production injected stores auto-select an audit path so the public
        # mock contract can verify already-present IDs without fake vectors.
        # DenseStore itself remains fail-closed even if audit_only=True.
        self.audit_only = not isinstance(dense, DenseStore) if audit_only is None else audit_only

    @staticmethod
    def _safe_message(stage: str, error: Optional[BaseException] = None) -> str:
        return stage if error is None else f"{stage}: {type(error).__name__}"

    @staticmethod
    def _sorted_ids(values: Iterable[Any], *, limit: int = MAX_AUDIT_IDS) -> Tuple[str, ...]:
        if isinstance(values, (str, bytes)):
            raise ValueError("chunk IDs must be an iterable of strings")
        iterator = iter(values)
        collected = []
        for _ in range(limit + 1):
            try:
                value = next(iterator)
            except StopIteration:
                break
            if type(value) is not str or not value:
                raise ValueError("chunk IDs must be nonempty strings")
            collected.append(value)
        if len(collected) > limit:
            raise ValueError("chunk ID scan exceeds safety limit")
        if len(set(collected)) != len(collected):
            raise ValueError("chunk ID scan contains duplicates")
        return tuple(sorted(collected))

    def _materialize_chunks(self, document_id: str, chunks: Iterable[Any]) -> list[ChunkRecord]:
        if type(document_id) is not str or not document_id.strip():
            raise ValueError("document_id must be a nonblank string")
        if isinstance(chunks, (str, bytes)):
            raise ValueError("chunks must be an iterable")
        iterator = iter(chunks)
        values = []
        for _ in range(self.max_chunks + 1):
            try:
                values.append(next(iterator))
            except StopIteration:
                break
        if not values:
            raise ValueError("chunks must be nonempty")
        if len(values) > self.max_chunks:
            raise ValueError("chunks exceed safety limit")
        if any(not isinstance(row, ChunkRecord) for row in values):
            raise ValueError("chunks must contain ChunkRecord values")
        if any(type(row.chunk_id) is not str or not row.chunk_id for row in values):
            raise ValueError("chunk_id must be an exact nonempty string")
        if any(type(row.document_id) is not str or not row.document_id for row in values):
            raise ValueError("chunk document_id must be an exact nonempty string")
        if any(row.document_id != document_id for row in values):
            raise ValueError("every chunk document_id must match document_id")
        chunk_ids = [row.chunk_id for row in values]
        indexes = [row.chunk_index for row in values]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("chunk_id must be unique")
        if any(type(index) is not int or index < 0 for index in indexes):
            raise ValueError("chunk_index must be a nonnegative integer")
        if len(set(indexes)) != len(indexes):
            raise ValueError("chunk_index must be unique")
        for row in values:
            if (
                type(row.token_count) is not int
                or row.token_count < 0
                or row.token_count > self.max_tokens
            ):
                raise ValueError("token_count is outside the configured limit")
        return values

    @staticmethod
    def _vectors(values: Iterable[Sequence[float]], expected: int) -> list[list[float]]:
        if isinstance(values, (str, bytes)):
            raise ValueError("embeddings must be an iterable")
        iterator = iter(values)
        outer = []
        for _ in range(expected + 1):
            try:
                outer.append(next(iterator))
            except StopIteration:
                break
        if len(outer) != expected:
            raise ValueError("embedding count must match chunk count")
        vectors: list[list[float]] = []
        dimension = None
        for vector in outer:
            if isinstance(vector, (str, bytes)):
                raise ValueError("embedding must be numeric")
            raw = []
            iterator = iter(vector)
            for _ in range(MAX_EMBEDDING_DIMENSION + 1):
                try:
                    raw.append(next(iterator))
                except StopIteration:
                    break
            if not raw or len(raw) > MAX_EMBEDDING_DIMENSION:
                raise ValueError("embedding dimension is invalid")
            if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in raw):
                raise ValueError("embedding values must be numeric")
            converted = [float(item) for item in raw]
            if any(not math.isfinite(item) for item in converted):
                raise ValueError("embedding values must be finite")
            if dimension is None:
                dimension = len(converted)
            elif dimension != len(converted):
                raise ValueError("embeddings must have one dimension")
            vectors.append(converted)
        return vectors

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "collection_version": COLLECTION_VERSION,
            "documents": {},
        }

    def _decode_state(self, raw: Optional[str]) -> dict[str, Any]:
        if raw is None:
            return self._empty_state()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("invalid index metadata")
        required = {"schema_version", "collection_version", "documents"}
        if set(parsed) != required:
            raise ValueError("invalid index metadata schema")
        if (
            type(parsed["schema_version"]) is not int
            or parsed["schema_version"] != STATE_SCHEMA_VERSION
            or type(parsed["collection_version"]) is not str
            or parsed["collection_version"] != COLLECTION_VERSION
        ):
            raise ValueError("invalid index metadata version")
        if not isinstance(parsed["documents"], dict):
            raise ValueError("invalid document states")
        entry_keys = {
            "state", "operation", "expected_ids", "max_token_count", "message",
            "collection_version", "model_version", "chunker_version",
            "dictionary_version",
        }
        for document_id, entry in parsed["documents"].items():
            if type(document_id) is not str or not document_id or not isinstance(entry, dict):
                raise ValueError("invalid document state")
            if set(entry) != entry_keys:
                raise ValueError("invalid document state schema")
            if type(entry["state"]) is not str or entry["state"] not in {"success", "in_progress", "inconsistent"}:
                raise ValueError("invalid document state value")
            if type(entry["operation"]) is not str or entry["operation"] not in {"upsert", "delete"}:
                raise ValueError("invalid document operation")
            ids = entry["expected_ids"]
            if not isinstance(ids, list) or ids != sorted(ids) or len(ids) != len(set(ids)):
                raise ValueError("invalid document expected IDs")
            if any(type(value) is not str or not value for value in ids):
                raise ValueError("invalid document expected IDs")
            if entry["operation"] == "upsert" and not ids:
                raise ValueError("upsert state must contain expected IDs")
            if entry["state"] == "success" and entry["operation"] != "upsert":
                raise ValueError("success state must describe an upsert")
            count = entry["max_token_count"]
            if type(count) is not int or count < 0:
                raise ValueError("invalid document token count")
            if type(entry["message"]) is not str:
                raise ValueError("invalid document state message")
            if type(entry["collection_version"]) is not str or entry["collection_version"] != COLLECTION_VERSION:
                raise ValueError("invalid document collection version")
            for key in ("model_version", "chunker_version", "dictionary_version"):
                if entry[key] is not None and type(entry[key]) is not str:
                    raise ValueError("invalid document generation")
        return parsed

    def _load_state(self) -> dict[str, Any]:
        return self._decode_state(self.lexical.get_index_metadata(INDEX_METADATA_KEY))

    @staticmethod
    def _dump_state(state: Mapping[str, Any]) -> str:
        return json.dumps(
            state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def _atomic_state_update(self, update: Callable[[dict[str, Any]], None]) -> None:
        def transform(raw: Optional[str]) -> str:
            state = self._decode_state(raw)
            update(state)
            dumped = self._dump_state(state)
            self._decode_state(dumped)
            return dumped

        atomic_update = getattr(self.lexical, "update_index_metadata", None)
        if callable(atomic_update):
            atomic_update(INDEX_METADATA_KEY, transform)
        else:
            # Injected fakes are serialized by the process lock. Production
            # LexicalStore uses the SQLite BEGIN IMMEDIATE helper above.
            transformed = transform(self.lexical.get_index_metadata(INDEX_METADATA_KEY))
            self.lexical.set_index_metadata(INDEX_METADATA_KEY, transformed)

    def _document_entry(
        self,
        state_value: str,
        operation: str,
        expected_ids: Sequence[str],
        max_token_count: int,
        message: str,
    ) -> dict[str, Any]:
        return {
            "state": state_value,
            "operation": operation,
            "expected_ids": sorted(expected_ids),
            "max_token_count": max_token_count,
            "message": message,
            "collection_version": COLLECTION_VERSION,
            "model_version": self.model_version,
            "chunker_version": self.chunker_version,
            "dictionary_version": self.dictionary_version,
        }

    def _save_document_state(
        self,
        document_id: str,
        state_value: str,
        expected_ids: Sequence[str],
        max_token_count: int,
        message: str,
        *,
        operation: str = "upsert",
    ) -> None:
        entry = self._document_entry(
            state_value, operation, expected_ids, max_token_count, message
        )
        self._atomic_state_update(
            lambda state: state["documents"].__setitem__(document_id, entry)
        )

    def _remove_document_state(self, document_id: str) -> None:
        self._atomic_state_update(
            lambda state: state["documents"].pop(document_id, None)
        )

    def _invalidate_ready(self) -> None:
        if self.ready_path is not None:
            try:
                self.ready_path.unlink()
            except FileNotFoundError:
                pass

    def _result(self, status: str, document_id: str, expected: Sequence[str], message: str) -> IndexWriteResult:
        try:
            dense_ids = self._sorted_ids(self.dense.ids_for_document(document_id))
        except Exception:
            dense_ids = ()
        try:
            lexical_ids = self._sorted_ids(self.lexical.ids_for_document(document_id))
        except Exception:
            lexical_ids = ()
        return IndexWriteResult(
            status, document_id, tuple(sorted(expected)), dense_ids, lexical_ids, message,
            {"expected_count": len(expected), "dense_count": len(dense_ids), "lexical_count": len(lexical_ids)},
        )

    def upsert_document(
        self,
        document_id: str,
        chunks: Iterable[ChunkRecord],
        embeddings: Optional[Iterable[Sequence[float]]] = None,
    ) -> IndexWriteResult:
        with _TRANSITION_LOCK:
            try:
                rows = self._materialize_chunks(document_id, chunks)
            except Exception as error:
                return IndexWriteResult("error", document_id if type(document_id) is str else "", message=self._safe_message("invalid input", error))
            expected = tuple(sorted(row.chunk_id for row in rows))
            max_token_count = max(row.token_count for row in rows)
            vectors = None
            try:
                if embeddings is not None:
                    vectors = self._vectors(embeddings, len(rows))
                elif self.embed_documents is not None:
                    vectors = self._vectors(
                        self.embed_documents(tuple(row.embedding_text for row in rows)), len(rows)
                    )
                elif isinstance(self.dense, DenseStore) or not self.audit_only:
                    raise ValueError("real embeddings are required")
            except Exception as error:
                self._invalidate_ready()
                try:
                    self._save_document_state(document_id, "inconsistent", expected, max_token_count, "embedding_failed")
                except Exception:
                    pass
                return self._result("error", document_id, expected, self._safe_message("embedding failed", error))

            # Validate the shared state before changing either store.  A
            # malformed metadata row cannot be merged safely without losing
            # other document states, so fail closed and require repair.
            try:
                self._load_state()
                old_dense = set(
                    self._sorted_ids(self.dense.ids_for_document(document_id))
                )
            except Exception as error:
                self._invalidate_ready()
                return self._result(
                    "error", document_id, expected,
                    self._safe_message("index metadata invalid", error),
                )

            self._invalidate_ready()
            try:
                self._save_document_state(
                    document_id,
                    "in_progress",
                    expected,
                    max_token_count,
                    "upsert_started",
                )
            except Exception as error:
                return self._result(
                    "error", document_id, expected,
                    self._safe_message("state write failed", error),
                )
            try:
                self.lexical.replace_document(document_id, list(rows))
            except Exception as error:
                try:
                    self._save_document_state(document_id, "inconsistent", expected, max_token_count, "lexical_failed")
                except Exception:
                    pass
                return self._result("error", document_id, expected, self._safe_message("lexical write failed", error))
            try:
                blocked_stale = set()
                if vectors is not None:
                    self.dense.upsert_chunks(list(rows), vectors)
                    stale = sorted(old_dense - set(expected))
                    if stale:
                        authoritative_ids = set(
                            self._sorted_ids(self.lexical.all_chunk_ids())
                        )
                        blocked_stale = set(stale).intersection(authoritative_ids)
                        safe_stale = sorted(set(stale) - blocked_stale)
                        if safe_stale:
                            self.dense.delete_ids(safe_stale)
                dense_ids = self._sorted_ids(self.dense.ids_for_document(document_id))
                lexical_ids = self._sorted_ids(self.lexical.ids_for_document(document_id))
                exact = (
                    dense_ids == expected
                    and lexical_ids == expected
                    and not blocked_stale
                )
                status = "success" if exact else "inconsistent"
                message = (
                    "index write complete"
                    if exact
                    else (
                        "shared_stale_id_corruption"
                        if blocked_stale
                        else "document_ids_mismatch"
                    )
                )
            except Exception as error:
                status, message = "inconsistent", self._safe_message("dense write failed", error)
            try:
                self._save_document_state(document_id, status, expected, max_token_count, message)
            except Exception as error:
                status, message = "inconsistent", self._safe_message("state write failed", error)
            return self._result(status, document_id, expected, message)

    def delete_document(self, document_id: str) -> IndexWriteResult:
        with _TRANSITION_LOCK:
            if type(document_id) is not str or not document_id.strip():
                return IndexWriteResult("error", document_id if type(document_id) is str else "", message="invalid document_id")
            try:
                self._load_state()
            except Exception as error:
                self._invalidate_ready()
                return IndexWriteResult(
                    "error", document_id,
                    message=self._safe_message("index metadata invalid", error),
                )
            self._invalidate_ready()
            errors = []
            try:
                expected = tuple(
                    sorted(
                        set(self._sorted_ids(self.lexical.ids_for_document(document_id)))
                        | set(self._sorted_ids(self.dense.ids_for_document(document_id)))
                    )
                )
                self._save_document_state(
                    document_id,
                    "in_progress",
                    expected,
                    0,
                    "delete_started",
                    operation="delete",
                )
            except Exception as error:
                return IndexWriteResult(
                    "error", document_id,
                    message=self._safe_message("delete preparation failed", error),
                )
            try:
                self.lexical.delete_document(document_id)
            except Exception as error:
                errors.append(self._safe_message("lexical delete failed", error))
            try:
                self.dense.delete_document(document_id)
            except Exception as error:
                errors.append(self._safe_message("dense delete failed", error))
            try:
                dense_ids = self._sorted_ids(self.dense.ids_for_document(document_id))
                lexical_ids = self._sorted_ids(self.lexical.ids_for_document(document_id))
                if dense_ids or lexical_ids:
                    errors.append("document_ids_remain")
            except Exception as error:
                errors.append(self._safe_message("delete verification failed", error))
            if errors:
                try:
                    remaining = tuple(
                        sorted(
                            set(self._sorted_ids(self.lexical.ids_for_document(document_id)))
                            | set(self._sorted_ids(self.dense.ids_for_document(document_id)))
                        )
                    )
                    self._save_document_state(
                        document_id,
                        "inconsistent",
                        remaining,
                        0,
                        ";".join(errors),
                        operation="delete",
                    )
                except Exception:
                    pass
                return self._result("inconsistent", document_id, (), ";".join(errors))
            try:
                self._remove_document_state(document_id)
            except Exception as error:
                return self._result("inconsistent", document_id, (), self._safe_message("state write failed", error))
            return self._result("success", document_id, (), "document deleted")

    @staticmethod
    def _version(value: Any) -> Optional[str]:
        return value if type(value) is str and bool(value.strip()) else None

    def check_ready(
        self,
        expected_dimension: int = 768,
        expected_model_version: Optional[str] = None,
        expected_chunker_version: Optional[str] = None,
        expected_dictionary_version: Optional[str] = None,
    ) -> ReadyCheckResult:
        with _TRANSITION_LOCK:
            failures = []
            facts: dict[str, Any] = {"collection_version": COLLECTION_VERSION}
            try:
                if type(expected_dimension) is not int or expected_dimension != SUPPORTED_DIMENSION:
                    raise ValueError("expected dimension must be exact integer 768")
                state = self._load_state()
                dense_ids = self._sorted_ids(self.dense.all_chunk_ids())
                lexical_ids = self._sorted_ids(self.lexical.all_chunk_ids())
                dense_count = self.dense.count()
                lexical_count = self.lexical.count()
                if (
                    type(dense_count) is not int
                    or dense_count < 0
                    or type(lexical_count) is not int
                    or lexical_count < 0
                ):
                    raise ValueError("invalid store count")
                raw_dimension = self.dense.dimension()
                dimension = raw_dimension if type(raw_dimension) is int else None
                if dimension is None:
                    failures.append("dimension_mismatch")
                facts.update(dimension=dimension, chunk_count=len(lexical_ids), dense_count=dense_count, lexical_count=lexical_count)
                if dimension != SUPPORTED_DIMENSION:
                    failures.append("dimension_mismatch")
                if not lexical_ids:
                    failures.append("empty_index")
                if dense_ids != lexical_ids or dense_count != len(dense_ids) or lexical_count != len(lexical_ids):
                    failures.append("global_ids_mismatch")
                expected_versions = (
                    expected_model_version if expected_model_version is not None else self.model_version,
                    expected_chunker_version if expected_chunker_version is not None else self.chunker_version,
                    expected_dictionary_version if expected_dictionary_version is not None else self.dictionary_version,
                )
                configured_versions = (
                    self.model_version,
                    self.chunker_version,
                    self.dictionary_version,
                )
                normalized_versions = {}
                for key, expected, configured in zip(
                    ("model_version", "chunker_version", "dictionary_version"),
                    expected_versions,
                    configured_versions,
                ):
                    normalized_versions[key] = self._version(expected)
                    configured_value = self._version(configured)
                    if normalized_versions[key] is None:
                        failures.append(key + "_missing")
                    if configured_value is None:
                        failures.append(key + "_configured_missing")
                    elif configured_value != normalized_versions[key]:
                        failures.append(key + "_configured_mismatch")
                    facts[key] = normalized_versions[key]
                union = set()
                for document_id, entry in state["documents"].items():
                    ids = set(entry["expected_ids"])
                    if entry["state"] != "success" or entry["operation"] != "upsert":
                        failures.append("inconsistent_documents")
                    if entry["collection_version"] != COLLECTION_VERSION:
                        failures.append("collection_version_mismatch")
                    for key, expected in normalized_versions.items():
                        if expected is None or entry[key] != expected:
                            failures.append(key + "_mismatch")
                    if entry["max_token_count"] > self.max_tokens:
                        failures.append("token_limit_exceeded")
                    actual_dense = set(self._sorted_ids(self.dense.ids_for_document(document_id)))
                    actual_lexical = set(self._sorted_ids(self.lexical.ids_for_document(document_id)))
                    if ids != actual_dense or ids != actual_lexical:
                        failures.append("document_ids_mismatch")
                    if union.intersection(ids):
                        failures.append("duplicate_document_ids")
                    union.update(ids)
                if union != set(lexical_ids):
                    failures.append("unrepresented_index_ids")
                if not state["documents"]:
                    failures.append("missing_document_states")
                facts["id_digest"] = hashlib.sha256("\n".join(lexical_ids).encode("utf-8")).hexdigest()
            except Exception as error:
                failures.append(self._safe_message("validation_exception", error))
            unique = tuple(dict.fromkeys(failures))
            return ReadyCheckResult(not unique, unique, facts)

    def can_mark_ready(self, expected_dimension: int = 768, expected_model_version: Optional[str] = None,
                       expected_chunker_version: Optional[str] = None,
                       expected_dictionary_version: Optional[str] = None) -> bool:
        return self.check_ready(expected_dimension, expected_model_version, expected_chunker_version, expected_dictionary_version).ready

    def mark_ready(self, expected_dimension: int = 768, expected_model_version: Optional[str] = None,
                   expected_chunker_version: Optional[str] = None,
                   expected_dictionary_version: Optional[str] = None) -> Mapping[str, Any]:
        with _TRANSITION_LOCK:
            if self.ready_path is None:
                raise ValueError("ready_path or index_root is required")
            check = self.check_ready(expected_dimension, expected_model_version, expected_chunker_version, expected_dictionary_version)
            if not check.ready:
                raise RuntimeError("index is not ready: " + ",".join(check.failures))
            payload = {
                "schema_version": STATE_SCHEMA_VERSION,
                "collection_version": COLLECTION_VERSION,
                "model_version": check.facts["model_version"],
                "chunker_version": check.facts["chunker_version"],
                "dictionary_version": check.facts["dictionary_version"],
                "dimension": check.facts["dimension"],
                "chunk_count": check.facts["chunk_count"],
                "id_digest": check.facts["id_digest"],
                "validation": {"global_ids_equal": True, "all_documents_success": True, "counts_equal": True},
            }
            self.ready_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=".READY.", suffix=".tmp", dir=self.ready_path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, self.ready_path)
                try:
                    directory_fd = os.open(self.ready_path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except OSError:
                    pass
            finally:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
            return payload

    def validate_ready_marker(self, expected_dimension: int = 768) -> bool:
        with _TRANSITION_LOCK:
            if self.ready_path is None:
                return False
            try:
                marker_stat = self.ready_path.lstat()
                if not stat.S_ISREG(marker_stat.st_mode):
                    return False
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self.ready_path, flags)
                try:
                    opened_stat = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(opened_stat.st_mode)
                        or opened_stat.st_ino != marker_stat.st_ino
                        or opened_stat.st_dev != marker_stat.st_dev
                        or opened_stat.st_size <= 0
                        or opened_stat.st_size > MAX_READY_BYTES
                    ):
                        return False
                    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                        descriptor = -1
                        raw = handle.read(MAX_READY_BYTES + 1)
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
                if len(raw.encode("utf-8")) > MAX_READY_BYTES:
                    return False
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    return False
                check = self.check_ready(expected_dimension)
                if not check.ready:
                    return False
                required = {
                    "schema_version", "collection_version", "model_version", "chunker_version",
                    "dictionary_version", "dimension", "chunk_count", "id_digest", "validation",
                }
                validation = payload.get("validation")
                return (
                    set(payload) == required
                    and type(payload["schema_version"]) is int
                    and payload["schema_version"] == STATE_SCHEMA_VERSION
                    and type(payload["collection_version"]) is str
                    and payload["collection_version"] == COLLECTION_VERSION
                    and type(payload["dimension"]) is int
                    and payload["dimension"] == check.facts["dimension"]
                    and payload["dimension"] == SUPPORTED_DIMENSION
                    and type(payload["chunk_count"]) is int
                    and payload["chunk_count"] > 0
                    and payload["chunk_count"] == check.facts["chunk_count"]
                    and type(payload["id_digest"]) is str
                    and len(payload["id_digest"]) == 64
                    and all(character in "0123456789abcdef" for character in payload["id_digest"])
                    and payload["id_digest"] == check.facts["id_digest"]
                    and all(
                        type(payload[key]) is str and bool(payload[key].strip())
                        for key in ("model_version", "chunker_version", "dictionary_version")
                    )
                    and payload["model_version"] == check.facts["model_version"]
                    and payload["chunker_version"] == check.facts["chunker_version"]
                    and payload["dictionary_version"] == check.facts["dictionary_version"]
                    and isinstance(validation, dict)
                    and set(validation) == {
                        "global_ids_equal", "all_documents_success", "counts_equal"
                    }
                    and all(type(value) is bool and value for value in validation.values())
                )
            except Exception:
                return False


__all__ = [
    "COLLECTION_VERSION", "INDEX_METADATA_KEY", "IndexWriteResult",
    "ReadyCheckResult", "V2IndexWriter",
]
