"""Shared records exchanged by report retrieval components."""

from dataclasses import dataclass, field, replace
from decimal import Decimal
import math
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from retrieval_core._copying import deep_freeze_mapping, deep_freeze_value


def _frozen_timings(values: Mapping[str, float]) -> Mapping[str, float]:
    normalized = {}
    for stage, value in values.items():
        if not isinstance(stage, str) or not stage:
            raise ValueError("timings must map stage names to finite non-negative numbers")
        try:
            frozen_value = deep_freeze_value(value)
            if type(frozen_value) not in (int, float, Decimal):
                raise ValueError
            number = float(frozen_value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(
                "timings must map stage names to finite non-negative numbers"
            ) from error
        if not math.isfinite(number) or number < 0:
            raise ValueError("timings must map stage names to finite non-negative numbers")
        normalized[str(stage)] = number
    return deep_freeze_mapping(normalized)


def _frozen_candidate_counts(values: Mapping[str, int]) -> Mapping[str, int]:
    normalized = {}
    for stage, value in values.items():
        if not isinstance(stage, str) or not stage:
            raise ValueError(
                "candidate_counts must map stage names to non-negative integers"
            )
        try:
            frozen_value = deep_freeze_value(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "candidate_counts must map stage names to non-negative integers"
            ) from error
        if type(frozen_value) is not int or frozen_value < 0:
            raise ValueError(
                "candidate_counts must map stage names to non-negative integers"
            )
        normalized[str(stage)] = frozen_value
    return deep_freeze_mapping(normalized)


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


@dataclass(frozen=True)
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
        object.__setattr__(self, "metadata", deep_freeze_mapping(self.metadata))
        object.__setattr__(
            self, "diagnostics", deep_freeze_mapping(self.diagnostics)
        )

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
    warnings: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    timings: Mapping[str, float] = field(default_factory=dict)
    candidate_counts: Mapping[str, int] = field(default_factory=dict)
    retrieval_version: str = "hybrid_v2"
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidates",
            tuple(replace(candidate) for candidate in self.candidates),
        )
        object.__setattr__(
            self,
            "warnings",
            tuple(deep_freeze_mapping(warning) for warning in self.warnings),
        )
        object.__setattr__(self, "timings", _frozen_timings(self.timings))
        object.__setattr__(
            self,
            "candidate_counts",
            _frozen_candidate_counts(self.candidate_counts),
        )
