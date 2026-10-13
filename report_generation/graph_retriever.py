# -*- coding: utf-8 -*-
"""Industry graph retrieval for report generation.

This module loads the selected industry's graph and asks the LLM to
choose 1-3 real terminal industry segments, then expands those segments through
the existing graph relationships.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from graph_hierarchy import GraphHierarchy
from llm_client import llm
from .industry_config import get_industry_config

REL_PARTICIPATES_IN = "参与环节"


def retrieve_industry_graph(query: str, industry: str = "ai") -> dict:
    """Retrieve selected-industry graph context for a report query.

    The retrieval flow is:
    1. Load the selected industry graph.
    2. Send the complete terminal-segment list to the LLM.
    3. Validate that the LLM selected 1-3 real terminal segments.
    4. Expand each selected segment through its complete ancestor path and
       collect entities directly attached to that terminal segment.
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

    llm_result = _select_terminal_segments_with_llm(normalized_query, graph, industry_name)
    if llm_result["status"] != "success":
        result = _error_response(llm_result["message"], normalized_query, normalized_industry)
        result["selection_diagnostics"] = llm_result.get("diagnostics", {})
        return result

    selected_segments = _validate_llm_terminal_selection(llm_result["data"], graph)
    if not selected_segments:
        return _error_response(
            "LLM 未能从末级环节清单中返回有效结果",
            normalized_query,
            normalized_industry,
        )

    matched_segments = []
    evidence_blocks = []
    for selection in selected_segments:
        segment_id = selection["id"]
        segment_path = graph.get_segment_path(segment_id)
        upward_path = graph.get_upward_path(segment_id)
        entities = graph.get_downward_entities(segment_id)
        chain_path = " > ".join(
            item["name"] for item in segment_path if item.get("name")
        )
        segment = graph.node_summary(segment_id)

        matched_segments.append(
            {
                "id": segment_id,
                "name": graph.node_name(segment_id),
                "level": segment.get("level"),
                "score": selection["score"],
                "reason": selection["reason"],
                "segment_path": segment_path,
            }
        )
        evidence_blocks.append(
            {
                "segment": segment,
                "segment_path": segment_path,
                "chain_path": chain_path,
                "upward_path": upward_path,
                "downward_entities": entities,
                "downward_total_count": len(entities),
                "context_text": _build_context_text(chain_path, graph.node_name(segment_id), entities),
            }
        )

    return {
        "status": "success",
        "industry": normalized_industry,
        "industry_name": industry_name,
        "query": normalized_query,
        "graph_context_text": _build_graph_context_text(normalized_query, evidence_blocks),
        "matched_segments": matched_segments,
        "evidence_blocks": evidence_blocks,
        "selection_diagnostics": llm_result.get("diagnostics", {}),
    }


def retrieve_graph(query: str, industry: str = "ai") -> dict:
    """Backward-compatible graph retrieval entry point."""
    return retrieve_industry_graph(query, industry=industry)


def retrieve_ai_graph(query: str) -> dict:
    """Backward-compatible AI-only retrieval entry point."""
    return retrieve_industry_graph(query, industry="ai")


