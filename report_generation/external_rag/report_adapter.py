"""Report-facing adapters for the hybrid external-material retriever.

This module is deliberately dependency-light: callers inject retrieval and tokenization
services, while local deterministic fallbacks keep report query preparation offline.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from itertools import islice
import math
from pathlib import PurePath
import re
from types import MappingProxyType
from typing import Any, Optional, Tuple
import unicodedata

from retrieval_core import RetrievalCandidate, RetrievalResult


RETRIEVAL_VERSION = "hybrid_v2"
INDUSTRY_DICTIONARY_VERSION = "report_industry_terms_v1"
ALL_LIBRARIES = (
    "policy",
    "speech",
    "expert_view",
    "company_case",
    "research_report",
)
MAX_BM25_TERMS = 512
_ROUTING_CANDIDATE_SCAN_ALLOWANCE = 32
_ROUTING_WARNING_LIMIT = 128

_CUSTOM_WORDS = (
    "央企智算中心",
    "国资央企",
    "智算中心",
    "人工智能",
    "数字化转型",
    "产业链",
    "政策法规",
    "企业案例",
    "专家观点",
    "研究报告",
)
_STOPWORDS = frozenset(
    {
        "的", "了", "和", "与", "及", "或", "在", "对", "中", "为", "是",
        "检索", "目标", "依据", "相关", "资料", "内容", "当前", "报告",
    }
)
_LABELS = {
    "用户需求": "user_requirement",
    "报告标题": "report_title",
    "当前一级标题": "current_section",
    "当前二级标题": "current_subsection",
    "检索目标": "retrieval_goal",
}
_LABELED_LINE = re.compile(
    r"^\s*(用户需求|报告标题|当前一级标题|当前二级标题|检索目标)\s*[:：]\s*(.*?)\s*$"
)
_FALLBACK_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[._+-][A-Za-z0-9]+)*|[\u4e00-\u9fff]")
_TERM_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[._+-][A-Za-z0-9]+)*|[\u4e00-\u9fff]+")
_NOISE_PHRASES = (
    "检索产业链结构、竞争格局、问题、政策、案例和建议依据",
    "产业链结构、竞争格局、问题、政策、案例和建议依据",
    "问题、政策、案例和建议",
)


@dataclass(frozen=True)
class ReportQuery:
    semantic_query: str
    bm25_terms: Tuple[str, ...]
    dictionary_version: str
    user_requirement: str = ""
    report_title: str = ""
    current_section: str = ""
    current_subsection: str = ""
    retrieval_goal: str = ""
    unlabeled_text: str = ""


@dataclass(frozen=True)
class LibraryRoute:
    preferred: frozenset[str]
    all_libraries: Tuple[str, ...] = ALL_LIBRARIES
    search_all_immediately: bool = False
    fallback_to_all: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.preferred, (str, bytes)) or not isinstance(
            self.preferred, Collection
        ):
            raise TypeError("preferred must be a collection of library names")
        if isinstance(self.all_libraries, (str, bytes)) or not isinstance(
            self.all_libraries, Collection
        ):
            raise TypeError("all_libraries must be a bounded collection")
        preferred = frozenset(self.preferred)
        supplied_all_libraries = tuple(self.all_libraries)
        if (
            len(supplied_all_libraries) != len(ALL_LIBRARIES)
            or set(supplied_all_libraries) != set(ALL_LIBRARIES)
        ):
            raise ValueError("all_libraries must contain exactly the five supported libraries")
        if not preferred or not preferred.issubset(ALL_LIBRARIES):
            raise ValueError("preferred must contain supported library names")
        if type(self.search_all_immediately) is not bool or type(self.fallback_to_all) is not bool:
            raise TypeError("route semantics must be boolean")
        object.__setattr__(self, "preferred", preferred)
        object.__setattr__(self, "all_libraries", ALL_LIBRARIES)


@dataclass(frozen=True)
class RoutingAttempt:
    libraries: Tuple[str, ...]
    status: str
    candidates: Tuple[RetrievalCandidate, ...] = field(default_factory=tuple)
    warnings: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    error_type: str = ""
    result: Optional[RetrievalResult] = None


@dataclass(frozen=True)
class SoftRoutingResult:
    query: str
    route: LibraryRoute
    top_k: int
    candidates: Tuple[RetrievalCandidate, ...]
    attempts: Tuple[RoutingAttempt, ...]
    warnings: Tuple[Mapping[str, Any], ...]
    retrieval_version: str = RETRIEVAL_VERSION


def build_report_query(
    raw_query: str,
    *,
    max_tokens: int = 100,
    token_counter: Optional[Callable[[str], int]] = None,
    tokenizer: Any = None,
    bm25_tokenizer: Optional[Callable[[str], Iterable[Any]]] = None,
) -> ReportQuery:
    """Parse and focus a report prompt for semantic and BM25 retrieval."""
    if not isinstance(raw_query, str):
        raise TypeError("raw_query must be a non-blank string")
    if not raw_query.strip():
        raise ValueError("raw_query must be a non-blank string")
    if type(max_tokens) is not int:
        raise TypeError("max_tokens must be a positive integer")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")
    if token_counter is not None and not callable(token_counter):
        raise TypeError("token_counter must be callable")
    if bm25_tokenizer is not None and not callable(bm25_tokenizer):
        raise TypeError("bm25_tokenizer must be callable")

    parsed = {field_name: "" for field_name in _LABELS.values()}
    unlabeled = []
    found_label = False
    seen_fields = set()
    active_field = None
    accept_continuations = False
    for line in raw_query.splitlines():
        match = _LABELED_LINE.match(line)
        if match:
            found_label = True
            field_name = _LABELS[match.group(1)]
            value = _clean_space(match.group(2))
            active_field = field_name
            accept_continuations = field_name not in seen_fields
            if accept_continuations:
                seen_fields.add(field_name)
                parsed[field_name] = value
        elif line.strip():
            value = _clean_space(line)
            if active_field is not None and accept_continuations:
                parsed[active_field] = _clean_space(
                    f"{parsed[active_field]} {value}"
                )
            else:
                unlabeled.append(value)
        else:
            active_field = None
            accept_continuations = False

    unlabeled_text = _clean_space(" ".join(unlabeled))
    if found_label:
        priority_values = (
            parsed["current_subsection"],
            parsed["current_section"],
            parsed["report_title"],
            parsed["user_requirement"],
        )
    else:
        priority_values = (unlabeled_text or _clean_space(raw_query),)
    priority_values = tuple(_strip_template_noise(value) for value in priority_values)
    counter = _make_token_counter(token_counter, tokenizer, max_tokens)
    semantic_query = _fit_priority_values(priority_values, max_tokens, counter)
    if not semantic_query:
        raise ValueError("raw_query contains no usable retrieval intent")

    terms = _bm25_terms(semantic_query, bm25_tokenizer)
    return ReportQuery(
        semantic_query=semantic_query,
        bm25_terms=terms,
        dictionary_version=INDUSTRY_DICTIONARY_VERSION,
        unlabeled_text=unlabeled_text if not found_label else "",
        **parsed,
    )


def route_libraries(section_or_query: Any) -> LibraryRoute:
    """Return deterministic soft library preferences for a report section."""
    if isinstance(section_or_query, ReportQuery):
        preferred = None
        for text in (
            section_or_query.current_subsection,
            section_or_query.current_section,
            section_or_query.report_title,
            section_or_query.user_requirement,
        ):
            preferred = _preferred_libraries_for_text(text)
            if preferred is not None:
                break
        if preferred is None:
            preferred = _preferred_libraries_for_text(
                section_or_query.semantic_query
            )
    elif isinstance(section_or_query, str):
        text = section_or_query.strip()
        if not text:
            raise ValueError("section_or_query must not be blank")
        preferred = _preferred_libraries_for_text(text)
    else:
        raise TypeError("section_or_query must be a non-blank string or ReportQuery")
    if preferred is None:
        preferred = frozenset(ALL_LIBRARIES)
    search_all = preferred == frozenset(ALL_LIBRARIES)
    return LibraryRoute(
        preferred=preferred,
        search_all_immediately=search_all,
        fallback_to_all=not search_all,
    )


def retrieve_with_soft_routing(
    retrieve: Callable[[str, Collection[str], int], RetrievalResult],
    focused_query: str,
    route: LibraryRoute,
    top_k: int,
) -> SoftRoutingResult:
    """Retrieve preferred libraries first, expanding to all libraries only if needed."""
    if not callable(retrieve):
        raise TypeError("retrieve must be callable")
    if not isinstance(focused_query, str):
        raise TypeError("focused_query must be a non-blank string")
    query = focused_query.strip()
    if not query:
        raise ValueError("focused_query must be a non-blank string")
    if not isinstance(route, LibraryRoute):
        raise TypeError("route must be a LibraryRoute")
    if type(top_k) is not int:
        raise TypeError("top_k must be a positive integer")
    if top_k <= 0:
        raise ValueError("top_k must be a positive integer")

    preferred_order = tuple(
        library for library in route.all_libraries if library in route.preferred
    )
    scopes = [route.all_libraries if route.search_all_immediately else preferred_order]
    attempts = []
    merged = []
    seen = set()

    first = _run_attempt(retrieve, query, scopes[0], top_k)
    attempts.append(first)
    _merge_viable(merged, seen, first.candidates, top_k)

    if (
        not route.search_all_immediately
        and route.fallback_to_all
        and (len(merged) < top_k or first.status not in {"success", "ok"})
    ):
        fallback = _run_attempt(retrieve, query, route.all_libraries, top_k)
        attempts.append(fallback)
        _merge_viable(merged, seen, fallback.candidates, top_k)

    warnings = tuple(warning for attempt in attempts for warning in attempt.warnings)
    return SoftRoutingResult(
        query=query,
        route=route,
        top_k=top_k,
        candidates=tuple(merged),
        attempts=tuple(attempts),
        warnings=warnings,
    )


def to_evidence_blocks(
    candidates: Collection[RetrievalCandidate], *, include_diagnostics: bool = True
) -> list[dict]:
    """Copy retrieval candidates into legacy-compatible, JSON-safe evidence blocks."""
    if isinstance(candidates, (str, bytes, bytearray)) or not isinstance(
        candidates, Collection
    ):
        raise TypeError("candidates must be a bounded collection")
    if type(include_diagnostics) is not bool:
        raise TypeError("include_diagnostics must be a boolean")

    blocks = []
    for rank, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, RetrievalCandidate):
            raise TypeError("every candidate must be a RetrievalCandidate")
        if not candidate.chunk_id.strip():
            raise ValueError("candidate chunk_id must not be blank")
        if not candidate.text.strip():
            raise ValueError("candidate text must not be blank")
        metadata = candidate.metadata
        paragraph_index = _coerce_int(metadata.get("paragraph_index"))
        if paragraph_index is None:
            paragraph_index = _coerce_int(metadata.get("chunk_index"))
        block = {
            "citation_id": f"外部资料{rank}",
            "rank": rank,
            "library": _safe_text(metadata.get("library")),
            "classification_type": _safe_text(metadata.get("classification_type")),
            "classification_name": _safe_text(metadata.get("classification_name")),
            "material_id": _safe_text(metadata.get("material_id")),
            "title": _safe_text(metadata.get("title")),
            "publish_date": _safe_text(metadata.get("publish_date")),
            "source_address": _safe_text(metadata.get("source_address")),
            "paragraph_index": paragraph_index,
            "vector_id": _safe_text(metadata.get("vector_id")) or candidate.chunk_id,
            "distance": _finite_float(candidate.dense_distance),
            "text": candidate.text,
            "retrieval_version": RETRIEVAL_VERSION,
        }
        if include_diagnostics:
            for field_name in (
                "dense_rank", "dense_score", "bm25_rank", "bm25_score", "rrf_rank",
                "rrf_score", "rerank_rank", "rerank_score", "business_score", "final_rank",
            ):
                value = getattr(candidate, field_name)
                if value is not None:
                    block[field_name] = _json_safe(value)
            block["diagnostics"] = _json_safe(candidate.diagnostics)
        blocks.append(block)
    return blocks


def build_rag_context_text(evidence_blocks: Collection[Mapping[str, Any]]) -> str:
    """Format evidence with the exact headings and labels used by legacy reports."""
    if isinstance(evidence_blocks, (str, bytes, bytearray)) or not isinstance(
        evidence_blocks, Collection
    ):
        raise TypeError("evidence_blocks must be a bounded collection")
    lines = ["【外部资料库检索结果】"]
    if not evidence_blocks:
        lines.extend(["", "未检索到匹配内容。"])
        return "\n".join(lines)
    for index, block in enumerate(evidence_blocks, 1):
        if not isinstance(block, Mapping):
            raise TypeError("every evidence block must be a mapping")
        paragraph_index = block.get("paragraph_index")
        citation_id = _safe_text(block.get("citation_id")) or f"外部资料{index}"
        lines.extend(
            [
                "",
                f"[{citation_id}]",
                f"资料类型：{_display_value(block.get('classification_name'))}",
                f"标题：{_display_value(block.get('title'))}",
                f"发布日期：{_display_value(block.get('publish_date'))}",
                f"来源：{_display_value(block.get('source_address'))}",
                f"段落序号：{paragraph_index if paragraph_index is not None else '未提供'}",
                f"内容：{_display_value(block.get('text'))}",
            ]
        )
    return "\n".join(lines)


format_rag_context_text = build_rag_context_text


def _preferred_libraries_for_text(text: Any) -> Optional[frozenset[str]]:
    if not isinstance(text, str) or not text.strip():
        return None
    if _contains_any(text, ("政策", "法规", "监管", "治理", "规制", "合规")):
        return frozenset(("policy", "speech"))
    if _contains_any(text, ("企业", "央企", "实践", "案例", "应用", "落地")):
        return frozenset(("company_case",))
    if _contains_any(text, ("专家", "观点", "研判", "研究", "趋势", "展望")):
        return frozenset(("expert_view", "research_report"))
    return None


def _make_token_counter(
    token_counter: Any, tokenizer: Any, max_tokens: int
) -> Callable[[str], int]:
    if token_counter is not None:
        supplied = token_counter
    elif tokenizer is not None:
        encode = getattr(tokenizer, "encode", None)
        if callable(encode):
            supplied = lambda text: _bounded_encoded_length(
                encode(text), max_tokens + 1
            )
        elif callable(tokenizer):
            supplied = lambda text: len(tokenizer(text))
        else:
            raise TypeError("tokenizer must be callable or provide encode()")
    else:
        supplied = lambda text: len(_FALLBACK_TOKEN.findall(text))

    def count(text: str) -> int:
        value = supplied(text)
        if type(value) is not int or value < 0:
            raise ValueError("token counter must return a non-negative integer")
        return value

    return count


def _bounded_encoded_length(encoded: Any, limit: int) -> int:
    if isinstance(encoded, (str, bytes, bytearray, Mapping)):
        raise TypeError("tokenizer.encode() must return a token sequence or iterable")
    try:
        iterator = iter(encoded)
    except TypeError as error:
        raise TypeError(
            "tokenizer.encode() must return a token sequence or iterable"
        ) from error
    count = 0
    for _ in islice(iterator, limit):
        count += 1
    return count


def _fit_priority_values(
    values: Iterable[str], max_tokens: int, count: Callable[[str], int]
) -> str:
    focused = ""
    for value in values:
        if not value:
            continue
        proposed = f"{focused} {value}".strip()
        if count(proposed) <= max_tokens:
            focused = proposed
            continue
        prefix = _longest_fitting_prefix(focused, value, max_tokens, count)
        if prefix:
            focused = f"{focused} {prefix}".strip()
        break
    return focused


def _longest_fitting_prefix(
    current: str, value: str, budget: int, count: Callable[[str], int]
) -> str:
    # Evaluate every finite character prefix: this does not assume token counts are monotonic.
    best = ""
    for end in range(1, len(value) + 1):
        prefix = value[:end].rstrip()
        prefix_end = len(prefix)
        if (
            prefix
            and _is_safe_unicode_boundary(value, prefix_end)
            and count(f"{current} {prefix}".strip()) <= budget
        ):
            if len(prefix) > len(best):
                best = prefix
    return best


def _is_safe_unicode_boundary(value: str, end: int) -> bool:
    if end <= 0 or end >= len(value):
        return True
    previous = value[end - 1]
    following = value[end]
    if previous == "\u200d" or following == "\u200d":
        return False
    if (
        unicodedata.combining(following)
        or unicodedata.category(following) in {"Mn", "Mc", "Me"}
        or _is_variation_selector(following)
        or _is_emoji_modifier(following)
    ):
        return False
    if _is_regional_indicator(previous) and _is_regional_indicator(following):
        preceding_indicators = 0
        index = end - 1
        while index >= 0 and _is_regional_indicator(value[index]):
            preceding_indicators += 1
            index -= 1
        if preceding_indicators % 2 == 1:
            return False
    return True


def _is_variation_selector(character: str) -> bool:
    codepoint = ord(character)
    return 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF


def _is_emoji_modifier(character: str) -> bool:
    return 0x1F3FB <= ord(character) <= 0x1F3FF


def _is_regional_indicator(character: str) -> bool:
    return 0x1F1E6 <= ord(character) <= 0x1F1FF


def _bm25_terms(text: str, injected: Any) -> Tuple[str, ...]:
    if injected is not None:
        raw_terms = injected(text)
    else:
        raw_terms = _local_jieba_tokens(text)
        if raw_terms is None:
            raw_terms = _regex_industry_tokens(text)
    if isinstance(raw_terms, (str, bytes)):
        raise TypeError("bm25 tokenizer must return an iterable of terms")
    try:
        iterator = iter(raw_terms)
    except TypeError as error:
        raise TypeError("bm25 tokenizer must return an iterable of terms") from error
    terms = []
    seen = set()
    for raw_term in islice(iterator, MAX_BM25_TERMS):
        term = _clean_space(str(raw_term)).lower()
        if (
            not term
            or term in _STOPWORDS
            or not any(character.isalnum() for character in term)
            or term in seen
        ):
            continue
        seen.add(term)
        terms.append(term)
    return tuple(terms)


def _local_jieba_tokens(text: str) -> Optional[Iterable[str]]:
    try:
        import jieba
    except ImportError:
        return None
    tokenizer = jieba.Tokenizer()
    for word in _CUSTOM_WORDS:
        tokenizer.add_word(word)
    return tokenizer.cut(text, HMM=False)


def _regex_industry_tokens(text: str) -> list[str]:
    terms = []
    custom_words = sorted(_CUSTOM_WORDS, key=len, reverse=True)
    index = 0
    while index < len(text):
        custom = next(
            (word for word in custom_words if text.startswith(word, index)), None
        )
        if custom is not None:
            terms.append(custom)
            index += len(custom)
            continue
        ascii_match = re.match(
            r"[A-Za-z0-9]+(?:[._+-][A-Za-z0-9]+)*", text[index:]
        )
        if ascii_match:
            terms.append(ascii_match.group(0))
            index += len(ascii_match.group(0))
            continue
        if "\u4e00" <= text[index] <= "\u9fff":
            terms.append(text[index])
        index += 1
    return terms


def _run_attempt(retrieve, query, libraries, top_k) -> RoutingAttempt:
    scope = tuple(libraries)
    preserved_warnings = ()
    try:
        result = retrieve(query, scope, top_k)
        if not isinstance(result, RetrievalResult):
            raise TypeError("retrieve must return a RetrievalResult")
        status = _snapshot_result_string(result.status, "status", allow_blank=False)
        result_query = _snapshot_result_string(
            result.query, "query", allow_blank=False
        )
        message = _snapshot_result_string(result.message, "message", allow_blank=True)
        retrieval_version = _snapshot_result_string(
            result.retrieval_version, "retrieval_version", allow_blank=False
        )
        preserved_warnings, warning_error_type = _snapshot_attempt_warnings(
            result.warnings, query
        )
        if warning_error_type:
            return _failed_attempt(scope, warning_error_type, preserved_warnings)
        candidates = _consume_viable_candidates(result.candidates, top_k)
        sanitized_result = RetrievalResult(
            status=status,
            query=result_query,
            candidates=candidates,
            warnings=preserved_warnings,
            timings=result.timings,
            candidate_counts=result.candidate_counts,
            retrieval_version=retrieval_version,
            message=message,
        )
    except Exception as error:
        return _failed_attempt(
            scope, type(error).__name__, preserved_warnings
        )
    return RoutingAttempt(
        libraries=scope,
        status=sanitized_result.status,
        candidates=sanitized_result.candidates,
        warnings=sanitized_result.warnings,
        result=sanitized_result,
    )


def _snapshot_result_string(value: Any, field_name: str, *, allow_blank: bool) -> str:
    if not isinstance(value, str):
        raise TypeError(f"RetrievalResult {field_name} must be a string")
    normalized = str(value)
    if not allow_blank and not normalized.strip():
        raise ValueError(f"RetrievalResult {field_name} must not be blank")
    return normalized


def _snapshot_attempt_warnings(
    warnings: Any, query: str
) -> Tuple[Tuple[Mapping[str, Any], ...], str]:
    if isinstance(warnings, (str, bytes, bytearray)):
        return (), "TypeError"
    try:
        iterator = iter(warnings)
    except Exception as error:
        return (), type(error).__name__

    preserved = []
    for index in range(_ROUTING_WARNING_LIMIT + 1):
        try:
            warning = next(iterator)
        except StopIteration:
            return tuple(preserved), ""
        except Exception as error:
            return tuple(preserved), type(error).__name__
        if index >= _ROUTING_WARNING_LIMIT:
            return tuple(preserved), "ValueError"
        try:
            frozen = RetrievalResult(
                status="error", query=query, warnings=(warning,)
            ).warnings[0]
        except Exception as error:
            return tuple(preserved), type(error).__name__
        preserved.append(frozen)
    return tuple(preserved), "ValueError"


def _failed_attempt(
    scope: Tuple[str, ...],
    error_type: str,
    preserved_warnings: Tuple[Mapping[str, Any], ...] = (),
) -> RoutingAttempt:
    warning = MappingProxyType(
        {"stage": "soft_routing", "error_type": error_type}
    )
    return RoutingAttempt(
        libraries=scope,
        status="error",
        warnings=preserved_warnings + (warning,),
        error_type=error_type,
    )


def _consume_viable_candidates(candidates: Any, top_k: int) -> Tuple[RetrievalCandidate, ...]:
    if isinstance(candidates, (str, bytes, bytearray)):
        raise TypeError("RetrievalResult candidates must be an iterable of candidates")
    try:
        iterator = iter(candidates)
    except TypeError as error:
        raise TypeError(
            "RetrievalResult candidates must be an iterable of candidates"
        ) from error

    viable = []
    seen = set()
    scan_limit = top_k + _ROUTING_CANDIDATE_SCAN_ALLOWANCE
    for _ in range(scan_limit):
        try:
            candidate = next(iterator)
        except StopIteration:
            break
        if not isinstance(candidate, RetrievalCandidate):
            raise TypeError("retrieval results must contain RetrievalCandidate values")
        if not isinstance(candidate.chunk_id, str) or not isinstance(candidate.text, str):
            continue
        chunk_id = candidate.chunk_id.strip()
        if not chunk_id or not candidate.text.strip() or chunk_id in seen:
            continue
        seen.add(chunk_id)
        viable.append(candidate)
        if len(viable) >= top_k:
            break
    return tuple(viable)


def _merge_viable(merged, seen, candidates, top_k):
    for candidate in candidates:
        if len(merged) >= top_k:
            return
        if not isinstance(candidate, RetrievalCandidate):
            raise TypeError("retrieval results must contain RetrievalCandidate values")
        if not isinstance(candidate.chunk_id, str) or not isinstance(candidate.text, str):
            continue
        chunk_id = candidate.chunk_id.strip()
        if not chunk_id or not candidate.text.strip() or chunk_id in seen:
            continue
        seen.add(chunk_id)
        merged.append(candidate)


def _json_safe(value: Any) -> Any:
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_safe(item) for item in value), key=repr)
    if isinstance(value, PurePath):
        return str(value)
    return str(value)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _display_value(value: Any) -> str:
    return _safe_text(value) or "未提供"


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or type(value) is bool:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _finite_float(value: Any) -> Optional[float]:
    if value is None or type(value) is bool:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _clean_space(value: str) -> str:
    return " ".join(value.strip().split())


def _strip_template_noise(value: str) -> str:
    cleaned = value
    for phrase in _NOISE_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    return _clean_space(cleaned).strip("，,。；;：: ")


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


__all__ = [
    "ALL_LIBRARIES",
    "INDUSTRY_DICTIONARY_VERSION",
    "MAX_BM25_TERMS",
    "LibraryRoute",
    "ReportQuery",
    "RoutingAttempt",
    "SoftRoutingResult",
    "build_rag_context_text",
    "build_report_query",
    "format_rag_context_text",
    "retrieve_with_soft_routing",
    "route_libraries",
    "to_evidence_blocks",
]
