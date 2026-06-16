import json
import tempfile
import unittest
from pathlib import Path

from core import navigator as nav


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
        job = nav.parse_job(JOB)
        self.assertEqual(job["title"], "SaaS inmobiliario")
        self.assertIn("repository pattern", job["plan"])
        self.assertEqual(job["rules"], ["usar PostgreSQL, nunca SQLite", "controllers finos"])
        self.assertEqual([m["name"] for m in job["modules"]], ["auth", "properties"])
        self.assertEqual(job["errors"], [])

    def test_section_names_are_case_insensitive(self):
        job = nav.parse_job("# JOB: x\n## plan\nhola\n## tasks\n### a\n- y\n")
        self.assertEqual(job["plan"], "hola")
        self.assertEqual([m["name"] for m in job["modules"]], ["a"])
        self.assertEqual(job["errors"], [])

    def test_title_without_job_prefix(self):
        self.assertEqual(nav.parse_job("# Mi App\n## TASKS\n### a\n")["title"], "Mi App")

    def test_missing_tasks_reports_error(self):
        errors = nav.parse_job("# JOB: x\n## PLAN\nhola\n")["errors"]
        self.assertTrue(any("TASKS" in e for e in errors))

    def test_empty_tasks_reports_error(self):
        errors = nav.parse_job("# JOB: x\n## PLAN\np\n## TASKS\n\n")["errors"]
        self.assertTrue(any("módulos" in e for e in errors))


JOB_V2 = """# JOB: API de notas

## STACK
- lenguaje: PHP 8.2
- dependencias: ninguna

## PLAN
Arquitectura por capas.

## CONTRACTS
NoteRepository::find(int $id): ?Note
ruta GET /notes -> NoteController::index

## RULES
- controllers finos

## TASKS
### repo
files:
- src/NoteRepository.php
uses:
- (ninguno)
done:
- implementa find() y all()

### http
files:
- src/NoteController.php
- public/index.php
uses:
- NoteRepository
done:
- expone GET /notes
"""


class ParseJobV2Tests(unittest.TestCase):
    def test_parses_stack_and_contracts(self):
        job = nav.parse_job(JOB_V2)
        self.assertIn("PHP 8.2", job["stack"])
        self.assertIn("NoteRepository::find", job["contracts"])

    def test_parses_structured_module_fields(self):
        mods = {m["name"]: m for m in nav.parse_job(JOB_V2)["modules"]}
        self.assertEqual(mods["http"]["files"],
                         ["src/NoteController.php", "public/index.php"])
        self.assertEqual(mods["http"]["uses"], ["NoteRepository"])
        self.assertEqual(mods["repo"]["uses"], [])  # "(ninguno)" → vacío
        self.assertTrue(mods["repo"]["done"])

    def test_inline_comma_list_supported(self):
        job = nav.parse_job(
            "# JOB: x\n## PLAN\np\n## TASKS\n### m\nfiles: a.py, b.py\n")
        self.assertEqual(job["modules"][0]["files"], ["a.py", "b.py"])

    def test_v1_module_without_fields_stays_backward_compatible(self):
        job = nav.parse_job(JOB)  # job v1 sin files:/uses:/done:
        mod = job["modules"][0]
        self.assertEqual(mod["files"], [])
        self.assertEqual(mod["uses"], [])
        self.assertIn("login", mod["body"])  # el body crudo se conserva

    def test_template_v2_declares_files_in_example_module(self):
        job = nav.parse_job(nav.job_template("demo"))
        self.assertEqual(job["errors"], [])
        self.assertTrue(job["modules"][0]["files"],
                        "el módulo de ejemplo debe declarar files:")


class ParseCorrectionsTests(unittest.TestCase):
    def test_parses_modules_and_items(self):
        corr = nav.parse_corrections(
            "## CORRECTIONS\n### auth\n- mover lógica HTTP\n### props\n- falta validación\n"
        )
        self.assertEqual([m["name"] for m in corr["modules"]], ["auth", "props"])
        self.assertEqual(corr["modules"][0]["items"], ["mover lógica HTTP"])
        self.assertEqual(corr["errors"], [])

    def test_missing_section_reports_error(self):
        self.assertTrue(nav.parse_corrections("nada acá")["errors"])


class StateTests(unittest.TestCase):
    def test_save_and_load_module_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nav.save_module_state(root, "auth", {"success": True, "files_written": ["a.py"]})
            st = nav.load_module_state(root, "auth")
            self.assertTrue(st["success"])
            self.assertEqual(st["files_written"], ["a.py"])
            self.assertEqual([s["module"] for s in nav.load_all_states(root)], ["auth"])

    def test_slug_keeps_filename_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = nav.save_module_state(root, "Auth / JWT!", {"success": False})
            self.assertTrue(path.name.endswith(".json"))
            self.assertNotIn("/", path.name)


