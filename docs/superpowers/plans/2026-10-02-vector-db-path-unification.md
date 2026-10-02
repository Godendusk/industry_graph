# 产业报告向量库路径统一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一八个产业报告向量库的路径配置，使页面可用性状态与实际检索目录一致，同时保持 `vector_db_QA` 独立。

**Architecture:** `report_generation/industry_config.py` 是产业报告向量库的唯一路径配置源。每个产业配置包含统一的 `vector_db_path`，并用 `rag_type` 和 `collection_name` 区分传统报告库与专题资讯库；任务卡、传统检索、具身智能检索和专题资讯检索都读取该配置。

**Tech Stack:** Python, Chroma, pytest/unittest, existing JavaScript task-card UI.

---

### Task 1: 扩展产业向量库配置

**Files:**
- Modify: `report_generation/industry_config.py`
- Test: `tests/test_industry_config.py` (create if absent)

- [x] **Step 1: Write failing configuration tests**

Add tests that assert every report industry has a path under `RAG/vector_db_<industry>`, that `ai` and `embodied` point to their real databases, and that `vector_db_QA` is not part of `INDUSTRY_CONFIG`.

```python
from pathlib import Path
from report_generation.industry_config import INDUSTRY_CONFIG


def test_report_industries_use_rag_vector_db_root():
    expected = {
        "ai": "vector_db_ai",
        "embodied": "vector_db_embodied",
        "low_altitude": "vector_db_low_altitude",
        "sea": "vector_db_sea",
        "quantum": "vector_db_quantum",
        "biology": "vector_db_biology",
        "brain": "vector_db_brain",
        "material": "vector_db_material",
    }
    for industry, dirname in expected.items():
        config = INDUSTRY_CONFIG[industry]
        assert Path(config["vector_db_path"]).name == dirname
        assert Path(config["vector_db_path"]).parent.name == "RAG"


def test_qa_database_is_not_report_industry():
    assert "QA" not in INDUSTRY_CONFIG
    assert "qa" not in INDUSTRY_CONFIG
```

- [x] **Step 2: Run the focused tests and verify the old paths fail**

Run: `pytest tests/test_industry_config.py -q`

Expected: FAIL because AI and embodied currently resolve through `report_generation/vector_db` and topic databases use a secondary path field.

- [x] **Step 3: Implement the canonical configuration**

Add `RAG_VECTOR_DB_ROOT`, set every report industry's `vector_db_path` to `RAG/vector_db_<industry>`, add `rag_type` (`report` for AI, `news` for embodied and the six topic industries), and add `collection_name` for news stores. Remove `news_vector_db_path` after all consumers are migrated.

- [x] **Step 4: Run the focused tests**

Run: `pytest tests/test_industry_config.py -q`

Expected: PASS.

- [x] **Step 5: Commit the configuration change**

```bash
git add report_generation/industry_config.py tests/test_industry_config.py
git commit -m "refactor: centralize industry vector db paths"
```

### Task 2: Make task-card availability use the canonical path

**Files:**
- Modify: `report_generation/task_card_agent.py`
- Test: `tests/test_task_card_agent.py`

- [x] **Step 1: Add failing availability tests**

Add tests using temporary Chroma marker files for report and news configurations. Report configuration must require `external_column_id`; news configuration must only require the configured database file.

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from report_generation.task_card_agent import _external_rag_available


def test_external_rag_available_for_news_store_without_column_id():
    with TemporaryDirectory() as tmp:
        path = Path(tmp)
        config = {"rag_type": "news", "vector_db_path": path}
        (path / "chroma.sqlite3").write_text("", encoding="utf-8")
        assert _external_rag_available(config)


def test_external_rag_available_for_real_ai_and_embodied_paths():
    from report_generation.industry_config import INDUSTRY_CONFIG
    for key in ("ai", "embodied"):
        config = INDUSTRY_CONFIG[key]
        assert config["vector_db_path"].name == f"vector_db_{key}"
