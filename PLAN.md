# deep v2 — Plan maestro

> Norte del proyecto. Evolución del CLI `deep` (DeepSeek) hacia un **agente con
> herramientas en loop**, estilo Claude Code, manteniendo la interfaz remota (PWA)
> y optimizando inteligencia/velocidad/tokens con un split de modelos Pro/Flash.

Branch de trabajo: `v2` (sacada de `feat/upgrade-cli`).
Fecha de inicio: 2026-06-17.

---

## 1. Visión

v1 es un **dispatcher de comandos + generador single-shot**: escribís `build`/`update`/`fix`
y cada comando dispara una función fija que genera o regenera archivos enteros en una
sola llamada al modelo.

v2 es **un agente conversacional**: hablás en lenguaje natural, el modelo decide qué
**herramientas** llamar (`read_file`, `edit_file`, `write_file`, `grep`, `run_command`…),
observa el resultado e itera hasta terminar. `build`/`update`/`fix` dejan de ser comandos:
son tareas que el mismo agente resuelve.

Eso es lo que hace cómodo a Claude Code. Todo lo demás (reglas, skills, permisos,
slash commands) cuelga de ese loop.

---

## 2. Estado actual (v1) — diagnóstico

| Pieza | Hoy |
|-------|-----|
| REPL (`cli/repl.py`) | Router de comandos, no agente. `ask` abre un Q&A con historial. |
| Motor (`core/system.py`) | `_plan` (1 llamada, prosa) → `_execute` (**1 llamada genera TODOS los archivos**) → `_evaluate`. `update`/`fix` vuelcan hasta 15 archivos enteros en un prompt. |
| Modelos | Uno solo (`deepseek-chat`). Sin split Pro/Flash. |
| Tool calling | No existe. Texto→texto, parseando bloques `### archivo: ruta`. |
| Skills (`core/skills.py`) | Swap de system prompt para un chat. |
| Rules (`core/rules.py`) | Lista plana inyectada al prompt. |
| Permisos | No hay. |
| PWA (`pwa/main.py`) | FastAPI: `/api/ask` (chat), `/api/run` (dispatch de build/fix/update/show), `/api/projects`, `/api/ls`. **Se conserva.** |

---

## 3. Paso 0 — verificación de la API (✅ HECHO, 2026-06-17)

Verificado contra `api.deepseek.com` con la key real:

- **Modelos existen**: `GET /models` devuelve `deepseek-v4-pro` y `deepseek-v4-flash`.
  (`deepseek-chat` y `deepseek-reasoner` quedan deprecados, sunset **2026-07-24** → migrar.)
- **Function calling nativo FUNCIONA** end-to-end: respuesta con
  `finish_reason: tool_calls` y `tool_calls[].function.{name, arguments}` (arguments = JSON string).
  → **El agent loop va por tool calling nativo. No hace falta protocolo JSON de emulación.**
- **Prompt caching disponible** (`prompt_cache_hit_tokens`): mantener system prompt +
  definición de tools estables maximiza cache hits y abarata.
- Flash devuelve `reasoning_tokens` (tiene modo thinking).

### Pricing real (USD / 1M tokens)

| Modelo | input cache hit | input cache miss | output |
|--------|-----------------|------------------|--------|
| `deepseek-v4-pro`   | $0.003625 | $0.435 | $0.87 |
| `deepseek-v4-flash` | $0.0028   | $0.14  | $0.28 |

Flash es **~3.1× más barato** en input y output. Esto fundamenta la orquestación.

---

## 4. Orquestación Pro / Flash

Patrón **jerárquico** (no un router que adivina por turno):

| Rol | Modelo | Por qué |
|-----|--------|---------|
| Orquestador del loop (entender, planear, elegir tool, revisar diffs, decidir fin) | **PRO** | Es el cerebro. Su contexto se mantiene liviano: ve specs y diffs, no código masivo. |
| Construcción (generar contenido, aplicar edits, transformaciones mecánicas) | **FLASH** | Las manos. Produce el texto verboso barato y rápido. |
| `read_file` / `grep` / `list_dir` / `run_command` | — | Determinista, sin LLM. |

