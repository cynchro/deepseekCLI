"""Tool spawn_agent: delega una tarea autocontenida a un sub-agente con contexto fresco."""
from core.models import ROLE_MODELS
from core.tools.base import ToolContext

_DEFAULT_ROLE = "build"  # FLASH: caso común, ejecución mecánica bien especificada


def spawn_agent(ctx: ToolContext, task: str, context_files: list = None,
                role: str = _DEFAULT_ROLE) -> str:
    if ctx.spawn is None:
        return "ERROR: no se pueden lanzar sub-agentes en este contexto"
    return ctx.spawn(task, context_files=context_files, role=role)


TOOLS = {
    "spawn_agent": {
        "impl": spawn_agent,
        "schema": {
            "name": "spawn_agent",
            "description": ("Delegá una tarea grande y autocontenida (un módulo, un subsistema) "
                            "a un sub-agente con contexto fresco. El sub-agente trabaja solo con "
                            "todas las herramientas y te devuelve un resumen + los archivos que "
                            "tocó, sin cargar tu contexto. Pasá una tarea clara y COMPLETA: el "
                            "sub-agente NO ve tu conversación. Las tareas chicas hacelas vos directo.\n"
                            "Elegí `role` según qué tan mecánica es la tarea delegada:\n"
                            "- 'build'/'generate'/'edit'/'patch'/'summarize' (FLASH, barato): la "
                            "tarea está bien especificada y es de bajo riesgo — seguir un patrón "
                            "existente, CRUD estándar, boilerplate, tests de algo ya diseñado. Es "
                            "el default: usalo salvo que la tarea lo justifique.\n"
                            "- 'orchestrate'/'plan'/'review'/'decide'/'reflect' (PRO, caro): la "
                            "tarea requiere diseño, ambigüedad a resolver, un algoritmo no trivial, "
                            "o decisiones de arquitectura — pedilo solo cuando de verdad haga falta."),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string",
                             "description": "Tarea completa y autocontenida para el sub-agente"},
                    "context_files": {"type": "array", "items": {"type": "string"},
                                      "description": "Archivos relevantes que debería leer primero"},
                    "role": {"type": "string", "enum": list(ROLE_MODELS),
                             "description": "Rol de la tarea delegada (ver arriba). "
                                            "Default: 'build' (FLASH)."},
                },
                "required": ["task"],
            },
        },
    },
}
