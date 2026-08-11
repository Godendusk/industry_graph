"""Deterministic reciprocal-rank fusion for retrieval candidates."""

from collections.abc import Mapping as MappingABC
from collections.abc import Sequence as SequenceABC
from dataclasses import replace
import math
from typing import Iterable, List, Mapping, Sequence

from retrieval_core._copying import deep_copy_mapping, deep_copy_value
from retrieval_core.schemas import RetrievalCandidate


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _rrf_constant(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("rrf_k must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("rrf_k must be a finite non-negative number")
    return result


def _candidate_copy(
    candidate: RetrievalCandidate, **changes: object
) -> RetrievalCandidate:
    values = dict(changes)
    values["metadata"] = deep_copy_mapping(
        values.get("metadata", candidate.metadata)
    )
    values["diagnostics"] = deep_copy_mapping(
        values.get("diagnostics", candidate.diagnostics)
    )
    return replace(candidate, **values)


def _route_candidates(
    candidates: Iterable[RetrievalCandidate], route: str
) -> List[RetrievalCandidate]:
    try:
        rows = list(candidates)
    except TypeError as error:
        raise ValueError(f"{route}_candidates must be iterable") from error

    rank_field = "dense_rank" if route == "dense" else "bm25_rank"
    seen = set()
    for row in rows:
        if not isinstance(row, RetrievalCandidate):
            raise ValueError(f"{route}_candidates must contain RetrievalCandidate rows")
        if row.chunk_id in seen:
            raise ValueError(
                f"duplicate chunk_id {row.chunk_id!r} in {route}_candidates"
            )
        seen.add(row.chunk_id)
        _positive_integer(getattr(row, rank_field), f"{route} rank")
    return rows


def _merged_mapping(
    left: Mapping[str, object], right: Mapping[str, object], name: str, chunk_id: str
) -> dict:
    merged = deep_copy_mapping(left)
    for key, value in right.items():
        if key in merged and not _values_equal(merged[key], value):
            raise ValueError(
                f"conflicting {name} for chunk_id {chunk_id!r}: key {key!r}"
            )
        merged[deep_copy_value(key)] = deep_copy_value(value)
    return merged


def _values_equal(left: object, right: object) -> bool:
    if left is right:
        return True
    if isinstance(left, MappingABC) or isinstance(right, MappingABC):
        if not isinstance(left, MappingABC) or not isinstance(right, MappingABC):
            return False
        if set(left) != set(right):
            return False
        return all(_values_equal(left[key], right[key]) for key in left)

    left_to_list = getattr(left, "tolist", None)
    right_to_list = getattr(right, "tolist", None)
    left_is_array = hasattr(left, "shape") and callable(left_to_list)
    right_is_array = hasattr(right, "shape") and callable(right_to_list)
    if left_is_array or right_is_array:
        if not left_is_array or not right_is_array:
            return False
        try:
            return _values_equal(left.shape, right.shape) and _values_equal(
                left_to_list(), right_to_list()
            )
        except Exception:
            return False

    sequence_types = (str, bytes, bytearray)
    left_is_sequence = isinstance(left, SequenceABC) and not isinstance(
        left, sequence_types
    )
    right_is_sequence = isinstance(right, SequenceABC) and not isinstance(
        right, sequence_types
    )
    if left_is_sequence or right_is_sequence:
        if not left_is_sequence or not right_is_sequence or len(left) != len(right):
            return False
        return all(_values_equal(a, b) for a, b in zip(left, right))

    try:
        return bool(left == right)
    except Exception:
        return False


def _merge_routes(
    dense: RetrievalCandidate, lexical: RetrievalCandidate
) -> RetrievalCandidate:
    if dense.document_id != lexical.document_id or dense.text != lexical.text:
        raise ValueError(f"conflicting identity data for chunk_id {dense.chunk_id!r}")
    metadata = _merged_mapping(
        dense.metadata, lexical.metadata, "metadata", dense.chunk_id
    )
    diagnostics = _merged_mapping(
        dense.diagnostics, lexical.diagnostics, "diagnostics", dense.chunk_id
    )
    return replace(
        dense,
        metadata=metadata,
        diagnostics=diagnostics,
        bm25_rank=lexical.bm25_rank,
        bm25_score=lexical.bm25_score,
    )


def reciprocal_rank_fusion(
    dense_candidates: Sequence[RetrievalCandidate],
    lexical_candidates: Sequence[RetrievalCandidate],
    *,
    rrf_k: float,
    limit: int,
    per_document_limit: int,
) -> List[RetrievalCandidate]:
    """Fuse dense and lexical results by ``chunk_id`` using RRF."""

    constant = _rrf_constant(rrf_k)
    output_limit = _nonnegative_integer(limit, "limit")
    document_limit = _positive_integer(per_document_limit, "per_document_limit")
    dense_rows = _route_candidates(dense_candidates, "dense")
    lexical_rows = _route_candidates(lexical_candidates, "lexical")

    if output_limit == 0 or (not dense_rows and not lexical_rows):
        return []

    by_chunk = {}
    dense_chunk_ids = set()
    lexical_chunk_ids = set()
    for row in dense_rows:
        by_chunk[row.chunk_id] = _candidate_copy(row)
        dense_chunk_ids.add(row.chunk_id)
    for row in lexical_rows:
        existing = by_chunk.get(row.chunk_id)
        by_chunk[row.chunk_id] = (
            _candidate_copy(row) if existing is None else _merge_routes(existing, row)
        )
        lexical_chunk_ids.add(row.chunk_id)

    scored = []
    for row in by_chunk.values():
        score = 0.0
        if row.chunk_id in dense_chunk_ids:
            score += 1.0 / (constant + row.dense_rank)
        if row.chunk_id in lexical_chunk_ids:
            score += 1.0 / (constant + row.bm25_rank)
        scored.append(_candidate_copy(row, rrf_score=score))
    scored.sort(key=lambda row: (-float(row.rrf_score), row.chunk_id))
    ranked = [
        _candidate_copy(row, rrf_rank=rank)
        for rank, row in enumerate(scored, start=1)
    ]

    selected = []
    document_counts = {}
    for row in ranked:
        count = document_counts.get(row.document_id, 0)
        if count >= document_limit:
            continue
        document_counts[row.document_id] = count + 1
        selected.append(row)
        if len(selected) == output_limit:
            break
    return selected
