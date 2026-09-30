"""Pure allocation of evidence candidates across report sections."""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any


def _material_key(block: Any) -> str:
    """Return a stable library/material identity, falling back to vector id."""
    if not isinstance(block, dict):
        return ""
    library = str(block.get("library") or "").strip()
    material_id = str(block.get("material_id") or "").strip()
    vector_id = str(block.get("vector_id") or "").strip()
    identity = material_id or vector_id
    return f"{library}:{identity}" if identity else ""


def allocate_evidence_blocks(section_candidates: list[dict[str, Any]], target_per_section: int) -> list[dict[str, Any]]:
    """Allocate at most ``target_per_section`` evidence blocks for each section.

    Candidates are consumed in section order. One candidate per material is selected
    first, preferring materials used in fewer preceding sections; a section's first
    valid candidate is always retained. Remaining slots may contain a second chunk
    from a selected material. Inputs and selected blocks are deep copied.
    """
    try:
        target = max(0, int(target_per_section))
    except (TypeError, ValueError):
        target = 0

    prior_usage: defaultdict[str, int] = defaultdict(int)
    allocated: list[dict[str, Any]] = []

    for section in section_candidates or []:
        section_copy = copy.deepcopy(section)
        candidates = section.get("candidates", []) if isinstance(section, dict) else []
        if not isinstance(candidates, list):
            candidates = []

        valid: list[tuple[int, dict[str, Any], str]] = []
        for index, candidate in enumerate(candidates):
            key = _material_key(candidate)
            if key and isinstance(candidate, dict):
                valid.append((index, candidate, key))

        selected: list[tuple[int, dict[str, Any], str]] = []
        selected_keys: set[str] = set()
        first = valid[0] if valid else None
        if target and first is not None:
            selected.append(first)
            selected_keys.add(first[2])

            # Distinct sources are ordered by report-level reuse, then retrieval order.
            distinct = sorted(
                (row for row in valid if row[2] not in selected_keys),
                key=lambda row: (prior_usage[row[2]], row[0]),
            )
            for row in distinct:
                if len(selected) >= target:
                    break
                selected.append(row)
                selected_keys.add(row[2])

            # Keep output order governed by reuse priority while retaining the first
            # candidate in the selected set (e.g. an unused source precedes a reused one).
            selected.sort(key=lambda row: (prior_usage[row[2]], row[0]))

            # Fill remaining slots with a second chunk, at most two per material.
            per_material = defaultdict(int)
            seen_vectors: set[str] = set()
            for _, candidate, key in selected:
                per_material[key] += 1
                vector_id = str(candidate.get("vector_id") or "").strip()
                seen_vectors.add(vector_id)
            for row in valid:
                if len(selected) >= target:
                    break
                index, candidate, key = row
                vector_id = str(candidate.get("vector_id") or "").strip()
                if key not in selected_keys or per_material[key] >= 2:
                    continue
                if vector_id in seen_vectors:
                    continue
                selected.append(row)
                per_material[key] += 1
                seen_vectors.add(vector_id)

        blocks = [copy.deepcopy(candidate) for _, candidate, _ in selected]
        selected_materials = {key for _, _, key in selected}
        reused = sorted(key for key in selected_materials if prior_usage[key] > 0)
        section_copy["evidence_blocks"] = blocks
        section_copy["diagnostics"] = {
            "candidate_count": len(candidates),
            "distinct_material_count": len(selected_materials),
            "reused_material_ids": reused,
        }
        allocated.append(section_copy)

        for key in selected_materials:
            prior_usage[key] += 1

    return allocated
