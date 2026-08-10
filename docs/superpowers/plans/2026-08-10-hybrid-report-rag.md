# Hybrid Report RAG v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a versioned local hybrid retrieval pipeline for industry-report materials using Chinese dense embeddings, SQLite FTS5/BM25, RRF fusion, and cross-encoder reranking while preserving the existing report-generation API and legacy rollback path.

**Architecture:** Add a reusable `retrieval_core` package with typed records and isolated dense, lexical, fusion, reranking, and orchestration components. Add a report-specific adapter that converts external materials to shared chunks and converts shared results back to existing evidence blocks. Build v2 indexes beside the legacy Chroma data and activate them through `legacy`, `compare`, or `hybrid_v2` modes.

**Tech Stack:** Python 3.10, `unittest`, SentenceTransformers, PyTorch MPS/CPU, ChromaDB, SQLite FTS5, jieba, BeautifulSoup.

---

## File map

### Shared retrieval package

- Create `retrieval_core/__init__.py`: public shared retrieval exports.
- Create `retrieval_core/config.py`: environment-backed paths, modes, model names, and candidate limits.
- Create `retrieval_core/schemas.py`: immutable chunk, candidate, and result records.
- Create `retrieval_core/model_manager.py`: lazy embedding/reranker loading, MPS health check, CPU fallback, and inference locks.
- Create `retrieval_core/chunker.py`: structure-aware block merging/splitting and deterministic chunk IDs.
- Create `retrieval_core/lexical_store.py`: SQLite schema, FTS5/BM25 indexing, filters, manifests, and neighbor reads.
- Create `retrieval_core/dense_store.py`: single-collection Chroma v2 read/write and ID validation.
- Create `retrieval_core/fusion.py`: RRF, candidate merging, duplicate control, and per-document caps.
- Create `retrieval_core/reranker.py`: bounded cross-encoder scoring and graceful fallback.
- Create `retrieval_core/pipeline.py`: dense + BM25 + RRF + reranker orchestration.

### Report adapter and migration

- Create `report_generation/external_rag/report_adapter.py`: report query focusing, library routing, material conversion, business adjustment, and evidence compatibility.
- Create `report_generation/external_rag/v2_index.py`: dual-index material upsert/delete, consistency checks, and READY validation.
- Create `scripts/build_report_hybrid_index.py`: dry-run and full v2 build from legacy Chroma or external API material payloads.
- Create `scripts/provision_retrieval_models.py`: explicit model download command; online service never downloads models.
- Create `scripts/evaluate_report_retrieval.py`: JSONL evaluation and legacy/v2 metric comparison.
- Create `scripts/build_report_retrieval_label_set.py`: deterministic 60-query labeling-set generator from indexed materials.
- Modify `report_generation/external_rag/retriever.py`: preserve legacy implementation and add mode selection/compare/fallback.
- Modify `report_generation/external_rag/ingestion.py`: retain legacy writes and add controlled v2 dual-write with complete chunk IDs.
- Modify `report_generation/external_rag/text_utils.py`: preserve structured HTML blocks and tables for the report adapter.
- Modify `README.md`: correct RAG paths and document v2 build, modes, and rollback.

### Tests and evaluation data

- Create `tests/test_retrieval_config_schemas.py`.
- Create `tests/test_retrieval_chunker.py`.
- Create `tests/test_retrieval_lexical_store.py`.
- Create `tests/test_retrieval_dense_store.py`.
- Create `tests/test_retrieval_model_manager.py`.
- Create `tests/test_retrieval_fusion_reranker.py`.
- Create `tests/test_retrieval_pipeline.py`.
- Create `tests/test_report_rag_adapter.py`.
- Create `tests/test_report_rag_v2_index.py`.
- Create `tests/test_report_rag_modes.py`.
- Create `tests/test_report_rag_ingestion_v2.py`.
- Create `tests/test_report_retrieval_evaluation.py`.
- Create `evaluation/report_retrieval/README.md`.
- Generate `evaluation/report_retrieval/labeling_set.jsonl` during the evaluation task.

## Execution prerequisite

Implementation should occur in an isolated feature worktree or branch. The current workspace contains unrelated vector-database and local configuration changes; never stage them with this feature. The untracked local model and vector data remain read-only inputs and must not be copied into Git.

Before Task 1, run:

```bash
git status --short
git branch --show-current
```

Expected: the engineer can identify the feature branch/worktree and distinguish tracked source changes from local `RAG/vector_db*`, model, token, and manifest data.

### Task 1: Shared configuration and typed records

**Files:**
- Create: `retrieval_core/__init__.py`
- Create: `retrieval_core/config.py`
- Create: `retrieval_core/schemas.py`
- Test: `tests/test_retrieval_config_schemas.py`

- [ ] **Step 1: Write the failing configuration and schema tests**

```python
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from retrieval_core.config import RetrievalConfig
from retrieval_core.schemas import ChunkRecord, RetrievalCandidate


class RetrievalConfigSchemasTest(unittest.TestCase):
    def test_defaults_are_versioned_and_local(self):
        with patch.dict(os.environ, {}, clear=True):
            config = RetrievalConfig.for_project(Path("/project"))
        self.assertEqual(config.mode, "legacy")
        self.assertEqual(config.index_root, Path("/project/RAG/indexes/report_v2"))
        self.assertEqual(config.dense_limit, 40)
        self.assertEqual(config.lexical_limit, 40)
        self.assertEqual(config.rerank_limit, 24)
        self.assertEqual(config.final_limit, 10)

    def test_chunk_and_candidate_keep_shared_identity(self):
        chunk = ChunkRecord(
            chunk_id="external:v2:policy:m1:c:0:abcd1234",
            document_id="policy:m1",
            chunk_index=0,
            text="正文",
            embedding_text="标题：测试\n正文：正文",
            search_text="测试 正文",
            token_count=8,
            content_hash="abcd1234",
            metadata={"library": "policy", "material_id": "m1"},
        )
        candidate = RetrievalCandidate.from_chunk(chunk)
        self.assertEqual(candidate.chunk_id, chunk.chunk_id)
        self.assertEqual(candidate.metadata["material_id"], "m1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the missing package failure**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_config_schemas -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'retrieval_core'`.

