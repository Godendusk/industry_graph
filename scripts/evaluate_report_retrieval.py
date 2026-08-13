"""Offline ranking metrics; evaluation datasets require human approval by default."""
from __future__ import annotations
import math
import argparse
import json
from pathlib import Path
from typing import Iterable

def evaluate_ranked_materials(ranked_ids: Iterable[str], relevant_ids: set[str], k: int) -> dict[str, float]:
    ranked, relevant = list(ranked_ids)[:k], set(relevant_ids)
    hits = [index for index, item in enumerate(ranked, 1) if item in relevant]
    recall = len(set(ranked) & relevant) / len(relevant) if relevant else 0.0
    mrr = 1.0 / hits[0] if hits else 0.0
    dcg = sum(1.0 / math.log2(index + 1) for index in hits)
    ideal = sum(1.0 / math.log2(index + 1) for index in range(1, min(k, len(relevant)) + 1))
    return {"recall_at_k": recall, "mrr": mrr, "ndcg_at_k": dcg / ideal if ideal else 0.0}

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--dataset", type=Path, required=True); parser.add_argument("--allow-unreviewed", action="store_true")
    args = parser.parse_args(); rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not args.allow_unreviewed and any(row.get("review_status") != "approved" for row in rows):
        parser.error("dataset contains rows not approved by human review; use --allow-unreviewed only for diagnostics")
    print(json.dumps({"rows": len(rows), "reviewed": all(row.get("review_status") == "approved" for row in rows)})); return 0

if __name__ == "__main__": raise SystemExit(main())
