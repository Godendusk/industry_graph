"""Failure-tolerant orchestration for hybrid report retrieval."""

from collections.abc import Iterable
from dataclasses import replace
from inspect import signature
import math
from time import monotonic
from typing import Any, Callable, Optional, Sequence

from retrieval_core._copying import deep_copy_mapping
from retrieval_core.fusion import reciprocal_rank_fusion
from retrieval_core.schemas import RetrievalCandidate, RetrievalResult


_STAGES = ("embed", "dense", "lexical", "fusion", "rerank", "business", "neighbor")
_COUNT_STAGES = (
    "dense",
    "lexical",
    "fused",
    "reranked",
    "business",
    "expanded",
    "final",
)


def _candidate_copy(
    candidate: RetrievalCandidate, **changes: object
) -> RetrievalCandidate:
    values = dict(changes)
    values["metadata"] = deep_copy_mapping(values.get("metadata", candidate.metadata))
    values["diagnostics"] = deep_copy_mapping(
        values.get("diagnostics", candidate.diagnostics)
    )
    return replace(candidate, **values)


def _candidate_copies(
    candidates: Iterable[RetrievalCandidate],
) -> list[RetrievalCandidate]:
    rows = list(candidates)
    if any(not isinstance(row, RetrievalCandidate) for row in rows):
        raise ValueError("candidates must contain RetrievalCandidate rows")
    return [_candidate_copy(row) for row in rows]


def _noop_rerank(
    query: str, candidates: Sequence[RetrievalCandidate], limit: int
) -> list[RetrievalCandidate]:
    return list(candidates[:limit])


def _noop_hook(candidates: Sequence[RetrievalCandidate]) -> list[RetrievalCandidate]:
    return list(candidates)


