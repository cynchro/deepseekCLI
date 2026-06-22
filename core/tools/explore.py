"""Tool explore: investigación de SOLO LECTURA delegada a FLASH.

PRO le hace una pregunta sobre el código existente; un mini-agente FLASH lee/grepea
el workspace (sin escribir ni ejecutar nada) y le devuelve a PRO un resumen compacto
y factual. Así PRO entiende una parte grande o desconocida del proyecto SIN cargar su
contexto caro con archivos enteros. Como FLASH solo lee y resume, no hay riesgo de
calidad: PRO sigue tomando todas las decisiones y escribiendo todo el código.
"""
from core.tools.base import ToolContext


def explore(ctx: ToolContext, question: str, paths: list = None) -> str:
    if ctx.explore is None:
        return "ERROR: exploración no disponible en este contexto"
    return ctx.explore(question, paths)


TOOLS = {
    "explore": {
        "impl": explore,
        "schema": {
            "name": "explore",
            "description": ("Investigá una parte del código haciéndole una pregunta a un agente "
                            "LECTOR rápido (FLASH): lee y grepea el workspace de solo lectura y te "
                            "devuelve un resumen compacto y factual (signaturas, rutas archivo:línea, "
                            "convenciones, cómo se usa algo). Usalo ANTES de editar un área grande o "
                            "desconocida, para no cargar tu contexto con archivos enteros. NO escribe "
                            "ni ejecuta nada: vos seguís decidiendo y escribiendo el código."),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string",
                                 "description": "Qué necesitás entender (ej. 'cómo se registran las tools y dónde se despachan')"},
                    "paths": {"type": "array", "items": {"type": "string"},
                              "description": "Archivos o carpetas donde mirar primero (opcional)"},
                },
                "required": ["question"],
            },
        },
    },
}