- [ ] **Step 3: Implement immutable records and validated defaults**

`RetrievalConfig` must expose `for_project(project_root)`, accept `REPORT_RETRIEVAL_MODE`, reject modes outside `legacy`, `compare`, and `hybrid_v2`, and derive model/index paths without downloading anything. `ChunkRecord` must validate non-empty IDs/text and expose optional previous/next IDs. `RetrievalCandidate` must carry dense, BM25, RRF, rerank, business, and final ranks/scores as optional fields.

The public constructor used by later tasks is:

```python
@dataclass(frozen=True)
class RetrievalConfig:
    project_root: Path
    mode: str
    index_root: Path
    embedding_model_path: Path
    reranker_model_path: Path
    dense_limit: int = 40
    lexical_limit: int = 40
    rerank_limit: int = 24
    final_limit: int = 10
    rrf_k: int = 60
    allow_legacy_fallback: bool = True

    @classmethod
    def for_project(cls, project_root: Path) -> "RetrievalConfig":
        root = project_root.resolve()
        mode = os.getenv("REPORT_RETRIEVAL_MODE", "legacy").strip()
        if mode not in {"legacy", "compare", "hybrid_v2"}:
            raise ValueError(f"unsupported retrieval mode: {mode}")
        return cls(
            project_root=root,
            mode=mode,
            index_root=root / "RAG" / "indexes" / "report_v2",
            embedding_model_path=root / "RAG" / "model_store" / "bge-base-zh-v1.5",
            reranker_model_path=root / "RAG" / "model_store" / "bge-reranker-base",
        )
```

- [ ] **Step 4: Run the focused test and the existing storage-separation test**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_config_schemas tests.test_rag_storage_separation -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add retrieval_core/__init__.py retrieval_core/config.py retrieval_core/schemas.py tests/test_retrieval_config_schemas.py
git commit -m "feat: add hybrid retrieval configuration and schemas"
```

### Task 2: Structure-aware report chunking

**Files:**
- Create: `retrieval_core/chunker.py`
- Modify: `report_generation/external_rag/text_utils.py`
- Test: `tests/test_retrieval_chunker.py`

- [ ] **Step 1: Write failing tests for short merging, long splitting, tables, token limits, and IDs**

```python
import unittest

from retrieval_core.chunker import ChunkingConfig, build_report_chunks
from report_generation.external_rag.text_utils import html_to_structured_blocks


class FakeTokenizer:
    def encode(self, text, add_special_tokens=True):
        extra = 2 if add_special_tokens else 0
        return list(range(len(text))) + list(range(extra))


class RetrievalChunkerTest(unittest.TestCase):
    def test_short_blocks_merge_inside_same_heading(self):
        blocks = [
            {"kind": "heading", "text": "建设进展", "level": 2},
            {"kind": "paragraph", "text": "中国移动建设智算中心。"},
            {"kind": "paragraph", "text": "中国电信扩大智能算力供给。"},
        ]
        chunks = build_report_chunks(
            blocks=blocks,
            library="company_case",
            material_id="m1",
            title="央企案例",
            metadata={"publish_date": "2025-01-01"},
            tokenizer=FakeTokenizer(),
            config=ChunkingConfig(min_chars=20, target_chars=40, soft_max_chars=60, hard_max_chars=80, max_tokens=180),
        )
        self.assertEqual(len(chunks), 1)
        self.assertIn("建设进展", chunks[0].embedding_text)
        self.assertIn("中国移动", chunks[0].text)
        self.assertIn("中国电信", chunks[0].text)

    def test_long_paragraph_splits_with_bounded_overlap(self):
        text = "第一句说明建设背景。第二句说明项目进展。第三句说明算力规模。第四句说明应用效果。"
        chunks = build_report_chunks(
            blocks=[{"kind": "paragraph", "text": text}],
            library="research_report",
            material_id="m2",
            title="研究报告",
            metadata={},
            tokenizer=FakeTokenizer(),
            config=ChunkingConfig(min_chars=10, target_chars=24, soft_max_chars=30, hard_max_chars=36, overlap_chars=12, max_tokens=120),
        )
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.token_count <= 120 for chunk in chunks))
        self.assertTrue(all(chunk.chunk_id.startswith("external:v2:research_report:m2:c:") for chunk in chunks))

    def test_html_table_becomes_searchable_rows(self):
        blocks = html_to_structured_blocks("<h2>智算布局</h2><table><tr><th>企业</th><th>规模</th></tr><tr><td>中国移动</td><td>10 EFLOPS</td></tr></table>")
        table_rows = [block for block in blocks if block["kind"] == "table"]
        self.assertEqual(table_rows[0]["text"], "企业：中国移动；规模：10 EFLOPS。")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify missing functions**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_chunker -v
```

Expected: FAIL because `build_report_chunks` and `html_to_structured_blocks` do not exist.

- [ ] **Step 3: Implement structured extraction and deterministic chunking**

Implement `html_to_structured_blocks(raw_html)` so headings update section context, table rows bind headers to values, and scripts/styles are removed. Implement `build_report_chunks(...)` with sentence-boundary splitting, same-section short-block merging, one-sentence overlap only for split long blocks, exact tokenizer validation, and IDs generated by:

```python
def make_chunk_id(library: str, material_id: str, index: int, text: str) -> str:
    digest = hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:8]
    return f"external:v2:{library}:{material_id}:c:{index}:{digest}"
