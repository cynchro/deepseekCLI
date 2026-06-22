"""Tools de la lista de tareas: write_tasks (plan completo) y update_task (un estado)."""
from core.tools.base import ToolContext
from core import tasks as store


def write_tasks(ctx: ToolContext, tasks: list, goal: str = None) -> str:
    norm = store.normalize(tasks)
    if not norm:
        return "ERROR: la lista de tareas está vacía"
    data = store.load_tasks(ctx.workspace)
    if goal is not None:
        data["goal"] = goal
    data["tasks"] = norm
    store.save_tasks(ctx.workspace, data)
    ctx.on_event("tasks", {"data": data})
    return "Plan de tareas actualizado:\n" + store.render(data)


def update_task(ctx: ToolContext, task: str, status: str, note: str = None) -> str:
    if status not in store.STATUSES:
        return f"ERROR: status inválido '{status}' (usá: {', '.join(store.STATUSES)})"
    data = store.load_tasks(ctx.workspace)
    tasks = data.get("tasks", [])
    if not tasks:
        return "ERROR: no hay tareas; creá el plan con write_tasks primero"
    idx = None
    key = str(task).strip()
    if key.isdigit():
        idx = int(key) - 1
    else:
        for i, t in enumerate(tasks):
            if key.lower() in t.get("title", "").lower():
                idx = i
                break
    if idx is None or idx < 0 or idx >= len(tasks):
        return f"ERROR: tarea no encontrada: {task}"
    tasks[idx]["status"] = status
    if note:
        tasks[idx]["note"] = note
    store.save_tasks(ctx.workspace, data)
    ctx.on_event("tasks", {"data": data})
    return "OK:\n" + store.render(data)


TOOLS = {
    "write_tasks": {
        "impl": write_tasks,
        "schema": {
            "name": "write_tasks",
            "description": ("Crea o reemplaza el plan de tareas (persistido en .deep/tasks.json). "
                            "Usalo al empezar un trabajo con varios pasos para descomponerlo, y "
                            "para re-planificar. Reenviá SIEMPRE la lista completa con el estado "
                            "actual de cada tarea."),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Objetivo general del trabajo"},
                    "tasks": {
                        "type": "array",
                        "description": "Lista completa de tareas en orden",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "Qué hay que hacer"},
                                "status": {"type": "string",
                                           "enum": ["pending", "in_progress", "completed", "failed"]},
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["tasks"],
            },
        },
    },
    "update_task": {
        "impl": update_task,
        "schema": {
            "name": "update_task",
            "description": ("Cambia el estado de UNA tarea del plan (más barato que reenviar todo "
                            "con write_tasks). Marcá in_progress al empezarla y completed al "
                            "terminarla, a medida que avanzás."),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Número (1-based) o parte del título de la tarea"},
                    "status": {"type": "string",
                               "enum": ["pending", "in_progress", "completed", "failed"]},
                    "note": {"type": "string", "description": "Nota opcional (ej. por qué falló)"},
                },
                "required": ["task", "status"],
            },
        },
    },
}
