"""Explicit, operator-invoked model provisioning command."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding", required=True)
    parser.add_argument("--reranker", required=True)
    parser.add_argument("--target-root", required=True, type=Path)
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    args.target_root.mkdir(parents=True, exist_ok=True)
    for name, repository in (("embedding", args.embedding), ("reranker", args.reranker)):
        path = snapshot_download(repo_id=repository, local_dir=str(args.target_root / repository.rsplit("/", 1)[-1]))
        print(f"{name}={Path(path).resolve()}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
