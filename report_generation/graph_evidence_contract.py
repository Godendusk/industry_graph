"""Pure, shared contract for curated graph-to-chunk evidence links."""
from __future__ import annotations
from typing import Any, Iterable, Mapping

CURATION_FIELDS = ("review_method", "review_note", "evidence_scope")


def merge_curation_fields(*sources: Mapping[str, Any]) -> dict[str, str]:
    """Keep distinct curated limits on a chunk, in their original order."""
    result = {}
    for field in CURATION_FIELDS:
        lines = []
        for source in sources:
            value = source.get(field)
            if value not in (None, ""):
                for line in str(value).splitlines():
                    if line and line not in lines:
                        lines.append(line)
        if lines:
            result[field] = "\n".join(lines)
    return result


def _ref_key(ref: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(ref.get("material_id") or ""),
        str(ref.get("document_id") or ""),
        str(ref.get("chunk_id") or ""),
    )



def filter_approved_evidence_refs(values: Iterable[Mapping[str, Any]]) -> tuple[dict, ...]:
    output = []
    for value in values:
        if not isinstance(value, Mapping) or value.get("verification_status", "approved") != "approved":
            continue
        ref = {key: value[key] for key in ("material_id", "document_id", "chunk_id", "library", "verification_status") if value.get(key) not in (None, "")}
        if not (ref.get("chunk_id") or ref.get("material_id")):
            continue
        ref.update(merge_curation_fields(value))
        existing = None
        for candidate in output:
            if ref.get("chunk_id") and candidate.get("chunk_id"):
                same_chunk = str(ref["chunk_id"]) == str(candidate["chunk_id"])
                conflict = any(
                    ref.get(field) not in (None, "")
                    and candidate.get(field) not in (None, "")
                    and str(ref[field]) != str(candidate[field])
                    for field in ("material_id", "document_id", "library")
                )
                if same_chunk and not conflict:
                    existing = candidate
                    break
            elif not ref.get("chunk_id") and not candidate.get("chunk_id"):
                if _ref_key(ref) == _ref_key(candidate):
                    existing = candidate
                    break
        if existing is None:
            output.append(ref)
        else:
            existing.update(merge_curation_fields(existing, ref))
            for field in ("material_id", "document_id", "chunk_id", "library"):
                if existing.get(field) in (None, "") and ref.get(field) not in (None, ""):
                    existing[field] = ref[field]
    return tuple(output)


def normalize_evidence_link(link: Mapping[str, Any]) -> dict:
    normalized = dict(link)
    element_type = str(link.get("element_type") or "").strip().lower()
    if element_type == "node":
        if link.get("id") in (None, ""):
            raise ValueError("node evidence requires id")
        expected_kind = "entity_mention"
    elif element_type == "relationship":
        if any(link.get(key) in (None, "") for key in ("source", "target", "type")) or not str(link["type"]).strip():
            raise ValueError("relationship evidence requires source, target and type")
        expected_kind = "relationship_support"
    else:
        raise ValueError("element_type must be node or relationship")
    if link.get("evidence_kind", expected_kind) != expected_kind:
        raise ValueError(f"{element_type} evidence_kind must be {expected_kind}")
    normalized.update(element_type=element_type, evidence_kind=expected_kind)
    values = link.get("evidence_refs", [])
    if not isinstance(values, list):
        raise ValueError("evidence_refs must be a list")
    with_defaults = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        ref = dict(value)
        for field in CURATION_FIELDS:
            if ref.get(field) in (None, "") and link.get(field) not in (None, ""):
                ref[field] = link[field]
        with_defaults.append(ref)
    normalized["evidence_refs"] = list(filter_approved_evidence_refs(with_defaults))
    return normalized


def validate_evidence_sidecar(payload: Mapping[str, Any]) -> list[str]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("links", []), list):
        return ["graph evidence sidecar must be an object containing a links list"]
    errors = []
    for index, link in enumerate(payload.get("links", [])):
        try:
            if not isinstance(link, Mapping):
                raise ValueError("link must be an object")
            normalize_evidence_link(link)
        except ValueError as exc:
            errors.append(f"links[{index}]: {exc}")
    return errors
