import tempfile
import unittest
from pathlib import Path

from core.writer import FileWriter


class ExtractNamedBlocksTests(unittest.TestCase):
    def test_unfenced_blocks_by_header(self):
        # Formato dominante del modelo: "### archivo: ruta" + código crudo SIN fences.
        content = (
            "### archivo: convert.py\n"
            '"""doc"""\n'
            "def f(c):\n"
            "    return c * 2\n"
            "\n"
            "### archivo: utils.py\n"
            "X = 1\n"
        )
        blocks = dict(FileWriter._extract_named_blocks(content))
        self.assertEqual(set(blocks), {"convert.py", "utils.py"})
        self.assertIn("def f(c):", blocks["convert.py"])
        self.assertEqual(blocks["utils.py"], "X = 1")

    def test_readme_with_inner_fences_and_section_headings(self):
        # El README tiene fences internos y encabezados de sección que NO deben
        # confundirse con nombres de archivo (regresión del bug Instalación/Uso/Tests).
        content = (
            "### archivo: app.py\n"
            "print('hola')\n"
            "\n"
            "### archivo: README.md\n"
            "# Proyecto\n"
            "## Instalación\n"
            "```bash\n"
            "pip install .\n"
            "```\n"
            "## Uso\n"
            "```python\n"
            "import app\n"
            "```\n"
        )
        blocks = dict(FileWriter._extract_named_blocks(content))
        self.assertEqual(set(blocks), {"app.py", "README.md"})
        self.assertNotIn("Instalación", blocks)
        self.assertNotIn("Uso", blocks)
        # el contenido del README conserva sus fences internos
        self.assertIn("```bash", blocks["README.md"])
        self.assertIn("## Uso", blocks["README.md"])

    def test_fenced_after_header_is_stripped(self):
        content = "### archivo: app.py\n```python\nprint('hi')\n```\n"
        self.assertEqual(
            FileWriter._extract_named_blocks(content), [("app.py", "print('hi')")]
        )

    def test_lang_filename_fence_fallback(self):
        content = "```python:main.py\nx = 1\n```"
        self.assertEqual(FileWriter._extract_named_blocks(content), [("main.py", "x = 1")])

    def test_dotfile_header(self):
        content = "### archivo: .gitignore\n__pycache__/\n*.pyc\n"
        blocks = dict(FileWriter._extract_named_blocks(content))
        self.assertIn(".gitignore", blocks)

    def test_lone_section_heading_is_not_a_file(self):
        # Sin ningún "### archivo:", un título de sección + fence no debe tomarse como archivo.
        content = "## Instalación\n```bash\npip install\n```"
        self.assertEqual(FileWriter._extract_named_blocks(content), [])


class WriteFromResponseTests(unittest.TestCase):
    def test_writes_unfenced_files_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = FileWriter(output_base_dir=tmp, root_is_output_dir=True)
            content = "### archivo: convert.py\ndef f():\n    return 1\n"
            written = w.write_from_response(content, "lib")
            target = Path(tmp) / "convert.py"
            self.assertTrue(target.exists())
            self.assertIn("def f():", target.read_text(encoding="utf-8"))
            self.assertTrue(any(p.endswith("RESPONSE.md") for p in written))


if __name__ == "__main__":
    unittest.main()