```

Set `previous_chunk_id` and `next_chunk_id` after all IDs are known. Preserve `text`, build `embedding_text` from classification/title/section/text, and build `search_text` through an injectable tokenizer function so tests do not depend on global jieba state.

- [ ] **Step 4: Run chunker tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_chunker -v
```

Expected: all tests PASS and no emitted chunk exceeds its configured token cap.

- [ ] **Step 5: Commit Task 2**

```bash
git add retrieval_core/chunker.py report_generation/external_rag/text_utils.py tests/test_retrieval_chunker.py
git commit -m "feat: add structure-aware report chunking"
```

### Task 3: SQLite FTS5 lexical store

**Files:**
- Create: `retrieval_core/lexical_store.py`
- Test: `tests/test_retrieval_lexical_store.py`

- [ ] **Step 1: Write failing store tests using a temporary database**

```python
import tempfile
import unittest
from pathlib import Path

from retrieval_core.lexical_store import LexicalStore
from retrieval_core.schemas import ChunkRecord


def chunk(chunk_id, document_id, index, text, library="policy"):
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=index,
        text=text,
        embedding_text=text,
        search_text=text.replace("智算中心", "智算中心 智算 中心"),
        token_count=len(text),
        content_hash=chunk_id[-8:],
        metadata={"library": library, "material_id": document_id, "title": "测试资料", "section_path": "建设进展"},
    )


class LexicalStoreTest(unittest.TestCase):
    def test_upsert_search_filter_neighbors_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LexicalStore(Path(directory) / "lexical.sqlite3")
            rows = [
                chunk("c1hash0001", "m1", 0, "中国移动 建设 智算中心"),
                chunk("c2hash0002", "m1", 1, "中国电信 扩大 算力供给"),
                chunk("c3hash0003", "m2", 0, "专家 讨论 人工智能", library="expert_view"),
            ]
            store.replace_document("m1", rows[:2])
            store.replace_document("m2", rows[2:])
            results = store.search("中国移动 智算中心", limit=10, libraries={"policy"})
            self.assertEqual(results[0].chunk_id, "c1hash0001")
            self.assertEqual(store.neighbors("c1hash0001", before=0, after=1)[1].chunk_id, "c2hash0002")
            store.delete_document("m1")
            self.assertEqual(store.search("中国移动", limit=10), [])

    def test_manifest_and_index_metadata_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LexicalStore(Path(directory) / "lexical.sqlite3")
            store.set_index_metadata("embedding_model", "bge-base-zh-v1.5")
            self.assertEqual(store.get_index_metadata("embedding_model"), "bge-base-zh-v1.5")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and verify the missing store failure**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_lexical_store -v
```

Expected: FAIL because `LexicalStore` does not exist.

- [ ] **Step 3: Implement transactional tables and FTS5 synchronization**

Create `documents`, `chunks`, `chunks_fts`, and `index_metadata`. Use one transaction in `replace_document`: delete old FTS rows and chunks for the document, insert all new chunks, then insert FTS rows. The FTS query must join back to `chunks`, apply optional library filters, order by `bm25(chunks_fts, 0.0, 5.0, 4.0, 2.0, 1.0) ASC`, and return `RetrievalCandidate` records with `bm25_rank` and `bm25_score`.

Sanitize FTS input by tokenizing first and joining individually quoted terms with `OR`; never interpolate raw user syntax into `MATCH`.

- [ ] **Step 4: Run lexical tests and SQLite integrity check**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_lexical_store -v
sqlite3 ':memory:' "SELECT sqlite_compileoption_used('ENABLE_FTS5');"
```

Expected: tests PASS and SQLite prints `1`.

- [ ] **Step 5: Commit Task 3**

```bash
git add retrieval_core/lexical_store.py tests/test_retrieval_lexical_store.py
git commit -m "feat: add SQLite BM25 retrieval store"
```

### Task 4: Model manager and Chroma dense store

**Files:**
- Create: `retrieval_core/model_manager.py`
- Create: `retrieval_core/dense_store.py`
- Test: `tests/test_retrieval_model_manager.py`
- Test: `tests/test_retrieval_dense_store.py`

- [ ] **Step 1: Write failing tests with injected model and collection factories**

```python
import unittest
from unittest.mock import Mock

from retrieval_core.dense_store import DenseStore
from retrieval_core.model_manager import ModelManager, select_device


class ModelManagerTest(unittest.TestCase):
    def test_device_prefers_mps_then_cpu(self):
        self.assertEqual(select_device(mps_available=True), "mps")
        self.assertEqual(select_device(mps_available=False), "cpu")

    def test_mps_failure_reloads_embedding_on_cpu_once(self):
        mps_model = Mock()
        mps_model.encode.side_effect = RuntimeError("MPS operator unsupported")
        cpu_model = Mock()
        cpu_model.encode.return_value = [[0.1, 0.2]]
        factory = Mock(side_effect=[mps_model, cpu_model])
        manager = ModelManager(embedding_factory=factory, reranker_factory=Mock(), preferred_device="mps")
        self.assertEqual(manager.embed_queries(["查询"]), [[0.1, 0.2]])
        self.assertEqual(manager.embedding_device, "cpu")
        self.assertEqual(factory.call_count, 2)


class DenseStoreTest(unittest.TestCase):
    def test_query_parses_ids_documents_metadata_and_cosine_distance(self):
        collection = Mock()
        collection.query.return_value = {
            "ids": [["c1"]],
            "documents": [["正文"]],
            "metadatas": [[{"material_id": "m1", "library": "policy"}]],
            "distances": [[0.2]],
        }
        store = DenseStore(collection=collection)
        result = store.search([0.1, 0.2], limit=40, libraries={"policy"})
        self.assertEqual(result[0].chunk_id, "c1")
        self.assertEqual(result[0].dense_rank, 1)
        self.assertEqual(result[0].dense_score, 0.8)
