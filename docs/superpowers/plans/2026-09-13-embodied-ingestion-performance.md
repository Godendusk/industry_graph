# 具身智能摄入性能优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐项执行本计划。以下步骤使用复选框（`- [ ]`）进行跟踪。

**目标：** 在不改变具身智能数据口径、向量模型、稳定 ID、metadata 和人工智能链路的前提下，通过跨资讯批量 embedding、批量写入 Chroma 以及 Apple Silicon MPS 加速，缩短 1000 条试运行和后续全量摄入的耗时。

**架构：** 保留 `build_chunks()` 的正文清洗和切片逻辑，把 `EmbodiedNewsStore.upsert()` 扩展为一次接收一页或多个资讯的全部 chunks，统一按批次编码后只执行少量 Chroma upsert。模型设备按 `cuda → mps → cpu` 自动选择；MPS 不可用时自动回退 CPU。manifest 仍在每页成功写入后更新，断点、失败重试、稳定 ID 和完整快照清理规则不变。

**Tech Stack：** Python、PyTorch 2.13、sentence-transformers、本地 `bge-base-zh-v1.5`、Chroma、pytest、Apple Silicon MPS。

---

## 文件职责

- 修改 `report_generation/external_rag/embodied_store.py`：集中负责设备选择、模型加载、跨资讯批量编码和批量 Chroma upsert。
- 修改 `report_generation/external_rag/embodied_ingestion.py`：按页收集所有 chunks，再调用一次批量存储；保持每页完成后才更新 manifest。
- 修改 `tests/test_embodied_full_ingestion.py`：验证一页只进行一次批量存储调用、数据 ID/metadata 不变、失败时不错误推进 manifest。
- 修改或新增 `tests/test_embodied_news_rag.py`：验证设备选择优先级和 MPS 不可用时的 CPU 回退；测试不得要求真实 MPS，使用 monkeypatch。
- 不修改 `report_generation` 中 AI 集合、AI 报告检索逻辑及现有具身智能查询接口。

## Task 1：先为跨资讯批量写入建立回归测试

**Files:**

- Modify: `tests/test_embodied_full_ingestion.py`
- Modify: `tests/test_embodied_news_rag.py`

- [x] **Step 1: 写批量调用行为测试**

让 fake store 记录每次 `upsert()` 的参数，增加测试：两页、每页两条资讯时，摄入流程每页只调用一次 `upsert()`，并且批次内包含该页所有片段。

```python
def test_full_ingestion_batches_all_chunks_in_one_upsert_per_page(tmp_path):
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
```

同时保留现有测试，确保列表已有正文时不调用详情接口。

- [x] **Step 2: 写设备选择测试**

使用 monkeypatch 构造三个设备状态，明确选择规则：CUDA 优先，CUDA 不可用且 MPS 可用时选择 MPS，两者都不可用时选择 CPU。

```python
def test_device_prefers_mps_when_cuda_is_unavailable(monkeypatch):
    import torch
    from report_generation.external_rag import embodied_store

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)

    assert embodied_store._device() == "mps"
```

- [x] **Step 3: 运行新增测试确认其失败**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q \
  tests/test_embodied_full_ingestion.py \
  tests/test_embodied_news_rag.py \
  -k 'batch or batches_all_chunks or device or mps'
```

预期：批量调用测试因当前每条资讯调用一次 `upsert()` 而失败；MPS 测试因当前 `_device()` 只识别 CUDA 而失败。

## Task 2：实现 MPS 自动选择和可控批量参数

**Files:**

- Modify: `report_generation/external_rag/embodied_store.py`
- Test: `tests/test_embodied_news_rag.py`

- [x] **Step 1: 修改设备选择逻辑**

将 `_device()` 改为以下明确顺序，并保留异常回退：

```python
def _device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"
```

`_get_model()` 和 `_load_custom_model()` 继续使用 `_device()`，不复制模型、不修改模型文件。MPS 不可用或 PyTorch 不支持 MPS 时自动使用 CPU。

- [x] **Step 2: 将 embedding 批大小作为 store 的参数**

保持默认值 64 以降低行为变化风险，并允许基准测试传入 128：

```python
class EmbodiedNewsStore:
    def __init__(self, db_dir=VECTOR_DB_DIR, model_path=MODEL_PATH,
                 embedding_batch_size=BATCH_SIZE):
        self.embedding_batch_size = max(1, int(embedding_batch_size))
```

`upsert()` 使用 `self.embedding_batch_size`，不得改变向量归一化、模型路径、集合名称或 ID 生成规则。

- [x] **Step 3: 运行设备与存储回归测试**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q \
  tests/test_embodied_news_rag.py \
  -k 'device or mps or store or upsert'
```

预期：全部通过；测试只验证设备选择，不要求实际在 MPS 上完成模型推理。

## Task 3：按页聚合 chunks 并进行一次批量 upsert

**Files:**

- Modify: `report_generation/external_rag/embodied_ingestion.py`
- Modify: `tests/test_embodied_full_ingestion.py`

- [x] **Step 1: 将单条处理函数改为返回 chunks**

保留详情回退逻辑，但 `_process_full_record()` 返回 `(source_id, chunks)`，不在函数内部调用 `store.upsert()`：