**⚠️ REVISADO (2026-06-18) — el "truco de tokens" se revierte.** El patrón original
("PRO no escribe código; describe specs y FLASH produce los bytes") costaba calidad: el
techo de calidad pasaba a ser FLASH, había una traducción con pérdida intención→spec→código,
y `apply_edit` reescribía archivos enteros (drift, código colateral alterado). **Principio
nuevo:** el modelo fuerte (PRO) escribe el código directo con `write_file`/`edit_file`
quirúrgico, igual que Claude Code. `generate_code`/`apply_edit` (FLASH) quedan como
EXCEPCIÓN para volumen mecánico de bajo riesgo (boilerplate, scaffolding, fixtures), nunca
para lógica/algoritmos/APIs. El split Pro/Flash se reserva para tareas no críticas de
escritura (resúmenes, compactación, búsqueda). Branch: `feat/quality-direct-write`.

FLASH sigue siendo "las manos" solo en ese rol acotado.

Telemetría: contabilizar gasto por modelo por separado.

---

## 5. Arquitectura objetivo

```
core/
  models.py        # MODEL_PRO, MODEL_FLASH + role->model
  router.py        # model_for(role)
  client.py        # + soporte tools (function calling) + parseo de tool_calls  [EXTENDER, no reescribir]
  agent_loop.py    # ★ el corazón: loop conversacional con tools
  tools/
    __init__.py    # registry + schemas JSON
    fs.py          # read_file, write_file, edit_file (string-replace), list_dir, glob
    search.py      # grep
    shell.py       # run_command (con permiso)
    build.py       # generate_code / apply_edit -> enrutan a FLASH
  permissions.py   # gate antes de write/edit/bash (modos: ask / auto-edits / plan)
  context.py       # carga DEEP.md (jerárquico) + scan de proyecto + compactación
  skills.py        # skills "agénticas" (el agente las invoca cuando aplican)  [EVOLUCIONAR]
  memory.py        # aprendizaje (opcional, se conserva)

cli/repl.py        # input natural -> agent_loop; "/comando" -> slash commands
pwa/main.py        # + /api/agent con streaming; endpoints viejos siguen vivos
```

- **Reglas → `DEEP.md`** (el CLAUDE.md de deep): jerárquico (global `~/.config/deep/DEEP.md`
  + `./DEEP.md`), auto-inyectado. `.deeprules` sigue funcionando por compatibilidad.
  `/init` escanea el proyecto y lo siembra.
- **Skills agénticas**: de "swap de prompt" a "capacidad nombrada con descripción +
  instrucciones + tools permitidas + hint de modelo" que PRO invoca a mitad del loop, o
  el usuario con `/skill`. Los `.skill` actuales siguen cargando.
- **Permisos**: gate antes de tocar disco/shell. Modos como Claude Code.

---

## 6. Roadmap por fases (incremental, sin romper v1)

**Fase 0 — Cimientos** ✅ HECHA. Verificación API + `core/models.py` (constantes,
ROLE_MODELS, PRICING, estimate_cost) + `core/router.py` (`model_for`, `resolve_model`)
+ `core/client.py` extendido (`complete()` con tool calling nativo, `chat()` retrocompatible,
`get_stats()` con desglose y costo por modelo). Bonus: defaults migrados de `deepseek-chat`
a `flash` (PWA y system.py incluidos).

**Fase 1 — Agent loop con tools (el corazón)** ✅ HECHA. `core/tools/` (base + fs:
read/write/edit/list/glob, search: grep, shell: run_command, con registry +
schemas + dispatch) y `core/agent_loop.py` (loop conversacional multi-turno con tool
calling nativo, permisos vía `ctx.confirm`, telemetría). Enganchado: `cli/agent_runner.py`
(consola con permisos + costo por modelo), comando `agent` en el REPL (conversacional,
`reset` reinicia) y subcomando `deep agent` en la CLI. Verificado e2e: el agente crea,
edita quirúrgicamente y corre código real. Pendiente (Fase 3): hacerlo el handler por
defecto del input natural.

