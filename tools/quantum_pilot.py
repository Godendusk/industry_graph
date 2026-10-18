from __future__ import annotations

import argparse
import html
import json
import os
import re
from pathlib import Path
from typing import Any

BASE_URL = "https://clb4yjzx.ciglobal.cn/clb-api"
SUBJECT_ID = "2064547487748272130"
LIST_URL = f"{BASE_URL}/subjectServer/info/subjectPageList"
DEFAULT_ROOT = Path("/root/autodl-tmp/quantum_rag")
DEFAULT_MODEL = Path("/root/autodl-tmp/industry_graph/RAG/model_store/bge-base-zh-v1.5")
INCLUDE_TERMS = (
    "量子科技", "量子计算", "量子通信", "量子芯片", "量子信息", "量子网络",
    "量子密码", "量子传感", "量子精密测量", "量子测量", "量子材料", "量子纠缠",
    "量子比特", "超导量子", "离子阱", "光量子", "量子模拟", "量子互联网",
    "quantum computing", "quantum communication", "quantum technology",
)
STRONG_EXCLUDE_TITLE = (
    "量子养生", "量子美容", "量子水", "量子鞋垫", "量子波动速读",
    "量子意识", "意识波",
)



def _clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def is_relevant(record: dict[str, Any]) -> bool:
    title = _clean(record.get("title"))
    title_lower = title.lower()
    if any(term.lower() in title_lower for term in STRONG_EXCLUDE_TITLE):
        return False
    return "量子" in title or "quantum" in title_lower or "离子阱" in title



def merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in records:
        source_id = str(record.get("id") or record.get("infoId") or "").strip()
        if source_id and source_id not in merged:
            merged[source_id] = record
    return list(merged.values())


def split_chunks(title: str, body: str, summary: str = "", max_chars: int = 500) -> list[dict[str, Any]]:
    title, summary, body = _clean(title), _clean(summary), _clean(body)
    summary = summary[: min(160, max(0, max_chars - len(title) - 81))]
    if not body:
        return []
    prefix = "\n".join(value for value in (title, summary) if value)
    max_body = max(80, max_chars - len(prefix) - 1)
    units = [part.strip() for part in re.split(r"(?<=[。！？!?；;])", body) if part.strip()] or [body]
    chunks, current = [], ""
    for unit in units:
        if current and len(current) + len(unit) > max_body:
            chunks.append(current)
            current = ""
        if len(unit) > max_body:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(unit[start : start + max_body] for start in range(0, len(unit), max_body))
        else:
            current += unit
    if current:
        chunks.append(current)
    return [
        {
            "id": f"__SOURCE_ID__:{index}",
            "document": f"{prefix}\n{chunk}" if prefix else chunk,
            "metadata": {"title": title, "chunk_index": index, "total_chunks": len(chunks)},
        }
        for index, chunk in enumerate(chunks)
    ]


def fetch_page(token: str, page_no: int, page_size: int, timeout: int = 60) -> dict[str, Any]:
    import requests

    payload = {
        "searchWordList": [],
        "fetchFields": ["id", "title", "summary", "author", "sourceAddress", "publishDate", "content", "contentWithTag"],
        "isSubject": "1", "column": "publishDate", "order": "desc", "subjectId": SUBJECT_ID,
        "startTime": "", "endTime": "", "pageNo": page_no, "pageSize": page_size,
        "labelIds": [], "labelList": [], "category": 1, "wordFrequency": [], "status": 1,
        "socialCreditCodeList": [], "dateFormat": "yyyy-MM-dd",
    }
    headers = {
        "Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
        "x-access-token": token, "X-Access-Token": token, "accessToken": token,
        "env": "prod", "environment": "prod",
    }
    response = requests.post(LIST_URL, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 200:
        raise RuntimeError(f"API code={data.get('code')} message={data.get('msg') or data.get('message')}")
    result = data.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("records"), list):
        raise RuntimeError("API response missing result.records")
    return result


