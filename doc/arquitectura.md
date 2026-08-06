# Arquitectura de deep

> Agente de programación para terminal con DeepSeek — loop conversacional con tools, estilo Claude Code.

---

## 1. Visión general

**deep** (`deepseek-builder` en PyPI) es un agente de programación que opera sobre un workspace en disco. El usuario describe la tarea en lenguaje natural y el agente la resuelve usando herramientas: explora el proyecto, lee y escribe archivos, ejecuta comandos, y verifica su propio trabajo iterando hasta terminar.

El núcleo es un **loop conversacional con function calling** sobre la API de DeepSeek. Dos modelos cooperan por rol: **PRO** (`deepseek-v4-pro`) orquesta, decide y escribe el código que importa; **FLASH** (`deepseek-v4-flash`) hace trabajo masivo y barato de lectura/resumen.

```
┌──────────────┐     ┌──────────────────────────────────┐     ┌───────────────┐
│   Terminal   │────▶│            deep                  │────▶│  DeepSeek API │
│  (usuario)   │◀────│  CLI  ──  Core  ──  PWA (serve)  │◀────│  (PRO/FLASH)  │
└──────────────┘     └──────────────────────────────────┘     └───────────────┘
                              │
                              ▼
                     ┌────────────────┐
                     │   Workspace    │
                     │  (archivos en  │
                     │   disco +      │
                     │  .deep/)       │
                     └────────────────┘
```

---

## 2. Estructura del proyecto

```
deepseekcli/
├── deep.py                  # Punto de entrada (CLI principal)
├── pyproject.toml           # Build y metadata del paquete
├── cli/                     # Capa de presentación (terminal)
│   ├── agent_repl.py        #   REPL agente-first (interactivo)
│   ├── agent_runner.py      #   Runner de consola: permisos + display de eventos
│   ├── daemon_client.py     #   Cliente WS del daemon (autostart + sesión síncrona)
│   ├── commands.py          #   Comandos de alto nivel (build, update, serve, etc.)
│   ├── display.py           #   Pretty-printing (balance, archivos, evaluación)
│   ├── spinner.py           #   Spinner animado para operaciones largas
│   └── repl.py              #   REPL clásico legacy
├── core/                    # Lógica de negocio (sin dependencias de UI)
│   ├── agent_loop.py        #   ★ Loop conversacional con tool calling
│   ├── client.py            #   Cliente HTTP para la API de DeepSeek
│   ├── builder.py           #   Generación/edición de código delegada a FLASH
│   ├── models.py            #   IDs de modelos, roles y pricing
│   ├── router.py            #   Enrutado de modelos por rol + migración de IDs deprecados
│   ├── config.py            #   API key, idioma, configuración persistente
│   ├── context.py           #   Carga de DEEP.md (jerárquico: global + proyecto)
│   ├── rules.py             #   Carga de .deeprules
│   ├── skills.py            #   Carga de skills (.skill files)
│   ├── tasks.py             #   Lista de tareas persistente (.deep/tasks.json)
│   ├── journal.py           #   Bitácora entre sesiones (.deep/journal.md)
│   ├── compaction.py        #   Compactación fiel del contexto (map-reduce con FLASH)
│   ├── rag.py               #   Índice BM25 incremental + búsqueda semántica opcional
│   ├── planner.py           #   Planificación estructurada (plan JSON con archivos y dependencias)
│   ├── builder.py           #   CodeBuilder: delega generación/edición a FLASH
│   ├── system.py            #   Sistema legacy: build de una sola pasada (plan → generar → evaluar)
│   ├── writer.py            #   FileWriter: escribe archivos generados en disco
│   ├── prompts.py           #   Bloques de instrucciones reutilizables
│   ├── context_builder.py   #   Construcción de contexto acotado por archivo
│   ├── build_state.py       #   Estado intra-build (decisiones, patrones, errores)
│   ├── postcheck.py         #   Validación post-build/update
│   ├── project_scanner.py   #   Escáner determinista de proyectos existentes
│   ├── claudejob.py         #   Parser y orquestación del flujo Claude-planifica/DeepSeek-construye
│   ├── memory.py            #   Memoria de experiencias acumuladas
│   ├── agent.py             #   Agente reflexivo (meta-cognición)
│   ├── debug.py             #   Logger de debug (singleton, activado con --debug)
│   ├── balance.py           #   Consulta de saldo de la cuenta DeepSeek
│   ├── i18n.py              #   Internacionalización de la interfaz (es/en)
│   ├── updater.py           #   Verificación de nuevas versiones en PyPI
│   └── tools/               #   Implementación de tools para el agent loop
│       ├── __init__.py      #     Registry: schemas OpenAI + dispatch
│       ├── base.py          #     ToolContext (dataclass compartido)
│       ├── fs.py            #     read_file, write_file, edit_file, list_dir, glob
│       ├── search.py        #     grep
│       ├── search_code.py   #     search_code (búsqueda por relevancia)
│       ├── shell.py         #     run_command
│       ├── build.py         #     generate_code, apply_edit (delegan a CodeBuilder/FLASH)
│       ├── tasks.py         #     write_tasks, update_task
│       ├── subagent.py      #     spawn_agent
│       └── explore.py       #     explore (investigación read-only delegada a FLASH)
├── pwa/                     # Daemon de sesiones (deep serve) + PWA (acceso desde el celular)
│   ├── main.py              #   FastAPI + WebSocket (/ws/session), endpoints REST
│   ├── session_hub.py       #   SessionHub/SessionRegistry: AgentLoop compartido, fan-out, confirm round-trip
│   ├── generate_icons.py    #   Generación de íconos PWA
│   └── static/              #   Frontend: HTML, JS, CSS, manifest, service worker
├── tests/                   # Tests unitarios
├── examples/skills/         # Skills de ejemplo (reviewer, security, docs, refactor, explainer)
└── projects/                # Directorio de salida por defecto para builds
```