```

- [ ] **Step 2: Run and verify failures**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_model_manager tests.test_retrieval_dense_store -v
```

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement model lifecycle and dense collection wrapper**

`ModelManager` must lazy-load `SentenceTransformer` and `CrossEncoder`, normalize document/query embeddings, wrap query embedding and reranking in separate locks, perform one MPS health attempt, and permanently fall back to CPU after an MPS runtime error. Missing model directories raise `FileNotFoundError` with the exact configured path.

`DenseStore` must use a single `report_external_v2` collection configured for cosine, implement batched upsert/delete/get IDs/search, translate optional library sets into Chroma `where`, and convert cosine distance to `dense_score = 1.0 - distance` while retaining the raw distance in diagnostics.

- [ ] **Step 4: Run focused tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_model_manager tests.test_retrieval_dense_store -v
```

Expected: all tests PASS without loading real model files.

- [ ] **Step 5: Commit Task 4**

```bash
git add retrieval_core/model_manager.py retrieval_core/dense_store.py tests/test_retrieval_model_manager.py tests/test_retrieval_dense_store.py
git commit -m "feat: add local model manager and dense store"
```

### Task 5: RRF fusion and bounded reranking

**Files:**
- Create: `retrieval_core/fusion.py`
- Create: `retrieval_core/reranker.py`
- Test: `tests/test_retrieval_fusion_reranker.py`

- [ ] **Step 1: Write failing deterministic ranking tests**

```python
import unittest

from retrieval_core.fusion import reciprocal_rank_fusion
from retrieval_core.reranker import rerank_candidates
from retrieval_core.schemas import RetrievalCandidate


def candidate(chunk_id, document_id, dense_rank=None, bm25_rank=None):
    return RetrievalCandidate(
        chunk_id=chunk_id,
        document_id=document_id,
        text=chunk_id,
        metadata={"material_id": document_id},
        dense_rank=dense_rank,
        bm25_rank=bm25_rank,
    )


class FusionRerankerTest(unittest.TestCase):
    def test_rrf_merges_same_chunk_and_caps_each_document(self):
        dense = [candidate("both", "m1", dense_rank=1), candidate("dense", "m1", dense_rank=2)]
        lexical = [candidate("both", "m1", bm25_rank=1), candidate("lexical", "m2", bm25_rank=2)]
        fused = reciprocal_rank_fusion(dense, lexical, rrf_k=60, limit=3, per_document_limit=2)
        self.assertEqual(fused[0].chunk_id, "both")
        self.assertEqual(fused[0].dense_rank, 1)
        self.assertEqual(fused[0].bm25_rank, 1)

    def test_reranker_orders_scores_and_falls_back_on_error(self):
        rows = [candidate("a", "m1"), candidate("b", "m2")]
        ranked = rerank_candidates("查询", rows, scorer=lambda pairs: [0.1, 0.9], final_limit=2)
        self.assertEqual([row.chunk_id for row in ranked], ["b", "a"])
        fallback = rerank_candidates("查询", rows, scorer=lambda pairs: (_ for _ in ()).throw(RuntimeError("failed")), final_limit=2)
        self.assertEqual([row.chunk_id for row in fallback], ["a", "b"])
        self.assertTrue(all(row.diagnostics.get("reranker_fallback") for row in fallback))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and verify failures**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_fusion_reranker -v
```

Expected: FAIL because fusion and reranker functions are missing.

- [ ] **Step 3: Implement stable fusion and reranking**

RRF must merge candidates by `chunk_id`, preserve both routes' ranks/scores, compute `1/(k+rank)` for each present route, sort deterministically by descending RRF and then chunk ID, and cap documents before reranking. Reranking must score at most the configured limit, assign `rerank_rank`, preserve RRF order on scorer failure, and never fabricate candidates to reach final_limit.

- [ ] **Step 4: Run tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_fusion_reranker -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add retrieval_core/fusion.py retrieval_core/reranker.py tests/test_retrieval_fusion_reranker.py
git commit -m "feat: add RRF fusion and reranking"
```

### Task 6: Hybrid pipeline and stage-level degradation

**Files:**
- Create: `retrieval_core/pipeline.py`
- Modify: `retrieval_core/__init__.py`
- Test: `tests/test_retrieval_pipeline.py`

- [ ] **Step 1: Write failing orchestration tests with fakes**

```python
import unittest

from retrieval_core.pipeline import HybridRetrievalPipeline


class HybridPipelineTest(unittest.TestCase):
    def test_runs_dense_and_bm25_then_reranks(self):
        events = []
        pipeline = HybridRetrievalPipeline(
            embed_query=lambda query: events.append(("embed", query)) or [0.1],
            dense_search=lambda vector, limit, libraries: events.append(("dense", limit)) or [],
            lexical_search=lambda query, limit, libraries: events.append(("bm25", limit)) or [],
            rerank=lambda query, candidates, limit: events.append(("rerank", limit)) or candidates,
            neighbor_expand=lambda candidates: candidates,
        )
        result = pipeline.retrieve("聚焦查询", libraries={"policy"}, top_k=10)
        self.assertEqual(result.status, "success")
        self.assertEqual([event[0] for event in events], ["embed", "dense", "bm25", "rerank"])

    def test_one_recall_route_failure_returns_other_route(self):
        from retrieval_core.schemas import RetrievalCandidate

        def fail_dense(vector, limit, libraries):
            raise RuntimeError("dense unavailable")

        lexical_row = RetrievalCandidate(
            chunk_id="c1",
            document_id="m1",
            text="正文",
            metadata={"material_id": "m1", "library": "policy"},
            bm25_rank=1,
        )
        pipeline = HybridRetrievalPipeline(
            embed_query=lambda query: [0.1],
            dense_search=fail_dense,
            lexical_search=lambda query, limit, libraries: [lexical_row],
            rerank=lambda query, candidates, limit: candidates,
            neighbor_expand=lambda candidates: candidates,
        )
        result = pipeline.retrieve("查询", libraries=None, top_k=10)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.candidates[0].chunk_id, "c1")
        self.assertEqual(result.warnings[0]["stage"], "dense")
```

