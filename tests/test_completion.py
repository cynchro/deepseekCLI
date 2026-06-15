import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.postcheck import analyze_project
from core.system import DeepSeekLearningSystem


class PhpIncludeCheckTests(unittest.TestCase):
    def test_missing_require_is_reported_as_missing_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "Http").mkdir(parents=True)
            (root / "src" / "Http" / "Ctrl.php").write_text(
                "<?php\nrequire_once __DIR__ . '/../../templates/home.php';\n",
                encoding="utf-8")
            report = analyze_project(root)
            self.assertIn("templates/home.php", report["missing_refs"])
            self.assertFalse(report["ok"])

    def test_existing_require_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "templates").mkdir(parents=True)
            (root / "templates" / "home.php").write_text("<?php // ok", encoding="utf-8")
            (root / "Ctrl.php").write_text(
                "<?php\nrequire_once __DIR__ . '/templates/home.php';\n", encoding="utf-8")
            report = analyze_project(root)
            self.assertEqual(report["missing_refs"], [])

    def test_dynamic_require_with_variable_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Router.php").write_text(
                "<?php\nrequire_once __DIR__ . '/Controller/' . $class . '.php';\n",
                encoding="utf-8")
            report = analyze_project(root)
            self.assertEqual(report["missing_refs"], [])


class CompleteMissingTests(unittest.TestCase):
    def test_generates_and_writes_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sys = DeepSeekLearningSystem(api_key="x", output_dir=str(root),
                                         root_is_output_dir=True)
            with patch.object(sys, "_generate_file",
                              side_effect=lambda *a, **k: ("<?php // generado", False, 5)):
                created = sys.complete_missing(
                    "t", "plan", ["templates/home.php"],
                    ["templates/home.php"], root)
            self.assertEqual(len(created), 1)
            self.assertTrue((root / "templates" / "home.php").is_file())

    def test_empty_generation_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sys = DeepSeekLearningSystem(api_key="x", output_dir=str(root),
                                         root_is_output_dir=True)
            with patch.object(sys, "_generate_file",
                              side_effect=lambda *a, **k: ("", True, 0)):
                created = sys.complete_missing("t", "p", [], ["x.php"], root)
            self.assertEqual(created, [])
            self.assertFalse((root / "x.php").exists())


class ReviewAndFixCompletesMissingTests(unittest.TestCase):
    def test_fix_generates_broken_reference_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".deep").mkdir()
            (root / "Ctrl.php").write_text(
                "<?php\nrequire_once __DIR__ . '/views/home.php';\n", encoding="utf-8")
            sys = DeepSeekLearningSystem(api_key="x", output_dir=str(root),
                                         root_is_output_dir=True)

            def fake_chat(prompt, **kw):
                base = {"success": True, "tokens": {"total_tokens": 5},
                        "truncated": False, "continuations": 0}
                if prompt.startswith("EVALÚA"):
                    return {**base, "content": '{"overall_score":8,"success":true,'
                                               '"issues":[],"positives":[],"suggestions":[]}'}
                return {**base, "content": "<?php // home view"}

            fake_result = {"files_written": [str(root / "Ctrl.php")],
                           "outcome": "{}", "plan": "p", "manifest": [],
                           "missing_files": []}
            with patch.object(sys.client, "chat", side_effect=fake_chat):
                out = sys.review_and_fix("tarea", fake_result)

            self.assertTrue((root / "views" / "home.php").is_file())
            self.assertEqual(len(out["files_completed"]), 1)
            self.assertTrue(out["success"])


if __name__ == "__main__":
    unittest.main()
