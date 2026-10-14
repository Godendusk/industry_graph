"""Offline, resumable lexical sidecars for the existing industry news vectors."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from contextlib import closing, contextmanager, nullcontext
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from time import monotonic
from typing import Callable

from ..industry_config import PROJECT_ROOT, get_industry_config
from retrieval_core.schemas import RetrievalCandidate

SCHEMA_VERSION = 1
TOKENIZER_VERSION = "jieba-search-v1"
INDEX_ROOT = PROJECT_ROOT / "RAG" / "indexes" / "report_v2_news"


def news_metadata(industry: str, vector_id: str, raw: dict) -> dict:
    config = get_industry_config(industry)
    metadata = dict(raw)
    metadata.update(
        industry=industry, library=config["collection_name"], vector_id=vector_id,
        material_id=str(raw.get("source_id") or vector_id.rsplit(":", 1)[0]),
        source_address=str(raw.get("url") or raw.get("source_url") or raw.get("source_address") or ""),
        paragraph_index=int(raw.get("chunk_index", 0)),
        classification_name=config["name"] + "专题资讯", classification_type="",
    )
    return metadata


def news_tokens(text: str) -> list[str]:
    import jieba

    return [word.lower() for word in jieba.cut_for_search(text)
            if re.fullmatch(r"[\w]+", word) and (len(word) > 1 or word.isascii())]


@lru_cache(maxsize=2048)
def _title_tokens(title: str) -> str:
    return " ".join(news_tokens(title))


def _tokenize_record(record):
    _, _, text, metadata, _ = record
    return _title_tokens(str(metadata.get("title") or "")), " ".join(news_tokens(text))


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _signature(path: Path) -> list:
    values = []
    for item in (path, Path(str(path) + "-wal")):
        if item.exists():
            stat = item.stat()
            values.append([item.name, stat.st_size, stat.st_mtime_ns])
    return values


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


class NewsSource:
    def __init__(self, industry: str, path: Path | None = None):
        self.industry = industry
        config = get_industry_config(industry)
        if config.get("rag_type") != "news":
            raise ValueError("news source requires a news industry")
        self.collection = config["collection_name"]
        self.path = Path(path) if path is not None else config["vector_db_path"] / "chroma.sqlite3"

    def info(self, connection: sqlite3.Connection) -> dict:
        row = connection.execute("SELECT id, dimension FROM collections WHERE name=?", (self.collection,)).fetchone()
        if row is None:
            raise ValueError(f"missing news collection: {self.collection}")
        if row["dimension"] not in (None, 768):
            raise ValueError(f"news collection must have 768 dimensions: {self.collection}")
        segments = connection.execute(
            "SELECT id FROM segments WHERE collection=? AND scope='METADATA'", (row["id"],)
        ).fetchall()
        if len(segments) != 1:
            raise ValueError("news collection must have one metadata segment")
        segment = segments[0]["id"]
        count = connection.execute("SELECT COUNT(*) FROM embeddings WHERE segment_id=?", (segment,)).fetchone()[0]
        return {"collection": self.collection, "collection_id": row["id"], "segment": segment,
                "count": count, "source": str(self.path.resolve()), "signature": _signature(self.path),
                "revision": self.revision(connection, segment, row["id"])}

    @staticmethod
    def revision(connection, segment, collection_id):
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"max_seq_id", "embeddings_queue"}.issubset(tables):
            return None
        row = connection.execute("SELECT seq_id FROM max_seq_id WHERE segment_id=?", (segment,)).fetchone()
        sequence = row[0] if row else None
        if isinstance(sequence, bytes):
            sequence = int.from_bytes(sequence, "big")
        queued = connection.execute("SELECT MAX(seq_id) FROM embeddings_queue").fetchone()[0]
        return [collection_id, segment, sequence, max(sequence or 0, queued or 0)]

    def batches(self, connection: sqlite3.Connection, segment: str, after: int = 0, batch_size: int = 2000):
        while True:
            embeddings = connection.execute(
                "SELECT id,embedding_id FROM embeddings WHERE segment_id=? AND id>? ORDER BY id LIMIT ?",
                (segment, after, batch_size),
            ).fetchall()
            if not embeddings:
                return
            upper = embeddings[-1]["id"]
            payloads = {row["id"]: {} for row in embeddings}
            for row in connection.execute(
                "SELECT m.* FROM embedding_metadata m JOIN embeddings e ON e.id=m.id "
                "WHERE e.segment_id=? AND e.id>? AND e.id<=? ORDER BY m.id", (segment, after, upper)
            ):
                if row["id"] not in payloads:
                    continue
                value = next((row[key] for key in ("string_value", "int_value", "float_value", "bool_value")
                              if row[key] is not None), None)
                payloads[row["id"]][row["key"]] = value
            batch = []
            for row in embeddings:
                raw = payloads[row["id"]]
                text = str(raw.pop("chroma:document", "") or "").strip()
                if not text:
                    raise ValueError(f"empty news text: {row['embedding_id']}")
                metadata = news_metadata(self.industry, row["embedding_id"], raw)
                digest = hashlib.sha256(_json([text, metadata]).encode("utf-8")).hexdigest()
                batch.append((row["id"], row["embedding_id"], text, metadata, digest))
            yield batch
            after = upper


def _chain(previous: str, row_id: int, chunk_id: str, digest: str) -> str:
    return hashlib.sha256(_json([previous, row_id, chunk_id, digest]).encode("utf-8")).hexdigest()


def _initialize(connection: sqlite3.Connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS chunks (
            rowid INTEGER PRIMARY KEY, source_row_id INTEGER NOT NULL UNIQUE,
            chunk_id TEXT NOT NULL UNIQUE, document_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL, text TEXT NOT NULL, metadata_json TEXT NOT NULL,
            content_hash TEXT NOT NULL, title_tokens TEXT NOT NULL, body_tokens TEXT NOT NULL,
            UNIQUE(document_id,chunk_index)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
            title_tokens, body_tokens, content='chunks', content_rowid='rowid'
        );
        CREATE TRIGGER IF NOT EXISTS chunks_insert AFTER INSERT ON chunks BEGIN
            INSERT INTO news_fts(rowid,title_tokens,body_tokens) VALUES(new.rowid,new.title_tokens,new.body_tokens);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks BEGIN
            INSERT INTO news_fts(news_fts,rowid,title_tokens,body_tokens)
            VALUES('delete',old.rowid,old.title_tokens,old.body_tokens);
        END;
        DROP TRIGGER IF EXISTS chunks_update;
        CREATE TRIGGER chunks_update AFTER UPDATE ON chunks
        WHEN old.title_tokens<>new.title_tokens OR old.body_tokens<>new.body_tokens BEGIN
            INSERT INTO news_fts(news_fts,rowid,title_tokens,body_tokens)
            VALUES('delete',old.rowid,old.title_tokens,old.body_tokens);
            INSERT INTO news_fts(rowid,title_tokens,body_tokens) VALUES(new.rowid,new.title_tokens,new.body_tokens);
        END;
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS seen (chunk_id TEXT PRIMARY KEY);
    """)