- [ ] **Step 2: Run and verify the missing pipeline failure**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_pipeline -v
```

Expected: FAIL because `HybridRetrievalPipeline` does not exist.

- [ ] **Step 3: Implement explicit stage orchestration**

Implement `retrieve(query, libraries, top_k)` with measured stages: embed, dense, lexical, fusion, rerank, business adjustment hook, and neighbor expansion. Dense and lexical failures become structured warnings; both failing returns `status="error"`. Reranker failure preserves RRF output. The result must contain timings, warnings, candidate counts, and retrieval version `hybrid_v2`.

- [ ] **Step 4: Run pipeline and lower-level tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_retrieval_pipeline tests.test_retrieval_fusion_reranker tests.test_retrieval_lexical_store tests.test_retrieval_dense_store -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 6**

```bash
git add retrieval_core/pipeline.py retrieval_core/__init__.py tests/test_retrieval_pipeline.py
git commit -m "feat: orchestrate hybrid retrieval pipeline"
```

### Task 7: Report query adapter and evidence compatibility

**Files:**
- Create: `report_generation/external_rag/report_adapter.py`
- Test: `tests/test_report_rag_adapter.py`

- [ ] **Step 1: Write failing adapter tests**

```python
import unittest

from report_generation.external_rag.report_adapter import (
    build_report_query,
    route_libraries,
    to_evidence_blocks,
)
from retrieval_core.schemas import RetrievalCandidate


class ReportRagAdapterTest(unittest.TestCase):
    def test_focus_query_drops_generic_template_tail(self):
        raw = "\n".join([
            "用户需求：分析央企智算中心近三年进展",
            "报告标题：人工智能产业报告",
            "当前一级标题：产业发展现状",
            "当前二级标题：央企智算中心布局",
            "检索目标：检索产业链结构、竞争格局、问题、政策、案例和建议依据。",
        ])
        query = build_report_query(raw)
        self.assertIn("央企智算中心布局", query.semantic_query)
        self.assertNotIn("问题、政策、案例和建议", query.semantic_query)

    def test_policy_section_soft_routes_policy_and_speech(self):
        self.assertEqual(route_libraries("政策环境与监管要求").preferred, {"policy", "speech"})

    def test_evidence_shape_remains_compatible(self):
        row = RetrievalCandidate(
            chunk_id="c1",
            document_id="m1",
            text="政策正文",
            metadata={"library": "policy", "classification_name": "政策法规", "material_id": "m1", "title": "政策", "publish_date": "2025-01-01", "source_address": "https://example.test", "chunk_index": 2},
            rerank_rank=1,
            rerank_score=0.9,
        )
        block = to_evidence_blocks([row])[0]
        self.assertEqual(block["citation_id"], "外部资料1")
        self.assertEqual(block["paragraph_index"], 2)
        self.assertEqual(block["text"], "政策正文")
        self.assertEqual(block["retrieval_version"], "hybrid_v2")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and verify missing adapter functions**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_adapter -v
```

Expected: FAIL because `report_adapter` does not exist.

- [ ] **Step 3: Implement deterministic query focusing and soft routing**

Parse labeled report queries, prioritize current subsection, parent section, report title, and user requirement, cap the semantic query by tokenizer budget, and derive BM25 terms with the versioned jieba dictionary. Implement soft routes for policy, company case, expert/research, and general sections; pipeline first queries preferred libraries and expands to all libraries only when fewer than top_k viable candidates remain. Convert results to existing evidence fields plus optional diagnostics.

- [ ] **Step 4: Run adapter tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_adapter -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 7**

```bash
git add report_generation/external_rag/report_adapter.py tests/test_report_rag_adapter.py
git commit -m "feat: adapt report queries and evidence for hybrid retrieval"
```

### Task 8: Versioned dual-index writer and READY validation

**Files:**
- Create: `report_generation/external_rag/v2_index.py`
- Test: `tests/test_report_rag_v2_index.py`

- [ ] **Step 1: Write failing consistency and failure-state tests**

```python
import unittest
from unittest.mock import Mock

from report_generation.external_rag.v2_index import V2IndexWriter


class ReportRagV2IndexTest(unittest.TestCase):
    def test_upsert_requires_dense_and_lexical_ids_to_match(self):
        dense = Mock()
        lexical = Mock()
        dense.ids_for_document.return_value = {"c1", "c2"}
        lexical.ids_for_document.return_value = {"c1", "c2"}
        writer = V2IndexWriter(dense=dense, lexical=lexical)
        result = writer.upsert_document("m1", [Mock(chunk_id="c1"), Mock(chunk_id="c2")])
        self.assertEqual(result.status, "success")

    def test_mismatch_marks_document_inconsistent_and_blocks_ready(self):
        dense = Mock()
        lexical = Mock()
        dense.ids_for_document.return_value = {"c1"}
        lexical.ids_for_document.return_value = {"c1", "c2"}
        writer = V2IndexWriter(dense=dense, lexical=lexical)
        result = writer.upsert_document("m1", [Mock(chunk_id="c1"), Mock(chunk_id="c2")])
        self.assertEqual(result.status, "inconsistent")
        self.assertFalse(writer.can_mark_ready(expected_dimension=768))
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_v2_index -v
```

Expected: FAIL because `V2IndexWriter` is missing.

- [ ] **Step 3: Implement two-store upsert, repair state, and READY checks**

Write lexical data transactionally, encode and upsert Dense data in bounded batches, delete stale IDs, compare per-document and whole-index ID sets, and persist `success` or `inconsistent` state in SQLite. `mark_ready()` must verify dimension 768, model/chunker versions, zero inconsistent documents, exact ID equality, and token limits before atomically writing `READY`.

- [ ] **Step 4: Run v2 index tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_v2_index -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 8**

```bash
git add report_generation/external_rag/v2_index.py tests/test_report_rag_v2_index.py
git commit -m "feat: add consistent report v2 index writer"
```

### Task 9: Dry-run and full index builder

**Files:**
- Create: `scripts/build_report_hybrid_index.py`
- Create: `scripts/provision_retrieval_models.py`
- Test: extend `tests/test_report_rag_v2_index.py`

- [ ] **Step 1: Add failing tests for legacy grouping and build reports**

Add a fake legacy client containing the five current collection names. Assert the builder groups rows by `library + material_id`, orders old paragraphs by `paragraph_index`, runs the new chunker, emits counts/token percentiles in dry-run mode, performs no store writes in dry-run, and refuses to create READY when models are missing or ID sets differ.

The test entry point is:

```python
from unittest.mock import Mock