**Fase 2 — Orquestación Pro/Flash** ✅ HECHA. `core/builder.py` (CodeBuilder: usa el
MISMO client que el loop, pasando model=FLASH) + tools `generate_code`/`apply_edit`
(`core/tools/build.py`) que delegan la generación pesada a FLASH; el loop sigue en PRO.
System prompt guía a PRO a delegar. Telemetría por modelo ya mostraba ambos. Verificado
e2e: PRO orquestó, FLASH generó calc.py+tests, tests verdes, by_model = {pro, flash}.

**Fase 3 — Capa "Claude"** ✅ HECHA. REPL agente-first `cli/agent_repl.py` (texto natural
→ agente; `/comando` → slash). `core/context.py`: DEEP.md jerárquico (global + proyecto)
inyectado al system prompt + `/init` (el agente explora y escribe DEEP.md). Permisos con
modos ask/auto/plan/yolo (`Permissions` en `cli/agent_runner.py`) + `/mode`. Slash commands:
/help /init /mode /model /cost /clear /rules /skills /skill + passthrough legacy
(/balance /history /doctor /show /serve /upgrade). `deep` (sin args) lanza el REPL v2;
`DEEP_CLASSIC_REPL=1` usa el clásico. Verificado e2e: /init escribió DEEP.md detectando
el stack; modo plan bloqueó escrituras.

**Fase 4 — PWA al día** ✅ HECHA. `pwa/main.py`: endpoint `/api/agent` con streaming SSE
sobre el AgentLoop (sesiones de agente por sid+workspace), permiso remoto seguro
(escrituras OK, shell BLOQUEADO salvo `DEEP_REMOTE_SHELL=1`). Frontend: toggle 🤖 Agente
(`index.html`/`app.js`) que rutea texto natural al stream y muestra la actividad de tools en
vivo + costo por modelo. Bug arreglado de raíz: el middleware `log_requests` reinyectaba
`request._receive` y rompía SSE *y* (según versión de Starlette) los handlers normales; ahora
no consume el body. Verificado e2e (TestClient): /api/agent streaming + /api/ask + /api/run +
/api/health, todos OK; shell remoto bloqueado.

**Fase 6 — Escala / proyectos grandes** 🚧 (en curso, branch `feat/tasks`).
- ✅ Plan + tareas persistentes (estilo TODO de Claude Code, + persistencia en disco):
  `core/tasks.py` (store en `.deep/tasks.json`) + tools `write_tasks`/`update_task`
  (`core/tools/tasks.py`). El loop inyecta el plan pendiente al arrancar (sobrevive al
  tope de pasos, al 'continuá' y al reinicio); system prompt guía a descomponer y marcar
  progreso; consola muestra el plan en vivo; slash `/tasks`. Verificado e2e.
- ✅ Subagentes: tool `spawn_agent` (`core/tools/subagent.py`) + `AgentLoop._spawn_subagent`.
  PRO delega una tarea autocontenida a un AgentLoop hijo con contexto fresco; el hijo trabaja
  solo y devuelve un resumen compacto (no su transcript) → el contexto del padre queda liviano.
  Comparte client (telemetría), workspace y permisos. Guards: `max_depth=2`, los sub-agentes
  no tocan el plan global (`.deep/tasks.json` excluido) ni anidan de más. Display anidado
  (↪/↩). Verificado e2e: PRO delegó 2 módulos, los hijos los construyeron, padre no usó
  generate_code/write_file. Pendiente opcional: paralelismo (hoy secuencial).

