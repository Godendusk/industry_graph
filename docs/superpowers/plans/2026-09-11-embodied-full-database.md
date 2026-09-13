# 具身智能全量数据库实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐项执行本计划。以下步骤使用复选框（`- [ ]`）进行跟踪。

**目标：** 将具身智能专题接口当前 `status=1` 范围内的全部资讯（当前约 24.36 万条）分页摄入独立 Chroma 数据库，并支持断点续传、失败重试、增量更新和报告检索。

**架构：** 继续使用 `subjectPageList` 列表接口，并在请求体中传入前端实际使用的 `fetchFields`，直接获取资讯正文；详情接口作为补充来源，不再作为唯一正文来源。列表记录已有可用正文时不再调用已知返回空响应的详情接口，只有列表没有正文时才尝试详情回退。全量摄入使用独立的批次状态文件记录页码和统计信息，正文清洗、分段、Embedding 与 Chroma upsert 分批执行。只有整批抓取成功后才清理不属于当前快照的旧片段，避免分页过程中误删已经写入的数据。

**数据口径：** 第一阶段固定为 `subjectId=2043590589800853505`、`status=1`、`column=publishDate`、`order=desc` 的全部记录。当前接口返回的 `total` 约为 243,658，但它代表该筛选条件下的平台专题记录数，不代表互联网中的全部具身智能信息。第二阶段如需抓取 `status=0` 的全部状态数据，必须使用另一份数据库或明确的重建批次，不能与第一阶段静默混合。

**Tech Stack：** Python `requests`、`sentence-transformers`、`chromadb`、本地 `bge-base-zh-v1.5`（768 维）、现有 `report_generation` 检索链路、`pytest`。

---

## 文件职责

- 修改 `industry_graph/report_generation/external_rag/embodied_client.py`：保留当前列表/详情 API，并确保列表请求包含 `fetchFields`；增加分页结果校验和明确的接口错误。
- 修改 `industry_graph/report_generation/external_rag/embodied_ingestion.py`：增加全量分页入口、断点续传、失败重试、批次状态和完整批次结束后的快照清理；保留现有最新 100 条入口。
- 修改 `industry_graph/report_generation/external_rag/embodied_store.py`：提供按批次 upsert、按资讯源清理、集合计数和只读校验能力。
- 新建 `industry_graph/report_generation/external_rag/embodied_manifest.py`：管理全量摄入状态文件，状态文件只保存在本地，不写入 Git。
- 修改 `industry_graph/tests/test_embodied_news_rag.py`：覆盖分页、断点、重试、批次清理和中断恢复。
- 新建 `industry_graph/tests/test_embodied_full_ingestion.py`：使用 fake API 和 fake store 验证全量摄入流程，不访问线上服务。
- 不修改人工智能集合、人工智能图谱或已有人工智能报告数据。

## Task 1：固定全量数据口径和运行参数

**Files:**

- Modify: `industry_graph/report_generation/external_rag/embodied_client.py`
- Create: `industry_graph/report_generation/external_rag/embodied_manifest.py`
- Test: `industry_graph/tests/test_embodied_full_ingestion.py`

- [ ] **Step 1: 写参数和状态失败测试**

测试下面的固定参数和状态结构：

```python
def test_full_run_uses_status_one_and_fetch_fields():
    client = FakeEmbodiedClient()
    result = client.list_news(page_no=3, page_size=100)
    assert result["current"] == 3
    assert client.last_request["status"] == 1
    assert "content" in client.last_request["fetchFields"]
    assert client.last_request["subjectId"] == "2043590589800853505"


def test_manifest_records_snapshot_and_page_progress(tmp_path):
    manifest = EmbodiedIngestionManifest(tmp_path / "embodied_full.json")
    state = manifest.start(total=243658, page_size=100, status=1)
    assert state["status"] == "running"
    assert state["next_page"] == 1

    manifest.mark_page_complete(page_no=1, records=100, chunks=650)
    saved = manifest.load()
    assert saved["next_page"] == 2
    assert saved["records_seen"] == 100
    assert saved["chunks_written"] == 650
```

