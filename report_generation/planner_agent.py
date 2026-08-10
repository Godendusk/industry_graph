"""报告研究规划 Agent。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from llm_client import llm

from .industry_config import INDUSTRY_CONFIG
from .structured_output import clean_text, clean_text_list, parse_json_object


MIN_CHAPTERS = 3
MAX_CHAPTERS = 6


def plan_report(intent: dict, resolved_industry: str = "") -> dict:
    """仅依据 Intent 规划研究问题和章节，格式异常时重试一次。"""
    if not isinstance(intent, dict) or not clean_text(intent.get("original_title")):
        return _error("validated intent is required")

    validation_error = ""
    raw_output = ""
    for attempt in range(2):
        try:
            raw_output = llm.query(
                user_prompt=_build_user_prompt(intent, validation_error),
                system_prompt=_build_system_prompt(),
                max_tokens=5000,
                extra_log_info=f"report_generation.planner_agent attempt={attempt + 1}",
            ) or ""
            planner = _normalize_planner(parse_json_object(raw_output))
            _validate_planner(planner, intent)
            graph_available = _graph_available(resolved_industry)
            warnings = []
            if planner["need_industry_graph"] and not graph_available:
                warnings.append({
                    "stage": "planner",
                    "code": "industry_graph_unavailable",
                    "message": "规划建议使用产业图谱，但当前行业没有可用图谱；将继续生成报告。",
                })
            planner["industry_graph_available"] = graph_available
            if not planner["need_industry_graph"]:
                planner["industry_graph_topic"] = ""
            return {"status": "success", "planner": planner, "warnings": warnings}
        except Exception as exc:
            validation_error = str(exc)

    return _error(
        f"planner structured output failed after retry: {validation_error}",
        raw_output=raw_output,
    )


def _normalize_planner(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Planner 顶层必须是对象")
    chapters = []
    for item in data.get("chapters") or []:
        if not isinstance(item, dict):
            continue
        chapters.append({
            "title": clean_text(item.get("title")),
            "research_question": clean_text(item.get("research_question")),
            "content_requirements": clean_text_list(item.get("content_requirements")),
            "evidence_requirements": clean_text_list(item.get("evidence_requirements")),
        })
    return {
        "report_goal": clean_text(data.get("report_goal")),
        "research_questions": clean_text_list(data.get("research_questions")),
        "chapters": chapters,
        "data_requirements": clean_text_list(data.get("data_requirements")),
        "need_industry_graph": data.get("need_industry_graph") is True,
        "industry_graph_topic": clean_text(data.get("industry_graph_topic")),
    }


def _validate_planner(planner: dict, intent: dict) -> None:
    if not planner["report_goal"]:
        raise ValueError("Planner 缺少 report_goal")
    questions = planner["research_questions"]
    chapters = planner["chapters"]
    if not MIN_CHAPTERS <= len(questions) <= MAX_CHAPTERS:
        raise ValueError(f"research_questions 必须为 {MIN_CHAPTERS} 到 {MAX_CHAPTERS} 个")
    if not MIN_CHAPTERS <= len(chapters) <= MAX_CHAPTERS:
        raise ValueError(f"chapters 必须为 {MIN_CHAPTERS} 到 {MAX_CHAPTERS} 章")
    for index, chapter in enumerate(chapters, 1):
        missing = [field for field in ("title", "research_question") if not chapter[field]]
        if missing or not chapter["content_requirements"] or not chapter["evidence_requirements"]:
            raise ValueError(f"第 {index} 章字段不完整")
    forbidden = [item for item in clean_text_list(intent.get("forbidden_extensions")) if item]
    chapter_text = json.dumps(chapters, ensure_ascii=False)
    if any(item in chapter_text for item in forbidden):
        raise ValueError("Planner 章节包含 Intent 明确禁止扩展的内容")


def _graph_available(industry: str) -> bool:
    config = INDUSTRY_CONFIG.get(clean_text(industry))
    return bool(config and Path(config.get("graph_path", "")).is_file())


def _build_system_prompt() -> str:
    return f"""你是报告规划 Planner，只能依据输入的 Intent JSON 进行规划，不得重新解释或改写原始标题。
围绕 research_type 和 core_question 先拆解 {MIN_CHAPTERS}～{MAX_CHAPTERS} 个核心研究问题，再形成 {MIN_CHAPTERS}～{MAX_CHAPTERS} 个逻辑清晰的章节。
每章必须回答一个明确问题，并给出内容要求以及数据、案例、事实等证据要求。
严格遵守 research_scope、explicit_requirements 和 forbidden_extensions，不得擅自扩大研究范围。
根据研究任务判断产业图谱是否有帮助；图谱不是规划成功的必要条件。
只输出一个 JSON 对象，不要输出 Markdown 或解释。"""


def _build_user_prompt(intent: dict, validation_error: str) -> str:
    retry = f"\n上次输出校验失败：{validation_error}\n请修正数量、字段和类型。" if validation_error else ""
    return f"""请仅根据以下 Intent JSON 制定报告规划：
{json.dumps(intent, ensure_ascii=False, indent=2)}

输出格式：
{{
  "report_goal": "报告目标",
  "research_questions": ["核心研究问题"],
  "chapters": [
    {{
      "title": "章节标题",
      "research_question": "本章回答的问题",
      "content_requirements": ["内容要求"],
      "evidence_requirements": ["证据要求"]
    }}
  ],
  "data_requirements": ["全局数据要求"],
  "need_industry_graph": false,
  "industry_graph_topic": "需要检索的图谱主题；不需要时为空字符串"
}}{retry}"""


def _error(message: str, raw_output: Optional[str] = None) -> dict:
    result = {"status": "error", "stage": "planner", "message": message, "warnings": []}
    if raw_output:
        result["raw_output"] = raw_output
    return result