def _load_state(path: Path, page_size: int) -> dict[str, Any]:
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("subject_id") == SUBJECT_ID and int(state.get("page_size", page_size)) == page_size:
            return state
    return {"version": 1, "status": "running", "snapshot_complete": False, "subject_id": SUBJECT_ID,
            "page_size": page_size, "next_page": 1, "total": 0, "total_pages": 0,
            "records_seen": 0, "records_kept": 0, "chunks_written": 0, "collection_count": 0, "errors": []}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _encode(model: Any, texts: list[str], batch_size: int) -> list[Any]:
    if not texts:
        return []
    try:
        return list(model.encode(texts, batch_size=batch_size, device="cuda", normalize_embeddings=True, show_progress_bar=False))
    except RuntimeError as exc:
        if "out of memory" not in str(exc).lower() or batch_size <= 8:
            raise
        import torch
        torch.cuda.empty_cache()
        half = max(8, batch_size // 2)
        midpoint = len(texts) // 2
        return _encode(model, texts[:midpoint], half) + _encode(model, texts[midpoint:], half)


def run(args: argparse.Namespace) -> None:
    token = os.environ.get("QUANTUM_TOKEN", "").strip()
    if not token:
        raise SystemExit("QUANTUM_TOKEN is required")
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    state_path, db_path = root / "quantum_manifest.json", root / "chroma"
    from sentence_transformers import SentenceTransformer
    import chromadb

    model = SentenceTransformer(str(Path(args.model_path)), device="cuda")
    collection = chromadb.PersistentClient(path=str(db_path)).get_or_create_collection(name="quantum_news")
    state = _load_state(state_path, args.page_size)
    page, processed, pages_done = max(1, int(state.get("next_page", 1))), int(state.get("records_seen", 0)), 0
    while processed < args.limit_records and pages_done < args.max_pages:
        result = fetch_page(token, page, args.page_size)
        records = merge_records(result.get("records") or [])
        if not records:
            raise RuntimeError(f"page {page} returned no records")
        state["total"], state["total_pages"] = int(result.get("total") or 0), int(result.get("pages") or 0)
        records = records[: max(0, args.limit_records - processed)]
        kept, chunks = [record for record in records if is_relevant(record)], []
        for record in kept:
            source_id = str(record.get("id") or record.get("infoId") or "").strip()
            body = record.get("contentWithTag") or record.get("content") or record.get("summary")
            for item in split_chunks(record.get("title"), body, record.get("summary"), args.max_chars):
                item["id"] = f"{source_id}:{item['metadata']['chunk_index']}"
                item["metadata"].update({"source_id": source_id, "publish_date": _clean(record.get("publishDate")), "source_url": _clean(record.get("sourceAddress"))})
                chunks.append(item)
        for start in range(0, len(chunks), args.embed_batch_size):
            batch = chunks[start : start + args.embed_batch_size]
            vectors = _encode(model, [item["document"] for item in batch], args.embed_batch_size)
            collection.upsert(ids=[item["id"] for item in batch], documents=[item["document"] for item in batch], metadatas=[item["metadata"] for item in batch], embeddings=[v.tolist() if hasattr(v, "tolist") else list(v) for v in vectors])
        processed += len(records)
        state["records_seen"], state["records_kept"] = processed, int(state.get("records_kept", 0)) + len(kept)
        state["chunks_written"], state["collection_count"] = int(state.get("chunks_written", 0)) + len(chunks), collection.count()
        state["next_page"] = page + 1
        _save_state(state_path, state)
        pages_done, page = pages_done + 1, page + 1
        print(f"page={page - 1} seen={processed}/{args.limit_records} kept={len(kept)} chunks={len(chunks)} collection={state['collection_count']}", flush=True)
    state["status"], state["snapshot_complete"] = ("completed", True) if processed >= args.limit_records else ("partial", False)
    _save_state(state_path, state)
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-records", type=int, default=5000)
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--embed-batch-size", type=int, default=256)
    parser.add_argument("--max-chars", type=int, default=500)
    parser.add_argument("--output-dir", default=str(DEFAULT_ROOT))
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL))
    run(parser.parse_args())


if __name__ == "__main__":
    main()