- [ ] **Step 2: 运行失败测试**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q tests/test_embodied_full_ingestion.py
```

预期：失败，因为全量状态对象和分页入口尚未实现。

- [ ] **Step 3: 实现固定参数和 manifest**

列表请求继续使用：

```python
{
    "subjectId": "2043590589800853505",
    "pageNo": page_no,
    "pageSize": page_size,
    "fetchFields": [
        "id", "title", "summary", "author",
        "sourceAddress", "publishDate", "content", "contentWithTag",
    ],
    "status": 1,
    "isSubject": "1",
    "category": 1,
    "searchWordList": [],
    "column": "publishDate",
    "order": "desc",
    "wordFrequency": [],
    "dateFormat": "yyyy-MM-dd",
    "socialCreditCodeList": [],
    "labelIds": [],
}
```

`EmbodiedIngestionManifest` 的最小状态结构为：

```python
{
    "version": 1,
    "status": "running",       # running / completed / failed
    "subject_id": "2043590589800853505",
    "data_status": 1,
    "page_size": 100,
    "total": 243658,
    "next_page": 1,
    "records_seen": 0,
    "details_succeeded": 0,
    "detail_fallbacks": 0,
    "chunks_written": 0,
    "collection_count": 0,
    "errors": [],
}
```

状态文件写入 `RAG/vector_db_embodied/embodied_full_manifest.json`，使用临时文件加替换方式保存，令牌绝不进入状态文件。已有最新 100 条模式继续使用独立的命令参数，不复用全量 manifest。

- [ ] **Step 4: 运行参数测试**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q tests/test_embodied_full_ingestion.py
```

预期：参数和 manifest 测试通过。

- [ ] **Step 5: 提交参数和状态功能**

```bash
git add report_generation/external_rag/embodied_client.py report_generation/external_rag/embodied_manifest.py tests/test_embodied_full_ingestion.py
git commit -m "feat: define embodied full ingestion state"
```

## Task 2：实现分页、断点和可恢复摄入

**Files:**

- Modify: `industry_graph/report_generation/external_rag/embodied_ingestion.py`
- Modify: `industry_graph/report_generation/external_rag/embodied_manifest.py`
- Test: `industry_graph/tests/test_embodied_full_ingestion.py`

- [ ] **Step 1: 写分页和中断恢复失败测试**

```python
def test_full_ingestion_walks_pages_until_total(tmp_path):
    client = FakePagedClient(
        pages={
            1: page(records=[record("a"), record("b")], current=1, pages=2),
            2: page(records=[record("c")], current=2, pages=2),
        }
    )
    store = FakeFullStore()

    result = ingest_all_news(
        client=client,
        store=store,
        manifest_path=tmp_path / "run.json",
        page_size=2,
    )

    assert result["status"] == "success"
    assert result["records_seen"] == 3
    assert client.pages_requested == [1, 2]


def test_resume_starts_at_manifest_next_page(tmp_path):
    manifest_path = tmp_path / "run.json"
    write_manifest(manifest_path, next_page=3, total=4, records_seen=2)
    client = FakePagedClient(pages={3: page(records=[record("c"), record("d")], current=3, pages=3)})

    result = ingest_all_news(
        client=client,
        store=FakeFullStore(),
        manifest_path=manifest_path,
        page_size=2,
        resume=True,
    )

    assert result["status"] == "success"
    assert client.pages_requested == [3]
```

- [ ] **Step 2: 运行失败测试**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q tests/test_embodied_full_ingestion.py -k 'page or resume'
```

预期：失败，因为当前只有单页 `ingest_latest_news()`。

- [ ] **Step 3: 实现 `ingest_all_news()`**

函数签名固定为：

```python
def ingest_all_news(
    client=None,
    store=None,
    manifest_path=DEFAULT_FULL_MANIFEST,
    page_size=100,
    max_pages=None,
    resume=True,
    retry_count=3,
):
    raise NotImplementedError
```

处理规则：

1. 首次运行请求第 1 页，读取 `total`、`pages` 或根据 `ceil(total / page_size)` 计算总页数。
2. 后续按 `current + 1` 请求，直到返回页码超过总页数或 `records` 为空。
3. 每页先完成正文清洗、切分和 upsert，再保存 manifest 的 `next_page`。
4. 列表请求失败或鉴权错误时立即停止，manifest 标记 `failed`，不清理现有数据。
5. 单页请求失败时按 `retry_count=3` 重试；仍失败则停止并保留 `next_page`，下次从该页恢复。
6. `max_pages` 只用于测试和小规模试运行，生产全量运行不设置该参数。
7. 列表记录没有可用正文时才调用详情接口；详情为空或非 JSON 时，优先使用当前列表记录中已经返回的 `contentWithTag`、`content`、`summary`。列表已有正文时跳过详情请求，避免对已知空响应接口产生无效流量。
8. 每处理一页等待一个可配置的短间隔，默认 `0.2` 秒，避免连续请求触发限流。

- [ ] **Step 4: 验证分页和恢复**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q tests/test_embodied_full_ingestion.py -k 'page or resume'
```

预期：通过，并确认失败页不会被错误标记为已完成。

- [ ] **Step 5: 提交分页功能**