def _build_document_keywords(connection):
    connection.executescript("""
        DROP TABLE IF EXISTS news_document_fts;
        DROP TABLE IF EXISTS news_documents;
        CREATE TABLE news_documents (rowid INTEGER PRIMARY KEY, document_id TEXT NOT NULL UNIQUE);
        CREATE VIRTUAL TABLE news_document_fts USING fts5(title_tokens,body_tokens,content='');
        INSERT INTO news_documents(document_id) SELECT DISTINCT document_id FROM chunks ORDER BY document_id;
        INSERT INTO news_document_fts(rowid,title_tokens,body_tokens)
        SELECT d.rowid,MAX(c.title_tokens),GROUP_CONCAT(c.body_tokens,' ')
        FROM news_documents d JOIN chunks c ON c.document_id=d.document_id GROUP BY d.rowid;
        INSERT INTO news_document_fts(news_document_fts) VALUES('integrity-check');
        INSERT INTO news_document_fts(news_document_fts) VALUES('optimize');
    """)
    return connection.execute("SELECT COUNT(*) FROM news_documents").fetchone()[0]


def upgrade_document_keywords(industry: str):
    """Upgrade an existing sidecar using saved tokens, without reading source rows."""
    root = INDEX_ROOT / industry
    with _build_lock(root):
        marker = json.loads((root / "READY").read_text(encoding="utf-8"))
        if marker.get("keyword_granularity") == "document":
            return {"industry": industry, "status": "unchanged", "documents": marker["documents"]}
        if marker["lexical_signature"] != _signature(root / "lexical.sqlite3"):
            raise ValueError("cannot upgrade an incomplete keyword index")
        source = NewsSource(industry)
        with closing(_readonly(source.path)) as connection:
            info = source.info(connection)
        if (info["count"] != marker["count"] or info["collection_id"] != marker["collection_id"]
                or info["source"] != marker["source"] or (info["signature"] != marker["signature"]
                and (info["revision"] is None or info["revision"] != marker.get("revision")))):
            raise ValueError("news source changed; run news index sync before upgrading")
        staging = root / "lexical.document.staging.sqlite3"
        started = monotonic()
        shutil.copy2(root / "lexical.sqlite3", staging)
        with closing(sqlite3.connect(staging)) as connection:
            documents = _build_document_keywords(connection)
            if documents != marker["documents"]:
                raise ValueError("document keyword count mismatch")
            connection.commit()
        if info["signature"] != _signature(source.path):
            raise ValueError("news source changed during document keyword upgrade")
        published = root / "lexical.sqlite3"
        os.replace(staging, published)
        marker.update(keyword_granularity="document", bytes=published.stat().st_size,
                      signature=info["signature"], revision=info["revision"],
                      lexical_signature=_signature(published),
                      document_index_seconds=round(monotonic()-started, 2))
        temporary = root / "READY.tmp"
        temporary.write_text(_json(marker), encoding="utf-8")
        os.replace(temporary, root / "READY")
        return {"industry": industry, "status": "success", "documents": documents,
                "elapsed_seconds": marker["document_index_seconds"], "bytes": marker["bytes"]}


