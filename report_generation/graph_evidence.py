"""Optional links from graph elements to report-retrieval evidence chunks.

The graph remains usable when no links have been curated. Links reference the
existing report material/chunk identifiers instead of copying source text into
the graph.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


from .graph_evidence_contract import (
    CURATION_FIELDS, filter_approved_evidence_refs, merge_curation_fields,
    normalize_evidence_link,
)


def _valid_refs(values: Any, defaults: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
    if not isinstance(values, list):
        return ()
    refs = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        ref = dict(value)
        for field in CURATION_FIELDS:
            if ref.get(field) in (None, "") and (defaults or {}).get(field) not in (None, ""):
                ref[field] = defaults[field]
        refs.append(ref)
    return filter_approved_evidence_refs(refs)


class GraphEvidenceIndex:
    """Read optional sidecar and inline evidence links for graph elements."""

    def __init__(
        self,
        nodes: Mapping[Any, Iterable[Mapping[str, Any]]] | None = None,
        relationships: Mapping[tuple[Any, Any, str], Iterable[Mapping[str, Any]]] | None = None,
    ) -> None:
        self._nodes = {key: tuple(value) for key, value in (nodes or {}).items()}
        self._relationships = {
            key: tuple(value) for key, value in (relationships or {}).items()
        }

    @classmethod
    def from_path(cls, path: Path) -> "GraphEvidenceIndex":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("graph evidence links must be a JSON object")
        links = payload.get("links", [])
        if not isinstance(links, list):
            raise ValueError("graph evidence links must contain a list")

        nodes: dict[Any, list[dict[str, Any]]] = {}
        relationships: dict[tuple[Any, Any, str], list[dict[str, Any]]] = {}
        for link in links:
            if not isinstance(link, Mapping):
                continue
            if link.get("verification_status", "approved") != "approved":
                continue
            try:
                link = normalize_evidence_link(link)
            except ValueError:
                continue
            refs = tuple(link["evidence_refs"])
            if not refs:
                continue
            element_type = str(link.get("element_type") or "").strip().lower()
            if element_type == "node" and link.get("id") is not None:
                nodes.setdefault(link["id"], []).extend(refs)
            elif element_type == "relationship":
                key = (
                    link.get("source"),
                    link.get("target"),
                    str(link.get("type") or ""),
                )
                relationships.setdefault(key, []).extend(refs)
        return cls(nodes, relationships)

    @staticmethod
    def _merge(*groups: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        return filter_approved_evidence_refs(ref for group in groups for ref in group)

    def for_node(self, node_id: Any, properties: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
        inline = _valid_refs((properties or {}).get("evidence_refs"))
        return self._merge(self._nodes.get(node_id, ()), inline)

    def for_relationship(self, relationship: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        key = (
            relationship.get("source"),
            relationship.get("target"),
            str(relationship.get("type") or ""),
        )
        inline = _valid_refs((relationship.get("properties") or {}).get("evidence_refs"))
        return self._merge(self._relationships.get(key, ()), inline)
