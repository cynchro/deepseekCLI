import json
import tempfile
import unittest
from pathlib import Path

from core import claudejob as cj


JOB = """# JOB: SaaS inmobiliario

## PLAN
Backend FastAPI con repository pattern.

## RULES
- usar PostgreSQL, nunca SQLite
- controllers finos

## TASKS
### auth
- login
- middleware jwt

### properties
- CRUD
"""


class ParseJobTests(unittest.TestCase):
    def test_parses_title_plan_rules_modules(self):
        job = cj.parse_job(JOB)
        self.assertEqual(job["title"], "SaaS inmobiliario")
        self.assertIn("repository pattern", job["plan"])
        self.assertEqual(job["rules"], ["usar PostgreSQL, nunca SQLite", "controllers finos"])
        self.assertEqual([m["name"] for m in job["modules"]], ["auth", "properties"])
        self.assertEqual(job["errors"], [])

    def test_section_names_are_case_insensitive(self):
        job = cj.parse_job("# JOB: x\n## plan\nhola\n## tasks\n### a\n- y\n")
        self.assertEqual(job["plan"], "hola")
        self.assertEqual([m["name"] for m in job["modules"]], ["a"])
        self.assertEqual(job["errors"], [])

    def test_title_without_job_prefix(self):
        self.assertEqual(cj.parse_job("# Mi App\n## TASKS\n### a\n")["title"], "Mi App")

    def test_missing_tasks_reports_error(self):
        errors = cj.parse_job("# JOB: x\n## PLAN\nhola\n")["errors"]
        self.assertTrue(any("TASKS" in e for e in errors))

    def test_empty_tasks_reports_error(self):
        errors = cj.parse_job("# JOB: x\n## PLAN\np\n## TASKS\n\n")["errors"]
        self.assertTrue(any("módulos" in e for e in errors))


class ParseCorrectionsTests(unittest.TestCase):
    def test_parses_modules_and_items(self):
        corr = cj.parse_corrections(
            "## CORRECTIONS\n### auth\n- mover lógica HTTP\n### props\n- falta validación\n"
        )
        self.assertEqual([m["name"] for m in corr["modules"]], ["auth", "props"])
        self.assertEqual(corr["modules"][0]["items"], ["mover lógica HTTP"])
        self.assertEqual(corr["errors"], [])

    def test_missing_section_reports_error(self):
        self.assertTrue(cj.parse_corrections("nada acá")["errors"])


class StateTests(unittest.TestCase):
    def test_save_and_load_module_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cj.save_module_state(root, "auth", {"success": True, "files_written": ["a.py"]})
            st = cj.load_module_state(root, "auth")
            self.assertTrue(st["success"])
            self.assertEqual(st["files_written"], ["a.py"])
            self.assertEqual([s["module"] for s in cj.load_all_states(root)], ["auth"])

    def test_slug_keeps_filename_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = cj.save_module_state(root, "Auth / JWT!", {"success": False})
            self.assertTrue(path.name.endswith(".json"))
            self.assertNotIn("/", path.name)


class TemplateTests(unittest.TestCase):
    def test_template_is_parseable_with_a_filled_module(self):
        tpl = cj.job_template("demo")
        self.assertTrue(tpl.startswith("# JOB: demo"))
        # la plantilla trae un módulo de ejemplo, así que parsea sin errores de TASKS
        self.assertNotIn("TASKS", " ".join(cj.parse_job(tpl)["errors"]))

    def test_template_ships_anti_invention_rules(self):
        rules = cj.parse_job(cj.job_template("demo"))["rules"]
        self.assertTrue(rules, "la plantilla debe traer reglas por defecto")
        joined = " ".join(rules).lower()
        self.assertIn("no inventar", joined)
        self.assertIn("dependencias", joined)


class RenderReviewTests(unittest.TestCase):
    def test_lists_built_files_and_flags_untracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "auth.py").write_text("x = 1", encoding="utf-8")
            (root / "surprise.py").write_text("y = 2", encoding="utf-8")  # no atribuido
            cj.save_module_state(root, "auth", {
                "success": True,
                "files_written": [str(root / "auth.py"), str(root / ".deep" / "RESPONSE.md")],
            })
            job = {"title": "demo", "modules": [{"name": "auth", "body": "- login"}]}
            out = cj.render_review(root, job)
            self.assertIn("Construido por DeepSeek", out)
            self.assertIn("auth.py", out)
            # surprise.py está en disco pero ningún módulo lo registró → se marca
            self.assertIn("NO ATRIBUIDOS", out)
            self.assertIn("surprise.py", out)
            # RESPONSE.md no se cuenta como archivo de código
            self.assertNotIn("RESPONSE.md", out)


if __name__ == "__main__":
    unittest.main()
