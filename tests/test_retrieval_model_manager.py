import tempfile
import threading
import time
import unittest
from pathlib import Path

from retrieval_core.model_manager import (
    BGE_QUERY_INSTRUCTION,
    ModelManager,
    _is_mps_device_error,
    select_device,
)


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

    def test_mps_error_classifier_is_narrow_and_covers_device_failures(self):
        device_errors = (
            NotImplementedError("operator not implemented for MPS"),
            RuntimeError("not implemented for MPS"),
            RuntimeError(
                "The operator aten::foo is not currently implemented for the MPS device."
            ),
            RuntimeError("not supported on the MPS device"),
            RuntimeError("PyTorch is not linked with support for mps devices"),
            RuntimeError("MPS backend out of memory"),
            RuntimeError("MPS device is not available"),
            RuntimeError("placeholder storage has not been allocated on MPS"),
            RuntimeError("Metal backend failure"),
            RuntimeError("Metal allocation failed"),
            RuntimeError("Metal device failure"),
            RuntimeError("MPS backend is not supported on this device"),
            RuntimeError("MPS device not found"),
            RuntimeError("Metal device could not be initialized"),
            RuntimeError("MPS does not support cumsum op with int64 input"),
            RuntimeError("MPS: out of memory"),
        )
        application_errors = (
            RuntimeError("invalid user input"),
            RuntimeError("shape mismatch"),
            RuntimeError("bad batch"),
            RuntimeError("application error"),
            RuntimeError("MPS input invalid"),
            RuntimeError("MPS business rule failed"),
            RuntimeError("Metal document invalid"),
            NotImplementedError("unrelated feature"),
            NotImplementedError("MPS input validation is not implemented"),
            ValueError("MPS input invalid"),
            RuntimeError("backend is not supported on this device"),
            RuntimeError("device not found"),
            RuntimeError("operator does not support int64 input"),
            RuntimeError("out of memory"),
        )

        self.assertTrue(all(_is_mps_device_error(error) for error in device_errors))
        self.assertFalse(any(_is_mps_device_error(error) for error in application_errors))

    def test_explicit_mps_operator_failure_retries_on_cpu_exactly_once(self):
        creations = []

        def factory(path, device):
            creations.append(device)
            if device == "mps":
                raise RuntimeError("MPS does not support cumsum op with int64 input")
            return EmbeddingModel()

        manager = self.make_manager(mps_available=True, embedding_factory=factory)

        self.assertEqual(manager.embed_documents(["doc"]), [[0.0, 1.0]])
        self.assertEqual(manager.embed_documents(["later"]), [[0.0, 1.0]])
        self.assertEqual(creations, ["mps", "cpu"])
        self.assertEqual(manager.embedding_device, "cpu")

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
        mps_model = EmbeddingModel(
            fail_on_call=2,
            failure=RuntimeError("not supported on the MPS device"),
        )
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

    def test_currently_not_implemented_pytorch_operator_reloads_embedding_on_cpu(self):
        creations = []
        mps_model = EmbeddingModel(
            fail_on_call=2,
            failure=RuntimeError(
                "The operator aten::foo is not currently implemented for the MPS device."
            ),
        )
        cpu_model = EmbeddingModel()

        def factory(path, device):
            creations.append(device)
            return mps_model if device == "mps" else cpu_model

        manager = self.make_manager(mps_available=True, embedding_factory=factory)

        self.assertEqual(manager.embed_documents(["doc"]), [[0.0, 1.0]])
        self.assertEqual(creations, ["mps", "cpu"])
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

    def test_arbitrary_runtime_from_mps_factories_propagates_without_cpu_fallback(self):
        failures = (
            RuntimeError("MPS business rule failed"),
            NotImplementedError("unrelated feature"),
        )
        for component in ("embedding", "reranker"):
            for failure in failures:
                with self.subTest(component=component, failure=type(failure).__name__):
                    creations = []

                    def failing_factory(path, device):
                        creations.append(device)
                        raise failure

                    manager = self.make_manager(
                        mps_available=True,
                        embedding_factory=(
                            failing_factory
                            if component == "embedding"
                            else lambda path, device: EmbeddingModel()
                        ),
                        reranker_factory=(
                            failing_factory
                            if component == "reranker"
                            else lambda path, device: RerankerModel()
                        ),
                    )
                    with self.assertRaises(type(failure)) as caught:
                        if component == "embedding":
                            manager.embed_documents(["doc"])
                        else:
                            manager.rerank_pairs("q", ["doc"])

                    self.assertIs(caught.exception, failure)
                    self.assertEqual(creations, ["mps"])
                    self.assertIsNone(
                        manager.embedding_device
                        if component == "embedding"
                        else manager.reranker_device
                    )

    def test_arbitrary_runtime_from_mps_health_check_does_not_fallback(self):
        failures = (
            RuntimeError("MPS input invalid"),
            NotImplementedError("unrelated health feature"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                creations = []

                def factory(path, device):
                    creations.append(device)
                    return EmbeddingModel(fail_on_call=1, failure=failure)

                manager = self.make_manager(
                    mps_available=True, embedding_factory=factory
                )
                with self.assertRaises(type(failure)) as caught:
                    manager.embed_documents(["doc"])

                self.assertIs(caught.exception, failure)
                self.assertEqual(creations, ["mps"])
                self.assertIsNone(manager.embedding_device)

    def test_arbitrary_runtime_from_mps_query_document_and_rerank_propagates(self):
        cases = (
            ("query", RuntimeError("MPS input invalid")),
            ("document", NotImplementedError("unrelated document feature")),
            ("rerank", RuntimeError("Metal document invalid")),
        )
        for operation, failure in cases:
            with self.subTest(operation=operation):
                creations = []
                if operation == "rerank":
                    model = RerankerModel(fail_on_call=2, failure=failure)

                    def factory(path, device):
                        creations.append(device)
                        return model

                    manager = self.make_manager(
                        mps_available=True, reranker_factory=factory
                    )
                    call = lambda: manager.rerank_pairs("q", ["doc"])
                else:
                    model = EmbeddingModel(fail_on_call=2, failure=failure)

                    def factory(path, device):
                        creations.append(device)
                        return model

                    manager = self.make_manager(
                        mps_available=True, embedding_factory=factory
                    )
                    if operation == "query":
                        call = lambda: manager.embed_queries(["query"])
                    else:
                        call = lambda: manager.embed_documents(["doc"])

                with self.assertRaises(type(failure)) as caught:
                    call()

                self.assertIs(caught.exception, failure)
                self.assertEqual(creations, ["mps"])
                self.assertEqual(
                    manager.reranker_device
                    if operation == "rerank"
                    else manager.embedding_device,
                    "mps",
                )

    def test_reranker_mps_runtime_failure_reloads_cpu_and_retries_once(self):
        creations = []
        mps_model = RerankerModel(
            fail_on_call=2,
            failure=NotImplementedError("operator not implemented for MPS"),
        )
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
        mps_embedding = EmbeddingModel(
            fail_on_call=2,
            failure=RuntimeError(
                "placeholder storage has not been allocated on MPS"
            ),
        )
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
