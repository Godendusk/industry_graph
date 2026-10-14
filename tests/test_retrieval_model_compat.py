import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from retrieval_core.model_manager import _default_embedding_factory


class LocalModelCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        modules = [{"type": "sentence_transformers.base.modules.transformer.Transformer", "path": ""},
                   {"type": "sentence_transformers.sentence_transformer.modules.pooling.Pooling", "path": "1_Pooling"},
                   {"type": "sentence_transformers.sentence_transformer.modules.normalize.Normalize", "path": "2_Normalize"}]
        (self.path / "modules.json").write_text(json.dumps(modules), encoding="utf-8")
        (self.path / "1_Pooling").mkdir()
        (self.path / "1_Pooling" / "config.json").write_text(
            json.dumps({"pooling_mode": "cls", "embedding_dimension": 768, "include_prompt": True}), encoding="utf-8")

    def test_only_known_module_migration_rebuilds_local_cls_stack(self):
        missing = ModuleNotFoundError("missing module", name="sentence_transformers.base")
        constructor = Mock(side_effect=[missing, "loaded"])
        modules = SimpleNamespace(Transformer=Mock(return_value="transformer"),
                                  Pooling=Mock(return_value="pooling"), Normalize=Mock(return_value="normalize"))
        package = SimpleNamespace(SentenceTransformer=constructor, models=modules)
        with patch.dict(sys.modules, {"sentence_transformers": package}):
            self.assertEqual(_default_embedding_factory(self.path, "mps"), "loaded")
        modules.Transformer.assert_called_once_with(str(self.path), model_args={"local_files_only": True},
                                                   tokenizer_args={"local_files_only": True})
        modules.Pooling.assert_called_once_with(768, pooling_mode="cls", include_prompt=True)
        self.assertEqual(constructor.call_args.kwargs["modules"], ["transformer", "pooling", "normalize"])

    def test_unrelated_import_errors_and_unknown_pooling_are_not_hidden(self):
        constructor = Mock(side_effect=ModuleNotFoundError("missing dependency", name="unrelated"))
        with patch.dict(sys.modules, {"sentence_transformers": SimpleNamespace(SentenceTransformer=constructor)}):
            with self.assertRaises(ModuleNotFoundError):
                _default_embedding_factory(self.path, "mps")
        constructor = Mock(side_effect=ModuleNotFoundError("missing module", name="sentence_transformers.base"))
        (self.path / "1_Pooling" / "config.json").write_text(json.dumps({"pooling_mode": "mean"}), encoding="utf-8")
        with patch.dict(sys.modules, {"sentence_transformers": SimpleNamespace(SentenceTransformer=constructor, models=Mock())}):
            with self.assertRaisesRegex(ValueError, "pooling configuration"):
                _default_embedding_factory(self.path, "mps")


if __name__ == "__main__":
    unittest.main()