---

## 3. Flujo principal: el Agent Loop

El corazón del sistema es `core/agent_loop.py`. Implementa un loop conversation-first con function calling nativo de la API de DeepSeek:

### 3.1 Ciclo de ejecución

```
Usuario escribe tarea
        │
        ▼
┌──────────────────────────────────────────────┐
│  AgentLoop.run(user_input)                   │
│                                              │
│  1. Agrega mensaje "user" al historial       │
│  2. Bucle _run_steps():                      │
│     ┌──────────────────────────────────┐     │
│     │ a. compact_if_needed()           │     │
│     │ b. client.complete(messages,     │     │
│     │      tools=schemas(), ...)       │     │
│     │ c. ¿finish_reason ==             │     │
│     │    "tool_calls"?                 │     │
│     │    ├─ Sí → dispatch() cada tool  │     │
│     │    │  (spawn_agent en paralelo   │     │
│     │    │   si son 2+ independientes) │     │
│     │    │  → agrega resultados como   │     │
│     │    │    mensajes "tool"          │     │
│     │    │  → vuelve a (a)            │     │
│     │    └─ No → respuesta final       │     │
│     └──────────────────────────────────┘     │
│  3. auto_verify() — corre tests si          │
│     detecta pytest/npm test                 │
│  4. Si fallan → reinyecta al loop           │
│  5. Si max_steps + tareas abiertas →        │
│     auto-resume (hasta max_auto_resume)     │
└──────────────────────────────────────────────┘
        │
        ▼
  Respuesta final + stats (tokens, costo)
```

### 3.2 Sistema de permisos

Cuatro modos que controlan escritura y ejecución:

| Modo | Escritura | Shell |
|------|-----------|-------|
| `ask` (default) | Pregunta | Pregunta |
| `auto` | Acepta | Pregunta |
| `plan` | Bloquea (propone plan) | Bloquea |
| `yolo` | Acepta | Acepta |

Cada tool llama a `ctx.confirm(descripción)` antes de operaciones sensibles. El gate de permisos se implementa en `cli/agent_runner.py` (clase `Permissions`) y se inyecta en el `ToolContext`.

