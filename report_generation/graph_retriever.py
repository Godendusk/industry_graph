# -*- coding: utf-8 -*-
"""Industry graph retrieval for report generation.

This module loads the selected industry's graph. It asks the LLM to
choose 1-3 real level-3 industry segments, then expands those segments through
the existing graph relationships.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llm_client import llm
from .industry_config import get_industry_config

REL_BELONGS_TO = "从属于"
REL_PARTICIPATES_IN = "参与环节"


def retrieve_industry_graph(query: str, industry: str = "ai") -> dict:
    """Retrieve selected-industry graph context for a report query.

    The retrieval flow is:
    1. Load the AI graph.
    2. Send the complete L3 segment list to the LLM.
    3. Validate that the LLM selected 1-3 real L3 nodes.
    4. Expand each selected L3 upward to L2/L1 and downward to all entities.
    """
    normalized_query = str(query or "").strip()
    normalized_industry = str(industry or "").strip()
    if not normalized_query:
        return _error_response("query 不能为空", normalized_query, normalized_industry)

    try:
        config = get_industry_config(normalized_industry)
    except ValueError as exc:
        return _error_response(str(exc), normalized_query, normalized_industry)

    industry_name = config["name"]
    graph_path = Path(config["graph_path"])

    try:
        graph = _IndustryGraph(graph_path)
    except Exception as exc:
        return _error_response(
            f"加载{industry_name}知识图谱失败: {exc}",
            normalized_query,
            normalized_industry,
        )

    llm_result = _select_level3_with_llm(normalized_query, graph, industry_name)
    if llm_result["status"] != "success":
        return _error_response(llm_result["message"], normalized_query, normalized_industry)

    selected_level3 = _validate_llm_level3_selection(llm_result["data"], graph)
    if not selected_level3:
        return _error_response(
            "LLM 未能从 L3 环节清单中返回有效结果",
            normalized_query,
            normalized_industry,
        )

    matched_level3 = []
    evidence_blocks = []
    for selection in selected_level3:
        l3_id = selection["id"]
        parent_l2, parent_l1, upward_path = graph.get_parent_path(l3_id)
        entities = graph.get_downward_entities(l3_id)
        chain_path = _format_chain_path(parent_l1, parent_l2, graph.node_summary(l3_id))

        matched_level3.append(
            {
                "id": l3_id,
                "name": graph.node_name(l3_id),
                "score": selection["score"],
                "reason": selection["reason"],
                "parent_l2": parent_l2,
                "parent_l1": parent_l1,
            }
        )
        evidence_blocks.append(
            {
                "level3": graph.node_summary(l3_id),
                "chain_path": chain_path,
                "upward_path": upward_path,
                "downward_entities": entities,
                "downward_total_count": len(entities),
                "context_text": _build_context_text(chain_path, graph.node_name(l3_id), entities),
            }
        )

    return {
        "status": "success",
        "industry": normalized_industry,
        "industry_name": industry_name,
        "query": normalized_query,
        "graph_context_text": _build_graph_context_text(normalized_query, evidence_blocks),
        "matched_level3": matched_level3,
        "evidence_blocks": evidence_blocks,
    }


def retrieve_ai_graph(query: str) -> dict:
    """Backward-compatible AI-only retrieval entry point."""
    return retrieve_industry_graph(query, industry="ai")


class _IndustryGraph:
    def __init__(self, graph_path: Path):
        self.graph_path = graph_path
        self.nodes_by_id: Dict[Any, dict] = {}
        self.out_edges_by_source: Dict[Any, List[dict]] = defaultdict(list)
        self.in_edges_by_target: Dict[Any, List[dict]] = defaultdict(list)
        self.level3_nodes: Dict[Any, dict] = {}
        self.l3_parent_paths: Dict[Any, Tuple[Optional[dict], Optional[dict], List[dict]]] = {}
        self._load()
        self._build_level3_parent_paths()

    def _load(self) -> None:
        if not self.graph_path.exists():
            raise FileNotFoundError(str(self.graph_path))

        data = json.loads(self.graph_path.read_text(encoding="utf-8"))
        for node in data.get("nodes", []):
            node_id = node.get("id")
            self.nodes_by_id[node_id] = node
            if self._is_level3_node(node):
                self.level3_nodes[node_id] = node

        for rel in data.get("relationships", []):
            source = rel.get("source")
            target = rel.get("target")
            self.out_edges_by_source[source].append(rel)
            self.in_edges_by_target[target].append(rel)

    def _build_level3_parent_paths(self) -> None:
        for l3_id in self.level3_nodes:
            parent_l2_node, edge_to_l2 = self._find_parent(l3_id, expected_level="2")
            parent_l1_node = None
            edge_to_l1 = None
            if parent_l2_node is not None:
                parent_l1_node, edge_to_l1 = self._find_parent(parent_l2_node.get("id"), expected_level="1")

            upward_path = []
            if edge_to_l2:
                upward_path.append(self.relationship_summary(edge_to_l2))
            if edge_to_l1:
                upward_path.append(self.relationship_summary(edge_to_l1))

            self.l3_parent_paths[l3_id] = (
                self.node_summary(parent_l2_node.get("id")) if parent_l2_node else None,
                self.node_summary(parent_l1_node.get("id")) if parent_l1_node else None,
                upward_path,
            )

    def _find_parent(self, node_id: Any, expected_level: str) -> Tuple[Optional[dict], Optional[dict]]:
        for rel in self.out_edges_by_source.get(node_id, []):
            if rel.get("type") != REL_BELONGS_TO:
                continue
            target = self.nodes_by_id.get(rel.get("target"))
            if target and self.node_level(target) == expected_level:
                return target, rel
        return None, None

    def _is_level3_node(self, node: dict) -> bool:
        return "环节" in (node.get("labels") or []) and self.node_level(node) == "3"

    def node_level(self, node: dict) -> str:
        props = node.get("properties") or {}
        return str(props.get("level", ""))

    def node_name(self, node_id: Any) -> str:
        node = self.nodes_by_id.get(node_id) or {}
        return _node_name(node)

    def node_summary(self, node_id: Any) -> dict:
        node = self.nodes_by_id.get(node_id) or {}
        return {"id": node_id, "name": _node_name(node)}

    def relationship_summary(self, rel: dict) -> dict:
        source = rel.get("source")
        target = rel.get("target")
        return {
            "source": source,
            "source_name": self.node_name(source),
            "type": rel.get("type", ""),
            "target": target,
            "target_name": self.node_name(target),
        }

    def get_parent_path(self, l3_id: Any) -> Tuple[Optional[dict], Optional[dict], List[dict]]:
        return self.l3_parent_paths.get(l3_id, (None, None, []))

    def get_downward_entities(self, l3_id: Any) -> List[dict]:
        entities = []
        seen_ids = set()
        for rel in self.in_edges_by_target.get(l3_id, []):
            if rel.get("type") != REL_PARTICIPATES_IN:
                continue
            source = rel.get("source")
            if source in seen_ids:
                continue
            node = self.nodes_by_id.get(source)
            if not node:
                continue
            seen_ids.add(source)
            entities.append(
                {
                    "id": source,
                    "name": _node_name(node),
                    "labels": node.get("labels") or [],
                    "edge_type": REL_PARTICIPATES_IN,
                }
            )
        entities.sort(key=lambda item: str(item.get("name") or ""))
        return entities

    def level3_prompt_rows(self) -> List[str]:
        rows = []
        for l3_id, node in sorted(self.level3_nodes.items(), key=lambda item: int(item[0])):
            parent_l2, parent_l1, _ = self.get_parent_path(l3_id)
            l1_name = (parent_l1 or {}).get("name") or "未知"
            l2_name = (parent_l2 or {}).get("name") or "未知"
            rows.append(f"ID: {l3_id} | L1: {l1_name} | L2: {l2_name} | L3: {_node_name(node)}")
        return rows


def _select_level3_with_llm(query: str, graph: _IndustryGraph, industry_name: str) -> dict:
    system_prompt = (
        f"你是{industry_name}产业知识图谱检索助手。"
        "你只能从用户提供的 L3 环节清单中选择相关环节。"
        "必须只输出 JSON 数组，不要输出解释、Markdown 或代码块。"
    )
    user_prompt = f"""请根据用户查询，从下面的{industry_name}产业 L3 环节清单中选择最相关的 1 到 3 个。

