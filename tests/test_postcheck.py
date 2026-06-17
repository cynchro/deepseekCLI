import tempfile
import unittest
from pathlib import Path

from core.postcheck import _check_docker_npm, _resolve_import, analyze_project


class PostcheckTests(unittest.TestCase):
    def test_resolve_import_finds_index_ts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = root / "core"
            mod.mkdir()
            (mod / "types.ts").write_text("export {}")
            entry = root / "inference" / "x.ts"
            entry.parent.mkdir()
            entry.write_text("import {} from '../core/types'")
            self.assertTrue(_resolve_import(entry, "../core/types"))

    def test_docker_npm_ci_without_lockfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            (root / "Dockerfile").write_text("RUN npm ci\n")
            issues = _check_docker_npm(root)
            self.assertTrue(any("package-lock" in i for i in issues))

    def test_docker_bad_copy_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Dockerfile").write_text("COPY core inference ./\n")
            issues = _check_docker_npm(root)
            self.assertTrue(any("aplasta" in i for i in issues))

    def test_broken_ts_import_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "main.ts"
            f.write_text("import x from '../missing/module'")
            report = analyze_project(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("Import roto" in i for i in report["issues"]))


if __name__ == "__main__":
    unittest.main()
