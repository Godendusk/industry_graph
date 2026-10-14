"""Build or inspect the versioned external-report hybrid index.

The module is deliberately offline: legacy Chroma is read locally and payload
mode reads files supplied by an operator.  Model provisioning is a separate
explicit command.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
from collections import defaultdict
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Optional

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from report_generation.external_rag.client import EXTERNAL_LIBRARIES
from report_generation.external_rag.text_utils import html_to_structured_blocks, normalize_text
from retrieval_core.chunker import build_report_chunks

MAX_METADATA_TITLE_CHARS = 120
_WORKER_MODELS = None


def _encode_material(arguments):
    global _WORKER_MODELS
    path, texts = arguments
    if _WORKER_MODELS is None:
        from retrieval_core.model_manager import ModelManager

        _WORKER_MODELS = ModelManager(Path(path), preferred_device="cpu")
    return _WORKER_MODELS.embed_documents(texts)


def _encoded_materials(materials, path, workers):
    if workers == 1:
        for chunks, material_id in materials:
            yield chunks, material_id, None
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = deque()
        remaining = iter(materials)
        while True:
            while len(pending) < workers * 2:
                try:
                    chunks, material_id = next(remaining)
                except StopIteration:
                    break
                future = pool.submit(_encode_material, (str(path), [chunk.embedding_text for chunk in chunks]))
                pending.append((chunks, material_id, future))
            if not pending:
                break
            chunks, material_id, future = pending.popleft()
            yield chunks, material_id, future.result()


class SQLiteReportClient:
    """Export source text without loading a legacy HNSW binary index."""

    def __init__(self, path: Path):
        self.path = path

    def get_collection(self, name):
        path = self.path

        class Collection:
            def get(self, include):
                documents, metadatas = [], []
                with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                    connection.row_factory = sqlite3.Row
                    connection.execute("BEGIN")
                    segment = connection.execute(
                        "SELECT s.id FROM segments s JOIN collections c ON c.id=s.collection "
                        "WHERE c.name=? AND s.scope='METADATA'", (name,),
                    ).fetchone()
                    if segment is None:
                        raise ValueError(f"missing report collection: {name}")
                    after = 0
                    while True:
                        rows = connection.execute(
                            "SELECT id FROM embeddings WHERE segment_id=? AND id>? ORDER BY id LIMIT 2000",
                            (segment[0], after),
                        ).fetchall()
                        if not rows:
                            break
                        upper = rows[-1][0]
                        payloads = {row[0]: {} for row in rows}
                        for row in connection.execute(
                            "SELECT m.* FROM embedding_metadata m JOIN embeddings e ON e.id=m.id "
                            "WHERE e.segment_id=? AND e.id>? AND e.id<=?", (segment[0], after, upper),
                        ):
                            payloads[row["id"]][row["key"]] = next((row[key] for key in (
                                "string_value", "int_value", "float_value", "bool_value") if row[key] is not None), None)
                        for payload in payloads.values():
                            documents.append(payload.pop("chroma:document", ""))
                            metadatas.append(payload)
                        after = upper
                return {"documents": documents, "metadatas": metadatas}

        return Collection()


def _bounded_metadata_title(value: object, fallback: str) -> str:
    """Keep malformed full-article titles out of the chunk embedding prefix."""
    title = normalize_text(value) or fallback
    if len(title) <= MAX_METADATA_TITLE_CHARS:
        return title
    return title[: MAX_METADATA_TITLE_CHARS - 1].rstrip() + "…"


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile))]


def _legacy_materials(legacy_client: Any) -> list[tuple[str, str, str, dict[str, Any], list[dict[str, str]]]]:
    grouped: dict[tuple[str, str], list[tuple[int, str, dict[str, Any]]]] = defaultdict(list)
    for library, config in EXTERNAL_LIBRARIES.items():
        response = legacy_client.get_collection(config["collection"]).get(include=["documents", "metadatas"])
        documents, metadatas = response.get("documents", ()), response.get("metadatas", ())
        if not isinstance(documents, list) or not isinstance(metadatas, list) or len(documents) != len(metadatas):
            raise ValueError(f"legacy collection {library} has invalid rows")
        for position, (document, metadata) in enumerate(zip(documents, metadatas)):
            if not isinstance(metadata, Mapping):
                raise ValueError("legacy metadata must be mappings")
            material_id = normalize_text(metadata.get("material_id"))
            text = normalize_text(document)
            if not material_id or not text:
                continue
            index = metadata.get("paragraph_index", position)
            if type(index) is not int or index < 0:
                raise ValueError("legacy paragraph_index must be a nonnegative integer")
            grouped[(library, material_id)].append((index, text, dict(metadata)))
    materials = []
    for (library, material_id), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row[0])
        title = _bounded_metadata_title(rows[0][2].get("title"), material_id)
        metadata = dict(rows[0][2])
        metadata.update({"library": library, "material_id": material_id, "title": title,
                         "classification_name": EXTERNAL_LIBRARIES[library]["classification_name"]})
        blocks = [{"kind": "paragraph", "text": text} for _, text, _ in rows]
        materials.append((library, material_id, title, metadata, blocks))
    return materials


def build_from_legacy(*, legacy_client: Any, writer: Any = None, tokenizer: Any,
                      dry_run: bool, embedding_model_path: Optional[Path] = None,
                      build_report_path: Optional[Path] = None, embedding_workers: int = 1,
                      resume: bool = False) -> dict[str, Any]:
    """Group old paragraph rows, construct v2 chunks, and optionally write them."""
    materials = _legacy_materials(legacy_client)
    built = []
    token_counts: list[int] = []
    for library, material_id, title, metadata, blocks in materials:
        chunks = build_report_chunks(blocks, library, material_id, title, metadata, tokenizer)
        built.append((chunks, material_id))
        token_counts.extend(chunk.token_count for chunk in chunks)
    report: dict[str, Any] = {"source": "legacy_chroma", "status": "dry_run" if dry_run else "pending",
                              "libraries": sorted({library for library, *_ in materials}),
                              "materials": len(materials),
                              "chunks": {"count": len(token_counts), "p50_tokens": _percentile(token_counts, .5), "p95_tokens": _percentile(token_counts, .95)}}
    if dry_run:
        return report
    if writer is None or embedding_model_path is None or not Path(embedding_model_path).is_dir():
        report.update(status="error", error="local_embedding_model_missing")
        return report
    skipped = 0
    expected_documents = {chunks[0].document_id for chunks, _ in built}
    if resume:
        state = writer._load_state()
        pending = []
        for chunks, material_id in built:
            entry = state["documents"].get(chunks[0].document_id, {})
            expected = {chunk.chunk_id for chunk in chunks}
            if (entry.get("state") == "success" and set(entry.get("expected_ids", ())) == expected
                    and entry.get("model_version") == writer.model_version
                    and entry.get("chunker_version") == writer.chunker_version
                    and entry.get("dictionary_version") == writer.dictionary_version
                    and writer.lexical.ids_for_document(chunks[0].document_id) == expected
                    and writer.dense.ids_for_document(chunks[0].document_id) == expected):
                skipped += 1
            else:
                pending.append((chunks, material_id))
        built = pending
        print(json.dumps({"industry": "ai", "materials_resumed": skipped}, ensure_ascii=False), flush=True)
    report["materials_resumed"] = skipped
    for position, (chunks, material_id, vectors) in enumerate(_encoded_materials(built, embedding_model_path, embedding_workers), 1):
        result = (writer.upsert_document(chunks[0].document_id, chunks) if vectors is None else
                  writer.upsert_document(chunks[0].document_id, chunks, embeddings=vectors))
        if getattr(result, "status", None) != "success":
            report.update(status="error", error="index_write_incomplete", material_id=material_id)
            return report
        if position % 25 == 0:
            print(json.dumps({"industry": "ai", "materials_done": position,
                              "materials_total": len(built)}, ensure_ascii=False), flush=True)
    try:
        for document_id in set(writer._load_state()["documents"]) - expected_documents:
            if writer.delete_document(document_id).status != "success":
                raise RuntimeError("stale report document could not be removed")
        writer.mark_ready()
    except Exception as error:
        report.update(status="error", error=f"ready_publish_failed:{type(error).__name__}")
        return report
    report["status"] = "success"
    if build_report_path is not None:
        path = Path(build_report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return report


def build_from_payload_directory(*, payload_dir: Path, writer: Any = None, tokenizer: Any,
                                 dry_run: bool, embedding_model_path: Optional[Path] = None,
                                 build_report_path: Optional[Path] = None, embedding_workers: int = 1,
                                 resume: bool = False) -> dict[str, Any]:
    """Build from operator-saved API JSON; HTML is converted with table support."""
    root = Path(payload_dir)
    if not root.is_dir():
        raise ValueError("payload_dir must be an existing directory")
    class PayloadClient:
        def __init__(self, rows): self.rows = rows
        def get_collection(self, name):
            library = next(key for key, value in EXTERNAL_LIBRARIES.items() if value["collection"] == name)
            rows = [row for row in self.rows if row["library"] == library]
            return type("Collection", (), {"get": lambda _, include: {"documents": [row["content"] for row in rows], "metadatas": [row for row in rows]}})()
    rows = []
    for path in sorted(root.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads = payload if isinstance(payload, list) else [payload]
        for item in payloads:
            if not isinstance(item, Mapping): raise ValueError("payload JSON rows must be objects")
            library, material_id = normalize_text(item.get("library")), normalize_text(item.get("material_id") or item.get("id"))
            content = item.get("contentWithTag", item.get("content", item.get("html", "")))
            blocks = html_to_structured_blocks(content)
            text = "\n".join(normalize_text(block.get("text")) for block in blocks)
            if library not in EXTERNAL_LIBRARIES or not material_id or not text: raise ValueError("payload row requires library, material_id, and content")
            rows.append({**dict(item), "library": library, "material_id": material_id, "content": text})
    return build_from_legacy(legacy_client=PayloadClient(rows), writer=writer, tokenizer=tokenizer,
                             dry_run=dry_run, embedding_model_path=embedding_model_path,
                             build_report_path=build_report_path, embedding_workers=embedding_workers, resume=resume)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("legacy-chroma", "payload-directory"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--publish", action="store_true", help="Publish the completed staging index")
    parser.add_argument("--embedding-workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--payload-dir", type=Path)
    args = parser.parse_args(argv)
    if args.dry_run == args.build:
        parser.error("choose exactly one of --dry-run or --build")
    if args.publish and not args.build:
        parser.error("--publish requires --build")
    if args.embedding_workers <= 0:
        parser.error("--embedding-workers must be positive")
    from retrieval_core.config import RetrievalConfig
    from retrieval_core.dense_store import DenseStore
    from retrieval_core.lexical_store import LexicalStore
    from retrieval_core.model_manager import ModelManager
    from report_generation.external_rag.v2_index import V2IndexWriter
    config = RetrievalConfig.for_project(Path.cwd())
    staging = config.index_root.parent / (config.index_root.name + ".staging")
    if args.publish:
        backup = config.index_root.with_name(config.index_root.name + ".previous")
        if config.index_root.exists() and backup.exists():
            raise RuntimeError("previous index backup exists; archive it before publishing again")
        # Native Windows HNSW handles can outlive client.stop(); publish only
        # after the isolated builder process has exited completely.
        command = [sys.executable, str(Path(__file__).resolve()), "--source", args.source,
                   "--build", "--embedding-workers", str(args.embedding_workers)]
        if args.resume:
            command.append("--resume")
        if args.payload_dir is not None:
            command.extend(["--payload-dir", str(args.payload_dir)])
        completed = subprocess.run(command, check=False)
        if completed.returncode:
            return completed.returncode
        report = json.loads((staging / "build_report.json").read_text(encoding="utf-8"))
        if report.get("status") != "success" or not (staging / "READY").is_file():
            raise RuntimeError("builder exited without a completed ready index")
        if config.index_root.exists():
            os.replace(config.index_root, backup)
        try:
            os.replace(staging, config.index_root)
        except OSError:
            if backup.exists() and not config.index_root.exists():
                os.replace(backup, config.index_root)
            raise
        print(json.dumps({"status": "published", "path": str(config.index_root)}, ensure_ascii=False))
        return 0
    tokenizer = _local_tokenizer(config.embedding_model_path)
    manager = ModelManager(config.embedding_model_path, config.reranker_model_path)
    writer = V2IndexWriter(DenseStore(staging / "chroma"), LexicalStore(staging / "lexical.sqlite3"),
                           ready_path=staging / "READY", embed_documents=manager.embed_documents,
                           model_version=config.embedding_model_path.name, chunker_version="v2", dictionary_version="v1")
    options = {"writer": writer, "tokenizer": tokenizer, "dry_run": args.dry_run,
               "embedding_model_path": config.embedding_model_path,
               "build_report_path": staging / "build_report.json",
               "embedding_workers": args.embedding_workers, "resume": args.resume}
    if args.source == "legacy-chroma":
        from report_generation.external_rag.vector_store import VECTOR_DB_DIR
        report = build_from_legacy(
            legacy_client=SQLiteReportClient(VECTOR_DB_DIR / "chroma.sqlite3"), **options
        )
    else:
        if args.payload_dir is None:
            parser.error("--payload-dir is required for payload-directory")
        report = build_from_payload_directory(payload_dir=args.payload_dir, **options)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] in {"dry_run", "success"} else 1


def _local_tokenizer(path: Path) -> Any:
    if not path.is_dir():
        raise RuntimeError(f"local embedding model missing: {path}")
    try:
        from transformers import AutoTokenizer
    except ImportError:
        # Dry-run only: preserve deterministic bounded accounting when the
        # optional HF loader is absent.  Full embedding still uses ModelManager.
        return type("CharacterTokenizer", (), {"encode": lambda _, text, add_special_tokens=True: list(range(len(text) + (2 if add_special_tokens else 0)))})()
    return AutoTokenizer.from_pretrained(str(path), local_files_only=True)


if __name__ == "__main__":
    raise SystemExit(main())