**Plan mode (`plan`)**: no es solo un bloqueo estático — tiene ciclo de vida, estilo Claude
Code. En modo `plan`, `AgentLoop` excluye del *schema* (no solo del gate en runtime) todas las
tools con efecto secundario (`_PLAN_BLOCKED_TOOLS` en `core/agent_loop.py`: `write_file`,
`edit_file`, `run_command`, `generate_code`, `apply_edit`, `write_tasks`, `update_task`,
`spawn_agent`, `browser_click`/`browser_type`/`browser_eval`/`browser_screenshot`) y le inyecta
al modelo (solo a él, no al evento que ve la UI) una directiva pidiéndole que investigue y
proponga con la tool `exit_plan_mode(plan)` en vez de intentar escribir. Esa tool dispara
`ctx.confirm_plan(plan)`: un round-trip de aprobación que **siempre** pregunta (bypassa el
gate de modo) y, si se aprueba, cambia el modo automáticamente al que estaba activo *antes* de
entrar a `plan` (`Permissions.set_mode`/`_pre_plan_mode`) — el agente sigue ejecutando el plan
en el mismo turno, sin que el usuario tenga que repetir el pedido. Si se rechaza, la sesión
sigue en `plan` y el modelo puede ajustar la propuesta.

---

## 4. Modelo de dos roles: PRO y FLASH

El sistema divide el trabajo entre dos modelos con distinto costo y capacidad:

| Rol | Modelo | Responsabilidades |
|-----|--------|-------------------|
| **PRO** (orquestador) | `deepseek-v4-pro` | Decidir qué tool llamar, escribir código (write_file/edit_file), revisar diffs, verificar |
| **FLASH** (constructor) | `deepseek-v4-flash` | Leer/resumir (`explore`), compactar contexto, generar código mecánico (`generate_code`/`apply_edit`), resumir sesión para la bitácora |

**Principio de calidad**: PRO escribe el código que importa. FLASH se usa solo para volumen mecánico de bajo riesgo (boilerplate, scaffolding, resúmenes). La calidad no se sacrifica por ahorrar tokens.

El enrutado se define en `core/models.py` (tabla `ROLE_MODELS`) y se resuelve en `core/router.py`. Los IDs deprecados `deepseek-chat` y `deepseek-reasoner` se mapean automáticamente a los modelos v4 (sunset 2026-07-24).

---

## 5. Tools: registro y dispatch

### 5.1 Registry central

En `core/tools/__init__.py`, cada módulo de tools exporta un diccionario `TOOLS` con entradas `{nombre: {schema, impl}}`. El registry unifica todos y expone:

- `schemas(exclude)` → lista de definiciones en formato OpenAI function calling
- `dispatch(name, args, ctx)` → ejecuta una tool por nombre (nunca levanta excepciones: devuelve el error como texto)

### 5.2 ToolContext

`core/tools/base.py` define `ToolContext`, un dataclass inyectado en cada tool con:

| Campo | Uso |
|-------|-----|
| `workspace` | `Path` raíz del proyecto |
| `on_event` | Callback para emitir eventos de UI |
| `confirm` | Gate de permisos |
| `confirm_plan` | Round-trip de aprobación de `exit_plan_mode` (siempre pregunta, bypassa el modo) |
| `builder` | Instancia de `CodeBuilder` (para generate_code/apply_edit) |
| `spawn` | Función para lanzar sub-agentes |
| `explore` | Función para investigación delegada a FLASH |

### 5.3 Tools disponibles

| Tool | Módulo | Rol |
|------|--------|-----|
| `read_file` | `fs.py` | Leer archivo (con offset/limit) |
| `write_file` | `fs.py` | Crear/sobreescribir archivo |
| `edit_file` | `fs.py` | Reemplazo quirúrgico de string |
| `list_dir` | `fs.py` | Listar directorio |
| `glob` | `fs.py` | Buscar archivos por patrón |
| `grep` | `search.py` | Buscar patrón regex |
| `search_code` | `search_code.py` | Búsqueda por relevancia (BM25 + semántico opcional) |
| `run_command` | `shell.py` | Ejecutar comando de shell |
| `generate_code` | `build.py` | Delegar generación de archivo a FLASH |
| `apply_edit` | `build.py` | Delegar edición quirúrgica a FLASH |
| `write_tasks` | `tasks.py` | Crear/reemplazar plan de tareas |
| `update_task` | `tasks.py` | Cambiar estado de una tarea |
| `spawn_agent` | `subagent.py` | Lanzar sub-agente para tarea autocontenida |
| `explore` | `explore.py` | Investigación read-only delegada a FLASH |
| `exit_plan_mode` | `plan.py` | Solo en modo `plan`: presenta el plan propuesto y pide aprobación antes de ejecutar |

