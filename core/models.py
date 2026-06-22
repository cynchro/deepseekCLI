"""Identificadores de modelo y enrutado por rol para deep v2.

PRO   = deepseek-v4-pro   → orquestar/decidir (planear, elegir tool, revisar diffs).
FLASH = deepseek-v4-flash → construir (generar/editar código), invocado por PRO.

deepseek-chat / deepseek-reasoner quedan deprecados (sunset 2026-07-24); se mapean
a los modelos v4 vía core.router.resolve_model.
"""

MODEL_PRO = "deepseek-v4-pro"
MODEL_FLASH = "deepseek-v4-flash"

# Default de la capa legacy mientras migramos el core.
MODEL_DEFAULT = MODEL_FLASH

# Rol -> modelo. El loop y los sub-flujos piden modelos por rol, no por nombre.
ROLE_MODELS = {
    "orchestrate": MODEL_PRO,
    "plan":        MODEL_PRO,
    "review":      MODEL_PRO,
    "decide":      MODEL_PRO,
    "reflect":     MODEL_PRO,
    "build":       MODEL_FLASH,
    "generate":    MODEL_FLASH,
    "edit":        MODEL_FLASH,
    "patch":       MODEL_FLASH,
    "summarize":   MODEL_FLASH,
}

# Modelos deprecados -> modelo v4 equivalente (sunset 2026-07-24).
DEPRECATED_MODELS = {
    "deepseek-chat":     MODEL_FLASH,   # modo no-thinking
    "deepseek-reasoner": MODEL_PRO,     # modo thinking
}

# Precio USD por 1M tokens (input cache miss / input cache hit / output).
# Fuente: api-docs 2026-06-17.
PRICING = {
    MODEL_PRO:   {"input": 0.435, "cache_hit": 0.003625, "output": 0.87},
    MODEL_FLASH: {"input": 0.14,  "cache_hit": 0.0028,   "output": 0.28},
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int,
                  cache_hit_tokens: int = 0) -> float:
    """Costo estimado (USD) de una llamada, contemplando el prompt caching:
    los tokens de prefijo cacheado se cobran ~100x más barato."""
    p = PRICING.get(model)
    if not p:
        return 0.0
    hit = max(int(cache_hit_tokens), 0)
    miss = max(prompt_tokens - hit, 0)
    return (hit / 1e6 * p["cache_hit"]
            + miss / 1e6 * p["input"]
            + completion_tokens / 1e6 * p["output"])
