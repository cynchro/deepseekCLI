from pathlib import Path
from typing import Dict, Optional

_GLOBAL_DIR = Path.home() / ".config" / "deep" / "skills"


def _parse(path: Path) -> Optional[Dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    meta = {
        "name": path.stem,
        "description": "",
        "temperature": 0.7,
        "max_tokens": 3000,
    }

    lines = text.splitlines()
    sep = next((i for i, l in enumerate(lines) if l.strip() == "---"), None)
    header = lines[:sep] if sep is not None else []
    body = lines[sep + 1:] if sep is not None else lines

    for line in header:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key, val = key.strip().lower(), val.strip()
            if key == "description":
                meta["description"] = val
            elif key == "temperature":
                try:
                    meta["temperature"] = float(val)
                except ValueError:
                    pass
            elif key == "max_tokens":
                try:
                    meta["max_tokens"] = int(val)
                except ValueError:
                    pass

    meta["system_prompt"] = "\n".join(body).strip()
    return meta if meta["system_prompt"] else None


def load(project_dir: Path = None) -> Dict[str, Dict]:
    """Return {name: skill} from global dir + optional project .deep/skills/."""
    skills: Dict[str, Dict] = {}
    dirs = [_GLOBAL_DIR]
    if project_dir:
        dirs.append(project_dir / ".deep" / "skills")

    for d in dirs:
        if not d.exists():
            continue
        for path in sorted(d.glob("*.skill")):
            skill = _parse(path)
            if skill:
                skills[skill["name"]] = skill
    return skills


def create(name: str, description: str, system_prompt: str,
           temperature: float = 0.7, max_tokens: int = 3000,
           project_local: bool = False) -> Path:
    skills_dir = (Path.cwd() / ".deep" / "skills") if project_local else _GLOBAL_DIR
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"{name}.skill"
    path.write_text(
        f"description: {description}\n"
        f"temperature: {temperature}\n"
        f"max_tokens: {max_tokens}\n"
        f"---\n"
        f"{system_prompt}\n",
        encoding="utf-8",
    )
    return path