```python
def _process_full_record(client, record, stats):
    source_id = str(record.get("id") or record.get("infoId") or "").strip()
    if not source_id:
        stats["skipped"] += 1
        _append_error(stats, {"stage": "record", "error": "missing source ID"})
        return "", []

    detail = {}
    if not _has_usable_list_text(record):
        try:
            detail = client.get_detail(source_id)
            if isinstance(detail, dict) and detail:
                stats["details_succeeded"] += 1
            else:
                detail = {}
        except Exception as exc:
            stats["detail_fallbacks"] += 1
            _append_error(stats, {
                "stage": "detail", "id": source_id, "error": str(exc),
                "fallback": "list_record",
            })

    chunks = build_chunks(_merge_nonempty(record, detail), SUBJECT_ID)
    if not chunks:
        stats["skipped"] += 1
    return source_id, chunks
```

- [x] **Step 2: 在分页循环中聚合并写入**

每页循环先收集 `page_chunks`，然后只调用一次 `store.upsert(page_chunks)`；只有 upsert 成功后才调用 manifest 的页完成更新。若 upsert 抛错，当前页不得计入完成页，manifest 保留当前 `next_page` 以便恢复。

```python
page_chunks = []
page_source_ids = set()
for record in records:
    source_id, chunks = _process_full_record(client, record, stats)
    if source_id:
        page_source_ids.add(source_id)
        current_source_ids.add(source_id)
    page_chunks.extend(chunks)

if page_chunks:
    written = int(store.upsert(page_chunks))
    stats["chunks_written"] += written

manifest.mark_page_complete(
    page_no=next_page,
    records=len(records),
    chunks=len(page_chunks),
    source_ids=page_source_ids,
)
next_page += 1
```

不能在这里调用 `prune_sources()`；清理仍只允许发生在完整快照结束后。最新 100 条入口可继续逐条处理，或复用同一批量接口，但其结果和清理语义必须保持现有测试兼容。

- [x] **Step 3: 增加批量失败和数据一致性测试**

增加 fake store：第二页 upsert 抛错，断言结果为 `failed`、manifest 的 `next_page` 仍为第二页、`prune_calls == 0`；另验证所有 chunks 的 `id`、`source_id`、`subject_id` 和 768 维向量行为没有改变。

- [x] **Step 4: 运行摄入全量回归测试**

```bash
PYTHONPATH=. conda run -n kunlun python -m pytest -q \
  tests/test_embodied_full_ingestion.py \
  tests/test_embodied_news_rag.py
```

预期：现有具身智能测试全部通过，且不访问线上接口。

## Task 4：执行受控基准测试，不直接启动 24 万条全量任务

**Files:**

- Modify: `report_generation/external_rag/embodied_ingestion.py`（仅当需要增加已有 CLI 参数）
- Create: `tests/benchmark_embodied_ingestion.py`（只在项目已有基准入口缺失时创建）

- [x] **Step 1: 清理或单独指定测试集合**

使用新的测试目录或独立 collection，禁止把基准数据直接混入正式全量 collection。不得删除现有数据库数据。

- [x] **Step 2: 分别测 CPU、MPS 和批大小**

用同一批 1000 条记录、同一模型和同一切片规则，至少记录以下组合：

```text
CPU + embedding_batch_size=64
CPU + embedding_batch_size=128
MPS + embedding_batch_size=64
MPS + embedding_batch_size=128
```

记录总耗时、embedding 耗时、Chroma 写入耗时、生成 chunks 数量、collection count 和失败数。首次 MPS 运行应忽略模型加载时间，另行记录冷启动时间。

- [x] **Step 3: 验证结果一致性**

确认四种组合均满足：记录数相同、chunk 数相同、collection count 相同、查询返回集合名称为 `embodied_news`，且没有写入 AI collection。允许浮点计算存在极小差异，但不得改变文档 ID 和 metadata。

- [x] **Step 4: 根据基准选择生产参数**

默认先采用 MPS + batch size 64；只有在 128 没有内存压力、没有 MPS 算子错误且明显更快时才改为 128。全量命令继续使用 manifest/resume，正式运行前确认 token 通过环境变量提供，不能写入日志或 manifest。

## 验收标准

- MPS 可用时运行日志或只读诊断明确显示设备为 `mps`；不可用时能回退 CPU。
- 每页只产生一次批量 Chroma upsert，embedding 跨资讯聚合，不改变切片内容、ID、metadata、模型和集合名称。
- 失败页不会推进 manifest，也不会触发快照清理；恢复运行从失败页继续。
- 1000 条基准可给出真实 CPU/MPS 和批量大小对比，不再使用未经测量的倍数作为生产承诺。
- 全部相关回归测试通过后，才允许启动约 24 万条正式全量摄入。

## 本次执行结果

在现有具身智能 collection 中读取 1000 个 chunks，并在临时 Chroma 目录中完成四组对比：

| 设备 | batch size | embedding | Chroma upsert | 总耗时 |
| --- | ---: | ---: | ---: | ---: |
| CPU | 64 | 93.817 秒 | 0.718 秒 | 94.680 秒 |
| CPU | 128 | 95.518 秒 | 0.723 秒 | 96.347 秒 |
| MPS | 64 | 48.848 秒 | 0.763 秒 | 50.110 秒 |
| MPS | 128 | 54.049 秒 | 0.755 秒 | 55.357 秒 |

本机选择 `mps + batch size 64`。正式 collection 只读校验结果为 7274 个 chunks、992 个来源、768 维；未被基准写入。

