import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.system import DeepSeekLearningSystem


def _chat(content, truncated=False, success=True):
    return {"success": success, "content": content,
            "tokens": {"total_tokens": 7}, "truncated": truncated,
            "continuations": 0}


def _make_system(tmp):
    return DeepSeekLearningSystem(api_key="x", output_dir=str(tmp),
                                  root_is_output_dir=True)


class BuildManifestTests(unittest.TestCase):
    def test_parses_json_dedups_and_filters_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            sys = _make_system(Path(tmp))
            raw = ('```json\n{"files":['
                   '{"path":"a.py","purpose":"uno"},'
                   '{"path":"a.py","purpose":"dup"},'
                   '{"path":"../evil","purpose":"x"},'
                   '{"path":"sub/b.py","purpose":"dos"}]}\n```')
            with patch.object(sys.client, "chat", return_value=_chat(raw)):
                files = sys._build_manifest("t", "p")
        paths = [f["path"] for f in files]
        self.assertEqual(paths, ["a.py", "sub/b.py"])

    def test_bad_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            sys = _make_system(Path(tmp))
            with patch.object(sys.client, "chat", return_value=_chat("no soy json")):
                self.assertEqual(sys._build_manifest("t", "p"), [])


class ExecuteDispatchTests(unittest.TestCase):
    def test_small_manifest_uses_single_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            sys = _make_system(Path(tmp))
            files = [{"path": f"f{i}.py", "purpose": ""} for i in range(3)]
            with patch.object(sys, "_build_manifest", return_value=files), \
                 patch.object(sys, "_execute_single_shot",
                              return_value={"code": "X", "tokens_used": 1,
                                            "truncated": False}) as ss, \
                 patch.object(sys, "_execute_by_manifest") as bm:
                out = sys._execute("t", "p", manifest_mode=True)
            ss.assert_called_once()
            bm.assert_not_called()
            self.assertEqual(out["manifest"], ["f0.py", "f1.py", "f2.py"])

    def test_large_manifest_generates_file_by_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sys = _make_system(Path(tmp))
            files = [{"path": f"f{i}.py", "purpose": ""} for i in range(12)]
            with patch.object(sys, "_build_manifest", return_value=files), \
                 patch.object(sys, "_execute_single_shot") as ss, \
                 patch.object(sys, "_generate_file",
                              side_effect=lambda *a: ("print(1)", False, 5)):
                out = sys._execute("t", "p", manifest_mode=True)
            ss.assert_not_called()
            # cada archivo aparece como bloque "### archivo: ruta"
            self.assertEqual(out["code"].count("### archivo:"), 12)
            self.assertEqual(out["missing_files"], [])
            self.assertFalse(out["truncated"])


class ExecuteByManifestTests(unittest.TestCase):
    def test_empty_generation_is_reported_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            sys = _make_system(Path(tmp))
            files = [{"path": "ok.py", "purpose": ""},
                     {"path": "fail.py", "purpose": ""}]

            def gen(task, plan, paths, path, purpose):
                return ("contenido", False, 5) if path == "ok.py" else ("", True, 0)

            with patch.object(sys, "_generate_file", side_effect=gen):
                out = sys._execute_by_manifest("t", "p", files)
        self.assertEqual(out["missing_files"], ["fail.py"])
        self.assertIn("### archivo: ok.py", out["code"])
        self.assertNotIn("### archivo: fail.py", out["code"])

    def test_combined_code_is_writable_and_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sys = _make_system(Path(tmp))
            files = [{"path": "src/a.py", "purpose": ""},
                     {"path": "src/b.py", "purpose": ""}]
            with patch.object(sys, "_generate_file",
                              side_effect=lambda *a: ("X = 1", False, 5)):
                out = sys._execute_by_manifest("t", "p", files)
            written = sys.file_writer.write_from_response(out["code"], "t")
        names = {Path(w).name for w in written}
        self.assertIn("a.py", names)
        self.assertIn("b.py", names)


if __name__ == "__main__":
    unittest.main()
