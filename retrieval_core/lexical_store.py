"""Transactional SQLite FTS5 storage for lexical report retrieval."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Set

from retrieval_core.schemas import ChunkRecord, RetrievalCandidate


_TUPLE_MARKER = "__retrieval_core_tuple__"


def _json_value(value: Any) -> Any:
    """Convert immutable/nested metadata into a JSON-safe representation."""
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return {_TUPLE_MARKER: [_json_value(item) for item in value]}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _json_object(value: Mapping[str, Any]) -> Any:
    if set(value) == {_TUPLE_MARKER} and isinstance(value[_TUPLE_MARKER], list):
        return tuple(value[_TUPLE_MARKER])
    return dict(value)


def _dump_json(value: Any) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, separators=(",", ":"))


def _load_json(value: str) -> Any:
    return json.loads(value, object_hook=_json_object)


def _field_text(value: Any) -> str:
    if isinstance(value, (tuple, list)):
        return " ".join(_field_text(item) for item in value if item is not None)
    return "" if value is None else str(value)


class LexicalStore:
    """SQLite-backed chunk authority and standalone FTS5 lexical index.

    Each public operation opens and closes its own connection, so instances do
    not share sqlite connection state between threads.
    """

    def __init__(
        self,
        path: Path,
        query_tokenizer: Optional[Callable[[str], Iterable[str]]] = None,
    ) -> None:
        self.path = Path(path)
        self.query_tokenizer = query_tokenizer
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    library TEXT NOT NULL,
                    material_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(document_id)
                        ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding_text TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    previous_chunk_id TEXT,
                    next_chunk_id TEXT,
                    library TEXT NOT NULL,
                    material_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    section_path_json TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    title_tokens TEXT NOT NULL,
                    entity_tokens TEXT NOT NULL,
                    section_tokens TEXT NOT NULL,
                    body_tokens TEXT NOT NULL,
                    UNIQUE(document_id, chunk_index)
                );

                CREATE INDEX IF NOT EXISTS chunks_document_index
                    ON chunks(document_id, chunk_index, chunk_id);
                CREATE INDEX IF NOT EXISTS chunks_library_index
                    ON chunks(library);

                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    title_tokens,
                    entity_tokens,
                    section_tokens,
                    body_tokens
                );

                CREATE TABLE IF NOT EXISTS index_metadata (
                    metadata_key TEXT PRIMARY KEY,
                    metadata_value TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterable[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _document_fields(chunk: ChunkRecord) -> tuple[str, str, str, Mapping[str, Any]]:
        metadata = chunk.metadata
        return (
            _field_text(metadata.get("library")),
            _field_text(metadata.get("material_id")),
            _field_text(metadata.get("title")),
            metadata,
        )

    @staticmethod
    def _validate_document(document_id: str, chunks: Sequence[ChunkRecord]) -> None:
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id must be a nonempty string")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError("chunks must be a nonempty list")
        for chunk in chunks:
            if not isinstance(chunk, ChunkRecord):
                raise ValueError("chunks must contain ChunkRecord values")
            if chunk.document_id != document_id:
                raise ValueError("every chunk document_id must match document_id")
            if isinstance(chunk.chunk_index, bool) or not isinstance(chunk.chunk_index, int):
                raise ValueError("chunk_index must be an integer")
            if chunk.chunk_index < 0:
                raise ValueError("chunk_index must be nonnegative")

    @staticmethod
    def _fts_fields(chunk: ChunkRecord) -> tuple[str, str, str, str]:
        metadata = chunk.metadata
        title = _field_text(metadata.get("title"))
        entities = _field_text(
            metadata.get("entity_tokens", metadata.get("entities", ""))
        )
        section = _field_text(metadata.get("section_path"))
        body = chunk.search_text or chunk.text
        return title, entities, section, body

    def replace_document(self, document_id: str, chunks: List[ChunkRecord]) -> None:
        """Atomically replace every chunk and FTS row for one document."""
        self._validate_document(document_id, chunks)
        library, material_id, title, document_metadata = self._document_fields(chunks[0])
        with self._connection() as connection:
            with connection:
                connection.execute(
                    "DELETE FROM chunks_fts WHERE chunk_id IN "
                    "(SELECT chunk_id FROM chunks WHERE document_id = ?)",
                    (document_id,),
                )
                connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
                connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
                connection.execute(
                    "INSERT INTO documents "
                    "(document_id, library, material_id, title, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        document_id,
                        library,
                        material_id,
                        title,
                        _dump_json(document_metadata),
                    ),
                )
                for chunk in chunks:
                    chunk_library, chunk_material_id, chunk_title, _ = self._document_fields(chunk)
                    section_path = chunk.metadata.get("section_path", ())
                    content_type = _field_text(chunk.metadata.get("content_type"))
                    title_tokens, entity_tokens, section_tokens, body_tokens = self._fts_fields(
                        chunk
                    )
                    connection.execute(
                        "INSERT INTO chunks ("
                        "chunk_id, document_id, chunk_index, text, embedding_text, search_text, "
                        "token_count, content_hash, metadata_json, previous_chunk_id, next_chunk_id, "
                        "library, material_id, title, section_path_json, content_type, "
                        "title_tokens, entity_tokens, section_tokens, body_tokens"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            chunk.chunk_id,
                            chunk.document_id,
                            chunk.chunk_index,
                            chunk.text,
                            chunk.embedding_text,
                            chunk.search_text,
                            chunk.token_count,
                            chunk.content_hash,
                            _dump_json(chunk.metadata),
                            chunk.previous_chunk_id,
                            chunk.next_chunk_id,
                            chunk_library,
                            chunk_material_id,
                            chunk_title,
                            _dump_json(section_path),
                            content_type,
                            title_tokens,
                            entity_tokens,
                            section_tokens,
                            body_tokens,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO chunks_fts "
                        "(chunk_id, title_tokens, entity_tokens, section_tokens, body_tokens) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            chunk.chunk_id,
                            title_tokens,
                            entity_tokens,
                            section_tokens,
                            body_tokens,
                        ),
                    )

    def delete_document(self, document_id: str) -> None:
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id must be a nonempty string")
        with self._connection() as connection:
            with connection:
                connection.execute(
                    "DELETE FROM chunks_fts WHERE chunk_id IN "
                    "(SELECT chunk_id FROM chunks WHERE document_id = ?)",
                    (document_id,),
                )
                connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
                connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))

    def _query_tokens(self, query: str) -> List[str]:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if self.query_tokenizer is None:
            raw_tokens: Iterable[Any] = query.split()
        elif callable(self.query_tokenizer):
            raw_tokens = self.query_tokenizer(query)
        elif callable(getattr(self.query_tokenizer, "cut", None)):
            raw_tokens = self.query_tokenizer.cut(query)
        else:
            raise ValueError("query_tokenizer must be callable or provide cut(text)")
        if isinstance(raw_tokens, str):
            raw_tokens = raw_tokens.split()
        try:
            return [str(token).strip() for token in raw_tokens if str(token).strip()]
        except TypeError as exc:
            raise ValueError("query_tokenizer must return an iterable of tokens") from exc

    @staticmethod
    def _fts_query(tokens: Sequence[str]) -> str:
        # Every token is a quoted literal phrase.  Doubling embedded quotes is
        # FTS5's documented escape, leaving no user-controlled syntax active.
        return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)

    @staticmethod
    def _libraries(libraries: Optional[Iterable[str]]) -> Optional[List[str]]:
        if libraries is None:
            return None
        if isinstance(libraries, str):
            values = [libraries]
        else:
            try:
                values = list(libraries)
            except TypeError as exc:
                raise ValueError("libraries must be an iterable of strings") from exc
        if any(not isinstance(value, str) for value in values):
            raise ValueError("libraries must be an iterable of strings")
        return sorted(set(values))

    @staticmethod
    def _candidate(row: sqlite3.Row, rank: int) -> RetrievalCandidate:
        metadata = _load_json(row["metadata_json"])
        metadata.update(
            {
                "chunk_index": row["chunk_index"],
                "previous_chunk_id": row["previous_chunk_id"],
                "next_chunk_id": row["next_chunk_id"],
                "library": row["library"],
                "material_id": row["material_id"],
                "title": row["title"],
                "section_path": _load_json(row["section_path_json"]),
                "content_type": row["content_type"],
            }
        )
        return RetrievalCandidate(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            text=row["text"],
            metadata=metadata,
            bm25_rank=rank,
            bm25_score=float(row["bm25_score"]),
        )

    def search(
        self,
        query: str,
        limit: int,
        libraries: Optional[Iterable[str]] = None,
    ) -> List[RetrievalCandidate]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        tokens = self._query_tokens(query)
        if not tokens:
            return []
        library_values = self._libraries(libraries)
        if library_values == []:
            return []

        sql = (
            "SELECT c.*, bm25(chunks_fts, 0.0, 5.0, 4.0, 2.0, 1.0) AS bm25_score "
            "FROM chunks_fts JOIN chunks AS c ON c.chunk_id = chunks_fts.chunk_id "
            "WHERE chunks_fts MATCH ?"
        )
        parameters: List[Any] = [self._fts_query(tokens)]
        if library_values is not None:
            sql += " AND c.library IN (" + ", ".join("?" for _ in library_values) + ")"
            parameters.extend(library_values)
        sql += " ORDER BY bm25_score ASC, c.chunk_id ASC LIMIT ?"
        parameters.append(limit)
        with self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._candidate(row, rank) for rank, row in enumerate(rows, start=1)]

    def neighbors(self, chunk_id: str, before: int = 1, after: int = 1) -> List[ChunkRecord]:
        for name, value in (("before", before), ("after", after)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        with self._connection() as connection:
            hit = connection.execute(
                "SELECT document_id, chunk_index FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
            if hit is None:
                return []
            rows = connection.execute(
                "SELECT * FROM chunks WHERE document_id = ? AND chunk_index BETWEEN ? AND ? "
                "ORDER BY chunk_index ASC, chunk_id ASC",
                (hit["document_id"], hit["chunk_index"] - before, hit["chunk_index"] + after),
            ).fetchall()
        return [self._chunk(row) for row in rows]

    @staticmethod
    def _chunk(row: sqlite3.Row) -> ChunkRecord:
        return ChunkRecord(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            embedding_text=row["embedding_text"],
            search_text=row["search_text"],
            token_count=row["token_count"],
            content_hash=row["content_hash"],
            metadata=_load_json(row["metadata_json"]),
            previous_chunk_id=row["previous_chunk_id"],
            next_chunk_id=row["next_chunk_id"],
        )

    def set_index_metadata(self, key: str, value: Optional[str]) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("metadata key must be a nonempty string")
        if value is not None and not isinstance(value, str):
            raise ValueError("metadata value must be a string or None")
        with self._connection() as connection:
            with connection:
                if value is None:
                    connection.execute("DELETE FROM index_metadata WHERE metadata_key = ?", (key,))
                else:
                    connection.execute(
                        "INSERT INTO index_metadata (metadata_key, metadata_value) VALUES (?, ?) "
                        "ON CONFLICT(metadata_key) DO UPDATE SET metadata_value = excluded.metadata_value",
                        (key, value),
                    )

    def get_index_metadata(self, key: str) -> Optional[str]:
        if not isinstance(key, str) or not key:
            raise ValueError("metadata key must be a nonempty string")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT metadata_value FROM index_metadata WHERE metadata_key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["metadata_value"])

    def ids_for_document(self, document_id: str) -> Set[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT chunk_id FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
        return {str(row["chunk_id"]) for row in rows}

    def all_chunk_ids(self) -> Set[str]:
        with self._connection() as connection:
            rows = connection.execute("SELECT chunk_id FROM chunks").fetchall()
        return {str(row["chunk_id"]) for row in rows}

    def count(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()
        return int(row["count"])
