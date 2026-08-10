"""Structure-aware chunk construction for report retrieval."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from report_generation.external_rag.text_utils import normalize_text
from retrieval_core.schemas import ChunkRecord


@dataclass(frozen=True)
class ChunkingConfig:
    min_chars: int = 80
    target_chars: int = 320
    soft_max_chars: int = 400
    hard_max_chars: int = 450
    overlap_chars: int = 60
    max_tokens: int = 480

    def __post_init__(self) -> None:
        positive_values = (
            self.min_chars,
            self.target_chars,
            self.soft_max_chars,
            self.hard_max_chars,
            self.max_tokens,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in positive_values
        ):
            raise ValueError("ChunkingConfig limits must be positive integers")
        if (
            isinstance(self.overlap_chars, bool)
            or not isinstance(self.overlap_chars, int)
            or self.overlap_chars < 0
        ):
            raise ValueError("ChunkingConfig overlap_chars must be a nonnegative integer")
        if not self.min_chars <= self.target_chars <= self.soft_max_chars <= self.hard_max_chars:
            raise ValueError(
                "ChunkingConfig requires min_chars <= target_chars <= "
                "soft_max_chars <= hard_max_chars"
            )
        if self.overlap_chars > self.hard_max_chars:
            raise ValueError("ChunkingConfig overlap_chars must not exceed hard_max_chars")


@dataclass(frozen=True)
class _SourceBlock:
    text: str
    section_path: Tuple[str, ...]
    content_type: str


@dataclass(frozen=True)
class _ChunkText:
    text: str
    section_path: Tuple[str, ...]
    content_type: str


def _token_count(tokenizer: object, text: str) -> int:
    encode = getattr(tokenizer, "encode", None)
    if not callable(encode):
        raise ValueError("tokenizer must provide encode(text, add_special_tokens=True)")
    try:
        return len(encode(text, add_special_tokens=True))
    except TypeError as exc:
        raise ValueError(
            "tokenizer must support encode(text, add_special_tokens=True)"
        ) from exc


def _fit_embedding_prefix(
    classification: str,
    title: str,
    section_path: Tuple[str, ...],
    sample_character: str,
    tokenizer: object,
    max_tokens: int,
) -> str:
    components = [classification, title]
    if section_path:
        components.append(" / ".join(section_path))
    components = [normalize_text(component) for component in components]
    if any(not component for component in components):
        raise ValueError("embedding prefix components must not be empty")

    prefix = "\n".join(components) + "\n"
    if _token_count(tokenizer, prefix + sample_character) > max_tokens:
        raise ValueError(
            "embedding prefix exceeds the token budget for required "
            "classification, title, section, and nonempty text"
        )
    return prefix


def _fits(
    text: str,
    prefix: str,
    tokenizer: object,
    config: ChunkingConfig,
    char_limit: Optional[int] = None,
) -> bool:
    limit = config.hard_max_chars if char_limit is None else char_limit
    return len(text) <= limit and _token_count(tokenizer, prefix + text) <= config.max_tokens


def _slice_at_matches(text: str, pattern: re.Pattern[str]) -> List[str]:
    pieces: List[str] = []
    start = 0
    for match in pattern.finditer(text):
        end = match.end()
        if end > start:
            pieces.append(text[start:end])
            start = end
    if start < len(text):
        pieces.append(text[start:])
    return [piece for piece in pieces if piece]


_SENTENCE_END = re.compile(
    r"(?:[。！？!?]+[”’\"']?\s*|(?<!\d)\.[”’\"']?(?:\s+|$))"
)
_SEMICOLON_END = re.compile(r"[；;]+\s*")
_ENUMERATION_START = re.compile(
    r"(?=(?:[（(]?[一二三四五六七八九十百]+[、）)]|[（(]?\d+[、.)）]))"
)
_COMPLETE_SENTENCE = re.compile(r"(?:[。！？!?]|(?<!\d)\.)[”’\"']?$")


def _split_at_enumerations(text: str) -> List[str]:
    starts = [match.start() for match in _ENUMERATION_START.finditer(text)]
    starts = sorted(set([0] + [start for start in starts if start > 0] + [len(text)]))
    return [text[starts[index] : starts[index + 1]] for index in range(len(starts) - 1)]


def _hard_split(
    text: str,
    prefix: str,
    tokenizer: object,
    config: ChunkingConfig,
) -> List[str]:
    pieces: List[str] = []
    remaining = text
    while remaining:
        upper_bound = min(len(remaining), config.target_chars, config.hard_max_chars)
        length = upper_bound
        while length > 0 and not _fits(
            remaining[:length], prefix, tokenizer, config
        ):
            length -= 1
        if length == 0:
            raise ValueError(
                "max_tokens creates an impossible token budget for nonempty chunk text"
            )
        pieces.append(remaining[:length])
        remaining = remaining[length:]
    return pieces


def _atomic_units(
    text: str,
    prefix: str,
    tokenizer: object,
    config: ChunkingConfig,
) -> List[str]:
    sentence_units = _slice_at_matches(text, _SENTENCE_END)
    units: List[str] = []
    for sentence in sentence_units:
        if _fits(sentence, prefix, tokenizer, config):
            units.append(sentence)
            continue
        semicolon_units = _slice_at_matches(sentence, _SEMICOLON_END)
        for semicolon_unit in semicolon_units:
            if _fits(semicolon_unit, prefix, tokenizer, config):
                units.append(semicolon_unit)
                continue
            enumeration_units = _split_at_enumerations(semicolon_unit)
            for enumeration_unit in enumeration_units:
                if _fits(enumeration_unit, prefix, tokenizer, config):
                    units.append(enumeration_unit)
                else:
                    units.extend(
                        _hard_split(enumeration_unit, prefix, tokenizer, config)
                    )
    return units


def _pack_units(
    units: Sequence[str],
    prefix: str,
    tokenizer: object,
    config: ChunkingConfig,
) -> List[str]:
    chunks: List[str] = []
    current = ""
    for unit in units:
        candidate = current + unit
        within_target = _fits(
            candidate,
            prefix,
            tokenizer,
            config,
            char_limit=config.target_chars,
        )
        needs_companion = len(current) < config.min_chars
        within_hard = _fits(candidate, prefix, tokenizer, config)
        if current and not within_target and not (needs_companion and within_hard):
            chunks.append(current)
            current = unit
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _last_complete_sentence(text: str, overlap_chars: int) -> str:
    units = [normalize_text(unit) for unit in _slice_at_matches(text, _SENTENCE_END)]
    if not units:
        return ""
    sentence = units[-1]
    if not _COMPLETE_SENTENCE.search(sentence) or len(sentence) > overlap_chars:
        return ""
    return sentence


def _split_long_block(
    block: _SourceBlock,
    prefix: str,
    tokenizer: object,
    config: ChunkingConfig,
) -> List[_ChunkText]:
    raw_chunks = _pack_units(
        _atomic_units(block.text, prefix, tokenizer, config),
        prefix,
        tokenizer,
        config,
    )
    results: List[_ChunkText] = []
    for index, raw_chunk in enumerate(raw_chunks):
        text = raw_chunk
        if index and config.overlap_chars:
            overlap = _last_complete_sentence(raw_chunks[index - 1], config.overlap_chars)
            candidate = overlap + raw_chunk
            if overlap and _fits(candidate, prefix, tokenizer, config):
                text = candidate
        results.append(_ChunkText(text, block.section_path, block.content_type))
    return results


def _extract_source_blocks(blocks: Sequence[Mapping[str, Any]]) -> List[_SourceBlock]:
    section_path: List[str] = []
    source_blocks: List[_SourceBlock] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            raise ValueError(f"blocks[{index}] must be a mapping")
        kind = normalize_text(block.get("kind"))
        text = normalize_text(block.get("text"))
        if kind == "heading":
            if not text:
                raise ValueError(f"blocks[{index}] heading text must not be empty")
            level = block.get("level")
            if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 6:
                raise ValueError(f"blocks[{index}] heading level must be between 1 and 6")
            section_path = section_path[: level - 1]
            section_path.append(text)
            continue
        if not text:
            continue
        if kind == "table":
            content_type = "table"
        elif kind in {"paragraph", "text", "list_item", "blockquote"}:
            content_type = "text"
        else:
            raise ValueError(f"blocks[{index}] has unsupported kind: {kind or '<empty>'}")
        source_blocks.append(_SourceBlock(text, tuple(section_path), content_type))
    return source_blocks


def _natural_chunks(
    blocks: Sequence[_SourceBlock],
    classification: str,
    title: str,
    tokenizer: object,
    config: ChunkingConfig,
) -> List[_ChunkText]:
    results: List[_ChunkText] = []
    pending: List[str] = []
    pending_key: Optional[Tuple[Tuple[str, ...], str]] = None

    def prefix_for(block: _SourceBlock) -> str:
        return _fit_embedding_prefix(
            classification,
            title,
            block.section_path,
            block.text[0],
            tokenizer,
            config.max_tokens,
        )

    def flush_pending() -> None:
        nonlocal pending, pending_key
        if pending and pending_key is not None:
            results.append(_ChunkText("\n".join(pending), pending_key[0], pending_key[1]))
        pending = []
        pending_key = None

    for block in blocks:
        key = (block.section_path, block.content_type)
        prefix = prefix_for(block)
        if len(block.text) > config.hard_max_chars or not _fits(
            block.text, prefix, tokenizer, config
        ):
            flush_pending()
            results.extend(_split_long_block(block, prefix, tokenizer, config))
            continue
        if pending_key != key:
            flush_pending()
            pending_key = key
        candidate = "\n".join(pending + [block.text])
        should_merge = not pending or (
            _fits(
                candidate,
                prefix,
                tokenizer,
                config,
                char_limit=config.target_chars,
            )
            or (
                (len("\n".join(pending)) < config.min_chars or len(block.text) < config.min_chars)
                and _fits(
                    candidate,
                    prefix,
                    tokenizer,
                    config,
                    char_limit=config.soft_max_chars,
                )
            )
        )
        if not should_merge:
            flush_pending()
            pending_key = key
        pending.append(block.text)
    flush_pending()
    return results


def _search_text(
    value: str,
    search_tokenizer: Optional[Callable[[str], Iterable[str]]],
) -> str:
    if search_tokenizer is not None:
        if callable(search_tokenizer):
            tokens = search_tokenizer(value)
        elif callable(getattr(search_tokenizer, "cut", None)):
            tokens = search_tokenizer.cut(value)
        else:
            raise ValueError("search_tokenizer must be callable or provide cut(text)")
        if isinstance(tokens, str):
            return normalize_text(tokens)
        return " ".join(
            token for token in (normalize_text(token) for token in tokens) if token
        )

    tokens = re.findall(
        r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*|[\u3400-\u9fff]|[^\s]",
        normalize_text(value),
    )
    return " ".join(tokens)


def build_report_chunks(
    blocks: Sequence[Mapping[str, Any]],
    library: str,
    material_id: str,
    title: str,
    metadata: Mapping[str, Any],
    tokenizer: object,
    config: ChunkingConfig = ChunkingConfig(),
    search_tokenizer: Optional[Callable[[str], Iterable[str]]] = None,
) -> List[ChunkRecord]:
    """Build deterministic, linked ChunkRecords from ordered report blocks."""
    if not isinstance(config, ChunkingConfig):
        raise ValueError("config must be a ChunkingConfig")
    if not blocks:
        raise ValueError("blocks must not be empty")
    normalized_library = normalize_text(library)
    normalized_material_id = normalize_text(material_id)
    normalized_title = normalize_text(title)
    for name, value in (
        ("library", normalized_library),
        ("material_id", normalized_material_id),
        ("title", normalized_title),
    ):
        if not value:
            raise ValueError(f"{name} must not be empty")
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a mapping")

    source_blocks = _extract_source_blocks(blocks)
    if not source_blocks:
        raise ValueError("blocks must contain at least one nonempty content block")
    classification = normalize_text(
        metadata.get("classification_name") or normalized_library
    )
    chunk_texts = _natural_chunks(
        source_blocks,
        classification,
        normalized_title,
        tokenizer,
        config,
    )
    document_id = f"external:v2:{normalized_library}:{normalized_material_id}"
    records: List[ChunkRecord] = []
    for index, chunk_text in enumerate(chunk_texts):
        prefix = _fit_embedding_prefix(
            classification,
            normalized_title,
            chunk_text.section_path,
            chunk_text.text[0],
            tokenizer,
            config.max_tokens,
        )
        embedding_text = prefix + chunk_text.text
        token_count = _token_count(tokenizer, embedding_text)
        if token_count > config.max_tokens:
            raise ValueError(
                f"chunk {index} exceeds max_tokens after splitting: "
                f"{token_count} > {config.max_tokens}"
            )
        digest = hashlib.sha256(normalize_text(chunk_text.text).encode("utf-8")).hexdigest()
        chunk_id = (
            f"external:v2:{normalized_library}:{normalized_material_id}:"
            f"c:{index}:{digest[:8]}"
        )
        chunk_metadata = dict(metadata)
        chunk_metadata.update(
            {
                "library": normalized_library,
                "material_id": normalized_material_id,
                "title": normalized_title,
                "section_path": chunk_text.section_path,
                "content_type": chunk_text.content_type,
                "chunker_version": "v2",
            }
        )
        search_source = "\n".join(
            filter(
                None,
                (
                    classification,
                    normalized_title,
                    " / ".join(chunk_text.section_path),
                    chunk_text.text,
                ),
            )
        )
        records.append(
            ChunkRecord(
                chunk_id=chunk_id,
                document_id=document_id,
                chunk_index=index,
                text=chunk_text.text,
                embedding_text=embedding_text,
                search_text=_search_text(search_source, search_tokenizer),
                token_count=token_count,
                content_hash=digest,
                metadata=chunk_metadata,
            )
        )

    linked_records: List[ChunkRecord] = []
    for index, record in enumerate(records):
        linked_records.append(
            replace(
                record,
                previous_chunk_id=records[index - 1].chunk_id if index else None,
                next_chunk_id=(
                    records[index + 1].chunk_id if index + 1 < len(records) else None
                ),
            )
        )
    return linked_records
