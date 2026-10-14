import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_report_hybrid_index as builder


class ReportIndexPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "report_v2"
        self.staging = self.root.with_name("report_v2.staging")
        self.backup = self.root.with_name("report_v2.previous")
        self.root.mkdir()
        (self.root / "old.txt").write_text("old", encoding="utf-8")
        config = patch("retrieval_core.config.RetrievalConfig.for_project",
                       return_value=SimpleNamespace(index_root=self.root))
        config.start()
        self.addCleanup(config.stop)
        tokenizer = patch.object(builder, "_local_tokenizer", side_effect=AssertionError("parent loaded model"))
        tokenizer.start()
        self.addCleanup(tokenizer.stop)

    def ready_child(self, command, **kwargs):
        self.assertTrue((self.root / "old.txt").exists())
        self.assertNotIn("--publish", command)
        self.assertIn("--resume", command)
        self.staging.mkdir()
        (self.staging / "READY").write_text("ready", encoding="utf-8")
        (self.staging / "build_report.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    def run_publish(self):
        return builder.main(["--source", "legacy-chroma", "--build", "--publish", "--resume"])

    def test_publish_occurs_after_child_exit_and_preserves_backup(self):
        with patch.object(builder.subprocess, "run", side_effect=self.ready_child):
            self.assertEqual(self.run_publish(), 0)
        self.assertTrue((self.root / "READY").exists())
        self.assertTrue((self.backup / "old.txt").exists())
        self.assertFalse(self.staging.exists())

    def test_child_failure_does_not_replace_existing_index(self):
        with patch.object(builder.subprocess, "run", return_value=SimpleNamespace(returncode=7)):
            self.assertEqual(self.run_publish(), 7)
        self.assertTrue((self.root / "old.txt").exists())
        self.assertFalse(self.backup.exists())

    def test_missing_ready_marker_refuses_publication(self):
        def child(command, **kwargs):
            result = self.ready_child(command, **kwargs)
            (self.staging / "READY").unlink()
            return result

        with patch.object(builder.subprocess, "run", side_effect=child):
            with self.assertRaisesRegex(RuntimeError, "completed ready index"):
                self.run_publish()
        self.assertTrue((self.root / "old.txt").exists())

    def test_move_failure_restores_old_index(self):
        original_replace = builder.os.replace

        def replace(source, destination):
            if source == self.staging:
                raise PermissionError("index is held open")
            return original_replace(source, destination)

        with patch.object(builder.subprocess, "run", side_effect=self.ready_child), patch.object(
            builder.os, "replace", side_effect=replace
        ):
            with self.assertRaises(PermissionError):
                self.run_publish()
        self.assertTrue((self.root / "old.txt").exists())
        self.assertTrue((self.staging / "READY").exists())

    def test_existing_backup_refuses_build_without_overwriting(self):
        self.backup.mkdir()
        with patch.object(builder.subprocess, "run") as child:
            with self.assertRaisesRegex(RuntimeError, "previous index backup"):
                self.run_publish()
        child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
