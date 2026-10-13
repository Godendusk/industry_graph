"""Topology-based traversal helpers for variable-depth industry graphs."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable


SEGMENT_LABEL = "环节"
COMPANY_LABEL = "公司"
REL_BELONGS_TO = "从属于"
REL_PARTICIPATES_IN = "参与环节"
MIN_SEGMENT_LEVEL = 2
MAX_SEGMENT_LEVEL = 5


def _key(value: Any) -> str:
    return str(value)


def _sort_key(value: Any) -> tuple[int, Any]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, _key(value))


class GraphHierarchy:
    """Index segment ancestry and direct company attachments once per graph."""

    def __init__(self, data: dict[str, Any]):
        self.nodes = list(data.get("nodes") or [])
        self.relationships = list(data.get("relationships") or [])
        self.nodes_by_key: dict[str, dict[str, Any]] = {}
        self.segment_children_by_key: dict[str, list[Any]] = {}
        self.parent_by_segment_key: dict[str, Any] = {}
        self.company_ids_by_segment_key: dict[str, list[Any]] = {}

        for node in self.nodes:
            node_id = node.get("id")
            if node_id is None:
                continue
            self.nodes_by_key[_key(node_id)] = node

        for relationship in self.relationships:
            if not isinstance(relationship, dict):
                continue
            source = relationship.get("source")
            target = relationship.get("target")
            source_node = self.node_for(source)
            target_node = self.node_for(target)
            if (
                relationship.get("type") == REL_BELONGS_TO
                and self.is_segment(source_node)
                and (self.is_segment(target_node) or self.is_root(target_node))
            ):
                self._append_unique(self.segment_children_by_key, _key(target), source)
                self.parent_by_segment_key[_key(source)] = target
            elif (
                relationship.get("type") == REL_PARTICIPATES_IN
                and self.is_company(source_node)
                and self.is_segment(target_node)
            ):
                self._append_unique(self.company_ids_by_segment_key, _key(target), source)

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "GraphHierarchy":
        return cls(copy.deepcopy(data))

    @classmethod
    def from_path(cls, path: Path) -> "GraphHierarchy":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("graph data must be an object")
        return cls(data)

    @staticmethod
    def _append_unique(target: dict[str, list[Any]], map_key: str, value: Any) -> None:
        values = target.setdefault(map_key, [])
        if not any(_key(existing) == _key(value) for existing in values):
            values.append(value)

    def node_for(self, node_id: Any) -> dict[str, Any] | None:
        return self.nodes_by_key.get(_key(node_id))

    @staticmethod
    def is_segment(node: dict[str, Any] | None) -> bool:
        return bool(node and SEGMENT_LABEL in (node.get("labels") or []))

    @staticmethod
    def is_company(node: dict[str, Any] | None) -> bool:
        return bool(node and COMPANY_LABEL in (node.get("labels") or []))

    @staticmethod
    def is_root(node: dict[str, Any] | None) -> bool:
        return bool(node and "Root" in (node.get("labels") or []))

    @staticmethod
    def node_level(node: dict[str, Any] | None) -> int | None:
        if not node:
            return None
        raw_level = (node.get("properties") or {}).get("level")
        try:
            return int(raw_level)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def node_name(node: dict[str, Any] | None) -> str:
        return str((node or {}).get("properties", {}).get("name", "")).strip()

    def segment_node_ids(self) -> list[Any]:
        return sorted(
            (node.get("id") for node in self.nodes if self.is_segment(node)),
            key=_sort_key,
        )

    def _is_terminal_segment(self, node_id: Any) -> bool:
        node = self.node_for(node_id)
        level = self.node_level(node)
        return bool(
            self.is_segment(node)
            and level is not None
            and MIN_SEGMENT_LEVEL <= level <= MAX_SEGMENT_LEVEL
            and not self.segment_children_by_key.get(_key(node_id))
        )

    def descendant_segment_ids(self, segment_id: Any) -> list[Any]:
        pending = list(self.segment_children_by_key.get(_key(segment_id), []))
        result: list[Any] = []
        visited: set[str] = set()
        while pending:
            current = pending.pop(0)
            current_key = _key(current)
            if current_key in visited:
                continue
            visited.add(current_key)
            result.append(current)
            pending.extend(self.segment_children_by_key.get(current_key, []))
        return sorted(result, key=_sort_key)

    def terminal_segment_ids(self, under_id: Any | None = None) -> list[Any]:
        candidates = (
            self.segment_node_ids()
            if under_id is None
            else self.descendant_segment_ids(under_id)
        )
        return sorted(
            (node_id for node_id in candidates if self._is_terminal_segment(node_id)),
            key=_sort_key,
        )

    def segment_path_ids(self, segment_id: Any, include_root: bool = False) -> list[Any]:
        path: list[Any] = []
        current = segment_id
        visited: set[str] = set()
        while current is not None and _key(current) not in visited:
            node = self.node_for(current)
            if not self.is_segment(node):
                break
            visited.add(_key(current))
            path.append(current)
            current = self.parent_by_segment_key.get(_key(current))
        path.reverse()
        if not include_root and path and self.node_level(self.node_for(path[0])) == 0:
            path = path[1:]
        return path

    def company_ids_for_segments(self, segment_ids: Iterable[Any]) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()
        for segment_id in segment_ids:
            for company_id in self.company_ids_by_segment_key.get(_key(segment_id), []):
                company_key = _key(company_id)
                if company_key not in seen:
                    seen.add(company_key)
                    result.append(company_id)
        return sorted(result, key=_sort_key)

    def node_summary(self, node_id: Any) -> dict[str, Any]:
        node = self.node_for(node_id) or {}
        return {
            "id": node_id,
            "name": self.node_name(node),
            "level": self.node_level(node),
            "labels": list(node.get("labels") or []),
        }
