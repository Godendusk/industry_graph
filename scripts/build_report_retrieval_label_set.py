"""Deterministic balanced allocation for human report-retrieval labeling."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Iterable

def allocate_library_samples(libraries: Iterable[str], total: int) -> dict[str, int]:
    values = sorted(set(libraries))
    if not values or type(total) is not int or total <= 0 or total % len(values):
        raise ValueError("total must divide the nonempty library set")
    return {library: total // len(values) for library in values}

def build_label_rows(materials: Iterable[dict], total: int = 60) -> list[dict]:
    grouped = {}
    for material in materials:
        library, material_id = material.get("library"), material.get("id")
        if isinstance(library, str) and isinstance(material_id, str) and material_id:
            grouped.setdefault(library, []).append(material)
    allocation = allocate_library_samples(grouped, total)
    rows = []
    for library in sorted(allocation):
        choices = sorted(grouped[library], key=lambda row: str(row["id"]))[:allocation[library]]
        if len(choices) != allocation[library]: raise ValueError(f"insufficient materials for {library}")
        for index, material in enumerate(choices, 1):
            title = str(material.get("title") or material["id"])
            rows.append({"query_id": f"{library}-{index:03d}", "query": title, "intent": "exact",
                         "preferred_libraries": [library], "relevant_material_ids": [material["id"]],
                         "review_status": "needs_human_review"})
    return rows

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--manifest-dir", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--total", type=int, default=60)
    args = parser.parse_args(); materials = []
    for path in sorted(args.manifest_dir.glob("*_manifest.json")):
        data = json.loads(path.read_text(encoding="utf-8")); materials.extend(data if isinstance(data, list) else data.get("materials", []))
    rows = build_label_rows(materials, args.total); args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return 0

if __name__ == "__main__": raise SystemExit(main())
