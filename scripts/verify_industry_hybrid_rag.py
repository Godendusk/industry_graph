"""Verify real hybrid recall and optional coordinator writing tasks per industry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import monotonic

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from report_generation.industry_config import INDUSTRY_CONFIG, PROJECT_ROOT
from report_generation.external_rag.retriever import retrieve_external_rag

QUERIES = {
    "ai": "人工智能产业发展 政策支持 大模型应用",
    "embodied": "具身智能 人形机器人 产业发展",
    "low_altitude": "低空经济 无人机 空域管理",
    "sea": "海洋经济 海洋装备 海上风电",
    "quantum": "量子科技 量子计算 量子通信",
    "biology": "生物制造 合成生物 发酵",
    "brain": "脑机接口 神经信号 临床应用",
    "material": "新材料 全固态电池 材料创新",
}


def verify(industry, writing_tasks=False):
    started = monotonic()
    retrieval = retrieve_external_rag(QUERIES[industry], 3, industry)
    blocks = retrieval.get("evidence_blocks") or []
    stages = retrieval.get("diagnostics", {})
    counts = stages.get("candidate_counts")
    if counts is None:
        counts = next((attempt["candidate_counts"] for attempt in stages.get("attempts", [])
                       if attempt.get("status") == "success"), {})
    checks = {
        "full_hybrid": retrieval.get("retrieval_version") == "hybrid_v2" and not retrieval.get("retrieval_fallback"),
        "both_recall_routes": counts.get("dense", 0) > 0 and counts.get("lexical", 0) > 0,
        "real_rerank": bool(blocks) and all("rerank_score" in block for block in blocks),
        "industry_isolated": bool(blocks) and all(block.get("industry") == industry for block in blocks),
        "evidence_with_source": bool(blocks) and all(block.get("text") and block.get("title")
                                                    and block.get("source_address") for block in blocks),
    }
    result = {"industry": industry, "checks": checks, "retrieval": retrieval}
    if writing_tasks and all(checks.values()):
        from report_generation.citations import register_evidence_blocks
        from report_generation.coordinator_agent import _build_writing_task_from_retrieval
        from report_generation.external_rag.report_adapter import build_rag_context_text

        mapped, references = register_evidence_blocks(blocks, [])
        retrieval["evidence_blocks"] = mapped
        retrieval["rag_context_text"] = build_rag_context_text(mapped)
        name = INDUSTRY_CONFIG[industry]["name"]
        subsection = {"outline_id": "S1.1", "parent_level1_id": "S1", "parent_level1_title": "产业现状",
                      "title": "发展情况"}
        task, warnings = _build_writing_task_from_retrieval(
            subsection, {"status": "skipped", "graph_context_text": ""}, retrieval,
            "根据已检索的资料生成当前小节的简短写作任务，使用资料引用编号。", name + "产业报告", [],
        )
        checks["writing_context_and_citations"] = (
            bool(task.get("writing_system_prompt")) and "[C1]" in retrieval["rag_context_text"]
            and any("C1" in use.get("citation_ids", [])
                    for use in task.get("writing_decision", {}).get("evidence_uses", []))
            and task.get("writing_prompt_status") == "generated"
            and bool(references) and not warnings
        )
        result.update(writing_task=task, references=references)
    result.update(status="success" if all(checks.values()) else "failed",
                  elapsed_seconds=round(monotonic() - started, 2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--industry", choices=["all", *INDUSTRY_CONFIG], default="all")
    parser.add_argument("--writing-tasks", action="store_true", help="Call the configured LLM for a small writing task")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "report_generation" / "outputs" / "industry_hybrid_acceptance.json")
    args = parser.parse_args()
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for industry in INDUSTRY_CONFIG if args.industry == "all" else [args.industry]:
        try:
            result = verify(industry, args.writing_tasks)
        except Exception as error:
            result = {"industry": industry, "status": "failed", "message": str(error)}
        results.append(result)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key not in {
            "retrieval", "writing_task", "references"}}, ensure_ascii=False), flush=True)
    return int(any(result["status"] != "success" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
