import tempfile
import threading
import time
import unittest
from pathlib import Path

from retrieval_core.model_manager import BGE_QUERY_INSTRUCTION, ModelManager, select_device


class EmbeddingModel:
    def __init__(self, *, fail_on_call=None, failure=None, delay=0.0):
        self.calls = []
        self.fail_on_call = fail_on_call
        self.failure = failure or RuntimeError("embedding device failed")
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.state_lock = threading.Lock()

    def encode(self, texts, **kwargs):
        with self.state_lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            call_number = len(self.calls) + 1
            self.calls.append((list(texts), dict(kwargs)))
            if self.delay:
                time.sleep(self.delay)
            if self.fail_on_call == call_number:
                raise self.failure
            return [[float(index), float(index + 1)] for index, _ in enumerate(texts)]
        finally:
            with self.state_lock:
                self.active -= 1


class RerankerModel:
    def __init__(self, *, fail_on_call=None, failure=None, delay=0.0):
        self.calls = []
        self.fail_on_call = fail_on_call
        self.failure = failure or RuntimeError("reranker device failed")
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.state_lock = threading.Lock()

    def predict(self, pairs, **kwargs):
        with self.state_lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            call_number = len(self.calls) + 1
            self.calls.append(([list(pair) for pair in pairs], dict(kwargs)))
            if self.delay:
                time.sleep(self.delay)
            if self.fail_on_call == call_number:
                raise self.failure
            return [index + 0.25 for index, _ in enumerate(pairs)]
        finally:
            with self.state_lock:
                self.active -= 1