用户查询：
{query}

选择要求：
1. 只能选择清单中真实存在的 L3 环节。
2. 输出数量必须是 1 到 3 个。
3. 每项必须包含 id、name、reason、score。
4. score 使用 0 到 1 的数字表示相关性。
5. name 必须与清单中的 L3 名称完全一致。

输出 JSON 示例：
[
  {{"id": 23, "name": "GPU/AI芯片", "reason": "与查询中的 GPU 和 AI 芯片直接相关", "score": 0.95}}
]

L3 环节清单：
{chr(10).join(graph.level3_prompt_rows())}
"""
    try:
        content = llm.query(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=1200,
            extra_log_info=f"report_generation.graph_retriever query={query}",
        )
    except Exception as exc:
        return {"status": "error", "message": f"LLM 调用失败: {exc}", "data": None}

    if not content:
        return {"status": "error", "message": "LLM 返回为空", "data": None}

    try:
        data = _parse_json_array(content)
    except ValueError as exc:
        return {"status": "error", "message": f"LLM 返回 JSON 解析失败: {exc}", "data": None}

    if not isinstance(data, list) or not (1 <= len(data) <= 3):
        return {"status": "error", "message": "LLM 返回的 L3 数量不合规，必须为 1 到 3 个", "data": None}

    return {"status": "success", "message": "", "data": data}


def _validate_llm_level3_selection(items: List[dict], graph: _IndustryGraph) -> List[dict]:
    selected = []
    seen_ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue

        if not all(key in item for key in ("id", "name", "reason", "score")):
            continue

        node_id = _coerce_node_id(item.get("id"))
        if node_id in seen_ids or node_id not in graph.level3_nodes:
            continue

        expected_name = graph.node_name(node_id)
        if str(item.get("name", "")).strip() != expected_name:
            continue

        score = _coerce_score(item.get("score"))
        if score is None:
            continue

        seen_ids.add(node_id)
        selected.append(
            {
                "id": node_id,
                "name": expected_name,
                "reason": str(item.get("reason", "")).strip(),
                "score": score,
            }
        )
    return selected


def _parse_json_array(text: str) -> list:
    cleaned = str(text).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    if not cleaned.startswith("["):
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if not match:
            raise ValueError("未找到 JSON 数组")
        cleaned = match.group(0)

    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("顶层 JSON 不是数组")
    return data


def _coerce_node_id(raw_id: Any) -> Optional[Any]:
    if isinstance(raw_id, int):
        return raw_id
    if isinstance(raw_id, str):
        value = raw_id.strip()
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        return value
    return raw_id


def _coerce_score(raw_score: Any) -> Optional[float]:
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, score))


def _node_name(node: dict) -> str:
    props = node.get("properties") or {}
    return str(props.get("name", "")).strip()


def _format_chain_path(parent_l1: Optional[dict], parent_l2: Optional[dict], level3: dict) -> str:
    parts = []
    if parent_l1 and parent_l1.get("name"):
        parts.append(parent_l1["name"])
    if parent_l2 and parent_l2.get("name"):
        parts.append(parent_l2["name"])
    if level3.get("name"):
        parts.append(level3["name"])
    return " > ".join(parts)


def _build_context_text(chain_path: str, l3_name: str, entities: List[dict]) -> str:
    entity_names = [item["name"] for item in entities if item.get("name")]
    if entity_names:
        entity_text = "、".join(entity_names)
    else:
        entity_text = "未检索到参与该环节的企业/实体"

    return (
        f"产业链路径：{chain_path}。"
        "该路径来自图谱中的“从属于”关系。"
        f"参与 {l3_name} 环节的企业/实体包括：{entity_text}。"
        "以上企业/实体来自图谱中的“参与环节”关系。"
    )


def _build_graph_context_text(query: str, evidence_blocks: List[dict]) -> str:
    lines = [
        "【知识图谱上下文】",
        f"围绕查询“{query}”，知识图谱检索命中以下三级环节：",
        "",
    ]

    for index, block in enumerate(evidence_blocks, 1):
        chain_path = block.get("chain_path") or ""
        entity_names = [
            item["name"]
            for item in block.get("downward_entities", [])
            if item.get("name")
        ]
        entity_text = "、".join(entity_names) if entity_names else "未检索到参与该环节的企业/实体"
        lines.append(f"{index}. 产业链路径：{chain_path}。")
        lines.append(f"   参与该环节的企业/实体包括：{entity_text}。")
        lines.append("")

    lines.append(
        "以上路径来自图谱中的“从属于”关系，企业/实体来自图谱中的“参与环节”关系。"
        "该内容是知识图谱上下文，可用于报告生成中的产业链位置、生态参与方和上下游结构分析，"
        "不等同于外部资料库引用。"
    )
    return "\n".join(lines).strip()


def _error_response(message: str, query: str, industry: str = "ai") -> dict:
    return {
        "status": "error",
        "industry": industry,
        "query": query,
        "message": message or "LLM 未能从 L3 环节清单中返回有效结果",
        "matched_level3": [],
        "evidence_blocks": [],
    }
