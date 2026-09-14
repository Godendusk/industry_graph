import json
from pathlib import Path

import pytest


def record(source_id, content="正文内容。"):
    return {
        "id": source_id,
        "title": f"标题-{source_id}",
        "summary": f"摘要-{source_id}",
        "content": content,
        "publishDate": "2026-09-11",
        "source": "测试来源",
        "sourceAddress": f"https://example.com/{source_id}",
    }


def page(records, current, pages, total=None):
    return {
        "records": records,
        "current": current,
        "pages": pages,
        "total": total if total is not None else len(records),
        "size": len(records),
    }


class FakePagedClient:
    def __init__(self, pages, failures=None):
        self.pages = pages
        self.failures = dict(failures or {})
        self.pages_requested = []
        self.last_request = None

    def list_news(self, page_no, page_size):
        self.pages_requested.append(page_no)
        self.last_request = {"pageNo": page_no, "pageSize": page_size, "status": 1,
                             "subjectId": "2043590589800853505",
                             "fetchFields": ["content"]}
        remaining = self.failures.get(page_no, 0)
        if remaining:
            self.failures[page_no] = remaining - 1
            raise RuntimeError(f"temporary page failure: {page_no}")
        return self.pages[page_no]

    def get_detail(self, source_id):
        raise AssertionError("detail should not be called when list record has content")


class FakeFullStore:
    def __init__(self, existing_sources=None):
        self.chunks = []
        self.existing_sources = set(existing_sources or set())
        self.prune_calls = 0

    def upsert(self, chunks):
        self.chunks.extend(chunks)
        return len(chunks)

    def count(self):
        return len(self.chunks)

    def prune_sources(self, source_ids):
        self.prune_calls += 1
        self.existing_sources.intersection_update(source_ids)
        self.existing_sources.update(source_ids)
        return 0


class RecordingFullStore(FakeFullStore):
    def __init__(self, existing_sources=None):
        super().__init__(existing_sources=existing_sources)
        self.upsert_batches = []

    def upsert(self, chunks):
        batch = list(chunks)
        self.upsert_batches.append(batch)
        return super().upsert(batch)


class FailingBatchStore(FakeFullStore):
    def __init__(self, fail_on_call, existing_sources=None):
        super().__init__(existing_sources=existing_sources)
        self.fail_on_call = fail_on_call
        self.upsert_calls = 0

    def upsert(self, chunks):
        self.upsert_calls += 1
        if self.upsert_calls == self.fail_on_call:
            raise RuntimeError("batch write failed")
        return super().upsert(chunks)


def test_manifest_records_snapshot_and_page_progress(tmp_path):
    from report_generation.external_rag.embodied_manifest import EmbodiedIngestionManifest

    manifest = EmbodiedIngestionManifest(tmp_path / "embodied_full.json")
    state = manifest.start(total=243658, page_size=100, status=1)
    assert state["status"] == "running"
    assert state["next_page"] == 1

    manifest.mark_page_complete(page_no=1, records=100, chunks=650)
    saved = manifest.load()
    assert saved["next_page"] == 2
    assert saved["records_seen"] == 100
    assert saved["chunks_written"] == 650


def test_full_ingestion_walks_pages_and_skips_unneeded_detail(tmp_path):
    from report_generation.external_rag.embodied_ingestion import ingest_all_news

    client = FakePagedClient({
        1: page([record("a"), record("b")], 1, 2, total=3),
        2: page([record("c")], 2, 2, total=3),
    })
    store = FakeFullStore()

    result = ingest_all_news(client=client, store=store,
                             manifest_path=tmp_path / "run.json", page_size=2,
                             sleep_seconds=0)

    assert result["status"] == "success"
    assert result["records_seen"] == 3
    assert result["details_succeeded"] == 0
    assert result["detail_fallbacks"] == 0
    assert client.pages_requested == [1, 2]
    assert store.prune_calls == 1


def test_full_ingestion_batches_all_chunks_in_one_upsert_per_page(tmp_path):
    from report_generation.external_rag.embodied_ingestion import ingest_all_news

    client = FakePagedClient({
        1: page([record("a", "第一篇。"), record("b", "第二篇。")], 1, 1, total=2),
    })
    store = RecordingFullStore()

    result = ingest_all_news(
        client=client,
        store=store,
        manifest_path=tmp_path / "run.json",
        page_size=2,
        sleep_seconds=0,
    )

    assert result["status"] == "success"
    assert len(store.upsert_batches) == 1
    assert {item["metadata"]["source_id"] for item in store.upsert_batches[0]} == {"a", "b"}


def test_resume_starts_at_manifest_next_page(tmp_path):
    from report_generation.external_rag.embodied_ingestion import ingest_all_news
    from report_generation.external_rag.embodied_manifest import EmbodiedIngestionManifest

    manifest_path = tmp_path / "run.json"
    manifest = EmbodiedIngestionManifest(manifest_path)
    manifest.start(total=4, page_size=2, status=1)
    manifest.mark_page_complete(page_no=1, records=2, chunks=2)
    client = FakePagedClient({2: page([record("c"), record("d")], 2, 2, total=4)})

    result = ingest_all_news(client=client, store=FakeFullStore(),
                             manifest_path=manifest_path, page_size=2,
                             resume=True, sleep_seconds=0)

    assert result["status"] == "success"
    assert client.pages_requested == [2]