from scripts.build_report_hybrid_index import build_from_legacy


class FakeCollection:
    def get(self, include):
        return {
            "ids": ["old-2", "old-1"],
            "documents": ["第二段说明建设进展。", "第一段说明建设背景。"],
            "metadatas": [
                {"library": "policy", "material_id": "m1", "paragraph_index": 1, "title": "政策资料"},
                {"library": "policy", "material_id": "m1", "paragraph_index": 0, "title": "政策资料"},
            ],
        }


class FakeLegacyClient:
    def get_collection(self, name):
        return FakeCollection()


class FakeTokenizer:
    def encode(self, text, add_special_tokens=True):
        return list(range(len(text) + (2 if add_special_tokens else 0)))


fake_writer = Mock()
report = build_from_legacy(
    legacy_client=FakeLegacyClient(),
    writer=fake_writer,
    tokenizer=FakeTokenizer(),
    dry_run=True,
)
self.assertEqual(report["source"], "legacy_chroma")
self.assertFalse(fake_writer.upsert_document.called)
self.assertIn("p95_tokens", report["chunks"])
```

- [ ] **Step 2: Run the test and verify missing builder behavior**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_v2_index -v
```

Expected: the new builder test FAILS.

- [ ] **Step 3: Implement explicit model provisioning**

`scripts/provision_retrieval_models.py` must accept `--embedding`, `--reranker`, and `--target-root`, call `huggingface_hub.snapshot_download` only from this explicit operator command, and print resolved local paths. It must never be imported by online retrieval code.

- [ ] **Step 4: Implement legacy-Chroma migration and API-payload build modes**

The builder CLI must support:

```bash
python scripts/build_report_hybrid_index.py --source legacy-chroma --dry-run
python scripts/build_report_hybrid_index.py --source legacy-chroma --build
python scripts/build_report_hybrid_index.py --source payload-directory --payload-dir /absolute/path --build
```

Legacy mode reads stored documents and metadata without external network calls. Payload-directory mode consumes saved external API JSON/HTML and enables table extraction. Both build into a staging index root, write `build_report.json`, validate, then publish through a READY marker. They must not delete or mutate `RAG/vector_db`.

- [ ] **Step 5: Run tests and a read-only dry-run against local legacy data**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_v2_index -v
/opt/miniconda3/bin/conda run -n kunlun python scripts/build_report_hybrid_index.py --source legacy-chroma --dry-run
```

Expected: tests PASS; dry-run reports five legacy libraries, material/chunk counts, merge/split counts, and token percentiles without creating `RAG/indexes/report_v2/READY`.

- [ ] **Step 6: Commit Task 9**

```bash
git add scripts/build_report_hybrid_index.py scripts/provision_retrieval_models.py tests/test_report_rag_v2_index.py
git commit -m "feat: add versioned report hybrid index builder"
```

### Task 10: Retrieval modes, shadow comparison, and legacy fallback

**Files:**
- Modify: `report_generation/external_rag/retriever.py`
- Modify: `report_generation/external_rag/__init__.py`
- Test: `tests/test_report_rag_modes.py`

- [ ] **Step 1: Write failing mode tests**

```python
import unittest
from unittest.mock import patch

from report_generation.external_rag.retriever import retrieve_external_rag


class ReportRagModesTest(unittest.TestCase):
    def test_legacy_returns_existing_result(self):
        with patch("report_generation.external_rag.retriever._mode", return_value="legacy"), patch("report_generation.external_rag.retriever._retrieve_legacy", return_value={"status": "success", "evidence_blocks": [{"citation_id": "外部资料1"}]}) as legacy:
            result = retrieve_external_rag("查询", top_k=10)
        self.assertEqual(result["status"], "success")
        legacy.assert_called_once()

    def test_compare_returns_legacy_and_logs_v2_difference(self):
        with patch("report_generation.external_rag.retriever._mode", return_value="compare"), patch("report_generation.external_rag.retriever._retrieve_legacy", return_value={"status": "success", "evidence_blocks": []}), patch("report_generation.external_rag.retriever._retrieve_hybrid", return_value={"status": "success", "evidence_blocks": [{"material_id": "m1"}]}), patch("report_generation.external_rag.retriever._log_comparison") as log:
            result = retrieve_external_rag("查询", top_k=10)
        self.assertEqual(result["evidence_blocks"], [])
        log.assert_called_once()

    def test_hybrid_failure_can_fallback_to_legacy(self):
        with patch("report_generation.external_rag.retriever._mode", return_value="hybrid_v2"), patch("report_generation.external_rag.retriever._retrieve_hybrid", return_value={"status": "error", "message": "not ready"}), patch("report_generation.external_rag.retriever._retrieve_legacy", return_value={"status": "success", "evidence_blocks": []}):
            result = retrieve_external_rag("查询", top_k=10)
        self.assertEqual(result["retrieval_fallback"], "legacy")
