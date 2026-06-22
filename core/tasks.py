"""Lista de tareas persistente del agente (.deep/tasks.json) — el TODO de deep.

Sobrevive al límite de pasos, al 'continuá' y al reinicio: el AgentLoop la carga
al arrancar e inyecta lo pendiente en el contexto, así un build grande se retoma
sin repetir lo ya hecho.
"""
import json
from datetime import datetime
from pathlib import Path

STATUSES = ("pending", "in_progress", "completed", "failed")
_MARK = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]", "failed": "[!]"}


def tasks_path(workspace) -> Path:
    return Path(workspace) / ".deep" / "tasks.json"


def load_tasks(workspace) -> dict:
    p = tasks_path(workspace)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("tasks"), list):
                return data
        except Exception:
            pass
    return {"goal": "", "tasks": []}


def save_tasks(workspace, data: dict) -> None:
    p = tasks_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize(tasks: list) -> list:
    """Acepta strings o dicts; devuelve [{title, status}]."""
    out = []
    for t in tasks or []:
        if isinstance(t, str):
            title, status = t, "pending"
        elif isinstance(t, dict):
            title = (t.get("title") or t.get("content") or "").strip()
            status = t.get("status", "pending")
        else:
            continue
        if not title:
            continue
        if status not in STATUSES:
            status = "pending"
        out.append({"title": title, "status": status})
    return out


def render(data: dict) -> str:
    tasks = data.get("tasks", [])
    if not tasks:
        return "(sin tareas)"
    lines = []
    if data.get("goal"):
        lines.append(f"Objetivo: {data['goal']}")
    for i, t in enumerate(tasks, 1):
        lines.append(f"{_MARK.get(t.get('status', 'pending'), '[ ]')} {i}. {t.get('title', '')}")
    done = sum(1 for t in tasks if t.get("status") == "completed")
    lines.append(f"({done}/{len(tasks)} completadas)")
    return "\n".join(lines)


def has_open(data: dict) -> bool:
    return any(t.get("status") in ("pending", "in_progress") for t in data.get("tasks", []))
