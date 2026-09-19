# Cross-Platform Coordinator Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent report-coordinator crashes caused by unbounded concurrent access to the local embodied-intelligence embedding model and vector database while preserving CUDA, MPS, and CPU acceleration selection.

**Architecture:** The coordinator keeps concurrent graph/RAG/LLM work, but limits it to three workers so a large outline cannot create one thread per subsection. The embodied store serializes native model encoding and default-store querying with standard-library locks, and `query_embodied_news` reuses one process-local store instead of creating a Chroma client per task. These changes use only `threading.Lock`, so the same code path runs on Windows, macOS, and Linux.

**Tech Stack:** Python 3, `unittest`, `concurrent.futures`, `threading`, ChromaDB, SentenceTransformers/PyTorch.

---

## File structure

- `report_generation/coordinator_agent.py` — bounds coordinator task concurrency while retaining ordered results and existing fallback behavior.
- `report_generation/external_rag/embodied_store.py` — serializes default-model encoding and default-store query access; caches the default store process-wide.
- `tests/test_coordinator_stability.py` — runs a mocked 20-subsection coordinator request and verifies the worker limit, input ordering, and task-failure fallback.
- `tests/test_embodied_news_rag.py` — verifies that concurrent default-store queries do not overlap `encode()` calls and share one cached default store.

### Task 1: Bound coordinator task concurrency

**Files:**
- Create: `tests/test_coordinator_stability.py`
- Modify: `report_generation/coordinator_agent.py:18-77`

- [x] **Step 1: Write a failing 20-subsection concurrency and ordering test**

```python
class CoordinatorStabilityTest(unittest.TestCase):
    def test_limits_twenty_subsections_to_three_workers_and_preserves_order(self):
        module = importlib.import_module("report_generation.coordinator_agent")
        active = 0
        peak = 0
        lock = threading.Lock()

        def build_task(*, subsection, **_kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return ({"outline_id": subsection["outline_id"]}, [])

        with patch.object(module, "_generate_writing_task_for_subsection", side_effect=build_task):
            result = module.generate_writing_tasks("需求", "标题", _outline_with_twenty_subsections())

        self.assertLessEqual(peak, 3)
        self.assertEqual([item["outline_id"] for item in result["writing_tasks"]], [f"S1.{index}" for index in range(1, 21)])
```

- [x] **Step 2: Run the test to verify the current code fails**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_coordinator_stability.CoordinatorStabilityTest.test_limits_twenty_subsections_to_three_workers_and_preserves_order -v`

Expected: FAIL because the observed peak is 20, exceeding three workers.

- [x] **Step 3: Write a failing task-exception fallback test**

```python
    def test_task_exception_returns_ordered_fallback_warning(self):
        module = importlib.import_module("report_generation.coordinator_agent")
        with patch.object(module, "_generate_writing_task_for_subsection", side_effect=RuntimeError("RAG unavailable")):
            result = module.generate_writing_tasks("需求", "标题", _outline_with_twenty_subsections())

        self.assertEqual(len(result["writing_tasks"]), 20)
        self.assertTrue(all(task["warnings"] for task in result["writing_tasks"]))
        self.assertEqual(result["writing_tasks"][0]["outline_id"], "S1.1")
```

- [x] **Step 4: Run the fallback test to verify the existing behavior remains covered**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_coordinator_stability.CoordinatorStabilityTest.test_task_exception_returns_ordered_fallback_warning -v`

Expected: PASS; this test records the existing degradation behavior before the concurrency change.

- [x] **Step 5: Implement the bounded worker count**

```python
DEFAULT_MAX_COORDINATOR_WORKERS = 3

worker_count = min(DEFAULT_MAX_COORDINATOR_WORKERS, len(final_subsections))
with ThreadPoolExecutor(max_workers=worker_count) as executor:
    future_to_index = {
        executor.submit(
            _generate_writing_task_for_subsection,
            subsection=subsection,
            user_prompt=normalized_prompt,
            report_title=normalized_title,
            industry=normalized_industry,
            top_k=normalized_top_k,
        ): index
        for index, subsection in enumerate(final_subsections)
    }
```

Keep the preallocated `writing_tasks` and index mapping unchanged so `as_completed()` cannot reorder the API response. Keep the existing `future.result()` exception handling unchanged.

- [x] **Step 6: Re-run both coordinator tests**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_coordinator_stability -v`

Expected: PASS; the peak is at most three, task order matches the outline order, and an individual task still yields a fallback warning.

- [x] **Step 7: Commit the coordinator change**

```bash
git add report_generation/coordinator_agent.py tests/test_coordinator_stability.py
git commit -m "fix: bound report coordinator concurrency"
```

### Task 2: Serialize embodied-model inference and reuse the default store

**Files:**
- Modify: `report_generation/external_rag/embodied_store.py:14-125`
- Modify: `tests/test_embodied_news_rag.py:200-350`

- [x] **Step 1: Write a failing concurrent-query encoding test**

```python
    def test_concurrent_default_store_queries_serialize_model_encoding(self):
        module = load_module(self, "report_generation.external_rag.embodied_store")
        active = 0
        peak = 0
        state_lock = threading.Lock()

        class FakeModel:
            def encode(self, documents, **_kwargs):
                nonlocal active, peak
                with state_lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.02)
                with state_lock:
                    active -= 1
                return [[1.0] for _ in documents]

        store = _store_with_fake_collection(module)
        with patch.object(module, "_get_model", return_value=FakeModel()), patch.object(module, "_get_default_store", return_value=store):
            with ThreadPoolExecutor(max_workers=5) as executor:
                list(executor.map(module.query_embodied_news, ["q1", "q2", "q3", "q4", "q5"]))

        self.assertEqual(peak, 1)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_embodied_news_rag.EmbodiedStoreTest.test_concurrent_default_store_queries_serialize_model_encoding -v`

Expected: FAIL because five concurrent `query()` calls can enter `FakeModel.encode()` at once.

- [x] **Step 3: Write a failing default-store reuse test**

```python
    def test_query_embodied_news_reuses_one_default_store(self):
        module = load_module(self, "report_generation.external_rag.embodied_store")
        first = MagicMock()
        with patch.object(module, "EmbodiedNewsStore", return_value=first) as factory:
            module._DEFAULT_STORE = None
            module.query_embodied_news("第一次")
            module.query_embodied_news("第二次")
        factory.assert_called_once_with()