class _IndustryGraph:
    def __init__(self, graph_path: Path):
        self.graph_path = graph_path
        self.nodes_by_id: Dict[Any, dict] = {}
        self.in_edges_by_target: Dict[Any, List[dict]] = defaultdict(list)
        self.hierarchy: GraphHierarchy
        self.terminal_segments: Dict[Any, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.graph_path.exists():
            raise FileNotFoundError(str(self.graph_path))

        data = json.loads(self.graph_path.read_text(encoding="utf-8"))
        self.hierarchy = GraphHierarchy.from_data(data)
        for node in data.get("nodes", []):
            node_id = node.get("id")
            self.nodes_by_id[node_id] = node
        self.terminal_segments = {
            node_id: self.nodes_by_id[node_id]
            for node_id in self.hierarchy.terminal_segment_ids()
            if node_id in self.nodes_by_id
        }

        for rel in data.get("relationships", []):
            target = rel.get("target")
            self.in_edges_by_target[target].append(rel)

    def node_level(self, node: dict) -> int | None:
        props = node.get("properties") or {}
        try:
            return int(props.get("level"))
        except (TypeError, ValueError):
            return None

    def node_name(self, node_id: Any) -> str:
        node = self.nodes_by_id.get(node_id) or {}
        return _node_name(node)

    def node_summary(self, node_id: Any) -> dict:
        node = self.nodes_by_id.get(node_id) or {}
        return {
            "id": node_id,
            "name": _node_name(node),
            "level": self.node_level(node),
            "labels": node.get("labels") or [],
        }

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

    def get_segment_path(self, segment_id: Any) -> List[dict]:
        return [self.node_summary(node_id) for node_id in self.hierarchy.segment_path_ids(segment_id)]

    def get_upward_path(self, segment_id: Any) -> List[dict]:
        path_ids = self.hierarchy.segment_path_ids(segment_id)
        upward_path = []
        for index in range(len(path_ids) - 1, 0, -1):
            child = path_ids[index]
            parent = path_ids[index - 1]
            upward_path.append(
                {
                    "source": child,
                    "source_name": self.node_name(child),
                    "type": "从属于",
                    "target": parent,
                    "target_name": self.node_name(parent),
                }
            )
        return upward_path

    def get_downward_entities(self, segment_id: Any) -> List[dict]:
        entities = []
        seen_ids = set()
        for rel in self.in_edges_by_target.get(segment_id, []):
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

    def terminal_prompt_rows(self) -> List[str]:
        rows = []
        for segment_id in sorted(self.terminal_segments, key=lambda value: int(value)):
            node = self.terminal_segments[segment_id]
            path = " > ".join(item["name"] for item in self.get_segment_path(segment_id))
            rows.append(
                f"ID: {segment_id} | Level: {self.node_level(node)} | 路径: {path}"
            )
        return rows


_QUERY_LABELS = (
    '用户需求', '用户重写要求', '报告标题', '当前一级标题', '章节目标',
    '内容边界', '当前二级标题', '二级写作重点', '建议检索 query', '检索目标',
)


def _graph_query_fields(query: str) -> dict:
    labels = '|'.join(re.escape(label) for label in _QUERY_LABELS)
    return dict(re.findall(
        rf'(?:^|\n)({labels})：([\s\S]*?)(?=\n(?:{labels})：|\Z)', query))


def _focus_graph_query(query: str) -> str:
    fields = _graph_query_fields(query)
    if not fields.get('当前二级标题', '').strip():
        return query
    # Local writing/rewrite requirements can change the requested segment, so
    # retain them; only the repeated global requirement and chapter boilerplate
    # are omitted from this node-selection prompt.
    keep = ('报告标题', '当前一级标题', '当前二级标题', '二级写作重点',
            '建议检索 query', '用户重写要求', '检索目标')
    return '\n'.join(f'{key}：{fields[key].strip()}' for key in keep
                     if fields.get(key, '').strip())


def _graph_candidate_focus(query: str) -> str:
    fields = _graph_query_fields(query)
    if not fields.get('当前二级标题', '').strip():
        return query
    return ' '.join(fields.get(key, '').strip() for key in (
        '当前二级标题', '二级写作重点', '建议检索 query', '用户重写要求')
        if fields.get(key, '').strip())


def _keyword_pairs(text: str) -> set:
    # Chinese pairs also match compound node names without a new tokenizer
    # dependency. Exclude generic report words that do not identify segments.
    generic = {'产业', '技术', '环节', '布局', '发展', '能力', '条件', '分析',
               '研究', '价值', '现状', '趋势', '路径', '关键', '相关', '央企', '智能'}
    pairs = set()
    text = text.replace('具身智能', '')
    for token in re.findall(r'[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9/+-]*', text.lower()):
        if re.fullmatch(r'[\u4e00-\u9fff]+', token):
            pairs.update(token[i:i + 2] for i in range(len(token) - 1))
        else:
            pairs.add(token)
    return pairs - generic


def _prefilter_terminal_rows(rows: List[str], focus: str) -> tuple:
    if len(rows) <= 15:
        return rows, 'full_small'
    terms = _keyword_pairs(focus)
    matches = []
    for index, row in enumerate(rows):
        path = row.split('路径: ', 1)[-1]
        leaf = path.split(' > ')[-1]
        leaf_hits = len(terms & _keyword_pairs(leaf))
        path_hits = len(terms & _keyword_pairs(path))
        # One short pair is too weak to exclude the rest of the graph.
        if path_hits >= 2:
            matches.append((leaf_hits, path_hits, index, row))
    if len(matches) < 3:
        return rows, 'full_fallback'
    matches.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in matches[:15]], 'keyword'