```

- [ ] **Step 2: Run and verify missing mode behavior**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_modes -v
```

Expected: FAIL because mode dispatch functions are absent.

- [ ] **Step 3: Refactor current code into `_retrieve_legacy` and add v2 dispatch**

Preserve the current legacy algorithm byte-for-byte where practical. Add `_retrieve_hybrid`, READY validation, report adapter conversion, structured timings/warnings, compare logging, and explicit fallback markers. `compare` must return the legacy result and must never delay the request indefinitely; protect shadow execution with a configurable timeout and log timeout as a comparison warning.

- [ ] **Step 4: Run mode and upstream compatibility tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_modes tests.test_report_rag_adapter tests.test_rag_storage_separation -v
```

Expected: all tests PASS and the default mode remains legacy.

- [ ] **Step 5: Commit Task 10**

```bash
git add report_generation/external_rag/retriever.py report_generation/external_rag/__init__.py tests/test_report_rag_modes.py
git commit -m "feat: add report retrieval modes and shadow fallback"
```

### Task 11: Incremental dual-write integration

**Files:**
- Modify: `report_generation/external_rag/ingestion.py`
- Modify: `report_generation/external_rag/text_utils.py`
- Test: `tests/test_report_rag_ingestion_v2.py`

- [ ] **Step 1: Write failing dual-write tests with no network or real models**

```python
import unittest
from unittest.mock import Mock, patch

from report_generation.external_rag.ingestion import _ingest_record


class ReportRagIngestionV2Test(unittest.TestCase):
    def test_success_manifest_contains_v2_chunk_ids(self):
        client = Mock()
        client.query_by_id.return_value = {"title": "政策", "contentWithTag": "<h2>目标</h2><p>到2027年形成一批具有竞争力的人工智能产业集群和示范项目。</p>"}
        with patch("report_generation.external_rag.ingestion.upsert_paragraphs"), patch("report_generation.external_rag.ingestion._v2_enabled", return_value=True), patch("report_generation.external_rag.ingestion._upsert_v2_material", return_value=["external:v2:policy:m1:c:0:abcd1234"]):
            result = _ingest_record("policy", {"classification_type": "1", "classification_name": "政策法规"}, client, {"id": "m1"}, None)
        self.assertEqual(result["manifest_record"]["v2_chunk_ids"], ["external:v2:policy:m1:c:0:abcd1234"])

    def test_v2_failure_preserves_legacy_write_and_marks_partial(self):
        client = Mock()
        client.query_by_id.return_value = {"title": "政策", "contentWithTag": "<p>这是一段足够长的政策资料正文，用于验证双写失败时旧索引仍然成功。</p>"}
        with patch("report_generation.external_rag.ingestion.upsert_paragraphs"), patch("report_generation.external_rag.ingestion._v2_enabled", return_value=True), patch("report_generation.external_rag.ingestion._upsert_v2_material", side_effect=RuntimeError("v2 failed")):
            result = _ingest_record("policy", {"classification_type": "1", "classification_name": "政策法规"}, client, {"id": "m1"}, None)
        self.assertEqual(result["manifest_record"]["v2_status"], "error")
        self.assertIn("v2 failed", result["manifest_record"]["v2_error"])
```

- [ ] **Step 2: Run and verify missing v2 manifest behavior**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_ingestion_v2 -v
```

Expected: FAIL because v2 dual-write fields and helpers are absent.

- [ ] **Step 3: Add structured-block conversion and controlled v2 writes**

Keep legacy `paragraphs` and `upsert_paragraphs` during the migration period. When v2 indexing is enabled and READY infrastructure exists, convert the same raw source to structured blocks, build v2 chunks, call `V2IndexWriter`, and record `v2_status`, `v2_chunk_ids`, `v2_error`, `chunker_version`, and `embedding_model` in the manifest. A v2 failure must not falsify legacy success, but must be visible as partial v2 state and logs.

- [ ] **Step 4: Run ingestion and all retrieval tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_rag_ingestion_v2 tests.test_report_rag_v2_index tests.test_report_rag_modes -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 11**

```bash
git add report_generation/external_rag/ingestion.py report_generation/external_rag/text_utils.py tests/test_report_rag_ingestion_v2.py
git commit -m "feat: dual-write external materials to report v2 index"
```

### Task 12: Evaluation harness, labeling set, docs, and final verification

**Files:**
- Create: `scripts/evaluate_report_retrieval.py`
- Create: `scripts/build_report_retrieval_label_set.py`
- Create: `evaluation/report_retrieval/README.md`
- Generate: `evaluation/report_retrieval/labeling_set.jsonl`
- Create: `tests/test_report_retrieval_evaluation.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing metric and labeling-generator tests**

```python
import unittest

from scripts.evaluate_report_retrieval import evaluate_ranked_materials
from scripts.build_report_retrieval_label_set import allocate_library_samples


