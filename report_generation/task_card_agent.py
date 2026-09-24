"""Build an editable writing task card before report outline generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_client import llm

from .industry_config import INDUSTRY_CONFIG, resolve_supported_industry
from .structured_output import clean_text, clean_text_list, parse_json_object


TASK_CARD_MAX_ATTEMPTS = 2
REPORT_REQUIREMENT_MAX_ATTEMPTS = 2
REPORT_REQUIREMENT_MAX_TOKENS = 1000
REPORT_REQUIREMENT_MIN_CHARS = 220
REPORT_REQUIREMENT_MAX_CHARS = 450
REPORT_REQUIREMENT_FALLBACK_MESSAGE = "模型未返回完整报告需求，已生成可编辑基础需求，请确认后继续。"


def generate_writing_task_card(
    title: str,
    user_requirement: str = "",
    page_industry: str = "",
) -> dict:
    """
    Generate editable requirements and validate industry/graph matches.
    生成可编辑的写作任务需求卡片，并做行业、内容匹配校验。
    """
    original_title = clean_text(title)
    requirement = clean_text(user_requirement)
    normalized_page_industry = clean_text(page_industry)
    if not original_title:
        return _error("title cannot be empty")
    page_industry_match = resolve_supported_industry(normalized_page_industry)
    if normalized_page_industry and normalized_page_industry not in INDUSTRY_CONFIG:
        if not page_industry_match.get("key"):
            return _error(f"unsupported industry: {normalized_page_industry}")
        normalized_page_industry = page_industry_match["key"]

    # task card 是“大纲生成”前的人工确认层：先让模型整理，再允许前端编辑确认。
    validation_error = ""
    raw_output = ""
    # 结构化输出偶尔会缺字段或 JSON 格式不完整，失败后带上校验错误重试一次。
    task_card = None
    for attempt in range(TASK_CARD_MAX_ATTEMPTS):
        try:
            # 调用大模型生成任务卡 JSON 输出
            query_result = llm.query_result(
                user_prompt=_build_user_prompt(
                    original_title,
                    requirement,
                    normalized_page_industry,
                    validation_error,
                ),
                system_prompt=_build_system_prompt(),
                max_tokens=3000,
                extra_log_info=f"report_generation.task_card_agent attempt={attempt + 1}",
            )
            raw_output = clean_text(query_result.content)
            if query_result.error_message:
                raise ValueError("task card model request failed")
            # 解析 JSON 输出并做字段校验
            data = parse_json_object(raw_output)
            # 规范化任务卡数据结构
            task_card = _normalize_task_card(
                data,
                original_title=original_title,
                original_requirement=requirement,
                page_industry=normalized_page_industry,
            )
            break
        except Exception as exc:
            validation_error = str(exc)

    if task_card is None:
        return _error(
            f"task card structured output failed after retry: {validation_error}",
            raw_output=raw_output,
        )

    # 任务卡 JSON 已有效时，需求生成必须独立重试，不能因需求正文失败而重新生成或丢弃任务卡。
    requirement_result = generate_report_requirement(
        title=original_title,
        user_requirement=requirement,
        industry=task_card.get("selected_industry", ""),
        industry_name=task_card.get("selected_industry_name", ""),
    )
    if requirement_result.get("status") != "success":
        return requirement_result
    task_card["report_requirement"] = requirement_result["report_requirement"]
    task_card["report_requirement_source"] = requirement_result["source"]
    return {"status": "success", "task_card": task_card, "warnings": requirement_result["warnings"]}


def generate_report_requirement(
    title: str,
    user_requirement: str = "",
    industry: str = "",
    industry_name: str = "",
) -> dict:
    """Generate report_requirement from original title, original requirement, and industry."""
    # 先清洗外部传入文本，避免空白、None 或异常格式影响后续 prompt 拼接。
    normalized_title = clean_text(title)
    normalized_requirement = clean_text(user_requirement)
    normalized_industry = clean_text(industry)
    # 前端可能只传 industry key；展示名缺失时从系统行业配置里补齐。
    normalized_industry_name = clean_text(industry_name) or _industry_name(normalized_industry)
    # 标题和行业是生成可用报告需求的最低必要条件，缺失时直接返回结构化错误。
    if not normalized_title:
        return _error("title cannot be empty")
    if not normalized_industry:
        return _error("industry cannot be empty")
    # 只允许系统配置内的行业进入后续流程，防止模型或前端传入未知行业 key。
    if normalized_industry not in INDUSTRY_CONFIG:
        return _error(f"unsupported industry: {normalized_industry}")

    failure_reason = ""
    for attempt in range(REPORT_REQUIREMENT_MAX_ATTEMPTS):
        result = llm.query_result(
            user_prompt=_build_report_requirement_prompt(
                title=normalized_title,
                user_requirement=normalized_requirement,
                industry=normalized_industry,
                industry_name=normalized_industry_name,
                retry=attempt > 0,
            ),
            system_prompt=_build_report_requirement_system_prompt(),
            max_tokens=REPORT_REQUIREMENT_MAX_TOKENS,
            reasoning_effort=None,
            extra_body={"thinking": {"type": "disabled"}},
            extra_log_info=(
                "report_generation.task_card_agent generate_report_requirement "
                f"attempt={attempt + 1}"
            ),
        )
        report_requirement = clean_text(result.content)
        failure_reason = _requirement_failure_reason(result, report_requirement)
        if not failure_reason:
            return {
                "status": "success",
                "report_requirement": report_requirement,
                "industry": normalized_industry,
                "industry_name": normalized_industry_name,
                "source": "model" if attempt == 0 else "model_retry",
                "warnings": [],
            }

    # 两次模型尝试都未提供可用正文时，仍保留用户可编辑的确定性本地需求。
    return {
        "status": "success",
        "report_requirement": _fallback_report_requirement(
            normalized_title,
            normalized_requirement,
            normalized_industry_name,
        ),
        "industry": normalized_industry,
        "industry_name": normalized_industry_name,
        "source": "fallback",
        "warnings": [{
            "stage": "report_requirement",
            "code": "report_requirement_fallback",
            "reason": failure_reason,
            "message": REPORT_REQUIREMENT_FALLBACK_MESSAGE,
        }],
    }


def _requirement_failure_reason(result: Any, text: str) -> str:
    """Classify model output without treating a completed request as usable by default."""
    if clean_text(getattr(result, "error_message", "")):
        return "llm_request_failed"
    if clean_text(getattr(result, "finish_reason", "")).lower() == "length":
        return "truncated"
    if not text:
        return "empty_visible_content"
    if len(text) > REPORT_REQUIREMENT_MAX_CHARS:
        return "truncated"
    if len(text) < REPORT_REQUIREMENT_MIN_CHARS or text[-1] != "。":
        return "incomplete"
    return ""


def _fallback_report_requirement(title: str, user_requirement: str, industry_name: str) -> str:
    """Create an editable local requirement while preserving the user's stated priority."""
    primary_requirement = user_requirement or f"围绕《{title}》开展研究"
    return (
        f"围绕{industry_name}产业，{primary_requirement}。"
        "请明确研究对象、时间范围、核心分析维度和数据口径，"
        "不纳入用户未要求的延伸议题，并形成可直接用于后续大纲规划的报告需求。"
    )