def _select_terminal_segments_with_llm(query: str, graph: _IndustryGraph, industry_name: str) -> dict:
    focused_query = _focus_graph_query(query)
    all_rows = graph.terminal_prompt_rows()
    candidate_rows, mode = _prefilter_terminal_rows(all_rows, _graph_candidate_focus(query))
    candidate_ids = {int(row.split(' | ', 1)[0].split(': ', 1)[1]) for row in candidate_rows}
    diagnostics = {'original_query_chars': len(query), 'focused_query_chars': len(focused_query),
                   'total_candidates': len(all_rows), 'sent_candidates': len(candidate_rows),
                   'candidate_mode': mode}

    def response(status, message, data=None):
        return {'status': status, 'message': message, 'data': data, 'diagnostics': diagnostics}
    system_prompt = (
        f"你是{industry_name}产业知识图谱检索助手。"
        "你只能从用户提供的末级环节清单中选择相关环节。"
        "必须只输出 JSON 数组，不要输出解释、Markdown 或代码块。"
        "为节省输出，只返回选中末级环节的数字 ID，不要返回名称、理由或分数。"
    )
    user_prompt = f"""请根据用户查询，从下面的{industry_name}产业末级环节清单中选择最相关的 1 到 3 个。

用户查询：
{focused_query}

选择要求：
1. 只能选择清单中真实存在的末级环节。
2. 输出数量必须是 1 到 3 个。
3. 输出数组中的每个值必须是清单中真实存在的数字 ID。
4. 不要输出名称、理由、分数或其他字段。

输出 JSON 示例：
[23, 31]

末级环节清单：
{chr(10).join(candidate_rows)}
"""
    try:
        content = llm.query(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=800,
            reasoning_effort=None,
            extra_body={"thinking": {"type": "disabled"}},
            extra_log_info=f"report_generation.graph_retriever query={query}",
        )
    except Exception as exc:
        return response('error', f'LLM 调用失败: {exc}')

    if not content:
        return response('error', 'LLM 返回为空')

    try:
        data = _parse_json_array(content)
    except ValueError as exc:
        return response('error', f'LLM 返回 JSON 解析失败: {exc}')

    if not isinstance(data, list) or not (1 <= len(data) <= 3):
        return response('error', 'LLM 返回的末级环节数量不合规，必须为 1 到 3 个')

    # Keep the historical object contract readable while accepting the compact
    # ID-only response used by the production prompt.
    if all(isinstance(item, (int, str)) for item in data):
        data = [
            {
                "id": item,
                "name": graph.node_name(_coerce_node_id(item)),
                "reason": "",
                "score": 1.0,
            }
            for item in data
        ]

    data = [item for item in data if isinstance(item, dict)
            and _coerce_node_id(item.get('id')) in candidate_ids]
    if not data:
        return response('error', 'LLM 未返回本次候选清单中的末级环节')
    return response('success', '', data)


def _validate_llm_terminal_selection(items: List[dict], graph: _IndustryGraph) -> List[dict]:
    selected = []
    seen_ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue

        if not all(key in item for key in ("id", "name", "reason", "score")):
            continue

        node_id = _coerce_node_id(item.get("id"))
        if node_id in seen_ids or node_id not in graph.terminal_segments:
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


def _build_context_text(chain_path: str, segment_name: str, entities: List[dict]) -> str:
    entity_names = [item["name"] for item in entities if item.get("name")]
    if entity_names:
        entity_text = "、".join(entity_names)
    else:
        entity_text = "未检索到参与该环节的企业/实体"

    return (
        f"产业链路径：{chain_path}。"
        "该路径来自图谱中的“从属于”关系。"
        f"参与 {segment_name} 环节的企业/实体包括：{entity_text}。"
        "以上企业/实体来自图谱中的“参与环节”关系。"
    )


def _build_graph_context_text(query: str, evidence_blocks: List[dict]) -> str:
    lines = [
        "【知识图谱上下文】",
        f"围绕查询“{query}”，知识图谱检索命中以下末级环节：",
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
        "message": message or "LLM 未能从末级环节清单中返回有效结果",
        "matched_segments": [],
        "evidence_blocks": [],
    }