Las tools `write_file` y `edit_file` son las herramientas PRINCIPALES para escribir código (las usa PRO directamente). `generate_code` y `apply_edit` son la EXCEPCIÓN, para volumen mecánico de bajo riesgo delegado a FLASH.

### 5.4 Sub-agentes y paralelismo

`spawn_agent` crea un `AgentLoop` hijo con contexto fresco que comparte el mismo `DeepSeekClient` y workspace. Cuando el modelo emite **2+ spawn_agent en el mismo turno**, se ejecutan en **paralelo** con `ThreadPoolExecutor`. Los sub-agentes:

- No tocan el plan global (`write_tasks`/`update_task` excluidos)
- No anidan más allá de `max_depth` (default 2)
- No corren verificación automática (el padre verifica una sola vez al final)
- Los prompts de permiso se serializan con un `threading.Lock`

`explore` es similar pero usa FLASH como orquestador y solo tiene tools de lectura (`read_file`, `grep`, `list_dir`, `glob`, `search_code`).

---

## 6. Compactación del contexto

Cuando el historial de mensajes supera ~150K caracteres (~37K tokens), `core/compaction.py` resume los turnos viejos para mantener el contexto dentro del límite de la API preservando la fidelidad.

### Algoritmo (map-reduce)

1. **Corte seguro**: se busca un boundary donde el mensaje sea `user` o `assistant` con `tool_calls`, para no partir un grupo tool_calls/tool.
2. **Render**: cada mensaje del tramo a resumir se convierte a texto con un tope por mensaje (6K chars).
3. **Segmentación**: si el tramo es enorme, se parte en segmentos de ~80K chars.
4. **Map**: cada segmento se resume con FLASH (prompt que exige preservar objetivo, archivos con rutas exactas, decisiones, comandos y sus resultados, y pendientes).
5. **Reduce**: si hay múltiples parciales, se combinan en un solo resumen coherente.
6. El resumen se inyecta como mensaje `assistant` con el marcador `[Resumen del trabajo previo en esta tarea]`.

---

## 7. Memoria y persistencia entre sesiones

### 7.1 DEEP.md (contexto del proyecto)

Archivo jerárquico estilo `CLAUDE.md`:

- `~/.config/deep/DEEP.md` — global (aplica a todos los proyectos)
- `<workspace>/DEEP.md` — del proyecto

Se inyecta como instrucciones autoritativas en el system prompt del agente. Se genera/actualiza con `/init`.

### 7.2 .deeprules

Lista de reglas (una por línea) que también se inyecta en el system prompt. Mantenido por compatibilidad.

### 7.3 .deep/tasks.json — plan de tareas persistente

Estructura:
```json
{
  "goal": "objetivo general",
  "tasks": [
    {"title": "qué hay que hacer", "status": "pending|in_progress|completed|failed"}
  ],
  "updated_at": "ISO timestamp"
}
```

Sobrevive al límite de pasos, al `continuá` y al reinicio. Al arrancar, el AgentLoop carga las tareas abiertas y las inyecta en el contexto. Si se alcanza `max_steps` con tareas pendientes, el agente **auto-reanuda** (hasta `max_auto_resume` veces).

### 7.4 .deep/journal.md — bitácora entre sesiones

Al cerrar la sesión, el REPL resume los mensajes no-system con FLASH y agrega una entrada datada con:
- **Hecho**: qué se hizo (archivos con rutas, cambios concretos)
- **Decisiones**: decisiones de diseño y su motivo
- **Próximo paso**: qué quedó pendiente

Al abrir `deep` en esa carpeta, se muestra la última entrada y se inyecta en el contexto del agente. El formato es markdown legible y editable a mano.

### 7.5 Memoria de experiencias

`core/memory.py` (`DeepSeekMemory`) persiste experiencias en `~/.config/deep/experiences.json`. Cada build/update analiza la experiencia con FLASH (lección, patrón, causa raíz) y la acumula. Se usa para encontrar experiencias similares al planificar y para extraer patrones recurrentes.

