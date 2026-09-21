"""Pure helpers for report-level external source citations."""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any


_CITATION_PATTERN = re.compile(r"\[(C[1-9]\d*)\]")


def register_evidence_blocks(
    blocks: list, references: list
) -> tuple[list[dict], list[dict]]:
    """Assign stable report-level citation ids to evidence blocks.

    Evidence blocks are deduplicated by ``library + material_id``.  For old
    records without a material id, ``library + vector_id`` is used instead.
    Existing references are copied and reused, and chunks from the same
    source are merged into its ``vector_ids`` list.
    """

    mapped = copy.deepcopy(blocks if isinstance(blocks, list) else [])
    registry = copy.deepcopy(references if isinstance(references, list) else [])
    by_key = {
        key: row
        for row in registry
        if isinstance(row, dict)
        for key in [_reference_key(row)]
        if key
    }
    next_number = (
        max((_citation_number(row.get("citation_id")) for row in registry if isinstance(row, dict)), default=0)
        + 1
    )

    for block in mapped:
        if not isinstance(block, dict):
            continue
        key = _reference_key(block)
        if not key:
            continue
        reference = by_key.get(key)
        if reference is None:
            reference = _new_reference(block, f"C{next_number}")
            next_number += 1
            registry.append(reference)
            by_key[key] = reference
        elif not _text(reference.get("retrieved_at")):
            reference["retrieved_at"] = _text(block.get("retrieved_at")) or datetime.now().astimezone().isoformat(timespec="seconds")
        _append_vector_id(reference, block.get("vector_id"))
        block["citation_id"] = reference["citation_id"]

    return mapped, registry


def validate_body_citations(
    body_text: Any, evidence_blocks: list
) -> tuple[str, list[str], list[dict]]:
    """Remove citation markers that are not present in section evidence.

    The returned citation ids follow their first appearance in ``body_text``;
    repeated valid markers remain in the text but are listed only once.
    """

    text = _text(body_text)
    allowed = {
        _text(row.get("citation_id"))
        for row in evidence_blocks
        if isinstance(row, dict) and _text(row.get("citation_id"))
    }
    used: list[str] = []
    invalid: list[str] = []

    def replace(match: re.Match[str]) -> str:
        citation_id = match.group(1)
        if citation_id not in allowed:
            if citation_id not in invalid:
                invalid.append(citation_id)
            return ""
        if citation_id not in used:
            used.append(citation_id)
        return match.group(0)

    cleaned = _CITATION_PATTERN.sub(replace, text)
    warnings: list[dict] = []
    if invalid:
        warnings.append(
            {
                "stage": "citation_validation",
                "message": "removed citation markers not present in section evidence",
                "invalid_citation_ids": invalid,
            }
        )
    return cleaned, used, warnings


def collect_used_references(body_sections: list, references: list) -> list[dict]:
    """Return report references used by successful body sections only."""

    used = {
        _text(citation_id)
        for section in body_sections
        if isinstance(section, dict) and section.get("status") == "success"
        for citation_id in section.get("citation_ids", [])
        if _text(citation_id)
    }
    return [
        copy.deepcopy(row)
        for row in references
        if isinstance(row, dict) and _text(row.get("citation_id")) in used
    ]


def _reference_key(row: dict) -> str:
    if not isinstance(row, dict):
        return ""
    library = _text(row.get("library"))
    material_id = _text(row.get("material_id"))
    vector_id = _text(row.get("vector_id"))
    if not vector_id and isinstance(row.get("vector_ids"), list) and row["vector_ids"]:
        vector_id = _text(row["vector_ids"][0])
    identity = material_id or vector_id
    return f"{library}:{identity}" if identity else ""


def _new_reference(block: dict, citation_id: str) -> dict:
    return {
        "citation_id": citation_id,
        "library": _text(block.get("library")),
        "classification_name": _text(block.get("classification_name")),
        "material_id": _text(block.get("material_id")),
        "title": _text(block.get("title")),
        "publish_date": _text(block.get("publish_date")),
        "retrieved_at": _text(block.get("retrieved_at"))
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_address": _text(block.get("source_address")),
        "vector_ids": [],
        "evidence_excerpt": _text(block.get("text")),
    }


def _append_vector_id(reference: dict, value: Any) -> None:
    vector_id = _text(value)
    vector_ids = reference.setdefault("vector_ids", [])
    if not isinstance(vector_ids, list):
        vector_ids = []
        reference["vector_ids"] = vector_ids
    if vector_id and vector_id not in vector_ids:
        vector_ids.append(vector_id)


def _citation_number(value: Any) -> int:
    match = re.fullmatch(r"C([1-9]\d*)", _text(value))
    return int(match.group(1)) if match else 0


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "collect_used_references",
    "register_evidence_blocks",
    "validate_body_citations",
]
