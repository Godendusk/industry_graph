"""Lazy, local-only embedding and reranking model management."""

from __future__ import annotations

import errno
import json
import logging
import re
from pathlib import Path
from threading import Lock
from typing import Any, Callable, List, Optional, Sequence, Tuple


LOGGER = logging.getLogger(__name__)
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

ModelFactory = Callable[[Path, str], Any]

# Fallback is intentionally allowlisted by phrase shape, not exception class or
# a bare mention of MPS/Metal.  Model libraries also use RuntimeError and
# NotImplementedError for inputs and application features.
_MPS_DEVICE_ERROR_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        # An operator or operation is unavailable on the named accelerator.
        r"\bnot\s+(?:currently\s+)?implemented\s+(?:for|on)\s+(?:the\s+)?(?:mps|metal)(?:\s+devices?)?\b",
        r"\b(?:not supported|unsupported)\s+(?:for|on|by)\s+(?:the\s+)?(?:mps|metal)(?:\s+devices?)?\b",
        r"\b(?:mps|metal)\b.{0,40}\b(?:operator|operation)\b.{0,40}\b(?:not implemented|not supported|unsupported)\b",
        # PyTorch/build linkage explicitly lacks accelerator support.
        r"\bnot linked with support for\s+(?:the\s+)?(?:mps|metal)(?:\s+devices?)?\b",
        # The named backend itself is unavailable, failed, or exhausted.
        r"\b(?:mps|metal)\s+backend\b.{0,40}\b(?:unavailable|not available|failed|failure|out of memory|allocation failed|allocation failure)\b",
        r"\b(?:mps|metal)\s+backend\b.{0,40}\b(?:is\s+)?not supported\b",
        # The named device itself is unavailable, failed, or exhausted.
        r"\b(?:mps|metal)\s+devices?\b.{0,40}\b(?:unavailable|not available|failed|failure|out of memory|allocation failed|allocation failure)\b",
        r"\b(?:mps|metal)\s+devices?\b.{0,40}\b(?:not found|could not be initialized|failed to initialize)\b",
        # The named accelerator explicitly rejects an operator.
        r"\b(?:mps|metal)\b.{0,20}\bdoes not support\b.{0,60}\b(?:op|operator|operation)\b",
        # Common terse allocator message includes only the accelerator prefix.
        r"\b(?:mps|metal)\b\s*:\s*out of memory\b",
        # Storage or another resource could not be allocated on MPS/Metal.
        r"\b(?:not|never)\s+been allocated\s+(?:on|for)\s+(?:the\s+)?(?:mps|metal)\b",
        r"\b(?:failed|unable)\s+to allocate\b.{0,80}\b(?:on|for)\s+(?:the\s+)?(?:mps|metal)\b",
        r"\b(?:mps|metal)\b.{0,40}\ballocat(?:e|ed|ion)\b.{0,40}\b(?:failed|failure|out of memory)\b",
        # Command-buffer failure is an explicit accelerator execution failure.
        r"\b(?:mps|metal)\s*command\s*buffer\b.{0,40}\b(?:failed|failure|error)\b",
    )
)


def select_device(mps_available: Optional[bool] = None) -> str:
    """Select MPS when available, otherwise CPU.

    ``mps_available`` is an explicit test/deployment override.  CUDA is
    deliberately not considered because this retrieval deployment is designed
    for Apple Silicon and CPU fallback.
    """
    if mps_available is None:
        try:
            import torch

            mps_available = bool(torch.backends.mps.is_available())
        except (ImportError, AttributeError):
            mps_available = False
    return "mps" if mps_available else "cpu"


def _is_mps_device_error(error: BaseException) -> bool:
    """Return whether an exception clearly indicates an MPS device failure.

    RuntimeError is also used by model libraries for invalid inputs, shapes,
    and application errors.  Those errors must remain visible to callers; only
    explicit backend/device failures are eligible for the one-time CPU retry.
    """
    if not isinstance(error, RuntimeError):
        return False
    return any(pattern.search(str(error)) for pattern in _MPS_DEVICE_ERROR_PATTERNS)