def _normalize_task_card(
    data: Any,
    original_title: str,
    original_requirement: str,
    page_industry: str,
) -> dict:
    # 统一把模型输出整理成前端和后续 outline 接口稳定消费的字段。
    if not isinstance(data, dict):
        raise ValueError("task card 顶层必须是对象")

    recognized_industry = clean_text(data.get("recognized_industry"))
    # recognized_industry 是任务卡最小可用字段；report_requirement 由独立函数二次生成。
    if not recognized_industry:
        raise ValueError("task card 缺少 recognized_industry")

    # 参考标题只保留最多两个，并去掉与用户原始标题完全相同的选项。
    suggestions = []
    for suggestion in clean_text_list(data.get("suggested_titles")):
        if suggestion != original_title and suggestion not in suggestions:
            suggestions.append(suggestion)
    suggestions = suggestions[:2]

    # 先把模型识别出的自然语言产业名映射到系统产业 key，再合并模型候选和页面上下文。
    recognized_match = resolve_supported_industry(recognized_industry)
    candidate_reasons = _normalize_candidate_reasons(data.get("industry_candidates"))
    model_candidates = list(candidate_reasons.keys())
    ranked_keys: List[str] = []
    for key in [recognized_match.get("key", ""), *model_candidates, page_industry]:
        if key in INDUSTRY_CONFIG and key not in ranked_keys:
            ranked_keys.append(key)
    # 其余系统支持产业也放进下拉框，方便用户手动纠偏。
    for key in INDUSTRY_CONFIG:
        if key not in ranked_keys:
            ranked_keys.append(key)

    # industry_matches 是前端“最终产业方向”下拉框的数据源。
    industry_matches = []
    for key in ranked_keys:
        config = INDUSTRY_CONFIG[key]
        # 图谱文件是否存在决定后续是否能走该产业的知识图谱增强。
        graph_available = Path(config.get("graph_path", "")).is_file()
        external_rag_available = _external_rag_available(config)
        source = "recognized" if key == recognized_match.get("key") else "candidate"
        if key == page_industry and source != "recognized":
            source = "page"
        industry_matches.append({
            "key": key,
            "name": clean_text(config.get("name")),
            "source": source,
            "reason": candidate_reasons.get(key, ""),
            "graph_available": graph_available,
            "graph_status": "matched" if graph_available else "unavailable",
            "external_rag_available": external_rag_available,
            "external_rag_status": "matched" if external_rag_available else "unavailable",
        })

    selected_industry = recognized_match.get("key", "")
    selection_source = "recognized" if selected_industry else ""
    # 默认优先相信标题/需求识别结果；识别不到系统产业时，再回退到当前页面产业。
    if not selected_industry and page_industry in INDUSTRY_CONFIG:
        selected_industry = page_industry
        selection_source = "page"

    selected_match = next(
        (item for item in industry_matches if item["key"] == selected_industry),
        None,
    )
    graph_available = bool(selected_match and selected_match["graph_available"])
    external_rag_available = bool(selected_match and selected_match["external_rag_available"])
    # graph_match 给前端展示图谱匹配状态，也给后续流程判断是否能启用图谱增强。
    # 返回的 task_card 会被前端保存到历史记录，并原样传给 outline 阶段。
    return {
        "original_title": original_title,
        "original_requirement": original_requirement,
        "selected_title": original_title,
        "suggested_titles": suggestions,
        "report_requirement": "",
        "page_industry": page_industry,
        "page_industry_name": _industry_name(page_industry),
        "recognized_industry": recognized_industry,
        "recognized_industry_key": recognized_match.get("key", ""),
        "industry_matches": industry_matches,
        "selected_industry": selected_industry,
        "selected_industry_name": _industry_name(selected_industry),
        "selection_source": selection_source or "none",
        "use_graph": graph_available,
        "use_external_rag": external_rag_available,
        "industry_conflict": bool(
            recognized_match.get("key")
            and page_industry in INDUSTRY_CONFIG
            and recognized_match.get("key") != page_industry
        ),
        "graph_match": {
            "status": "matched" if graph_available else "unavailable",
            "industry": selected_industry,
            "industry_name": _industry_name(selected_industry),
            "graph_available": graph_available,
            "message": (
                "已匹配可用产业图谱，将用于辅助报告生成。"
                if graph_available
                else "未匹配到可用产业图谱，将使用已有资料和大模型能力继续生成。"
            ),
        },
        "external_rag_match": {
            "status": "matched" if external_rag_available else "unavailable",
            "industry": selected_industry,
            "industry_name": _industry_name(selected_industry),
            "external_rag_available": external_rag_available,
            "message": (
                "已匹配可用外部资料库，后续生成将调用该资料库。"
                if external_rag_available
                else "未匹配到可用外部资料库，后续生成不会调用外部资料库。"
            ),
        },
    }