```

- [x] **Step 4: Run the reuse test to verify it fails**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_embodied_news_rag.EmbodiedStoreTest.test_query_embodied_news_reuses_one_default_store -v`

Expected: FAIL because `_get_default_store` does not yet exist and the function constructs a new `EmbodiedNewsStore` for each request.

- [x] **Step 5: Implement standard-library locking and default-store caching**

```python
_MODEL_INFERENCE_LOCK = Lock()
_DEFAULT_STORE_LOCK = Lock()
_DEFAULT_STORE_QUERY_LOCK = Lock()
_DEFAULT_STORE = None

def _encode_with_fallback(model, documents):
    with _MODEL_INFERENCE_LOCK:
        return _encode_with_fallback_unlocked(model, documents)

def _get_default_store() -> EmbodiedNewsStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        with _DEFAULT_STORE_LOCK:
            if _DEFAULT_STORE is None:
                _DEFAULT_STORE = EmbodiedNewsStore()
    return _DEFAULT_STORE
```

Split the existing recursive body into `_encode_with_fallback_unlocked()` so the single outer `_MODEL_INFERENCE_LOCK` does not re-enter a non-reentrant `Lock`. In `query()`, put the one direct `model.encode(...)` call inside `_MODEL_INFERENCE_LOCK`. Make the public helper serialize the shared Chroma collection as well:

```python
def query_embodied_news(query: str, top_k: int = 10) -> Dict[str, Any]:
    with _DEFAULT_STORE_QUERY_LOCK:
        return _get_default_store().query(query, top_k=top_k)
```

This leaves `_device()` unchanged, applies the same standard-library model lock to CUDA/MPS/CPU, and does not add a platform branch.

- [x] **Step 6: Run the affected embodied-store tests**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_embodied_news_rag.EmbodiedStoreTest -v`

Expected: PASS; existing device selection and batch fallback tests remain green, encoding overlap is zero, and two queries build one default store.

- [x] **Step 7: Commit the store change**

```bash
git add report_generation/external_rag/embodied_store.py tests/test_embodied_news_rag.py
git commit -m "fix: serialize embodied rag inference"
```

### Task 3: Run the mocked coordinator regression suite

**Files:**
- Modify: `tests/test_coordinator_stability.py`

- [x] **Step 1: Add a mock-only full pipeline test**

```python
    def test_twenty_mocked_tasks_complete_without_native_rag_or_llm(self):
        module = importlib.import_module("report_generation.coordinator_agent")
        with patch.object(module, "retrieve_industry_graph", return_value={"status": "success", "graph_evidence_blocks": []}), \
             patch.object(module, "retrieve_external_rag", return_value={"status": "success", "evidence_blocks": []}), \
             patch.object(module.llm, "query", return_value="写作要求"):
            result = module.generate_writing_tasks("需求", "标题", _outline_with_twenty_subsections(), industry="embodied")

        self.assertEqual(len(result["writing_tasks"]), 20)
        self.assertEqual(result["warnings"], [])
```

- [x] **Step 2: Run the full mocked test**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_coordinator_stability.CoordinatorStabilityTest.test_twenty_mocked_tasks_complete_without_native_rag_or_llm -v`

Expected: PASS; all 20 tasks are returned without contacting the remote LLM or touching the local 24 GB RAG database.

- [x] **Step 3: Run the focused regression suite and record results**

Run:

```bash
PYTHONPATH=. conda run -n kunlun python -m unittest \
  tests.test_direct_outline_json_recovery \
  tests.test_report_rag_modes \
  tests.test_embodied_news_rag \
  tests.test_coordinator_stability -v
node --test tests/js/test_industry_report_navigation.test.js
```

Expected: all Python and JavaScript tests pass. If a test fails, identify whether it contradicts the intended three-worker limit, lock behavior, or unrelated existing behavior; fix only a regression caused by this plan.

- [x] **Step 4: Commit the final regression test**

```bash
git add tests/test_coordinator_stability.py
git commit -m "test: cover coordinator stability under large outlines"
```

## Self-review

- The plan covers the three observed failure sources: 20 coordinator threads, concurrent `model.encode()`, and repeated Chroma store construction.
- It does not add a platform-specific branch, CPU-only fallback, process start method, file lock, checksum, migration, or feature flag.
- Constants and helper names are consistent across the implementation and tests: `DEFAULT_MAX_COORDINATOR_WORKERS`, `_MODEL_INFERENCE_LOCK`, and `_get_default_store`.
- Mocked pipeline verification deliberately avoids real remote LLM and local RAG data; a failure would signal the coordinator integration itself and should be fixed before any manual UI run.