@contextmanager
def _build_lock(root: Path):
    path = root / "BUILD.lock"
    if path.exists():
        pid = int(path.read_text(encoding="ascii"))
        if not _pid_exists(pid):
            path.unlink()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        path.unlink()


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
            return True
        return ctypes.get_last_error() != 87
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def check_news_index(industry: str, root: Path | None = None, source_path: Path | None = None) -> dict:
    root = Path(root) if root is not None else INDEX_ROOT / industry
    source = NewsSource(industry, source_path)
    try:
        marker = json.loads((root / "READY").read_text(encoding="utf-8"))
        if marker["schema_version"] != SCHEMA_VERSION or marker["tokenizer_version"] != TOKENIZER_VERSION:
            raise ValueError("news index version mismatch")
        if marker["industry"] != industry or marker["collection"] != source.collection:
            raise ValueError("news index industry mismatch")
        if marker.get("keyword_granularity") != "document":
            raise ValueError("news document keyword index missing; run news index sync")
        if marker["source"] != str(source.path.resolve()):
            raise ValueError("news source path changed; run news index sync")
        if marker["signature"] != _signature(source.path):
            with closing(_readonly(source.path)) as connection:
                revision = source.revision(connection, marker["segment"], marker["collection_id"])
            if revision is None or revision != marker.get("revision"):
                raise ValueError("news source changed; run news index sync")
        if marker["lexical_signature"] != _signature(root / "lexical.sqlite3"):
            raise ValueError("news lexical index changed or incomplete")
        return {**marker, "status": "ready"}
    except (OSError, ValueError, KeyError) as error:
        return {"status": "not_ready", "industry": industry, "message": str(error)}


