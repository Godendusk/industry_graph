"""Bounded, failure-safe reranking for retrieval candidates."""

from dataclasses import replace
import math
from typing import Callable, Iterable, List, Optional, Sequence

from retrieval_core.schemas import RetrievalCandidate


def _candidate_copy(
    candidate: RetrievalCandidate, **changes: object
) -> RetrievalCandidate:
    values = {
        "metadata": dict(candidate.metadata),
        "diagnostics": dict(candidate.diagnostics),
    }
    values.update(changes)
    return replace(candidate, **values)


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _fallback(
    candidates: Sequence[RetrievalCandidate], final_limit: int
) -> List[RetrievalCandidate]:
    result = []
    for candidate in candidates[:final_limit]:
        diagnostics = dict(candidate.diagnostics)
        diagnostics["reranker_fallback"] = True
        result.append(_candidate_copy(candidate, diagnostics=diagnostics))
    return result


def _validated_scores(values: Iterable[object], expected: int) -> List[float]:
    try:
        raw_scores = list(values)
    except (TypeError, ValueError) as error:
        raise ValueError("reranker scores must be iterable") from error
    if len(raw_scores) != expected:
        raise ValueError(
            f"reranker returned {len(raw_scores)} scores for {expected} candidates"
        )

    scores = []
    for value in raw_scores:
        if isinstance(value, bool):
            raise ValueError("reranker scores must be finite numbers")
        try:
            score = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("reranker scores must be finite numbers") from error
        if not math.isfinite(score):
            raise ValueError("reranker scores must be finite numbers")
        scores.append(score)
    return scores


def rerank_candidates(
    query: str,
    candidates: Sequence[RetrievalCandidate],
    *,
    scorer: Callable[[Sequence[tuple[str, str]]], Iterable[object]],
    final_limit: int,
    rerank_limit: Optional[int] = None,
) -> List[RetrievalCandidate]:
    """Rerank a bounded prefix, falling back to input order on any scorer failure."""

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-blank string")
    output_limit = _nonnegative_integer(final_limit, "final_limit")
    if rerank_limit is not None:
        score_limit = _positive_integer(rerank_limit, "rerank_limit")

    try:
        rows = list(candidates)
    except TypeError as error:
        raise ValueError("candidates must be iterable") from error
    if any(not isinstance(row, RetrievalCandidate) for row in rows):
        raise ValueError("candidates must contain RetrievalCandidate rows")
    if output_limit == 0 or not rows:
        return []
    if rerank_limit is None:
        score_limit = len(rows)

    scored_count = min(score_limit, len(rows))
    pairs = [(query, row.text) for row in rows[:scored_count]]
    try:
        scores = _validated_scores(scorer(pairs), scored_count)
    except Exception:
        return _fallback(rows, output_limit)

    scored_rows = [
        (index, _candidate_copy(row, rerank_score=scores[index]))
        for index, row in enumerate(rows[:scored_count])
    ]
    scored_rows.sort(key=lambda item: (-float(item[1].rerank_score), item[0]))
    ordered = [
        _candidate_copy(row, rerank_rank=rank)
        for rank, (_index, row) in enumerate(scored_rows, start=1)
    ]
    ordered.extend(_candidate_copy(row) for row in rows[scored_count:])
    return ordered[:output_limit]
