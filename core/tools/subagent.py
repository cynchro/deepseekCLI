"""Tool spawn_agent: delega una tarea autocontenida a un sub-agente con contexto fresco."""
from core.tools.base import ToolContext


def spawn_agent(ctx: ToolContext, task: str, context_files: list = None) -> str:
    if ctx.spawn is None:
        return "ERROR: no se pueden lanzar sub-agentes en este contexto"
    return ctx.spawn(task, context_files)


TOOLS = {
    "spawn_agent": {
        "impl": spawn_agent,
        "schema": {
            "name": "spawn_agent",
            "description": ("Delegá una tarea grande y autocontenida (un módulo, un subsistema) "
                            "a un sub-agente con contexto fresco. El sub-agente trabaja solo con "
                            "todas las herramientas y te devuelve un resumen + los archivos que "
                            "tocó, sin cargar tu contexto. Pasá una tarea clara y COMPLETA: el "
                            "sub-agente NO ve tu conversación. Las tareas chicas hacelas vos directo."),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string",
                             "description": "Tarea completa y autocontenida para el sub-agente"},
                    "context_files": {"type": "array", "items": {"type": "string"},
                                      "description": "Archivos relevantes que debería leer primero"},
                },
                "required": ["task"],
            },
        },
    },
}
