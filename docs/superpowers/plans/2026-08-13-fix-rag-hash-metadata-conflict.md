# Fix RAG Hash Metadata Conflict Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dense and lexical retrieval candidates use unambiguous chunk-level and source-level hash metadata so real hybrid fusion succeeds.

**Architecture:** `build_report_chunks` will reserve `content_hash` for the generated chunk hash and rename any incoming material-level `content_hash` to `source_content_hash`. Both stores will persist the same canonical chunk metadata, while RRF will continue rejecting unrelated metadata conflicts.

**Tech Stack:** Python, unittest/pytest, Chroma, SQLite FTS5, SentenceTransformers.

---

### Task 1: Add the real-data regression test

**Files:**
- Modify: `tests/test_retrieval_chunker.py`
- Modify: `tests/test_retrieval_fusion_reranker.py`

- [ ] **Step 1: Write a failing chunk metadata test**

Add a test that passes an incoming material-level `content_hash` to `build_report_chunks` and asserts that the output exposes it as `source_content_hash`, while `content_hash` is not copied into metadata.

- [ ] **Step 2: Write a failing fusion test**

Add a test using the generated chunk hash in the dense candidate and the source hash in the lexical candidate; assert that fusion succeeds and preserves the chunk hash plus the source hash under its distinct key.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_retrieval_chunker.py tests/test_retrieval_fusion_reranker.py
```

Expected: the new metadata/fusion assertions fail because the current chunker copies the incoming `content_hash` and RRF sees a conflict.

### Task 2: Normalize source and chunk hashes

**Files:**
- Modify: `retrieval_core/chunker.py:584-616`

- [ ] **Step 1: Implement the minimal metadata normalization**

Before constructing `chunk_metadata`, copy the incoming metadata, remove `content_hash` if present, and store that value under `source_content_hash`. Then set the generated chunk hash in `content_hash` so both dense and lexical stores read the same value.

- [ ] **Step 2: Run the focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_retrieval_chunker.py tests/test_retrieval_fusion_reranker.py
```

Expected: all focused tests pass.

### Task 3: Run the full regression suite

**Files:**
- No additional production files.

- [ ] **Step 1: Run all tests with the repository root on the import path**

Run:

```bash
PYTHONPATH=. pytest -q
```

Expected: 261 passed, 1 skipped, 148 subtests passed or a higher count including the new tests, with zero failures.

### Task 4: Re-run the real AI collection smoke evaluation

**Files:**
- No committed files; use a temporary evaluation script outside the repository.

- [ ] **Step 1: Rebuild a temporary index from 12 materials per AI collection**

Read the five Chroma collections from `/Users/livictor/Desktop/industry/industry_graph/RAG/vector_db`, regroup paragraphs by `material_id`, build v2 chunks, and write dense plus lexical stores under a temporary directory.

- [ ] **Step 2: Validate index consistency and hybrid fusion**

Assert that the temporary index has equal dense/lexical chunk IDs, dimension 768, a valid READY marker, and no metadata conflict during RRF.

- [ ] **Step 3: Report title-query metrics**

Run 60 title queries with library filters and report Recall@1/3/5/10 and MRR for dense, BM25, and hybrid. Treat this as a smoke test, not a generalization benchmark.