def build_news_index(industry: str, *, action: str = "build", root: Path | None = None,
                     source_path: Path | None = None, batch_size: int = 2000,
                     workers: int = 1,
                     progress: Callable[[dict], None] | None = None) -> dict:
    if action not in {"build", "resume", "sync"} or batch_size <= 0:
        raise ValueError("invalid news build action or batch size")
    source = NewsSource(industry, source_path)
    root = Path(root) if root is not None else INDEX_ROOT / industry
    root.mkdir(parents=True, exist_ok=True)
    started = monotonic()
    staging = root / "lexical.staging.sqlite3"
    published = root / "lexical.sqlite3"
    with _build_lock(root), closing(_readonly(source.path)) as src:
        src.execute("BEGIN")
        info = source.info(src)
        state_key = _json({**info, "schema_version": SCHEMA_VERSION, "tokenizer_version": TOKENIZER_VERSION})
        if action != "resume":
            if staging.exists():
                staging.unlink()
            if action == "sync" and published.exists():
                shutil.copy2(published, staging)
        elif not staging.exists():
            raise ValueError("no staging index to resume")
        pool_context = ProcessPoolExecutor(max_workers=workers) if workers > 1 else nullcontext(None)
        with closing(sqlite3.connect(staging, timeout=30)) as target, pool_context as pool:
            _initialize(target)
            old_state = target.execute("SELECT value FROM state WHERE key='checkpoint'").fetchone()
            if action == "resume":
                checkpoint = json.loads(old_state[0]) if old_state else {}
                if checkpoint.get("source_key") != state_key:
                    raise ValueError("source changed since checkpoint; use sync or build")
            else:
                target.execute("DELETE FROM seen")
                checkpoint = {"source_key": state_key, "after": 0, "count": 0, "digest": ""}
                target.execute("INSERT OR REPLACE INTO state VALUES('checkpoint',?)", (_json(checkpoint),))
                target.commit()
            for batch in source.batches(src, info["segment"], checkpoint["after"], batch_size):
                changed = []
                for record in batch:
                    row_id, chunk_id, _, _, digest = record
                    existing = target.execute(
                        "SELECT content_hash,source_row_id,text,metadata_json,title_tokens,body_tokens "
                        "FROM chunks WHERE chunk_id=?", (chunk_id,)
                    ).fetchone()
                    if existing and existing[2] == record[2] and json.loads(existing[3]).get("title") == record[3].get("title"):
                        # Metadata migrations need no repeated Chinese segmentation.
                        continue
                    if not existing or existing[:2] != (digest, row_id):
                        changed.append(record)
                tokenized = dict(zip(
                    (record[1] for record in changed),
                    pool.map(_tokenize_record, changed, chunksize=50) if pool else map(_tokenize_record, changed),
                ))
                with target:
                    for row_id, chunk_id, text, metadata, digest in batch:
                        existing = target.execute(
                            "SELECT content_hash,source_row_id,title_tokens,body_tokens FROM chunks WHERE chunk_id=?",
                            (chunk_id,),
                        ).fetchone()
                        if not existing or existing[:2] != (digest, row_id):
                            title_tokens, body_tokens = tokenized.get(chunk_id, existing[2:] if existing else ("", ""))
                            target.execute(
                                "DELETE FROM chunks WHERE chunk_id<>? AND (source_row_id=? OR "
                                "(document_id=? AND chunk_index=?))",
                                (chunk_id, row_id, metadata["material_id"], metadata["paragraph_index"]),
                            )
                            target.execute(
                                "INSERT INTO chunks(source_row_id,chunk_id,document_id,chunk_index,text,metadata_json,"
                                "content_hash,title_tokens,body_tokens) VALUES(?,?,?,?,?,?,?,?,?) "
                                "ON CONFLICT(chunk_id) DO UPDATE SET source_row_id=excluded.source_row_id,"
                                "document_id=excluded.document_id,chunk_index=excluded.chunk_index,text=excluded.text,"
                                "metadata_json=excluded.metadata_json,content_hash=excluded.content_hash,"
                                "title_tokens=excluded.title_tokens,body_tokens=excluded.body_tokens",
                                (row_id, chunk_id, metadata["material_id"], metadata["paragraph_index"], text,
                                 _json(metadata), digest, title_tokens, body_tokens),
                            )
                        target.execute("INSERT OR IGNORE INTO seen VALUES(?)", (chunk_id,))
                        checkpoint["digest"] = _chain(checkpoint["digest"], row_id, chunk_id, digest)
                    checkpoint["after"] = batch[-1][0]
                    checkpoint["count"] += len(batch)
                    target.execute("INSERT OR REPLACE INTO state VALUES('checkpoint',?)", (_json(checkpoint),))
                if progress:
                    progress({"industry": industry, "chunks": checkpoint["count"], "total": info["count"],
                              "elapsed_seconds": round(monotonic() - started, 2)})
            with target:
                target.execute("DELETE FROM chunks WHERE chunk_id NOT IN (SELECT chunk_id FROM seen)")
            count = target.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            digest = ""
            for row_id, chunk_id, text, metadata_json, saved_hash in target.execute(
                "SELECT source_row_id,chunk_id,text,metadata_json,content_hash FROM chunks ORDER BY source_row_id"
            ):
                actual_hash = hashlib.sha256(_json([text, json.loads(metadata_json)]).encode("utf-8")).hexdigest()
                if actual_hash != saved_hash:
                    raise ValueError("news index content hash mismatch")
                digest = _chain(digest, row_id, chunk_id, actual_hash)
            if count != info["count"] or count != checkpoint["count"] or digest != checkpoint["digest"]:
                raise ValueError("news source/index count or ID/content digest mismatch")
            if info["signature"] != _signature(source.path):
                raise ValueError("news source changed during build; retry sync")
            target.execute("INSERT INTO news_fts(news_fts,rank) VALUES('integrity-check',1)")
            target.execute("INSERT INTO news_fts(news_fts) VALUES('optimize')")
            target.commit()
            documents = target.execute("SELECT COUNT(DISTINCT document_id) FROM chunks").fetchone()[0]
            if _build_document_keywords(target) != documents:
                raise ValueError("news document keyword count mismatch")
            target.commit()
        os.replace(staging, published)
        marker = {**info, "industry": industry, "schema_version": SCHEMA_VERSION,
                  "tokenizer_version": TOKENIZER_VERSION, "digest": digest, "documents": documents,
                  "keyword_granularity": "document",
                  "elapsed_seconds": round(monotonic() - started, 2), "bytes": published.stat().st_size,
                  "lexical_signature": _signature(published)}
        temporary = root / "READY.tmp"
        temporary.write_text(_json(marker), encoding="utf-8")
        os.replace(temporary, root / "READY")
        return {**marker, "status": "success"}