class TemplateTests(unittest.TestCase):
    def test_template_is_parseable_with_a_filled_module(self):
        tpl = nav.job_template("demo")
        self.assertTrue(tpl.startswith("# JOB: demo"))
        # la plantilla trae un módulo de ejemplo, así que parsea sin errores de TASKS
        self.assertNotIn("TASKS", " ".join(nav.parse_job(tpl)["errors"]))

    def test_template_ships_anti_invention_rules(self):
        rules = nav.parse_job(nav.job_template("demo"))["rules"]
        self.assertTrue(rules, "la plantilla debe traer reglas por defecto")
        joined = " ".join(rules).lower()
        self.assertIn("no inventar", joined)
        self.assertIn("dependencias", joined)


class BuildModulePlanTests(unittest.TestCase):
    def test_plan_includes_stack_contracts_and_module_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = nav.parse_job(JOB_V2)
            http = next(m for m in job["modules"] if m["name"] == "http")
            plan = nav.build_module_plan(job, http, root)
            self.assertIn("STACK", plan)
            self.assertIn("PHP 8.2", plan)
            self.assertIn("CONTRACTS", plan)
            self.assertIn("NoteRepository::find", plan)
            self.assertIn("src/NoteController.php", plan)  # files: del módulo
            self.assertIn("expone GET /notes", plan)        # done:

    def test_plan_injects_already_built_sibling_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            repo_file = root / "src" / "NoteRepository.php"
            repo_file.write_text("<?php\nclass NoteRepository { public function find($id){} }",
                                 encoding="utf-8")
            nav.save_module_state(root, "repo", {
                "success": True, "files_written": [str(repo_file)]})
            job = nav.parse_job(JOB_V2)
            http = next(m for m in job["modules"] if m["name"] == "http")
            plan = nav.build_module_plan(job, http, root)
            # el código real del módulo hermano ya construido aparece en el plan
            self.assertIn("YA CONSTRUIDO POR OTROS MÓDULOS", plan)
            self.assertIn("class NoteRepository", plan)

    def test_sibling_excerpts_respect_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            big = root / "src" / "NoteRepository.php"
            big.write_text("X" * 5000, encoding="utf-8")
            nav.save_module_state(root, "repo", {
                "success": True, "files_written": [str(big)]})
            job = nav.parse_job(JOB_V2)
            http = next(m for m in job["modules"] if m["name"] == "http")
            exc = nav._sibling_excerpts(job, http, root, budget=2000, per_file=800)
            self.assertLessEqual(len(exc), 2000)
            self.assertIn("truncado", exc)


class RenderReviewTests(unittest.TestCase):
    def test_lists_built_files_and_flags_untracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "auth.py").write_text("x = 1", encoding="utf-8")
            (root / "surprise.py").write_text("y = 2", encoding="utf-8")  # no atribuido
            nav.save_module_state(root, "auth", {
                "success": True,
                "files_written": [str(root / "auth.py"), str(root / ".deep" / "RESPONSE.md")],
            })
            job = {"title": "demo", "modules": [{"name": "auth", "body": "- login"}]}
            out = nav.render_review(root, job)
            self.assertIn("Construido por DeepSeek", out)
            self.assertIn("auth.py", out)
            # surprise.py está en disco pero ningún módulo lo registró → se marca
            self.assertIn("NO ATRIBUIDOS", out)
            self.assertIn("surprise.py", out)
            # RESPONSE.md no se cuenta como archivo de código
            self.assertNotIn("RESPONSE.md", out)


class InitForceTests(unittest.TestCase):
    def test_init_creates_and_does_not_overwrite_without_force(self):
        from cli.commands import run_navigator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / ".deep" / "job.md"
            run_navigator(api_key="x", project_dir=root, init=True)
            self.assertTrue(job.exists())
            job.write_text("# JOB: lleno por el usuario\n", encoding="utf-8")
            # sin --force no debe pisar el contenido del usuario
            run_navigator(api_key="x", project_dir=root, init=True)
            self.assertEqual(job.read_text(encoding="utf-8"), "# JOB: lleno por el usuario\n")

    def test_init_force_regenerates_and_backs_up(self):
        from cli.commands import run_navigator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / ".deep" / "job.md"
            run_navigator(api_key="x", project_dir=root, init=True)
            job.write_text("# JOB: viejo\n", encoding="utf-8")
            run_navigator(api_key="x", project_dir=root, init=True, force=True)
            # el job se regeneró (plantilla) y el viejo quedó en .bak
            self.assertIn("## TASKS", job.read_text(encoding="utf-8"))
            self.assertEqual((job.parent / "job.md.bak").read_text(encoding="utf-8"), "# JOB: viejo\n")


if __name__ == "__main__":
    unittest.main()
