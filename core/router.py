"""Enrutado de modelos por rol + migración de IDs deprecados."""
from core.models import DEPRECATED_MODELS, MODEL_FLASH, ROLE_MODELS


def resolve_model(model: str) -> str:
    """Mapea IDs deprecados (deepseek-chat / -reasoner) a su equivalente v4.

    No-op para modelos ya vigentes. Garantiza que ninguna llamada use un modelo
    que desaparece el 2026-07-24.
    """
    if not model:
        return MODEL_FLASH
    return DEPRECATED_MODELS.get(model, model)


def model_for(role: str) -> str:
    """Resuelve un ROL (no un nombre de modelo) al modelo que le corresponde vía
    core.models.ROLE_MODELS. Rol ausente/desconocido -> FLASH: el fallback caro
    sería PRO, así que ante la duda el sistema se cae del lado barato."""
    return ROLE_MODELS.get(role, MODEL_FLASH)
