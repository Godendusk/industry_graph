"""Shared records exchanged by report retrieval components."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    embedding_text: str
    search_text: str
    token_count: int
    content_hash: str
    metadata: Mapping[str, Any]
    previous_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None

    def __post_init__(self) -> None:
        for field_name in ("chunk_id", "document_id", "text"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass
class RetrievalCandidate:
    chunk_id: str
    document_id: str
    text: str
    metadata: Mapping[str, Any]
    dense_rank: Optional[int] = None
    dense_score: Optional[float] = None
    dense_distance: Optional[float] = None
    bm25_rank: Optional[int] = None
    bm25_score: Optional[float] = None
    rrf_rank: Optional[int] = None
    rrf_score: Optional[float] = None
    rerank_rank: Optional[int] = None
    rerank_score: Optional[float] = None
    business_score: Optional[float] = None
    final_rank: Optional[int] = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.metadata = MappingProxyType(dict(self.metadata))
        self.diagnostics = MappingProxyType(dict(self.diagnostics))

    @classmethod
    def from_chunk(cls, chunk: ChunkRecord) -> "RetrievalCandidate":
        return cls(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            text=chunk.text,
            metadata=chunk.metadata,
        )


@dataclass(frozen=True)
class RetrievalResult:
    status: str
    query: str
    candidates: Tuple[RetrievalCandidate, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    timings: Mapping[str, float] = field(default_factory=dict)
    retrieval_version: str = "hybrid_v2"
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "timings", MappingProxyType(dict(self.timings)))