def _missing_path(path: Path) -> FileNotFoundError:
    return FileNotFoundError(errno.ENOENT, "Local model path does not exist", str(path))


def _default_embedding_factory(path: Path, device: str) -> Any:
    if not path.exists():
        raise _missing_path(path)
    from sentence_transformers import SentenceTransformer
    if device == "cpu":
        import torch

        torch.set_num_threads(4)

    try:
        return SentenceTransformer(str(path), device=device, local_files_only=True)
    except ModuleNotFoundError as error:
        if not error.name or not error.name.startswith((
            "sentence_transformers.base", "sentence_transformers.sentence_transformer"
        )):
            raise
        # New ST exports moved these classes; reconstruct only the known BGE stack.
        from sentence_transformers import models

        modules = json.loads((path / "modules.json").read_text(encoding="utf-8"))
        expected = ("Transformer", "Pooling", "Normalize")
        if len(modules) != 3 or tuple(item["type"].rsplit(".", 1)[-1] for item in modules) != expected:
            raise ValueError("unsupported local embedding module stack") from error
        if [item["path"] for item in modules] != ["", "1_Pooling", "2_Normalize"]:
            raise ValueError("unsupported local embedding module paths") from error
        pooling = json.loads((path / "1_Pooling" / "config.json").read_text(encoding="utf-8"))
        if pooling.get("pooling_mode") != "cls" or pooling.get("embedding_dimension") != 768:
            raise ValueError("unsupported local BGE pooling configuration") from error
        transformer = models.Transformer(
            str(path), model_args={"local_files_only": True},
            tokenizer_args={"local_files_only": True},
        )
        pool = models.Pooling(768, pooling_mode="cls", include_prompt=pooling.get("include_prompt", True))
        LOGGER.warning("Loading local BGE with compatible Transformer/CLS/Normalize modules")
        return SentenceTransformer(modules=[transformer, pool, models.Normalize()], device=device)


def _default_reranker_factory(path: Path, device: str) -> Any:
    if not path.exists():
        raise _missing_path(path)
    from sentence_transformers import CrossEncoder
    if device == "cpu":
        import torch

        torch.set_num_threads(4)

    try:
        return CrossEncoder(str(path), device=device, local_files_only=True)
    except AttributeError as error:
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
        if str(error) != "'dict' object has no attribute 'model_type'" or config.get("model_type") != "xlm-roberta":
            raise
        LOGGER.warning("Loading local XLM-R reranker with the compatible fast tokenizer")
        return _CompatibleCrossEncoder(path, device)


class _CompatibleCrossEncoder:
    """Bypass the Transformers 4.57.2 local large-vocabulary loader bug."""

    def __init__(self, path: Path, device: str):
        from transformers import AddedToken, AutoModelForSequenceClassification, XLMRobertaTokenizerFast

        config = json.loads((path / "tokenizer_config.json").read_text(encoding="utf-8"))
        tokens = {}
        for key in ("bos_token", "eos_token", "sep_token", "cls_token", "unk_token", "pad_token", "mask_token"):
            value = config[key]
            if isinstance(value, dict):
                value = AddedToken(**{name: item for name, item in value.items() if name != "__type"})
            tokens[key] = value
        self.tokenizer = XLMRobertaTokenizerFast(
            tokenizer_file=str(path / "tokenizer.json"), model_max_length=config.get("model_max_length", 512),
            **tokens,
        )
        self.model = AutoModelForSequenceClassification.from_pretrained(str(path), local_files_only=True).to(device).eval()
        self.device = device

    def predict(self, pairs, batch_size=4):
        import torch

        scores = []
        with torch.inference_mode():
            for start in range(0, len(pairs), batch_size):
                batch = pairs[start:start + batch_size]
                encoded = self.tokenizer([pair[0] for pair in batch], [pair[1] for pair in batch],
                                         padding=True, truncation=True, max_length=512, return_tensors="pt")
                logits = self.model(**{key: value.to(self.device) for key, value in encoded.items()}).logits
                if logits.shape[-1] != 1:
                    raise ValueError("compatible BGE reranker requires one classification logit")
                scores.extend(torch.sigmoid(logits[:, 0]).cpu().tolist())
        return scores