class ReportRetrievalEvaluationTest(unittest.TestCase):
    def test_recall_mrr_and_ndcg(self):
        metrics = evaluate_ranked_materials(
            ranked_ids=["m2", "m1", "m3"],
            relevant_ids={"m1", "m4"},
            k=3,
        )
        self.assertEqual(metrics["recall_at_k"], 0.5)
        self.assertEqual(metrics["mrr"], 0.5)
        self.assertGreater(metrics["ndcg_at_k"], 0.0)

    def test_sixty_examples_are_balanced_across_five_libraries(self):
        allocation = allocate_library_samples(["policy", "speech", "expert_view", "company_case", "research_report"], total=60)
        self.assertEqual(sum(allocation.values()), 60)
        self.assertTrue(all(value == 12 for value in allocation.values()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and verify missing evaluation functions**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python -m unittest tests.test_report_retrieval_evaluation -v
```

Expected: FAIL because evaluation scripts do not exist.

- [ ] **Step 3: Implement metrics and deterministic labeling-set generation**

The labeling generator must sample 12 materials from each of the five libraries using a fixed seed, create one factual/exact query and one semantic query candidate per sampled material, then select 60 balanced rows with fields:

```json
{"query_id":"policy-001","query":"政策标题或人工审核后的问题","intent":"exact","preferred_libraries":["policy"],"relevant_material_ids":["material-id"],"review_status":"needs_human_review"}
```

It must not mark the set production-ready until a human changes every `review_status` to `approved`. The evaluator must reject unapproved rows unless `--allow-unreviewed` is explicitly passed for development diagnostics.

- [ ] **Step 4: Document operation and dependency assumptions**

Confirm the existing environment already contains SentenceTransformers, PyTorch, ChromaDB, jieba, BeautifulSoup, and SQLite FTS5, so no dependency file change is required. Update `README.md` with model provisioning, dry-run, full build, `REPORT_RETRIEVAL_MODE`, compare logs, evaluation commands, rollback to legacy, and the fact that legacy-Chroma migration cannot recover table text that v1 never extracted.

- [ ] **Step 5: Generate the labeling set and run unit tests**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python scripts/build_report_retrieval_label_set.py --output evaluation/report_retrieval/labeling_set.jsonl --total 60
/opt/miniconda3/bin/conda run -n kunlun python -m unittest discover -s tests -v
```

Expected: exactly 60 JSONL rows with 12 per library and all unit tests PASS. Rows remain `needs_human_review` until domain review.

- [ ] **Step 6: Provision real models with explicit network approval**

Run only after the operator approves model downloads:

```bash
/opt/miniconda3/bin/conda run -n kunlun python scripts/provision_retrieval_models.py --embedding BAAI/bge-base-zh-v1.5 --reranker BAAI/bge-reranker-base --target-root RAG/model_store
```

Expected: both local model directories exist and online retrieval performs no network access.

- [ ] **Step 7: Build the real v2 index and verify READY**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python scripts/build_report_hybrid_index.py --source legacy-chroma --dry-run
/opt/miniconda3/bin/conda run -n kunlun python scripts/build_report_hybrid_index.py --source legacy-chroma --build
test -f RAG/indexes/report_v2/READY
```

Expected: build report records model `bge-base-zh-v1.5`, dimension 768, zero token-limit violations, zero inconsistent documents, exact Dense/BM25 ID equality, and READY exists.

- [ ] **Step 8: Run real local smoke tests in all modes**

Run:

```bash
REPORT_RETRIEVAL_MODE=legacy /opt/miniconda3/bin/conda run -n kunlun python -c "from report_generation.external_rag.retriever import retrieve_external_rag; r=retrieve_external_rag('央企智算中心近三年建设进展', 10); print(r['status'], len(r['evidence_blocks']))"
REPORT_RETRIEVAL_MODE=compare /opt/miniconda3/bin/conda run -n kunlun python -c "from report_generation.external_rag.retriever import retrieve_external_rag; r=retrieve_external_rag('央企智算中心近三年建设进展', 10); print(r['status'], len(r['evidence_blocks']))"
REPORT_RETRIEVAL_MODE=hybrid_v2 /opt/miniconda3/bin/conda run -n kunlun python -c "from report_generation.external_rag.retriever import retrieve_external_rag; r=retrieve_external_rag('央企智算中心近三年建设进展', 10); print(r['status'], len(r['evidence_blocks']), r.get('retrieval_version'))"
```

Expected: all modes return success; compare returns legacy evidence while logging v2; hybrid returns up to 10 v2 evidence blocks.

- [ ] **Step 9: Run evaluation after human labels are approved**

Run:

```bash
/opt/miniconda3/bin/conda run -n kunlun python scripts/evaluate_report_retrieval.py --dataset evaluation/report_retrieval/labeling_set.jsonl --compare legacy hybrid_v2 --output evaluation/report_retrieval/latest_results.json
```

Expected: output includes Recall@10, nDCG@10, MRR, duplicate rate, P50/P95 latency, per-intent metrics, and human-review coverage. Hybrid Recall@10 and nDCG@10 are not below legacy and at least one is higher before changing the default mode.

- [ ] **Step 10: Run final syntax, diff, and repository checks**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/industry-rag-pycache /opt/miniconda3/bin/conda run -n kunlun python -m py_compile retrieval_core/*.py report_generation/external_rag/*.py scripts/build_report_hybrid_index.py scripts/provision_retrieval_models.py scripts/evaluate_report_retrieval.py scripts/build_report_retrieval_label_set.py
git diff --check
git status --short
```

Expected: compilation and diff checks pass. Only intended source, tests, docs, and evaluation fixtures are staged; local models, Chroma files, SQLite indexes, READY, logs, tokens, and manifests are not staged.

- [ ] **Step 11: Commit Task 12**

```bash
git add scripts/evaluate_report_retrieval.py scripts/build_report_retrieval_label_set.py evaluation/report_retrieval/README.md evaluation/report_retrieval/labeling_set.jsonl tests/test_report_retrieval_evaluation.py README.md
git commit -m "test: add report hybrid retrieval evaluation and operations"
```

## Final integration review

After all task commits:

```bash
git log --oneline --decorate -15
git diff main...HEAD --stat
/opt/miniconda3/bin/conda run -n kunlun python -m unittest discover -s tests -v
```

Review the implementation against every section of `docs/superpowers/specs/2026-08-10-hybrid-report-rag-design.md`. Do not enable `hybrid_v2` as the default until the 60-query dataset is human-approved and the acceptance metrics pass. Keep `legacy` as the default during code merge and model/index provisioning.