def test_failed_page_is_retried_and_incomplete_run_is_not_pruned(tmp_path):
    from report_generation.external_rag.embodied_ingestion import ingest_all_news

    client = FakePagedClient(
        {1: page([record("a")], 1, 2, total=2),
         2: page([record("b")], 2, 2, total=2)},
        failures={2: 3},
    )
    store = FakeFullStore(existing_sources={"old"})

    result = ingest_all_news(client=client, store=store,
                             manifest_path=tmp_path / "run.json", page_size=1,
                             retry_count=2, sleep_seconds=0)

    assert result["status"] == "failed"
    assert client.pages_requested == [1, 2, 2, 2]
    assert store.prune_calls == 0
    assert "old" in store.existing_sources


def test_failed_batch_write_keeps_page_resumable_and_does_not_prune(tmp_path):
    from report_generation.external_rag.embodied_ingestion import ingest_all_news
    from report_generation.external_rag.embodied_manifest import EmbodiedIngestionManifest

    manifest_path = tmp_path / "run.json"
    client = FakePagedClient({
        1: page([record("a")], 1, 2, total=2),
        2: page([record("b")], 2, 2, total=2),
    })
    store = FailingBatchStore(fail_on_call=2, existing_sources={"old"})

    result = ingest_all_news(
        client=client,
        store=store,
        manifest_path=manifest_path,
        page_size=1,
        retry_count=0,
        sleep_seconds=0,
    )

    assert result["status"] == "failed"
    assert store.prune_calls == 0
    assert "old" in store.existing_sources
    saved = EmbodiedIngestionManifest(manifest_path).load()
    assert saved["status"] == "failed"
    assert saved["next_page"] == 2


def test_skip_failed_page_records_page_and_continues(tmp_path):
    from report_generation.external_rag.embodied_ingestion import ingest_all_news
    from report_generation.external_rag.embodied_manifest import EmbodiedIngestionManifest

    manifest_path = tmp_path / "run.json"
    client = FakePagedClient({
        1: page([record("a")], 1, 3, total=3),
        2: page([record("bad")], 2, 3, total=3),
        3: page([record("c")], 3, 3, total=3),
    })
    store = FailingBatchStore(fail_on_call=2)

    result = ingest_all_news(
        client=client,
        store=store,
        manifest_path=manifest_path,
        page_size=1,
        retry_count=0,
        sleep_seconds=0,
        skip_failed_pages=True,
    )

    assert result["status"] == "partial_success"
    assert result["records_seen"] == 3
    assert result["chunks_written"] == 2
    assert result["skipped_pages"] == [2]
    assert client.pages_requested == [1, 2, 3]
    assert store.prune_calls == 0
    saved = EmbodiedIngestionManifest(manifest_path).load()
    assert saved["status"] == "completed_with_skips"
    assert saved["skipped_pages"] == [2]
    assert saved["next_page"] == 4


def test_skip_failed_pages_does_not_skip_list_request_failures(tmp_path):
    from report_generation.external_rag.embodied_ingestion import ingest_all_news

    client = FakePagedClient(
        {1: page([record("a")], 1, 2, total=2),
         2: page([record("b")], 2, 2, total=2)},
        failures={2: 1},
    )

    result = ingest_all_news(
        client=client,
        store=FakeFullStore(),
        manifest_path=tmp_path / "run.json",
        page_size=1,
        retry_count=0,
        sleep_seconds=0,
        skip_failed_pages=True,
    )

    assert result["status"] == "failed"
    assert result["skipped_pages"] == []
    assert client.pages_requested == [1, 2]


def test_incomplete_manifest_remains_resumable(tmp_path):
    from report_generation.external_rag.embodied_manifest import EmbodiedIngestionManifest

    path = tmp_path / "run.json"
    manifest = EmbodiedIngestionManifest(path)
    manifest.start(total=10, page_size=2, status=1)
    saved = manifest.finish(collection_count=3, snapshot_complete=False)

    assert saved["status"] == "running"
    assert manifest.load()["status"] == "running"


def test_resume_after_transient_page_failure_can_finish_successfully(tmp_path):
    from report_generation.external_rag.embodied_ingestion import ingest_all_news

    manifest_path = tmp_path / "run.json"
    first_client = FakePagedClient(
        {1: page([record("a")], 1, 2, total=2),
         2: page([record("b")], 2, 2, total=2)},
        failures={2: 1},
    )
    store = FakeFullStore()
    first = ingest_all_news(client=first_client, store=store,
                            manifest_path=manifest_path, page_size=1,
                            retry_count=0, sleep_seconds=0)
    assert first["status"] == "failed"

    second = ingest_all_news(client=FakePagedClient(
        {2: page([record("b")], 2, 2, total=2)}
    ), store=store, manifest_path=manifest_path, page_size=1,
        retry_count=0, sleep_seconds=0, resume=True)

    assert second["status"] == "success"
    assert second["error_count"] == 0


def test_manifest_does_not_store_tokens(tmp_path):
    from report_generation.external_rag.embodied_manifest import EmbodiedIngestionManifest

    path = tmp_path / "run.json"
    manifest = EmbodiedIngestionManifest(path)
    manifest.start(total=1, page_size=1, status=1)
    raw = path.read_text(encoding="utf-8")
    assert "accessToken" not in raw
    assert "X-Access-Token" not in raw