def _plain_vectors(values: Any) -> List[List[float]]:
    if hasattr(values, "tolist"):
        values = values.tolist()
    return [
        [float(value) for value in (row.tolist() if hasattr(row, "tolist") else row)]
        for row in values
    ]


def _plain_scores(values: Any) -> List[float]:
    if hasattr(values, "tolist"):
        values = values.tolist()
    return [float(value) for value in values]


class ModelManager:
    """Own one lazy embedding model and one lazy cross-encoder.

    Injected factories use the same ``factory(Path, device)`` signature as the
    built-in local-only loaders.  Path existence is delegated to injected
    factories, allowing deterministic fakes without creating model trees.
    """

    def __init__(
        self,
        embedding_model_path: Optional[Path] = None,
        reranker_model_path: Optional[Path] = None,
        *,
        embedding_factory: Optional[ModelFactory] = None,
        reranker_factory: Optional[ModelFactory] = None,
        mps_available: Optional[bool] = None,
        preferred_device: Optional[str] = None,
    ) -> None:
        if preferred_device not in (None, "mps", "cpu"):
            raise ValueError("preferred_device must be 'mps', 'cpu', or None")
        self.embedding_model_path = (
            Path() if embedding_model_path is None else Path(embedding_model_path)
        )
        self.reranker_model_path = (
            Path() if reranker_model_path is None else Path(reranker_model_path)
        )
        self._embedding_path_configured = embedding_model_path is not None
        self._reranker_path_configured = reranker_model_path is not None
        self._embedding_uses_default_factory = embedding_factory is None
        self._reranker_uses_default_factory = reranker_factory is None
        self._embedding_factory = embedding_factory or _default_embedding_factory
        self._reranker_factory = reranker_factory or _default_reranker_factory
        self._preferred_device = preferred_device or select_device(mps_available)
        self._cpu_only = self._preferred_device == "cpu"
        self._fallback_logged = False

        self._embedding_model: Any = None
        self._reranker_model: Any = None
        self._embedding_device: Optional[str] = None
        self._reranker_device: Optional[str] = None

        # Encoding and reranking must be serialized independently: the models
        # are not thread-safe, but the two workloads need not block each other.
        self._embedding_lock = Lock()
        self._reranker_lock = Lock()
        self._device_state_lock = Lock()

    @property
    def embedding_device(self) -> Optional[str]:
        return self._embedding_device

    @property
    def reranker_device(self) -> Optional[str]:
        return self._reranker_device

    def _fall_back_to_cpu(self, component: str, error: RuntimeError) -> None:
        with self._device_state_lock:
            self._cpu_only = True
            self._preferred_device = "cpu"
            # A model already loaded by the other component is also no longer
            # eligible for future calls once this manager has fixed itself to
            # CPU.  Clearing references here does not interrupt an inference
            # already holding a local reference, and avoids cross-locking the
            # two independent execution paths.
            if self._embedding_device == "mps":
                self._embedding_model = None
                self._embedding_device = None
            if self._reranker_device == "mps":
                self._reranker_model = None
                self._reranker_device = None
            if not self._fallback_logged:
                LOGGER.warning(
                    "MPS %s failed; reloading local models on CPU: %s",
                    component,
                    error,
                )
                self._fallback_logged = True

    def _create_embedding(self, device: str) -> Any:
        if self._embedding_uses_default_factory and not self._embedding_path_configured:
            raise ValueError("embedding_model_path is required with the default factory")
        model = self._embedding_factory(self.embedding_model_path, device)
        if device == "mps":
            model.encode(
                ["MPS health check"],
                batch_size=1,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return model

    def _create_reranker(self, device: str) -> Any:
        if self._reranker_uses_default_factory and not self._reranker_path_configured:
            raise ValueError("reranker_model_path is required with the default factory")
        model = self._reranker_factory(self.reranker_model_path, device)
        if device == "mps":
            model.predict([["MPS health check", "MPS health check"]], batch_size=1)
        return model

    def _embedding_locked(self) -> Tuple[Any, str]:
        with self._device_state_lock:
            if self._embedding_model is not None:
                return self._embedding_model, str(self._embedding_device)
            device = "cpu" if self._cpu_only else self._preferred_device
        try:
            model = self._create_embedding(device)
        except RuntimeError as error:
            if device != "mps" or not _is_mps_device_error(error):
                raise
            self._fall_back_to_cpu("embedding model", error)
            model = self._create_embedding("cpu")
            device = "cpu"
        if device == "mps":
            with self._device_state_lock:
                retry_on_cpu = self._cpu_only
                if not retry_on_cpu:
                    self._embedding_model = model
                    self._embedding_device = device
                    return model, device
            model = self._create_embedding("cpu")
            device = "cpu"
        with self._device_state_lock:
            self._embedding_model = model
            self._embedding_device = device
        return model, device

    def _reranker_locked(self) -> Tuple[Any, str]:
        with self._device_state_lock:
            if self._reranker_model is not None:
                return self._reranker_model, str(self._reranker_device)
            device = "cpu" if self._cpu_only else self._preferred_device
        try:
            model = self._create_reranker(device)
        except RuntimeError as error:
            if device != "mps" or not _is_mps_device_error(error):
                raise
            self._fall_back_to_cpu("reranker model", error)
            model = self._create_reranker("cpu")
            device = "cpu"
        if device == "mps":
            with self._device_state_lock:
                retry_on_cpu = self._cpu_only
                if not retry_on_cpu:
                    self._reranker_model = model
                    self._reranker_device = device
                    return model, device
            model = self._create_reranker("cpu")
            device = "cpu"
        with self._device_state_lock:
            self._reranker_model = model
            self._reranker_device = device
        return model, device

    def _encode(self, texts: Sequence[str], batch_size: int) -> List[List[float]]:
        with self._embedding_lock:
            model, inference_device = self._embedding_locked()
            try:
                values = model.encode(
                    list(texts),
                    batch_size=batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            except RuntimeError as error:
                if inference_device != "mps" or not _is_mps_device_error(error):
                    raise
                self._fall_back_to_cpu("embedding inference", error)
                model, _ = self._embedding_locked()
                values = model.encode(
                    list(texts),
                    batch_size=batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            return _plain_vectors(values)

    def embed_queries(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        prepared = [
            text if text.startswith(BGE_QUERY_INSTRUCTION) else BGE_QUERY_INSTRUCTION + text
            for text in texts
        ]
        return self._encode(prepared, batch_size=16)

    def embed_documents(
        self, texts: Sequence[str], batch_size: int = 16
    ) -> List[List[float]]:
        if not texts:
            return []
        return self._encode(list(texts), batch_size=batch_size)

    def rerank_pairs(
        self, query: str, documents: Sequence[str], batch_size: int = 4
    ) -> List[float]:
        if not documents:
            return []
        pairs = [[query, document] for document in documents]
        with self._reranker_lock:
            model, inference_device = self._reranker_locked()
            try:
                values = model.predict(pairs, batch_size=batch_size)
            except RuntimeError as error:
                if inference_device != "mps" or not _is_mps_device_error(error):
                    raise
                self._fall_back_to_cpu("reranker inference", error)
                model, _ = self._reranker_locked()
                values = model.predict(pairs, batch_size=batch_size)
            return _plain_scores(values)
