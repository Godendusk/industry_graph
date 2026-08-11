"""Chroma-backed dense retrieval storage with explicit embeddings."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Set

from retrieval_core.schemas import ChunkRecord, RetrievalCandidate


COLLECTION_NAME = "report_external_v2"
_JSON_PREFIX = "__retrieval_core_json_v1__:"


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return [
            "mapping",
            [
                [str(key), _json_value(item)]
                for key, item in sorted(
                    value.items(), key=lambda pair: str(pair[0])
                )
            ],
        ]
    if isinstance(value, tuple):
        return ["tuple", [_json_value(item) for item in value]]
    if isinstance(value, list):
        return ["list", [_json_value(item) for item in value]]
    if value is None or isinstance(value, (str, int, float, bool)):
        return ["scalar", value]
    return ["scalar", str(value)]


def _restore_json(value: Any) -> Any:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("invalid dense metadata payload")
    kind, payload = value
    if kind == "mapping":
        return {str(key): _restore_json(item) for key, item in payload}
    if kind == "tuple":
        return tuple(_restore_json(item) for item in payload)
    if kind == "list":
        return [_restore_json(item) for item in payload]
    if kind == "scalar":
        return payload
    raise ValueError("unknown dense metadata payload")


def _encode_metadata_value(value: Any) -> Any:
    if (
        isinstance(value, (str, int, float, bool))
        and value is not None
        and not (isinstance(value, str) and value.startswith(_JSON_PREFIX))
    ):
        return value
    encoded = json.dumps(_json_value(value), ensure_ascii=False, separators=(",", ":"))
    return _JSON_PREFIX + encoded


def _decode_metadata_value(value: Any) -> Any:
    if not isinstance(value, str) or not value.startswith(_JSON_PREFIX):
        return value
    try:
        return _restore_json(json.loads(value[len(_JSON_PREFIX) :]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _list_value(value: Any) -> List[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _query_row(value: Any) -> List[Any]:
    values = _list_value(value)
    if values and isinstance(values[0], (list, tuple)):
        return _list_value(values[0])
    return values


def _numeric_vector(vector: Sequence[Any], name: str) -> List[float]:
    if isinstance(vector, (str, bytes)):
        raise ValueError(f"{name} must be a nonempty numeric vector")
    try:
        values = list(vector)
    except TypeError as error:
        raise ValueError(f"{name} must be a nonempty numeric vector") from error
    if not values:
        raise ValueError(f"{name} must be a nonempty vector")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in values
    ):
        raise ValueError(f"{name} values must be numeric")
    result = [float(value) for value in values]
    if any(not math.isfinite(value) for value in result):
        raise ValueError(f"{name} values must be finite")
    return result


class DenseStore:
    """Wrap exactly one cosine Chroma collection.

    ``client_factory`` receives the configured :class:`Path`.  Supplying a
    collection directly avoids importing or initializing Chroma, which keeps
    unit tests and callers with externally managed clients isolated.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        collection: Any = None,
        client_factory: Optional[Callable[[Path], Any]] = None,
        batch_size: int = 100,
        page_size: int = 1000,
    ) -> None:
        for name, value in (("batch_size", batch_size), ("page_size", page_size)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.path = None if path is None else Path(path)
        self._collection_value = collection
        self._client_factory = client_factory
        self._client: Any = None
        self.batch_size = batch_size
        self.page_size = page_size

    def _collection(self) -> Any:
        if self._collection_value is not None:
            return self._collection_value
        if self.path is None:
            raise ValueError("path is required when collection is not injected")
        if self._client_factory is None:
            # Construction is intentionally delayed until the store is used.
            self.path.mkdir(parents=True, exist_ok=True)
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.path))
        else:
            self._client = self._client_factory(self.path)
        self._collection_value = self._client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
        return self._collection_value

    @staticmethod
    def _metadata(chunk: ChunkRecord) -> Mapping[str, Any]:
        values = dict(chunk.metadata)
        values.update(
            {
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
                "content_hash": chunk.content_hash,
                "previous_chunk_id": chunk.previous_chunk_id,
                "next_chunk_id": chunk.next_chunk_id,
            }
        )
        return {
            str(key): _encode_metadata_value(value)
            for key, value in sorted(values.items(), key=lambda pair: str(pair[0]))
        }

    def upsert_chunks(
        self, chunks: Sequence[ChunkRecord], embeddings: Sequence[Sequence[float]]
    ) -> None:
        chunks_values = list(chunks)
        embeddings_values = list(embeddings)
        if not chunks_values:
            raise ValueError("chunks must be nonempty")
        if len(chunks_values) != len(embeddings_values):
            raise ValueError("chunks and embeddings must have the same length")
        if any(not isinstance(item, ChunkRecord) for item in chunks_values):
            raise ValueError("chunks must contain ChunkRecord values")
        vectors = [
            _numeric_vector(vector, f"embedding {index}")
            for index, vector in enumerate(embeddings_values)
        ]
        dimension = len(vectors[0])
        if any(len(vector) != dimension for vector in vectors):
            raise ValueError("all embeddings must have the same dimension")

        collection = self._collection()
        for start in range(0, len(chunks_values), self.batch_size):
            chunk_batch = chunks_values[start : start + self.batch_size]
            collection.upsert(
                ids=[item.chunk_id for item in chunk_batch],
                documents=[item.text for item in chunk_batch],
                metadatas=[self._metadata(item) for item in chunk_batch],
                embeddings=vectors[start : start + self.batch_size],
            )

    @staticmethod
    def _ids(ids: Iterable[str]) -> List[str]:
        if isinstance(ids, str):
            values = [ids]
        else:
            try:
                values = list(ids)
            except TypeError as error:
                raise ValueError("ids must be an iterable of strings") from error
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("ids must contain nonempty strings")
        return values

    def delete_ids(self, ids: Iterable[str]) -> None:
        values = self._ids(ids)
        if not values:
            return
        collection = self._collection()
        for start in range(0, len(values), self.batch_size):
            collection.delete(ids=values[start : start + self.batch_size])

    def delete_document(self, document_id: str) -> None:
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id must be a nonempty string")
        self._collection().delete(where={"document_id": document_id})

    def _paged_ids(self, where: Optional[Mapping[str, Any]] = None) -> Set[str]:
        collection = self._collection()
        result: Set[str] = set()
        offset = 0
        while True:
            arguments: dict[str, Any] = {
                "limit": self.page_size,
                "offset": offset,
                "include": [],
            }
            if where is not None:
                arguments["where"] = dict(where)
            response = collection.get(**arguments) or {}
            page = _list_value(response.get("ids")) if isinstance(response, Mapping) else []
            result.update(str(value) for value in page if isinstance(value, str))
            if len(page) < self.page_size:
                break
            offset += len(page)
        return result

    def ids_for_document(self, document_id: str) -> Set[str]:
        if not isinstance(document_id, str) or not document_id:
            raise ValueError("document_id must be a nonempty string")
        return self._paged_ids({"document_id": document_id})

    def all_chunk_ids(self) -> Set[str]:
        return self._paged_ids()

    def count(self) -> int:
        return int(self._collection().count())

    def dimension(self) -> Optional[int]:
        collection = self._collection()
        if int(collection.count()) == 0:
            return None
        response = collection.get(limit=1, include=["embeddings"]) or {}
        if not isinstance(response, Mapping):
            return None
        embeddings = _list_value(response.get("embeddings"))
        if not embeddings:
            return None
        first = _list_value(embeddings[0])
        return len(first) or None

    @staticmethod
    def _libraries(libraries: Optional[Iterable[str]]) -> Optional[List[str]]:
        if libraries is None:
            return None
        if isinstance(libraries, str):
            values = [libraries]
        else:
            try:
                values = list(libraries)
            except TypeError as error:
                raise ValueError("libraries must be an iterable of strings") from error
        if any(not isinstance(value, str) for value in values):
            raise ValueError("libraries must be an iterable of strings")
        return sorted(set(values))

    def search(
        self,
        query_embedding: Sequence[float],
        limit: int,
        libraries: Optional[Iterable[str]] = None,
    ) -> List[RetrievalCandidate]:
        vector = _numeric_vector(query_embedding, "query_embedding")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        library_values = self._libraries(libraries)
        if library_values == []:
            return []

        arguments: dict[str, Any] = {
            "query_embeddings": [vector],
            "n_results": limit,
            "include": ["documents", "metadatas", "distances"],
        }
        if library_values is not None:
            arguments["where"] = (
                {"library": library_values[0]}
                if len(library_values) == 1
                else {"library": {"$in": library_values}}
            )
        response = self._collection().query(**arguments) or {}
        if not isinstance(response, Mapping):
            return []
        ids = _query_row(response.get("ids"))
        documents = _query_row(response.get("documents"))
        metadatas = _query_row(response.get("metadatas"))
        distances = _query_row(response.get("distances"))
        candidates: List[RetrievalCandidate] = []
        for index, chunk_id in enumerate(ids):
            if not isinstance(chunk_id, str) or not chunk_id:
                continue
            if index >= len(documents) or index >= len(distances):
                continue
            document = documents[index]
            distance = distances[index]
            if not isinstance(document, str):
                continue
            if isinstance(distance, bool) or not isinstance(distance, (int, float)):
                continue
            stored_metadata = metadatas[index] if index < len(metadatas) else {}
            if not isinstance(stored_metadata, Mapping):
                stored_metadata = {}
            metadata = {
                str(key): _decode_metadata_value(value)
                for key, value in stored_metadata.items()
            }
            document_id = metadata.get("document_id", metadata.get("material_id", ""))
            candidates.append(
                RetrievalCandidate(
                    chunk_id=chunk_id,
                    document_id=str(document_id),
                    text=document,
                    metadata=metadata,
                    dense_rank=index + 1,
                    dense_distance=float(distance),
                    dense_score=1.0 - float(distance),
                    diagnostics={"dense_distance": float(distance)},
                )
            )
        return candidates
