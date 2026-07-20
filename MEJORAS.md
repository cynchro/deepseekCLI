# Mejoras pendientes — deep

> Backlog de mejoras detectadas en el análisis del código (v0.9.0). Ordenadas por
> impacto/esfuerzo. Cada ítem incluye archivo:línea para retomarlo sin re-investigar.

---

## ✅ Resueltos

### 1. El retry reintenta errores que NO se deben reintentar — RESUELTO
**Archivo:** `core/client.py` (`APIStatusError`, `complete()`, `_call_api()`)

Se agregó `APIStatusError(status_code, message)`, levantada con el status real desde
ambos paths (`requests` y `curl`). `complete()` ahora reintenta solo `429`/`5xx`; el
resto de los `4xx` (401, 400, 402) falla en el primer intento. Test: `tests/test_client.py`
(`test_401_fails_without_retrying`, `test_400_...`, `test_402_...`, `test_429_retries_up_to_max`,
`test_500_retries_up_to_max`).

### 2. `finish_reason == "length"` no se maneja — RESUELTO
**Archivo:** `core/agent_loop.py:416-430` (`_run_steps`)

Si el modelo corta por límite de tokens en medio de un batch de `tool_calls`, ese
assistant se descarta SIN adjuntarle `tool_calls` (evita el grupo huérfano que la API
rechazaba con 400 "must be followed by tool messages") y se le pide al modelo reintentar
con llamadas más chicas. Test: `tests/test_agent_loop_truncation.py`.

### 3. El path de fallback con `curl` no detecta errores HTTP — RESUELTO
**Archivo:** `core/client.py` (`_call_api`, rama sin `requests`)

Se agregó `-w "\n%{http_code}"` al comando de `curl` para leer el status real; si es
`>= 400` levanta `APIStatusError` igual que el path de `requests` (mismo manejo de
retry). Test: `tests/test_client.py` (`test_curl_fallback_detects_http_error_status`,
`test_curl_fallback_success_still_parses_body`, `test_curl_fallback_retries_on_500`).

### 4. La API key se escribe en plaintext en `~/.bashrc` / `~/.zshrc` — RESUELTO
**Archivo:** `core/config.py` (`prompt_and_save`)

`deep.py` ya lee la key siempre desde `config.json` (0600) vía `load_api_key()`;
`_add_to_shell` nunca fue necesario para que `deep` funcione, solo era conveniencia
para tener la variable en otros scripts. Ahora es opt-in explícito: `prompt_and_save`
avisa el trade-off (texto plano, riesgo de dotfiles) y solo exporta al rc si el usuario
contesta que sí — por default (Enter/EOF) no toca ni `.bashrc` ni `.zshrc`. Test:
`tests/test_config_api_key.py`.

### 6. Falta cobertura en lo más crítico — RESUELTO
`safe_path()` (`core/tools/base.py:38`) ahora tiene test: `tests/test_safe_path.py`
cubre `../`, paths absolutos, symlinks que escapan y symlinks que se quedan adentro.

---

## 🔴 Bugs / robustez (alto impacto, bajo esfuerzo)

_(sin ítems pendientes por ahora — ver Resueltos arriba)_

---

## 🟢 Limpieza / deuda técnica

### 5. ~~Código muerto en `client.py`~~ — DESCARTADO (no está muerto)
**Archivo:** `core/client.py:188` (`chat_with_context`) y `client.py:196`
(`compact_history`).

Al verificar antes de borrar apareció uso real: `pwa/main.py:154` (`chat_with_context`,
endpoint `/api/ask` del servidor PWA) y `cli/commands.py:240,250` (`run_ask`, el comando
legacy de preguntas con historial, usa ambos métodos). Son parte del camino legacy
(single-shot, pre-agente) y usan el límite viejo de 64K en vez de `core/compaction.py`,
pero borrarlos rompería el servidor PWA y `run_ask`. Migrar esas dos rutas a
`core/compaction.py` y recién ahí borrar sería un cambio aparte, no una limpieza
autocontenida — se descarta por ahora.

---

## 🔵 UX (más esfuerzo, alto valor de producto)

### 7. No hay streaming de la respuesta del modelo
**Archivo:** `core/client.py::complete()` (no soporta `stream=True`); afecta
`core/agent_loop.py`, `cli/agent_runner.py` y el SSE de `pwa/main.py`.

El usuario mira un spinner hasta que el turno termina entero. Claude Code streamea token
a token. Es el gap de UX más grande contra el norte del proyecto, pero el cambio más
invasivo (toca client + agent_loop + runner + SSE de la PWA).

**Fix:** soportar `stream=True` en el cliente y propagar los chunks por `on_event` hasta
la consola y el SSE.

---

## Orden sugerido de ataque
1. ~~Ítems **1, 2, 3, 4, 6**~~ — RESUELTOS.
2. Ítem **5** — descartado, no era código muerto (ver arriba).
3. Ítem **7** (streaming) queda como único pendiente, proyecto aparte.