**Fase 5 — Pulido** ✅ (núcleo HECHO). Compactación de contexto en el AgentLoop
(`_compact_if_needed`: resume turnos viejos con FLASH en límites de mensaje 'user', sin
romper grupos tool_calls/tool; umbral configurable). Costo preciso con prompt caching:
`PRICING` con precio cache-hit, `estimate_cost` contempla tokens cacheados, el cliente
captura `prompt_cache_hit_tokens`, `/cost` los muestra. Verificado: caching real activo
(4096/6582 tok cacheados en un run). Pendiente opcional: subagentes; el single-shot
`system.py` queda como fast-path del `build` legacy/PWA (no se retira).

---

## 7. Reglas de oro (para que sea v2 ESTABLE, no beta)

1. **El `deep` viejo nunca se rompe.** Comandos (`build`/`update`/`fix`/`serve`) y endpoints
   PWA siguen respondiendo durante toda la migración (al principio, wrappers finos sobre el loop).
2. **PWA sin tocar el frontend** hasta la fase 4.
3. **Migrar IDs de modelo** fuera de `deepseek-chat`/`deepseek-reasoner` (sunset 2026-07-24).
4. Cada fase mergeable a `main` por separado.

---

## 8. Definición de "estable" (criterio de salida v2.0)

- [x] El loop con tools edita un proyecto existente **sin regenerar archivos enteros** (edit_file / apply_edit).
- [x] Split Pro/Flash funcionando, con telemetría de tokens y costo por modelo.
- [x] Permisos: confirma antes de tocar disco/shell (+ opción 'a' / modos ask/auto/plan/yolo).
- [x] `DEEP.md` se carga (global + proyecto).
- [x] La PWA anda igual o mejor (agente en streaming + fix de estabilidad del middleware).
- [x] Comandos legacy siguen respondiendo (CLI subcomandos + endpoints PWA).

**→ v2 cumple la definición de estable.** Falta opcional: subagentes, retiro del single-shot,
y mergear `v2` → `main` + version bump.

---

## 9. Qué se conserva / qué se reemplaza

**Se conserva (sólido):** `client.py` (extender), `config.py`, `balance.py`, `debug.py`,
`rules.py`, toda la PWA `pwa/`.

**Se reemplaza:** `system.py` single-shot → `agent_loop.py` + tools.
(El planner por-archivo de `feat/new-planner` —`models.py`, `context_builder.py`— se
cherry-pickea como utilidades; el planner queda como sub-flujo opcional, no como paradigma.)

---

## 10. Riesgos abiertos

1. ~~IDs de modelo + tool calling~~ → ✅ resuelto en Paso 0.
2. **Reconciliación con `feat/new-planner`**: el agent-loop absorbe su planner como sub-flujo.
3. **Scope**: el loop es una reescritura real del core. Decidido: agent loop completo.
4. **Sunset de modelos viejos (2026-07-24)**: migrar defaults antes de esa fecha.

---

## Estado / próximos pasos

- [x] Paso 0 — verificación API (modelos + tool calling + pricing).
- [x] Branch `v2` creada.
- [x] `PLAN.md` (este archivo).
- [x] Fase 0 — `core/models.py`, `core/router.py`, `core/client.py` extendido. Verificado (smoke test + imports + compile).
- [x] Fase 1 — `core/tools/` (fs/search/shell) + `core/agent_loop.py` + `cli/agent_runner.py` + comando `agent`. Verificado e2e real (crea/edita/corre código).
- [x] Fase 2 — orquestación Pro/Flash: `core/builder.py` + tools `generate_code`/`apply_edit` → FLASH; loop en PRO. Verificado e2e (by_model = {pro, flash}, tests verdes).
- [x] Fase 3 — capa "Claude": REPL agente-first (`cli/agent_repl.py`), `DEEP.md` + `/init` (`core/context.py`), permisos/modos (ask/auto/plan/yolo), slash commands, `/skill`. Verificado e2e.
- [x] Fase 4 — PWA: `/api/agent` SSE + toggle 🤖 Agente en el front + permiso remoto (shell gated). Fix middleware. Verificado e2e (TestClient): agent + legacy intactos.
- [x] Fase 5 — pulido (núcleo): compactación de contexto + costo con prompt caching (verificado real). Opcionales (subagentes) y retiro del single-shot: diferidos.