```bash
git add report_generation/external_rag/embodied_ingestion.py report_generation/external_rag/embodied_manifest.py tests/test_embodied_full_ingestion.py
git commit -m "feat: add resumable embodied full ingestion"
```

## Task 3：实现全量批次的快照清理和一致性校验

**Files:**

- Modify: `industry_graph/report_generation/external_rag/embodied_store.py`
- Modify: `industry_graph/report_generation/external_rag/embodied_ingestion.py`
- Test: `industry_graph/tests/test_embodied_full_ingestion.py`

- [ ] **Step 1: 写清理边界失败测试**

```python
def test_full_ingestion_does_not_prune_between_pages(tmp_path):
    store = FakeFullStore(existing_sources={"old"})
    result = ingest_all_news(
        client=FakePagedClient(two_pages()),
        store=store,
        manifest_path=tmp_path / "run.json",
        page_size=2,
    )
    assert store.prune_calls == 1
    assert result["status"] == "success"


def test_incomplete_run_keeps_previous_sources():
    store = FakeFullStore(existing_sources={"old"})
    result = ingest_all_news(
        client=FailingPagedClient(fail_on_page=2),
        store=store,
        manifest_path=tmp_path / "run.json",
        page_size=2,
    )
    assert result["status"] == "failed"
    assert store.prune_calls == 0
    assert "old" in store.sources()
```

- [ ] **Step 2: 运行失败测试**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q tests/test_embodied_full_ingestion.py -k 'prune or incomplete'
```

- [ ] **Step 3: 实现批次清理**

保留现有 `EmbodiedNewsStore.prune_sources(source_ids)`，但只能在以下条件同时满足时调用：

```python
if run_completed and records_seen > 0 and not fatal_errors:
    stale_removed = store.prune_sources(all_current_source_ids)
```

全量运行期间收集所有页的 `source_id`。如果中途失败、用户中断、鉴权失败或页数不完整，不执行清理。清理结果写入 `stale_chunks_removed`，并将最终 `collection_count` 与 Chroma 实际数量进行比较。

增加只读校验函数：

```python
def validate_embodied_collection(store):
    rows = store.collection.get(include=["metadatas"])
    source_ids = {
        str(metadata.get("source_id"))
        for metadata in rows.get("metadatas", [])
        if isinstance(metadata, dict) and metadata.get("source_id")
    }
    return {
        "collection": "embodied_news",
        "count": store.count(),
        "unique_source_ids": len(source_ids),
        "embedding_dimension": 768,
    }
```

- [ ] **Step 4: 验证批次一致性**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q tests/test_embodied_full_ingestion.py -k 'prune or incomplete'
```

预期：只有完整成功批次会清理旧源，失败批次保留上一个可用快照。

- [ ] **Step 5: 提交快照清理功能**

```bash
git add report_generation/external_rag/embodied_store.py report_generation/external_rag/embodied_ingestion.py tests/test_embodied_full_ingestion.py
git commit -m "feat: keep embodied full index snapshot consistent"
```

## Task 4：先做小规模试运行，再执行全量构建

**Files:**

- Modify: `industry_graph/report_generation/external_rag/embodied_ingestion.py`（仅增加 CLI 参数）
- Runtime-only: `industry_graph/RAG/vector_db_embodied/embodied_full_manifest.json`
- Runtime-only: `industry_graph/RAG/vector_db_embodied/`

- [ ] **Step 1: 小规模试运行 1,000 条**

在仓库外通过环境变量传入两个令牌：

```bash
export EMBODIED_ACCESS_TOKEN='从当前登录会话获取的 accessToken'
export EMBODIED_X_ACCESS_TOKEN='从当前登录会话获取的 X-Access-Token'
```

运行：

```bash
PYTHONPATH=. conda run -n kunlun python -m report_generation.external_rag.embodied_ingestion \
  --all \
  --limit-records 1000 \
  --page-size 100 \
  --manifest RAG/vector_db_embodied/embodied_trial_manifest.json
```

预期检查：

- `records_seen=1000`；
- 正文片段数量大于 0；
- `failed=0`；
- `embodied_news` 可返回 Top 5；
- 每个向量的维度为 768；
- 旧人工智能集合数量和内容不变。

- [ ] **Step 2: 观察试运行资源和数据质量**

记录运行时间、请求失败数、平均每条片段数、数据库大小和 Top 5 检索结果。只有试运行数据质量可接受时才进入全量。

- [ ] **Step 3: 执行全量 `status=1` 构建**

```bash
PYTHONPATH=. conda run -n kunlun python -m report_generation.external_rag.embodied_ingestion \
  --all \
  --page-size 100 \
  --manifest RAG/vector_db_embodied/embodied_full_manifest.json \
  --resume
```