```

- [x] **Step 2: Run the focused tests and verify the old logic fails**

Run: `pytest tests/test_task_card_agent.py -q`

Expected: FAIL for the news configuration because the current implementation only understands `external_column_id` or `news_vector_db_path`.

- [x] **Step 3: Update `_external_rag_available`**

Implement the rules from the design:

```python
def _external_rag_available(config: dict) -> bool:
    vector_db_path = config.get("vector_db_path")
    if not vector_db_path or not (Path(vector_db_path) / "chroma.sqlite3").is_file():
        return False
    if config.get("rag_type") == "news":
        return True
    return bool(clean_text(config.get("external_column_id")))
```

- [x] **Step 4: Run task-card tests**

Run: `pytest tests/test_task_card_agent.py -q`

Expected: PASS, including the existing column-id regression tests.

- [x] **Step 5: Commit the availability change**

```bash
git add report_generation/task_card_agent.py tests/test_task_card_agent.py
git commit -m "fix: report vector store availability detection"
```

### Task 3: Remove duplicate path mappings from retrieval modules

**Files:**
- Modify: `report_generation/external_rag/vector_store.py`
- Modify: `report_generation/external_rag/embodied_store.py`
- Modify: `RAG/topic_news.py`
- Modify: `report_generation/external_rag/retriever.py`
- Test: `tests/test_topic_news_integration.py`
- Test: `tests/test_rag_storage_separation.py`

- [x] **Step 1: Add route assertions before changing implementations**

Extend retrieval tests to assert that AI uses `INDUSTRY_CONFIG["ai"]["vector_db_path"]`, embodied uses its configured path, and each topic news query uses its configured path and collection name.

- [x] **Step 2: Run the retrieval tests**

Run: `pytest tests/test_topic_news_integration.py tests/test_rag_storage_separation.py -q`

Expected: Existing tests pass or expose the duplicated path assumptions that need replacement.

- [x] **Step 3: Replace module-local path constants with configuration lookups**

Use `get_industry_config(industry)["vector_db_path"]` in the AI and embodied stores. Change `RAG/topic_news.py` to build its supported mapping from the configured topic industries and each config's `collection_name`; retain its query API and metadata behavior.

Keep `retriever.py`'s dispatch behavior unchanged, but ensure every branch receives the configured path through its store module. Do not modify `vector_db_QA` code.

- [ ] **Step 4: Run retrieval integration tests**

Run: `pytest tests/test_topic_news_integration.py tests/test_rag_storage_separation.py tests/test_embodied_news_rag.py -q`

Expected: PASS, with no access to `report_generation/vector_db/*` for the eight report industries.

- [x] **Step 5: Commit retrieval path changes**

```bash
git add report_generation/external_rag/vector_store.py report_generation/external_rag/embodied_store.py RAG/topic_news.py report_generation/external_rag/retriever.py tests/test_topic_news_integration.py tests/test_rag_storage_separation.py
git commit -m "refactor: route report retrieval through industry config"
```

### Task 4: Validate the task-card UI contract and full regression suite

**Files:**
- Modify: none unless a contract mismatch is found in `static/js/modules/industry_report.js`
- Test: existing task-card and retrieval tests

- [ ] **Step 1: Run the complete focused regression set**

Run:

```bash
pytest tests/test_task_card_agent.py tests/test_industry_config.py tests/test_topic_news_integration.py tests/test_rag_storage_separation.py tests/test_embodied_news_rag.py -q
```

Expected: PASS.

- [x] **Step 2: Verify the API payload contract**

Run a task-card generation test and assert every `industry_matches` entry contains `graph_available`, `external_rag_available`, and the expected status. Confirm the frontend label construction in `static/js/modules/industry_report.js` needs no change because it already renders the backend boolean.

- [x] **Step 3: Check the QA boundary**

Run the existing QA-related tests and search for accidental changes:

```bash
rg -n "vector_db_QA|vector_db_qa" RAG report_generation tests
pytest -q
```

Expected: QA paths remain unchanged and the full suite passes.

- [ ] **Step 4: Review the final diff and commit**

```bash
git diff HEAD~3..HEAD --stat
git status --short
git commit --allow-empty -m "test: verify unified report vector db paths"
```

The final review must confirm that only the planned code and tests changed; existing unrelated working-tree files remain untouched.
