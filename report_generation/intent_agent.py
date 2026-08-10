"""报告意图理解 Agent。"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from llm_client import llm

from .industry_config import INDUSTRY_CONFIG
from .structured_output import clean_text, clean_text_list, missing_text_fields, parse_json_object


INTENT_TEXT_FIELDS = (
    "research_subject",
    "industry",
    "research_type",
    "research_scope",
    "core_question",
)
INTENT_LIST_FIELDS = (
    "focus_areas",
    "explicit_requirements",
    "forbidden_extensions",
)


def parse_report_intent(title: str, user_requirement: str = "") -> dict:
    """解析用户报告意图；格式异常时携带校验错误重试一次。"""
    original_title = str(title or "").strip()
    requirement = str(user_requirement or "").strip()
    if not original_title:
        return _error("title cannot be empty")

    validation_error = ""
    raw_output = ""
    for attempt in range(2):
        try:
            raw_output = llm.query(
                user_prompt=_build_user_prompt(original_title, requirement, validation_error),
                system_prompt=_build_system_prompt(),
                max_tokens=3000,
                extra_log_info=f"report_generation.intent_agent attempt={attempt + 1}",
            ) or ""
            intent = _normalize_intent(parse_json_object(raw_output), original_title)
            _validate_intent(intent)
            resolved = resolve_supported_industry(intent["industry"])
            return {
                "status": "success",
                "intent": intent,
                "resolved_industry": resolved.get("key", ""),
                "resolved_industry_name": resolved.get("name", ""),
                "warnings": [] if resolved else [{
                    "stage": "intent",
                    "code": "unsupported_intent_industry",
                    "message": f"识别到的行业“{intent['industry']}”暂未配置产业图谱，将继续进行无图谱规划。",
                }],
            }
        except Exception as exc:
            validation_error = str(exc)

    return _error(
        f"intent structured output failed after retry: {validation_error}",
        raw_output=raw_output,
    )


def resolve_supported_industry(industry_text: str) -> Dict[str, str]:
    """将模型识别的行业名称映射为系统行业键；不确定时不猜测。"""
    normalized = clean_text(industry_text).lower().replace("产业", "").replace("行业", "")
    if not normalized:
        return {}
    for key, config in INDUSTRY_CONFIG.items():
        name = clean_text(config.get("name"))
        candidates = {key.lower(), name.lower(), name.lower().replace("产业", "").replace("行业", "")}
        if normalized in candidates or any(candidate and candidate in normalized for candidate in candidates):
            return {"key": key, "name": name}
    return {}


def _normalize_intent(data: Any, original_title: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Intent 顶层必须是对象")
    intent = {"original_title": original_title}
    for field in INTENT_TEXT_FIELDS:
        intent[field] = clean_text(data.get(field))
    for field in INTENT_LIST_FIELDS:
        intent[field] = clean_text_list(data.get(field))
    return intent


def _validate_intent(intent: dict) -> None:
    missing = missing_text_fields(intent, INTENT_TEXT_FIELDS)
    if missing:
        raise ValueError(f"Intent 缺少必填字段: {', '.join(missing)}")
    for field in INTENT_LIST_FIELDS:
        if not isinstance(intent.get(field), list):
            raise ValueError(f"Intent 字段 {field} 必须是数组")


def _build_system_prompt() -> str:
    return """你是报告意图理解 Agent，只负责忠实解析用户意图并输出 JSON。
不得修改 original_title，不得因为任何既有报告模板改变研究意图。
如果用户只要求优势分析、布局分析或趋势分析，禁止擅自扩展为现状、问题、建议等其他任务。
可以对未明确的信息做保守推断，但不得改变用户明确的研究对象、范围和方向。
forbidden_extensions 应列出容易偏题且用户没有要求扩展的方向。
只输出一个 JSON 对象，不要输出 Markdown 或解释。"""


def _build_user_prompt(title: str, requirement: str, validation_error: str) -> str:
    retry = f"\n上次输出校验失败：{validation_error}\n请修正全部字段和类型。" if validation_error else ""
    return f"""请解析以下报告意图。
原始标题：{title}
补充需求：{requirement or '无'}

输出格式：
{{
  "original_title": {json.dumps(title, ensure_ascii=False)},
  "research_subject": "研究对象",
  "industry": "产业或研究领域",
  "research_type": "研究任务类型",
  "research_scope": "研究范围",
  "core_question": "报告最核心要回答的问题",
  "focus_areas": ["重点方向"],
  "explicit_requirements": ["用户明确要求"],
  "forbidden_extensions": ["不应擅自扩展的内容"]
}}{retry}"""


def _error(message: str, raw_output: Optional[str] = None) -> dict:
    result = {"status": "error", "stage": "intent", "message": message, "warnings": []}
    if raw_output:
        result["raw_output"] = raw_output
    return result
