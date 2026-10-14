"""Build/check local news lexical indexes without touching Chroma vectors."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from time import monotonic

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from report_generation.industry_config import INDUSTRY_CONFIG
from report_generation.external_rag.news_index import build_news_index, check_news_index


def main():
    industries = [key for key, config in INDUSTRY_CONFIG.items() if config.get("rag_type") == "news"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--industry", choices=["all", *industries], required=True)
    parser.add_argument("--action", choices=["check", "build", "resume", "sync"], default="check")
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()
    failed = False
    last_progress = [0.0]

    def progress(row):
        if monotonic() - last_progress[0] >= 25:
            print(json.dumps(row, ensure_ascii=False), flush=True)
            last_progress[0] = monotonic()

    for industry in industries if args.industry == "all" else [args.industry]:
        try:
            result = (check_news_index(industry) if args.action == "check" else
                      build_news_index(industry, action=args.action, batch_size=args.batch_size,
                                       workers=args.workers, progress=progress))
        except Exception as error:
            result = {"industry": industry, "status": "error", "message": str(error)}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        failed |= result["status"] not in {"ready", "success"}
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