全量运行过程中：

- 不提交 token、manifest、日志或 Chroma 二进制文件；
- 不删除旧数据库目录；
- 如果进程中断，重新执行相同命令继续；
- 如果鉴权失败，停止并保留当前可用快照；
- 如果接口限流，降低请求频率后从 manifest 继续。

- [ ] **Step 4: 做全量一致性校验**

```bash
PYTHONPATH=. conda run -n kunlun python -m report_generation.external_rag.embodied_ingestion \
  --validate-only \
  --manifest RAG/vector_db_embodied/embodied_full_manifest.json
```

验证 `manifest.status=completed`、`records_seen` 与列表接口总数一致、集合数量与 manifest 一致、向量维度为 768，且所有元数据包含 `source_id`、`title`、`publish_date`、`source`、`url`。

## Task 5：验证报告生成链路和增量更新

**Files:**

- Modify: `industry_graph/report_generation/external_rag/embodied_ingestion.py`（增加后续更新入口）
- Test: `industry_graph/tests/test_embodied_full_ingestion.py`
- Existing verification: `industry_graph/tests/test_embodied_news_rag.py` 和报告 RAG 测试集

- [ ] **Step 1: 写增量更新测试**

```python
def test_incremental_run_upserts_new_source_and_removes_replaced_chunks(tmp_path):
    # 同一 source_id 的正文更新后，稳定的 source_id:chunk_index 被覆盖；
    # 新 source_id 被加入；完整快照结束后不保留已离开当前快照的旧 source。
    result = run_incremental_update(
        client=FakePagedClient(pages={1: page(records=[record("new")], current=1, pages=1)}),
        store=FakeFullStore(existing_sources={"old"}),
        manifest_path=tmp_path / "incremental.json",
        page_size=1,
    )
    assert result["status"] == "success"
    assert result["stale_chunks_removed"] == 1
```

- [ ] **Step 2: 实现增量入口**

默认每日或按需执行最近日期范围的列表请求；对已存在的 `source_id` 仍执行 upsert，以覆盖正文变化。增量任务完成后只清理明确不在当前全量快照中的旧源，不因单条详情失败清理整个库。保留最近一次全量 manifest 作为基线。

- [ ] **Step 3: 验证具身智能报告链路**

依次执行：

```python
retrieve_external_rag("具身智能人形机器人最新进展", top_k=5, industry="embodied")
retrieve_external_rag("具身智能产业链核心环节", top_k=5, industry="embodied")
retrieve_external_rag("具身智能政策支持", top_k=5, industry="embodied")
```

确认 `retrieval_version="embodied_chroma"`，所有证据的 `library="embodied_news"`，并确认 `industry="ai"` 仍使用原有人工智能资料库。

- [ ] **Step 4: 运行完整相关测试集**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q \
  tests/test_embodied_news_rag.py \
  tests/test_embodied_full_ingestion.py \
  tests/test_report_rag_modes.py \
  tests/test_rag_storage_separation.py \
  tests/test_report_rag_adapter.py \
  tests/test_report_rag_ingestion_v2.py \
  tests/test_report_rag_v2_index.py \
  tests/test_retrieval_pipeline.py
```

预期：所有选定测试通过，最多保留已知且与本次改动无关的 skip；任何失败都要先定位原因，不修改人工智能链路来掩盖问题。

- [ ] **Step 5: 只提交源代码和测试**

```bash
git add report_generation/external_rag/embodied_client.py \
  report_generation/external_rag/embodied_ingestion.py \
  report_generation/external_rag/embodied_store.py \
  report_generation/external_rag/embodied_manifest.py \
  tests/test_embodied_news_rag.py \
  tests/test_embodied_full_ingestion.py
git commit -m "feat: build resumable full embodied news database"
```

不要添加 `RAG/vector_db_embodied/`、manifest、日志、token 或其他现有未跟踪文件。

## 运行规模和风险边界

- 24 万条是当前专题接口、当前筛选条件下的记录量，不是全网数据总量。
- `status=1` 与 `status=0` 必须分开统计和存储，避免报告引用口径混乱。
- 全量构建会产生百万级片段，实际磁盘和耗时必须通过 1,000 条试运行测量后再估算。
- 全量期间不能逐页 prune；只能在完整快照成功后 prune。
- 详情接口为空时使用列表正文回退；如果列表也没有正文，只记录跳过原因，不生成空向量。
- token 只通过进程环境变量传入，不写源代码、manifest、日志或 Chroma metadata。
- 具身智能使用 `RAG/vector_db_embodied/`，不得写入原有人工智能五类集合。