---

## 8. Índice de código: search_code

`core/rag.py` implementa un índice BM25 incremental sobre los archivos de texto del workspace, sin dependencias externas.

### Características

- **Incremental**: solo re-chunkea archivos cuyo fingerprint (mtime+size) cambió.
- **Tokenización consciente de código**: parte `camelCase` y `snake_case` para que `getUserName` matchee `user` y `name`.
- **Persistencia**: `.deep/index/manifest.json` + `chunks.json` + `vectors.json`.
- **Búsqueda semántica opcional**: con `pip install "deepseek-builder[semantic]"` se activa `fastembed`. El score es híbrido: 50% coseno semántico + 50% BM25 léxico. Esto permite que consultas en español matcheen identificadores en inglés. Se configura con `DEEP_EMBED_MODEL`.
- **Chunking**: ventanas de 60 líneas con solapamiento de 15.

---

## 9. Workflow legacy: build de una pasada

El sistema legacy (`core/system.py` → `DeepSeekLearningSystem`) implementa un flujo en 8 fases para generación de proyectos completos:

| Fase | Descripción | Modelo |
|------|-------------|--------|
| 1 | Planificación estructurada (JSON con arquitectura + archivos + dependencias) | PRO |
| 2 | Ejecución iterativa: genera archivos en orden topológico, con re-plan cada N archivos | FLASH |
| 3 | Verificación heurística + postcheck | — (determinista) |
| 4 | Evaluación final (revisión global del proyecto) | PRO |
| 5 | Análisis de experiencia (aprendizaje) | PRO |
| 6 | Reflexión profunda (opcional) | PRO |
| 7 | Meta-cognición (cada 5 builds) | PRO |
| 8 | Detección de patrones (cada 5 builds) | FLASH |

### Generación paralela

En la fase 2, los archivos sin dependencias entre sí se generan en **paralelo** (hasta 4 workers) usando `ThreadPoolExecutor`.

### Re-planificación adaptativa

Cada `REPLAN_EVERY_N` archivos (default 3), el sistema re-evalúa el plan: PRO recibe el progreso real (archivos escritos con snippets) y actualiza el plan para mantener coherencia con lo ya construido.

---

## 10. Flujo claudejob

`claudejob` es una capa de orquestación donde **Claude planifica** y **DeepSeek construye y corrige**:

1. **Claude** escribe `.deep/job.md` con secciones `## PLAN`, `## RULES`, `## TASKS` (módulos con archivos concretos).
2. **DeepSeek** construye módulo por módulo respetando exactamente el plan. Si el módulo declara archivos explícitos (`archivo ruta: detalle`), se usa un plan estructurado sin re-planificar.
3. **Review**: `deep claudejob --review` vuelca el estado (pedido vs construido + inventario en disco) para que Claude lo revise.
4. **Fix**: Claude escribe correcciones en `review.md` y `deep claudejob --fix review.md` las aplica módulo por módulo.

---

## 11. Interfaz de usuario

### 11.1 REPL agente-first (principal)

`cli/agent_repl.py` — El usuario escribe en lenguaje natural. Sobre un workspace **local**, el texto
va al daemon (`deep serve`, ver 11.3) vía `cli/daemon_client.py`, que lo autoarranca en background
si hace falta; sobre un workspace **SSH** (`--host`/`/remote`), el texto va directo a un `AgentLoop`
local, sin pasar por el daemon. Los `/comandos` controlan la sesión:

| Comando | Acción |
|---------|--------|
| `/init` | Explorar proyecto y escribir DEEP.md |
| `/scan` | Analizar proyecto existente |
| `/mode ask\|auto\|plan\|yolo` | Cambiar permisos |
| `/model pro\|flash` | Cambiar modelo orquestador |
| `/cost` | Tokens y costo por modelo de la sesión |
| `/clear` `/new` | Reiniciar conversación |
| `/skills` `/skill` | Listar/ejecutar skills |
| `/sessions` | Listar sesiones activas del daemon (terminal + PWA) |
| `/attach <id>` | Atachearse a una sesión del daemon en curso |

### 11.2 Modo directo (CLI)

`deep agent "tarea"` lanza el loop para una sola tarea y termina. Útil para scripting.

