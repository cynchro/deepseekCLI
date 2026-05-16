import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple


class FileWriter:
    LANG_EXTENSIONS = {
        "php": "php", "python": "py", "py": "py",
        "javascript": "js", "js": "js", "typescript": "ts", "ts": "ts",
        "html": "html", "css": "css", "sql": "sql",
        "bash": "sh", "shell": "sh", "sh": "sh",
        "json": "json", "yaml": "yaml", "yml": "yml",
        "go": "go", "rust": "rs", "java": "java", "c": "c", "cpp": "cpp",
        "ruby": "rb", "swift": "swift", "kotlin": "kt",
        "plaintext": "txt", "text": "txt", "txt": "txt",
    }

    def __init__(self, output_base_dir: str = "output",
                 root_is_output_dir: bool = False,
                 on_file: Callable[[str], None] = None):
        self.output_base_dir = Path(output_base_dir)
        self.root_is_output_dir = root_is_output_dir
        self.last_project_dir: Optional[Path] = None
        self._on_file = on_file or (lambda p: None)

    def write_from_response(self, content: str, task: str) -> List[str]:
        project_dir = self._make_project_dir(task)
        self.last_project_dir = project_dir
        written = []

        named = self._extract_named_blocks(content)
        if named:
            for filename, code in named:
                written.append(str(self._write_file(project_dir, filename, code)))
        else:
            counters = defaultdict(int)
            for lang, code in self._extract_anonymous_blocks(content):
                ext = self.LANG_EXTENSIONS.get(lang.lower(), lang.lower() or "txt")
                counters[ext] += 1
                suffix = f"_{counters[ext]}" if counters[ext] > 1 else ""
                written.append(str(self._write_file(project_dir, f"main{suffix}.{ext}", code)))

        deep_dir = project_dir / ".deep"
        deep_dir.mkdir(exist_ok=True)
        response_path = deep_dir / "RESPONSE.md"
        response_path.write_text(content, encoding="utf-8")
        written.append(str(response_path))
        return written

    def _make_project_dir(self, task: str) -> Path:
        if self.root_is_output_dir:
            self.output_base_dir.mkdir(parents=True, exist_ok=True)
            return self.output_base_dir
        slug = re.sub(r"[^\w\s-]", "", task.lower())
        slug = re.sub(r"[\s_-]+", "_", slug).strip("_")[:50]
        project_dir = self.output_base_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}"
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir

    def _extract_named_blocks(self, content: str) -> List[Tuple[str, str]]:
        results = []
        for m in re.compile(r"```[\w]*:([^\n]+)\n(.*?)```", re.DOTALL).finditer(content):
            results.append((m.group(1).strip(), m.group(2).rstrip()))
        if results:
            return results
        for m in re.compile(
            r"(?:#{1,4}\s*(?:archivo|file|fichero)?:?\s*|\*\*|`)"
            r"([\w./\-]+\.\w+)(?:\*\*|`)?\s*\n+```(?:\w+)?\n(.*?)```",
            re.DOTALL | re.IGNORECASE,
        ).finditer(content):
            results.append((m.group(1).strip(), m.group(2).rstrip()))
        return results

    def _extract_anonymous_blocks(self, content: str) -> List[Tuple[str, str]]:
        return [
            (m.group(1).strip() or "txt", m.group(2).rstrip())
            for m in re.compile(r"```(\w*)\n(.*?)```", re.DOTALL).finditer(content)
            if m.group(2).strip()
        ]

    def _write_file(self, project_dir: Path, filename: str, code: str) -> Path:
        safe = [p for p in Path(filename).parts if p not in ("..", ".", "~")]
        filepath = project_dir.joinpath(*safe)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(code, encoding="utf-8")
        self._on_file(str(filepath))
        return filepath
