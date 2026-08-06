"""Tool de plan mode: exit_plan_mode presenta el plan propuesto y pide
aprobación explícita antes de pasar a modo ejecución."""
from core.tools.base import ToolContext


def exit_plan_mode(ctx: ToolContext, plan: str) -> str:
    ctx.on_event("plan_proposed", {"plan": plan})
    approved = ctx.confirm_plan(plan)
    if approved:
        return ("OK: el usuario APROBÓ el plan. El modo ya cambió a ejecución (podés "
                "escribir/ejecutar sin volver a pedir permiso por esto). Seguí ejecutando "
                "el plan tal cual lo propusiste, paso a paso, en este mismo turno.")
    return ("El usuario NO aprobó el plan todavía. Seguís en modo plan (solo lectura). "
            "Podés seguir investigando o ajustar la propuesta y volver a llamar "
            "exit_plan_mode con una versión revisada cuando quieras.")


TOOLS = {
    "exit_plan_mode": {
        "impl": exit_plan_mode,
        "schema": {
            "name": "exit_plan_mode",
            "description": (
                "SOLO disponible en modo plan. Presentá tu plan de implementación final, "
                "completo y en markdown, y pedile aprobación explícita al usuario ANTES de "
                "escribir o ejecutar nada. Si aprueba, el modo cambia solo a ejecución y "
                "podés seguir el mismo turno aplicando el plan. Si no aprueba, seguís en "
                "modo plan: investigá más o ajustá la propuesta y volvé a llamarla."),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan": {"type": "string", "description": (
                        "El plan completo en markdown: qué se va a hacer, en qué archivos, "
                        "en qué orden, y riesgos/decisiones de diseño. Autosuficiente — el "
                        "usuario no vio tu investigación, solo esto.")},
                },
                "required": ["plan"],
            },
        },
    },
}
