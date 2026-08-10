"""报告生成 Agent 共用的结构化输出解析工具。"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, List


def parse_json_object(text: str) -> dict:
    """从模型输出中提取单个 JSON 对象，兼容 Markdown 代码块和前后说明。"""
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("未找到 JSON 对象")
        cleaned = cleaned[start:end + 1]
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON 顶层必须是对象")
    return value


def clean_text(value: Any) -> str:
    """将任意标量清洗为去除首尾空白的文本。"""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def clean_text_list(value: Any) -> List[str]:
    """清洗字符串数组，丢弃空值并保持原顺序去重。"""
    if not isinstance(value, (list, tuple, set)):
        return []
    result: List[str] = []
    seen = set()
    for item in value:
        text = clean_text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def missing_text_fields(data: dict, fields: Iterable[str]) -> List[str]:
    """返回缺失或为空的必填文本字段。"""
    return [field for field in fields if not clean_text(data.get(field))]