### 11.3 Daemon multi-sesión y PWA (serve)

`deep serve` levanta un servidor FastAPI que es, a la vez, el daemon de sesiones para la terminal y
el backend de la PWA — ambos son clientes del mismo proceso:

- **`SessionHub`/`SessionRegistry`** (`pwa/session_hub.py`): cada sesión envuelve un `AgentLoop` +
  `Permissions`, con fan-out a N suscriptores (terminal, PWA, o ambos a la vez sobre la misma
  sesión) y confirm round-trip (el pedido de permiso se transmite a todos los clientes atacheados;
  el primero que contesta resuelve el turno, con timeout de 120s que deniega por default). El
  `confirm_request` lleva un campo `kind` (`"confirm"` normal o `"plan"` para la aprobación de
  `exit_plan_mode`); aprobar un plan cambia el modo de la sesión y se propaga a todos los
  clientes atacheados vía el mismo evento `mode_changed` que ya usa `/mode`.
- **`/ws/session`** (WebSocket): protocolo único para turnos, eventos en vivo, confirmaciones,
  cambio de modo/modelo y cierre prolijo (journal). Reemplazó el streaming SSE viejo de `/api/agent`
  (ya retirado).
- **`GET /api/sessions`**: lista sesiones activas (id, workspace, modo, si están ocupadas).
- **`cli/daemon_client.py`**: cliente WS síncrono usado por la terminal (`ensure_daemon()` autoarranca
  `deep serve` en background la primera vez que hace falta, sin que el usuario lo corra a mano).
- **Auth obligatoria**: token en `~/.config/deep/config.json` (mismo archivo/permisos que la API
  key), generado solo si no hay `DEEP_APP_PASSWORD`; lo comparten terminal y PWA.
- **Frontend PWA**: `pwa/static/` — HTML+JS+CSS vanilla, instalable como app nativa en el celular,
  con panel de sesiones y confirmación de permisos por botones.
- **HTTPS**: `deep serve --https` genera certificados autofirmados con `trustme` para instalar la PWA.

---

## 12. Comunicación con la API de DeepSeek

`core/client.py` (`DeepSeekClient`) encapsula todas las llamadas HTTP a `https://api.deepseek.com/v1/chat/completions`:

- Soporta **function calling nativo**: recibe `tools` (schema OpenAI) y devuelve `tool_calls` + `finish_reason`.
- **Retry automático**: hasta 3 intentos con backoff.
- **Debug logging**: cada llamada registra modelo, tokens (incluyendo cache hits), latencia y finish_reason.
- **Prompt caching**: consciente de `prompt_cache_hit_tokens` para estimar costo real (los prefijos cacheados se cobran ~100× menos).
- **Fallback sin requests**: si `requests` no está instalado, usa `curl` vía subprocess.
- **Telemetría**: `get_stats()` devuelve total de llamadas, tokens, costo estimado por modelo, y cache hits.

---

## 13. Internacionalización (i18n)

La UI soporta español e inglés. `core/i18n.py` usa un diccionario de strings por clave + idioma. El idioma se persiste en `~/.config/deep/config.json` y se configura con `deep config set-lang` o `/lang` en el REPL.

El idioma del **código generado** se controla independientemente con variables de entorno:

| Variable | Controla | Default |
|----------|----------|---------|
| `DEEP_CODE_LANG` | Idioma de identificadores (variables, funciones, clases, archivos) | `inglés` |
| `DEEP_COMMENT_LANG` | Idioma de comentarios y docstrings | igual que `DEEP_CODE_LANG` |

---

## 14. Debug

`core/debug.py` es un singleton que se activa con `--debug` o `DEEP_DEBUG=1`. Escribe `debug.log` en el directorio actual con:

- Cada llamada a la API (modelo, tokens, latencia, finish_reason, tool_calls)
- Cada tool call con argumentos y resultado
- Eventos del loop (compactación, verificación, subagentes, auto-resume)
- Bloques de contenido (system prompts, responses)

---

## 15. Dependencias

### Dependencias core (install default)
- `requests>=2.28` — Cliente HTTP
- `prompt_toolkit` — REPL con autocompletado e historial
- `websocket-client` — cliente WS síncrono del REPL contra el daemon (`cli/daemon_client.py`)