class NewsLexicalStore:
    def __init__(self, industry: str, root: Path | None = None, source_path: Path | None = None):
        self.industry = industry
        self.root = Path(root) if root is not None else INDEX_ROOT / industry
        self.source_path = source_path

    def search(self, query: str, limit: int, libraries=None) -> list[RetrievalCandidate]:
        state = check_news_index(self.industry, self.root, self.source_path)
        if state["status"] != "ready":
            raise RuntimeError(state["message"])
        collection = get_industry_config(self.industry)["collection_name"]
        if libraries is not None and collection not in libraries:
            return []
        tokens = news_tokens(query)
        if not tokens:
            return []
        expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in dict.fromkeys(tokens))
        with closing(_readonly(self.root / "lexical.sqlite3")) as connection:
            documents = connection.execute(
                "SELECT d.document_id,bm25(news_document_fts,5.0,1.0) AS score FROM news_document_fts "
                "JOIN news_documents d ON d.rowid=news_document_fts.rowid WHERE news_document_fts MATCH ? "
                "ORDER BY score,d.document_id LIMIT ?", (expression, limit),
            ).fetchall()
            rows = []
            wanted = set(tokens)
            for document in documents:
                chunks = connection.execute("SELECT * FROM chunks WHERE document_id=? ORDER BY chunk_index",
                                            (document["document_id"],)).fetchall()
                # Return an original vector ID so dense and lexical recall can fuse.
                best = max(chunks, key=lambda row: sum(token in wanted for token in row["body_tokens"].split()))
                rows.append({**dict(best), "score": document["score"]})
        return [RetrievalCandidate(chunk_id=row["chunk_id"], document_id=row["document_id"],
                                  text=row["text"], metadata=news_metadata(self.industry, row["chunk_id"], json.loads(row["metadata_json"])),
                                  bm25_rank=rank, bm25_score=float(row["score"]))
                for rank, row in enumerate(rows, 1)]