def _external_rag_available(config: dict) -> bool:
    """Return whether an industry has a configured source and local Chroma store."""
    if not clean_text(config.get("external_column_id")):
        return False
    vector_db_path = config.get("vector_db_path")
    if not vector_db_path:
        return False
    return (Path(vector_db_path) / "chroma.sqlite3").is_file()


def _normalize_candidate_keys(value: Any) -> List[str]:
    """兼容只返回 key 列表的旧模型输出。"""
    if not isinstance(value, list):
        return []
    keys = []
    for item in value:
        candidate = item.get("key") if isinstance(item, dict) else item
        key = clean_text(candidate)
        if key in INDUSTRY_CONFIG and key not in keys:
            keys.append(key)
    return keys


def _normalize_candidate_reasons(value: Any) -> Dict[str, str]:
    """提取模型给出的产业候选 key 及识别依据，供前端展示。"""
    if not isinstance(value, list):
        return {}
    reasons: Dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        key = clean_text(item.get("key"))
        if key in INDUSTRY_CONFIG and key not in reasons:
            reasons[key] = clean_text(item.get("reason"))
    return reasons


def _industry_name(industry: str) -> str:
    """根据系统产业 key 返回展示名；无效 key 返回空字符串。"""
    config = INDUSTRY_CONFIG.get(clean_text(industry)) or {}
    return clean_text(config.get("name"))


def _build_system_prompt() -> str:
    # 这里控制任务卡质量：需求边界、参考标题风格、产业识别依据都由该提示词约束。
    return """你是企业产业洞察报告的写作任务确认助手。你只负责根据用户原始标题和需求生成写作任务卡 JSON。
参考标题给出 2 个，要符合企业产业洞察报告风格：严谨、克制、问题导向或趋势研判导向，避免学生论文式和模板化标题。
参考标题不得使用夸张营销词。
两个参考标题应有明显差异，一个偏趋势/变量研判，一个偏产业链/竞争格局/生态结构。
产业候选只能从给定的系统产业键中选择，并按相关性排序；当前页面产业仅是弱上下文，不能覆盖标题和需求中的明确产业。
industry_candidates 的 reason 要简明说明识别依据，优先引用标题和需求中的明确词。
只输出一个 JSON 对象，不要输出 Markdown 或解释。"""


