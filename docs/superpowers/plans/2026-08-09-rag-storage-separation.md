# RAG Storage Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the generic Q&A RAG and report-generation RAG open the existing Chroma databases that contain their expected collections.

**Architecture:** Keep all existing Chroma data in place and change only the two module-level default paths. Add a read-only regression test that imports both modules and inspects the actual SQLite collection metadata without mutating either database.

**Tech Stack:** Python 3.10, `unittest`, SQLite, Chroma persistent storage.

---

### Task 1: Add the failing storage-separation regression test

**Files:**
- Create: `tests/test_rag_storage_separation.py`
- Test: `tests/test_rag_storage_separation.py`

- [ ] **Step 1: Write the failing test**

```python
import importlib
import sqlite3
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _database_stats(directory: Path) -> tuple[set[str], int]:
    database_path = directory / "chroma.sqlite3"
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        collections = {
            row[0]
            for row in connection.execute("SELECT name FROM collections")
        }
        embedding_count = connection.execute(
            "SELECT COUNT(*) FROM embeddings"
        ).fetchone()[0]
    finally:
        connection.close()
    return collections, embedding_count


class RagStorageSeparationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_llm_client = sys.modules.get("llm_client")
        sys.modules["llm_client"] = types.SimpleNamespace(llm=object())
        cls.qa_rag = importlib.import_module("RAG.build_vector_db")
        cls.report_rag = importlib.import_module(
            "report_generation.external_rag.vector_store"
        )

    @classmethod
    def tearDownClass(cls):
        if cls.original_llm_client is None:
            sys.modules.pop("llm_client", None)
        else:
            sys.modules["llm_client"] = cls.original_llm_client

    def test_default_directories_are_separate_and_match_existing_data(self):
        self.assertEqual(self.qa_rag.DB_DIR, PROJECT_ROOT / "RAG" / "vector_db1")
        self.assertEqual(
            self.report_rag.VECTOR_DB_DIR,
            PROJECT_ROOT / "RAG" / "vector_db",
        )
        self.assertNotEqual(self.qa_rag.DB_DIR, self.report_rag.VECTOR_DB_DIR)

    def test_default_directories_contain_expected_collections(self):
        qa_collections, qa_embedding_count = _database_stats(self.qa_rag.DB_DIR)
        report_collections, report_embedding_count = _database_stats(
            self.report_rag.VECTOR_DB_DIR
        )
        self.assertIn("knowledge_base", qa_collections)
        self.assertGreater(qa_embedding_count, 0)
        self.assertTrue(
            {
                "report_policy_ai",
                "report_speech_ai",
                "report_expert_view_ai",
                "report_company_case_ai",
                "report_research_report_ai",
            }.issubset(report_collections)
        )
        self.assertGreater(report_embedding_count, 0)
```

- [ ] **Step 2: Run the test to verify it fails for the old paths**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_rag_storage_separation -v
```

Expected: FAIL because `RAG.build_vector_db.DB_DIR` is `RAG/vector_db` and `report_generation.external_rag.vector_store.VECTOR_DB_DIR` is `report_generation/vector_db`.

### Task 2: Point each RAG module at its own existing database

**Files:**
- Modify: `RAG/build_vector_db.py:22`
- Modify: `report_generation/external_rag/vector_store.py:15`
- Test: `tests/test_rag_storage_separation.py`

- [ ] **Step 1: Change the generic Q&A RAG path**

```python
DB_DIR = BASE_DIR / "vector_db1"                 # 通用问答库：knowledge_base
```

- [ ] **Step 2: Change the report RAG path**

```python
VECTOR_DB_DIR = PROJECT_ROOT / "RAG" / "vector_db"  # 报告五库：report_*_ai
```

- [ ] **Step 3: Run the focused test to verify it passes**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_rag_storage_separation -v
```

Expected: 2 tests pass.

### Task 3: Verify the repaired data routing

**Files:**
- Verify: `RAG/vector_db1/chroma.sqlite3`
- Verify: `RAG/vector_db/chroma.sqlite3`

- [ ] **Step 1: Run all discovered unit tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run syntax checks**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m py_compile RAG/build_vector_db.py report_generation/external_rag/vector_store.py tests/test_rag_storage_separation.py
node --check static/js/modules/industry_report.js
```

Expected: both commands exit with status 0.

- [ ] **Step 3: Print final collection and embedding counts read-only**

Run SQLite queries against both `chroma.sqlite3` files in read-only mode.

Expected:

- `RAG/vector_db1`: `knowledge_base`, 26,879 embeddings.
- `RAG/vector_db`: five `report_*_ai` collections, 39,341 embeddings.

No Git commit is included because this workspace has no initial commit and the user did not ask Codex to establish repository history.
