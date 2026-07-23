"""Enrutado de modelos por rol + migración de IDs deprecados."""
from core.models import DEPRECATED_MODELS, MODEL_FLASH


def resolve_model(model: str) -> str:
    """Mapea IDs deprecados (deepseek-chat / -reasoner) a su equivalente v4.

    No-op para modelos ya vigentes. Garantiza que ninguna llamada use un modelo
    que desaparece el 2026-07-24.
    """
    if not model:
        return MODEL_FLASH
    return DEPRECATED_MODELS.get(model, model)