class HybridRetrievalPipeline:
    """Run the bounded hybrid retrieval stages with injectable dependencies."""

    def __init__(
        self,
        *,
        embed_query: Callable[[str], Any],
        dense_search: Callable[
            [Any, int, Optional[Sequence[str]]], Iterable[RetrievalCandidate]
        ],
        lexical_search: Callable[
            [str, int, Optional[Sequence[str]]], Iterable[RetrievalCandidate]
        ],
        rerank: Callable[..., Iterable[RetrievalCandidate]] = _noop_rerank,
        business_adjust: Callable[
            [Sequence[RetrievalCandidate]], Iterable[RetrievalCandidate]
        ] = _noop_hook,
        neighbor_expand: Callable[
            [Sequence[RetrievalCandidate]], Iterable[RetrievalCandidate]
        ] = _noop_hook,
        fusion: Callable[..., Iterable[RetrievalCandidate]] = reciprocal_rank_fusion,
        dense_limit: int = 40,
        lexical_limit: int = 40,
        rerank_limit: int = 24,
        rrf_k: float = 60,
        per_document_limit: int = 3,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._require_positive_integer(dense_limit, "dense_limit")
        self._require_positive_integer(lexical_limit, "lexical_limit")
        self._require_positive_integer(rerank_limit, "rerank_limit")
        self._require_positive_integer(per_document_limit, "per_document_limit")
        if (
            isinstance(rrf_k, bool)
            or not isinstance(rrf_k, (int, float))
            or not math.isfinite(rrf_k)
            or rrf_k < 0
        ):
            raise ValueError("rrf_k must be a finite non-negative number")
        for dependency, name in (
            (embed_query, "embed_query"),
            (dense_search, "dense_search"),
            (lexical_search, "lexical_search"),
            (rerank, "rerank"),
            (business_adjust, "business_adjust"),
            (neighbor_expand, "neighbor_expand"),
            (fusion, "fusion"),
            (clock, "clock"),
        ):
            if not callable(dependency):
                raise ValueError(f"{name} must be callable")

        self._embed_query = embed_query
        self._dense_search = dense_search
        self._lexical_search = lexical_search
        self._rerank = rerank
        self._rerank_uses_keyword_limits = self._uses_keyword_rerank_limits(rerank)
        self._business_adjust = business_adjust
        self._neighbor_expand = neighbor_expand
        self._fusion = fusion
        self.dense_limit = dense_limit
        self.lexical_limit = lexical_limit
        self.rerank_limit = rerank_limit
        self.rrf_k = rrf_k
        self.per_document_limit = per_document_limit
        self._clock = clock

    @staticmethod
    def _require_positive_integer(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return value

    @staticmethod
    def _libraries(value: Optional[Iterable[str]]) -> Optional[tuple[str, ...]]:
        if value is None:
            return None
        if isinstance(value, (str, bytes)):
            raise ValueError("libraries must be an iterable of non-empty strings or None")
        try:
            libraries = tuple(value)
        except TypeError as error:
            raise ValueError(
                "libraries must be an iterable of non-empty strings or None"
            ) from error
        if any(not isinstance(item, str) or not item.strip() for item in libraries):
            raise ValueError("libraries must contain only non-empty strings")
        return libraries

    @staticmethod
    def _warning(stage: str, error: Exception) -> dict[str, str]:
        return {
            "stage": stage,
            "error_type": type(error).__name__,
            "message": f"{stage} stage failed",
        }

    @staticmethod
    def _uses_keyword_rerank_limits(rerank: Callable[..., object]) -> bool:
        try:
            parameters = signature(rerank).parameters
        except (TypeError, ValueError):
            return False
        return "final_limit" in parameters and "rerank_limit" in parameters

    def _call_reranker(
        self, query: str, candidates: Sequence[RetrievalCandidate]
    ) -> Iterable[RetrievalCandidate]:
        if self._rerank_uses_keyword_limits:
            return self._rerank(
                query,
                candidates,
                final_limit=self.rerank_limit,
                rerank_limit=self.rerank_limit,
            )
        return self._rerank(query, candidates, self.rerank_limit)

    def _elapsed(self, started: float) -> float:
        return max(0.0, float(self._clock() - started))

    def retrieve(
        self, query: str, libraries: Optional[Iterable[str]], top_k: int
    ) -> RetrievalResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-blank string")
        self._require_positive_integer(top_k, "top_k")
        selected_libraries = self._libraries(libraries)

        timings = {stage: 0.0 for stage in _STAGES}
        counts = {stage: 0 for stage in _COUNT_STAGES}
        warnings = []
        dense_rows = []
        lexical_rows = []
        dense_failed = False
        lexical_failed = False

        started = self._clock()
        try:
            vector = self._embed_query(query)
        except Exception as error:
            dense_failed = True
            warnings.append(self._warning("embed", error))
        finally:
            timings["embed"] = self._elapsed(started)

        if not dense_failed:
            started = self._clock()
            try:
                dense_rows = _candidate_copies(
                    self._dense_search(vector, self.dense_limit, selected_libraries)
                )
            except Exception as error:
                dense_failed = True
                warnings.append(self._warning("dense", error))
            finally:
                timings["dense"] = self._elapsed(started)

        counts["dense"] = len(dense_rows)
        started = self._clock()
        try:
            lexical_rows = _candidate_copies(
                self._lexical_search(query, self.lexical_limit, selected_libraries)
            )
        except Exception as error:
            lexical_failed = True
            warnings.append(self._warning("lexical", error))
        finally:
            timings["lexical"] = self._elapsed(started)
        counts["lexical"] = len(lexical_rows)

        if dense_failed and lexical_failed:
            return RetrievalResult(
                status="error",
                query=query,
                warnings=warnings,
                timings=timings,
                candidate_counts=counts,
                message="Both dense and lexical recall routes failed.",
            )

        started = self._clock()
        try:
            fused_rows = _candidate_copies(
                self._fusion(
                    dense_rows,
                    lexical_rows,
                    rrf_k=self.rrf_k,
                    limit=self.rerank_limit,
                    per_document_limit=self.per_document_limit,
                )
            )
        except Exception as error:
            timings["fusion"] = self._elapsed(started)
            warnings.append(self._warning("fusion", error))
            return RetrievalResult(
                status="error",
                query=query,
                warnings=warnings,
                timings=timings,
                candidate_counts=counts,
                message="Candidate fusion failed.",
            )
        timings["fusion"] = self._elapsed(started)
        counts["fused"] = len(fused_rows)

        started = self._clock()
        try:
            reranked_rows = _candidate_copies(
                self._call_reranker(query, _candidate_copies(fused_rows))
            )[: self.rerank_limit]
            if any(
                row.diagnostics.get("reranker_fallback") is True
                for row in reranked_rows
            ):
                warnings.append(
                    {
                        "stage": "rerank",
                        "error_type": "RerankerFallback",
                        "message": "rerank stage used fallback",
                    }
                )
        except Exception as error:
            warnings.append(self._warning("rerank", error))
            reranked_rows = _candidate_copies(fused_rows)
        finally:
            timings["rerank"] = self._elapsed(started)
        counts["reranked"] = len(reranked_rows)

        business_rows = self._run_hook(
            "business", self._business_adjust, reranked_rows, timings, warnings
        )
        counts["business"] = len(business_rows)
        expanded_rows = self._run_hook(
            "neighbor", self._neighbor_expand, business_rows, timings, warnings
        )
        counts["expanded"] = len(expanded_rows)

        final_rows = [
            _candidate_copy(row, final_rank=rank)
            for rank, row in enumerate(expanded_rows[:top_k], start=1)
        ]
        counts["final"] = len(final_rows)
        return RetrievalResult(
            status="success",
            query=query,
            candidates=final_rows,
            warnings=warnings,
            timings=timings,
            candidate_counts=counts,
        )

    def _run_hook(
        self,
        stage: str,
        hook: Callable[[Sequence[RetrievalCandidate]], Iterable[RetrievalCandidate]],
        previous: Sequence[RetrievalCandidate],
        timings: dict[str, float],
        warnings: list[dict[str, str]],
    ) -> list[RetrievalCandidate]:
        fallback = _candidate_copies(previous)
        started = self._clock()
        try:
            result = _candidate_copies(hook(_candidate_copies(previous)))
        except Exception as error:
            warnings.append(self._warning(stage, error))
            result = fallback
        finally:
            timings[stage] = self._elapsed(started)
        return result