class ModelManagerTests(unittest.TestCase):
    def make_manager(self, **kwargs):
        defaults = {
            "embedding_model_path": Path("/virtual/embedding"),
            "reranker_model_path": Path("/virtual/reranker"),
            "mps_available": False,
        }
        defaults.update(kwargs)
        return ModelManager(**defaults)

    def test_select_device_is_mps_or_cpu_only_and_supports_injection(self):
        self.assertEqual(select_device(mps_available=True), "mps")
        self.assertEqual(select_device(mps_available=False), "cpu")

    def test_preferred_device_override_supports_factory_only_construction(self):
        model = EmbeddingModel()
        manager = ModelManager(
            embedding_factory=lambda path, device: model,
            reranker_factory=lambda path, device: RerankerModel(),
            preferred_device="cpu",
        )

        self.assertEqual(manager.embed_documents(["doc"]), [[0.0, 1.0]])
        self.assertEqual(manager.embedding_device, "cpu")
        with self.assertRaisesRegex(ValueError, "preferred_device"):
            ModelManager(
                embedding_factory=lambda path, device: model,
                reranker_factory=lambda path, device: RerankerModel(),
                preferred_device="cuda",
            )

    def test_models_are_lazy_singletons_and_empty_inputs_do_not_load(self):
        embedding_models = []
        reranker_models = []

        def embedding_factory(path, device):
            embedding_models.append(EmbeddingModel())
            return embedding_models[-1]

        def reranker_factory(path, device):
            reranker_models.append(RerankerModel())
            return reranker_models[-1]

        manager = self.make_manager(
            embedding_factory=embedding_factory, reranker_factory=reranker_factory
        )
        self.assertEqual(manager.embed_queries([]), [])
        self.assertEqual(manager.embed_documents([]), [])
        self.assertEqual(manager.rerank_pairs("query", []), [])
        self.assertEqual(embedding_models, [])
        self.assertEqual(reranker_models, [])

        manager.embed_documents(["one"])
        manager.embed_queries(["two"])
        manager.rerank_pairs("q", ["one"])
        manager.rerank_pairs("q", ["two"])

        self.assertEqual(len(embedding_models), 1)
        self.assertEqual(len(reranker_models), 1)
        self.assertEqual(manager.embedding_device, "cpu")
        self.assertEqual(manager.reranker_device, "cpu")

    def test_embedding_arguments_and_query_instruction_exactly_once(self):
        model = EmbeddingModel()
        manager = self.make_manager(embedding_factory=lambda path, device: model)

        documents = manager.embed_documents([" doc-a ", "doc-b"], batch_size=7)
        queries = manager.embed_queries(
            ["产业发展", BGE_QUERY_INSTRUCTION + "已加前缀"]
        )

        self.assertEqual(documents, [[0.0, 1.0], [1.0, 2.0]])
        self.assertEqual(queries, [[0.0, 1.0], [1.0, 2.0]])
        self.assertEqual(model.calls[0][0], [" doc-a ", "doc-b"])
        self.assertEqual(
            model.calls[1][0],
            [BGE_QUERY_INSTRUCTION + "产业发展", BGE_QUERY_INSTRUCTION + "已加前缀"],
        )
        for _, kwargs in model.calls:
            self.assertTrue(kwargs["normalize_embeddings"])
            self.assertFalse(kwargs["show_progress_bar"])
        self.assertEqual(model.calls[0][1]["batch_size"], 7)

    def test_reranker_constructs_pairs_and_returns_plain_floats(self):
        model = RerankerModel()
        manager = self.make_manager(reranker_factory=lambda path, device: model)

        scores = manager.rerank_pairs("q", ["a", "b"], batch_size=9)

        self.assertEqual(scores, [0.25, 1.25])
        self.assertEqual(model.calls, [([["q", "a"], ["q", "b"]], {"batch_size": 9})])

    def test_embedding_and_reranking_capacity_are_independently_serialized(self):
        embedding = EmbeddingModel(delay=0.04)
        reranker = RerankerModel(delay=0.04)
        manager = self.make_manager(
            embedding_factory=lambda path, device: embedding,
            reranker_factory=lambda path, device: reranker,
        )
        errors = []

        def run(function, *args):
            try:
                function(*args)
            except Exception as exc:  # pragma: no cover - assertion reports unexpected errors
                errors.append(exc)

        threads = [
            threading.Thread(target=run, args=(manager.embed_documents, ["a"])),
            threading.Thread(target=run, args=(manager.embed_documents, ["b"])),
            threading.Thread(target=run, args=(manager.rerank_pairs, "q", ["a"])),
            threading.Thread(target=run, args=(manager.rerank_pairs, "q", ["b"])),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(embedding.max_active, 1)
        self.assertEqual(reranker.max_active, 1)

    def test_mps_health_inference_and_later_runtime_failure_reload_cpu_once(self):
        creations = []
        mps_model = EmbeddingModel(fail_on_call=2)
        cpu_model = EmbeddingModel()

        def factory(path, device):
            creations.append((path, device))
            return mps_model if device == "mps" else cpu_model

        manager = self.make_manager(mps_available=True, embedding_factory=factory)

        result = manager.embed_documents(["real input"])
        second = manager.embed_documents(["stays cpu"])

        self.assertEqual(result, [[0.0, 1.0]])
        self.assertEqual(second, [[0.0, 1.0]])
        self.assertEqual(creations, [(Path("/virtual/embedding"), "mps"), (Path("/virtual/embedding"), "cpu")])
        self.assertEqual(len(mps_model.calls), 2)  # health, then failing real inference
        self.assertEqual(len(cpu_model.calls), 2)  # retry, then subsequent inference
        self.assertEqual(manager.embedding_device, "cpu")

    def test_mps_creation_failure_falls_back_but_cpu_failure_propagates(self):
        creations = []

        def factory(path, device):
            creations.append(device)
            if device == "mps":
                raise RuntimeError("MPS backend unavailable")
            return EmbeddingModel(fail_on_call=1, failure=RuntimeError("bad CPU input"))

        manager = self.make_manager(mps_available=True, embedding_factory=factory)

        with self.assertRaisesRegex(RuntimeError, "bad CPU input"):
            manager.embed_documents(["bad"])
        self.assertEqual(creations, ["mps", "cpu"])
        self.assertEqual(manager.embedding_device, "cpu")

    def test_non_device_errors_on_mps_do_not_trigger_fallback(self):
        creations = []

        def factory(path, device):
            creations.append(device)
            return EmbeddingModel(fail_on_call=1, failure=ValueError("invalid input"))

        manager = self.make_manager(mps_available=True, embedding_factory=factory)
        with self.assertRaisesRegex(ValueError, "invalid input"):
            manager.embed_documents(["bad"])
        self.assertEqual(creations, ["mps"])

    def test_reranker_mps_runtime_failure_reloads_cpu_and_retries_once(self):
        creations = []
        mps_model = RerankerModel(fail_on_call=2, failure=NotImplementedError("mps op"))
        cpu_model = RerankerModel()

        def factory(path, device):
            creations.append(device)
            return mps_model if device == "mps" else cpu_model

        manager = self.make_manager(mps_available=True, reranker_factory=factory)
        self.assertEqual(manager.rerank_pairs("q", ["doc"]), [0.25])
        self.assertEqual(creations, ["mps", "cpu"])
        self.assertEqual(manager.reranker_device, "cpu")

    def test_any_mps_fallback_discards_other_loaded_mps_model_for_future_calls(self):
        embedding_creations = []
        reranker_creations = []
        mps_embedding = EmbeddingModel(fail_on_call=2)
        mps_reranker = RerankerModel()
        cpu_reranker = RerankerModel()

        def embedding_factory(path, device):
            embedding_creations.append(device)
            return mps_embedding if device == "mps" else EmbeddingModel()

        def reranker_factory(path, device):
            reranker_creations.append(device)
            return mps_reranker if device == "mps" else cpu_reranker

        manager = self.make_manager(
            mps_available=True,
            embedding_factory=embedding_factory,
            reranker_factory=reranker_factory,
        )
        manager.rerank_pairs("q", ["before fallback"])
        manager.embed_documents(["triggers fallback"])
        manager.rerank_pairs("q", ["after fallback"])

        self.assertEqual(embedding_creations, ["mps", "cpu"])
        self.assertEqual(reranker_creations, ["mps", "cpu"])
        self.assertEqual(manager.reranker_device, "cpu")

    def test_default_factories_reject_missing_paths_lazily_with_exact_path(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        embedding_path = Path(directory.name) / "missing embedding"
        reranker_path = Path(directory.name) / "missing reranker"
        manager = ModelManager(
            embedding_model_path=embedding_path,
            reranker_model_path=reranker_path,
            mps_available=False,
        )

        with self.assertRaises(FileNotFoundError) as embedding_error:
            manager.embed_documents(["doc"])
        with self.assertRaises(FileNotFoundError) as reranker_error:
            manager.rerank_pairs("q", ["doc"])
        self.assertEqual(embedding_error.exception.filename, str(embedding_path))
        self.assertEqual(reranker_error.exception.filename, str(reranker_path))


if __name__ == "__main__":
    unittest.main()
