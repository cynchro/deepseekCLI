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


class InitForceTests(unittest.TestCase):
    def test_init_creates_and_does_not_overwrite_without_force(self):
        from cli.commands import run_claudejob
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / ".deep" / "job.md"
            run_claudejob(api_key="x", project_dir=root, init=True)
            self.assertTrue(job.exists())
            job.write_text("# JOB: lleno por el usuario\n", encoding="utf-8")
            # sin --force no debe pisar el contenido del usuario
            run_claudejob(api_key="x", project_dir=root, init=True)
            self.assertEqual(job.read_text(encoding="utf-8"), "# JOB: lleno por el usuario\n")

    def test_init_force_regenerates_and_backs_up(self):
        from cli.commands import run_claudejob
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / ".deep" / "job.md"
            run_claudejob(api_key="x", project_dir=root, init=True)
            job.write_text("# JOB: viejo\n", encoding="utf-8")
            run_claudejob(api_key="x", project_dir=root, init=True, force=True)
            # el job se regeneró (plantilla) y el viejo quedó en .bak
            self.assertIn("## TASKS", job.read_text(encoding="utf-8"))
            self.assertEqual((job.parent / "job.md.bak").read_text(encoding="utf-8"), "# JOB: viejo\n")


class ModuleFilesTests(unittest.TestCase):
    def test_extracts_archivo_bullets_with_description(self):
        mod = {"name": "auth", "body": (
            "- archivo auth/login.py: función login(user) -> Token\n"
            "- archivo auth/middleware.py: valida el JWT en cada request\n"
        )}
        files = cj.module_files(mod)
        self.assertEqual([f["path"] for f in files], ["auth/login.py", "auth/middleware.py"])
        self.assertIn("login(user)", files[0]["description"])

    def test_path_token_fallback_without_archivo_prefix(self):
        mod = {"name": "x", "body": "- el entrypoint vive en src/app.py y arranca todo"}
        files = cj.module_files(mod)
        self.assertEqual([f["path"] for f in files], ["src/app.py"])

    def test_ignores_version_like_tokens(self):
        # "3.0.0" no debe contarse como archivo (extensión arranca con dígito)
        mod = {"name": "deps", "body": "- usar flask==3.0.0 y mantener compatibilidad"}
        self.assertEqual(cj.module_files(mod), [])

    def test_empty_when_module_has_no_files(self):
        # módulo del fixture JOB: bullets en prosa, sin rutas → vacío (cae a fallback)
        job = cj.parse_job(JOB)
        auth = next(m for m in job["modules"] if m["name"] == "auth")
        self.assertEqual(cj.module_files(auth), [])

    def test_dedupes_repeated_paths(self):
        mod = {"name": "x", "body": "- archivo a/b.py: una cosa\n- archivo a/b.py: otra mención"}
        self.assertEqual([f["path"] for f in cj.module_files(mod)], ["a/b.py"])

    def test_built_plan_passes_normalize_plan(self):
        # el dict que arma claudejob a partir de un módulo debe ser un plan válido
        from core.planner import normalize_plan
        mod = {"name": "auth", "body": (
            "- archivo auth/login.py: login\n- archivo auth/jwt.py: tokens\n"
        )}
        spec = cj.module_files(mod)
        plan = {
            "architecture": "Backend con repository pattern",
            "files": [{"path": f["path"], "description": f["description"],
                       "depends_on": []} for f in spec],
        }
        norm = normalize_plan(plan)
        self.assertEqual(sorted(f["path"] for f in norm["files"]),
                         ["auth/jwt.py", "auth/login.py"])
        self.assertEqual(len(norm["order"]), 2)


if __name__ == "__main__":
    unittest.main()