### Dependencias opcionales
| Extras | Paquete | Para |
|--------|---------|------|
| `[serve]` | `fastapi`, `uvicorn[standard]`, `python-multipart` | Servidor web / PWA |
| `[https]` | `trustme`, `qrcode` | HTTPS autofirmado para PWA |
| `[semantic]` | `fastembed` | Búsqueda semántica en `search_code` |

### Python
- Requiere Python 3.9+

---

## 16. Diagrama de componentes

```
┌────────────────────────────────────────────────────────────────────┐
│  deep.py (entry point)                                            │
│  ├─ Sin args → cli/agent_repl.py (REPL agente-first)              │
│  └─ Con args → _legacy() → comandos (agent/build/update/serve...) │
└──────────────────────────┬───────────────────────────────────────┘
                           │
            ┌──────────────┴──────────────┐
            ▼                              ▼
   ┌──────────────────┐   WS (daemon_client.py)  ┌──────────────────┐
   │  cli/            │◀─────────────────────────│  pwa/            │
   │  agent_repl.py   │  workspace local: la      │  main.py         │
   │  agent_runner.py │  terminal es cliente WS   │  (FastAPI + WS)  │
   │  commands.py     │  del daemon, no dueña      │  session_hub.py │
   │  display.py      │  del AgentLoop             │  static/ (PWA)  │
   └────────┬─────────┘                            └────────┬─────────┘
            │ (solo SSH: AgentLoop local, sin daemon)         │
            └───────────────────────┬─────────────────────────┘
                                    ▼
              ┌─────────────────────────┐
              │  core/agent_loop.py     │
              │  (AgentLoop)            │
              │                         │
              │  • run(user_input)      │
              │  • _run_steps()         │
              │  • _spawn_subagent()    │
              │  • _explore()           │
              │  • _auto_verify()       │
              │  • _compact_if_needed() │
              └──────┬──────────┬───────┘
                     │          │
        ┌────────────┘          └────────────┐
        ▼                                    ▼
┌───────────────┐                  ┌───────────────────┐
│ core/client.py│                  │ core/tools/       │
│ DeepSeekClient│                  │ (registry +       │
│               │                  │  dispatch)         │
│ • complete()  │                  │                    │
│ • chat()      │                  │ fs/search/shell/   │
│ • get_stats() │                  │ build/tasks/       │
└───────┬───────┘                  │ subagent/explore   │
        │                          └─────────┬─────────┘
        ▼                                     │
┌─────────────────┐               ┌───────────┴───────────┐
│ DeepSeek API    │               │ core/builder.py       │
│ (PRO / FLASH)   │               │ CodeBuilder (FLASH)   │
└─────────────────┘               │ core/compaction.py    │
                                  │ core/rag.py (BM25)    │
                                  │ core/planner.py       │
                                  │ core/journal.py       │
                                  │ core/tasks.py         │
                                  │ core/memory.py        │
                                  └───────────────────────┘
```

---

## 17. Resumen de flujos principales

| Flujo | Entry point | Modelo principal | Descripción |
|-------|-------------|------------------|-------------|
| **REPL agente** | `cli/agent_repl.py::run()` | PRO | Loop interactivo: el usuario escribe tareas y el agente las resuelve con tools |
| **Agente one-shot** | `cli/agent_runner.py::run_agent()` | PRO | Igual que el REPL pero para una sola tarea |
| **Build legacy** | `core/system.py::execute_and_learn()` | PRO + FLASH | Generación completa: plan → generar → evaluar → aprender |
| **Update legacy** | `core/system.py::execute_update()` | FLASH | Modificación de proyecto existente |
| **Claudejob** | `cli/commands.py::run_claudejob()` | PRO + FLASH | Claude planifica (job.md), DeepSeek construye y corrige |
| **Scan** | `core/project_scanner.py::scan()` | — (determinista) | Análisis de proyecto existente sin LLM |
| **Serve (daemon + PWA)** | `pwa/main.py` (FastAPI) | PRO (loop vía WebSocket) | Daemon de sesiones compartido por la terminal y el celular — ver 11.3 |

---

*Documento generado a partir del análisis del código fuente de deep v0.9.0.*