def _build_user_prompt(
    title: str,
    requirement: str,
    page_industry: str,
    validation_error: str,
) -> str:
    """
    构造生成任务卡片的用户提示词
    - 将页面传入产业作为弱参考，识别优先以用户标题、需求为准
    - 重试时带上上一轮校验错误，指导模型修正输出
    """
    # 获取系统全部合法产业列表，转为字符串给大模型参考，防止编造key
    supported = [
        {"key": key, "name": clean_text(config.get("name"))}
        for key, config in INDUSTRY_CONFIG.items()
    ]
    supported_text = json.dumps(supported, ensure_ascii=False)

    # 重试场景：拼接上一轮校验报错信息
    retry_block = ""
    if validation_error:
        retry_block = f"\n上次输出校验失败：{validation_error}\n请修正全部字段与类型。"

    prompt = f"""请生成报告写作任务卡。
            原始标题：{title}
            用户原始需求：{requirement or '无补充需求'}
            当前页面产业键：{page_industry or '无'}
            系统支持产业：{supported_text}

输出JSON格式(保留全部key，不要原样复制模板中的占位文字，所有value全部替换为本次任务的真实结果)：
{{
  "suggested_titles": ["参考标题1", "参考标题2"],
  "recognized_industry": "根据标题和需求识别的产业方向",
  "industry_candidates": [
    {{"key": "系统支持产业键", "reason": "匹配原因"}}
  ]
}}{retry_block}"""

    return prompt


def _build_report_requirement_system_prompt() -> str:
    # system prompt 负责限定角色、优先级和输出形态，防止模型额外输出标题或解释
    return """你是企业产业洞察报告的写作任务生成助手，只负责生成 report_requirement。

【输出硬约束】
1. 只输出一段正文，字数严格控制在 220 至450 个中文字符，最后一个字符必须是“。”。
2. 只输出正文本身，不要输出 JSON、Markdown、标题、序号、解释说明或任何额外内容。

【内容规则】
report_requirement 要写成一段完整、明确、可直接用于后续大纲规划的写作需求，包含研究对象、核心问题、最多四个或者五个重点分析维度、边界排除和输出口径。
1. 必须忠实保留用户明确的研究对象、范围、重点、篇幅和禁止扩展项，可补足表达但不得擅自增加任务。
2. 报告需求需包含：研究对象、核心问题、最多 4个或者5个重点分析维度、边界排除、输出口径。
3. 分析维度之间相互独立、不交叉。
4. 用户明确排除的内容，不得作为分析维度、佐证案例、背景铺垫或延伸议题，完全不纳入研究范围。
5. 如果用户没有给出额外需求，则依据原始标题自动推导合理的研究任务，生成完整 report_requirement，禁止直接填写“无补充需求”作为任务书内容。

【优先级规则】
生成依据重要程度：用户原始需求 > 产业方向 > 用户原始标题。
产业方向必须进入报告需求，作为后续大纲规划、产业图谱和资料检索的产业上下文。
当用户需求与产业方向存在范围差异时，以用户需求为核心研究边界，产业方向仅作为行业背景和数据口径，不得扩展至全产业。
如用户原始需求与产业方向存在张力，应以用户原始需求为准，并围绕产业方向建立合理研究边界。

【风格要求】
符合企业产业洞察报告风格：严谨、克制、陈述客观、问题导向。避免学生论文式、模板化和夸张营销表述。
报告需求要符合企业产业洞察报告风格：严谨、克制、问题导向或趋势研判导向，

【输出前自检】
1. 字数是否在 220-450 字之间；
2. 最后一个字符是否为“。”；
3. 是否只输出了正文，无标题、序号、解释；
4. 是否未超出用户原始需求范围；
5. 分析维度是否不超过 5 个且互不重叠。"""

def _build_report_requirement_prompt(
    title: str,
    user_requirement: str,
    industry: str,
    industry_name: str,
    retry: bool = False,
) -> str:
    # user prompt 只传递本次任务的变量信息，具体写作规则由 system prompt 统一约束。
    retry_instruction = ""
    if retry:
        retry_instruction = "\n上次正文为空或不完整。请直接输出一段完整正文，务必以“。”结束。"
    return f"""请根据以下信息生成报告需求。
用户原始需求：{user_requirement or '无补充需求'}
产业方向：{industry_name}（系统产业键：{industry}）
用户原始标题：{title}

请严格按“用户原始需求 > 产业方向 > 用户原始标题”的优先级生成。{retry_instruction}"""



def _error(message: str, raw_output: Optional[str] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": "error",
        "stage": "task_card",
        "message": message,
        "warnings": [],
    }
    if raw_output:
        result["raw_output"] = raw_output
    return result
