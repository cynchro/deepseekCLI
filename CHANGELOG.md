# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto adhiere a [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

## [0.9.0] - 2026-06-22

Planner adaptativo + conciencia de proyectos existentes (PR #5), con refinamientos.

### Added
- **Planner adaptativo iterativo por archivo**: el build pasó de un solo tiro a
  `plan estructurado → generación por archivo → re-plan → revisión/parche → revisión
  final`, con memoria intra-build (`core/planner.py`, `core/build_state.py`,
  `core/context_builder.py`).
- **Onboarding de proyectos existentes**: comando `scan` que analiza el proyecto y
  cachea su contexto (`core/project_scanner.py`); `.deep/PROJECT.md` editable que el
  CLI respeta en build y update.
- **`scan` + auto-onboarding en el REPL agente-first** (`/scan`). El onboarding es
  **opt-in**: al entrar a un proyecto sin contexto lo detecta y sugiere `/scan`, sin
  disparar la llamada LLM en el arranque (sin costo ni demora sorpresa).

### Changed
- **claudejob usa el plan de Claude como plan estructurado directo**: DeepSeek
  construye exactamente los archivos declarados en `TASKS` sin re-planificar ni
  inventar (honra la regla "no crear archivos fuera de TASKS"). Si un módulo no
  nombra archivos, cae al plan de texto sembrado.

### Fixed
- Resiliencia en el build paralelo y consistencia de `_api_lock`.
- El evaluador final ya no penaliza requisitos fuera del alcance pedido.

## [0.8.1] - 2026-06-21

### Fixed
- **RAG**: se saltea `vendor/` al indexar (proyectos PHP/Composer) y se calculan los
  embeddings por lotes, acotando el pico de RAM; persistencia incremental de vectores
  para no recalcular todo ante una interrupción.

## [0.8.0] - 2026-06-19

Consola bilingüe (español / inglés): apertura a uso internacional.

### Added
- **Interfaz internacionalizada** (`core/i18n.py`): banner, ayuda, prompts y mensajes de
  ambos REPLs se muestran en español o inglés según el idioma elegido. Un **único setting**
  (`language`) controla las respuestas del modelo **y** la interfaz: `es` → consola en
  español; cualquier otro idioma (`en`/`pt`/`zh`/`fr`/`de`) → consola en inglés (base
  internacional), con respuestas del modelo en el idioma elegido.
- **Comando `/lang`** en el REPL agente-first para cambiar de idioma; `config set-lang` del
  REPL clásico ahora también cambia la interfaz. Ambos REPLs preguntan el idioma en el
  primer arranque.
- **`differences.md`**: versión en inglés de `diferencias.md`, enlazadas entre sí.

## [0.7.1] - 2026-06-19

Cierre estable: modelo de embeddings configurable + validación end-to-end.

### Added
- **`DEEP_EMBED_MODEL`**: elige el modelo de embeddings de `fastembed`. Para consultas en
  español conviene uno multilingüe (ej. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`),
  que mejora notablemente el ranking sobre código en inglés (margen #1 vs #2 de ~0.04 a 0.32).

### Notes
- Validación grande end-to-end: build de una librería de 3 módulos independientes (prompt en
  español) que descompuso en tareas, delegó los módulos en paralelo, generó código en inglés y
  dejó 87 tests en verde vía auto-verify. Todo el stack funcionando junto.
- Se decidió mantener el motor single-shot legacy (`core/system.py`, usado por la PWA y los
  comandos `build`/`claudejob`) y diferir los checkpoints de git, por estabilidad.

## [0.7.0] - 2026-06-19

Control de idioma: describir en tu idioma, obtener código en inglés.

### Added
- **Código en inglés por defecto** sin importar el idioma del pedido: identificadores,
  comentarios, docstrings y mensajes de commit/log en inglés (estándar de industria, facilita
  soporte/reventa). El agente conversa con vos en tu idioma, pero el código va en inglés.
  Configurable con `DEEP_CODE_LANG` (ej. `=español`).
- **Idioma de comentarios independiente** (`DEEP_COMMENT_LANG`): permite código en inglés con
  comentarios/docstrings en otro idioma. Los comentarios referencian los identificadores por su
  nombre real en inglés, sin traducirlos (ej. `getSeller()`/`seller`). Default = `DEEP_CODE_LANG`.
- Validado el camino real de la búsqueda semántica con `fastembed` instalado (embeddings de
  384 dims; rescata coincidencias cross-idioma que BM25 no ve).

## [0.6.0] - 2026-06-19

Refina la escala: búsqueda semántica opcional y autonomía en builds largos.

### Added
- **Búsqueda semántica opcional en `search_code`**: con `pip install "deepseek-builder[semantic]"`
  (fastembed), el índice suma embeddings locales y `search_code` usa score híbrido (BM25 + coseno),
  que además rescata coincidencias cross-idioma (consulta en español sobre código en inglés). Sin
  la extra, sigue funcionando con BM25 puro. El backend es perezoso y enchufable (no importa nada
  pesado al cargar); se apaga con `DEEP_NO_SEMANTIC=1`. Vectores incrementales en `.deep/index/`.
- **Auto-resume en builds largos**: al agotar `max_steps` con tareas abiertas en el plan
  (`.deep/tasks.json`), el agente se auto-reanuda solo (hasta `max_auto_resume=3`) en vez de cortar
  y pedir `continuá` a mano. No aplica a sub-agentes ni cuando no hay plan abierto.

## [0.5.0] - 2026-06-19

Escala a codebases y proyectos grandes con tres mejoras de fondo del agent loop.

### Added
- **RAG en el loop (`search_code`)**: índice BM25 léxico en Python puro (sin dependencias,
  offline) con tokenización code-aware (parte camelCase/snake_case). Ubica "dónde se hace X"
  por relevancia —mejor que grep— y devuelve los fragmentos con `archivo:línea`. Índice
  incremental por fingerprint (mtime+size), persistido en `.deep/index/`. DeepSeek no expone
  embeddings (verificado), así que el scoring queda desacoplado para enchufar `fastembed`
  opcional más adelante. (`core/rag.py`)
- **Sub-agentes en paralelo**: si el agente emite 2+ `spawn_agent` en el mismo turno (partes
  independientes), corren concurrentes (ThreadPoolExecutor, `max_parallel=4`) en vez de
  secuencial. Permisos serializados con lock; los sub-agentes no auto-verifican (evita N
  pytest a la vez) y el padre verifica una sola vez al cerrar con lo que tocaron todos.

### Changed
- **Compactación de contexto fiel** (`core/compaction.py`): ya no pre-trunca cada mensaje a
  1500 chars; usa map-reduce (segmenta, resume y combina) para historiales enormes y un prompt
  estructurado anti-alucinación con `temperature=0` que prohíbe inventar archivos/decisiones y
  exige reportar los tests que fallan como fallos. Reemplaza el resumen one-shot que perdía
  diffs, rutas y resultados (y podía declarar falsamente "tests OK").

## [0.4.0] - 2026-06-18

Salto de calidad estilo Claude Code: el modelo fuerte escribe el código (se revierte
el "truco de tokens"), con diffs visibles, edición quirúrgica y verificación automática.
La premisa: maximizar la calidad sin perderla por ahorrar tokens — DeepSeek ya es barato.

### Changed
- **PRO escribe el código directo** con `write_file`/`edit_file`, en vez de delegar los
  bytes a FLASH. El techo de calidad pasa a ser PRO, no el modelo débil. `generate_code`/
  `apply_edit` (FLASH) quedan como excepción para volumen mecánico de bajo riesgo. System
  prompt reescrito con disciplina de código (seguir convenciones, no inventar APIs, ser
  quirúrgico) y un loop de verificación obligatorio.
- **`apply_edit` quirúrgico**: FLASH devuelve bloques `SEARCH/REPLACE` que se aplican de
  forma determinística, en vez de reescribir el archivo entero (se elimina el drift).

### Added
- **`explore`**: investigación read-only delegada a FLASH. PRO le hace una pregunta sobre
  el código y un mini-agente lector (solo `read_file`/`grep`/`list_dir`/`glob`) devuelve un
  resumen compacto, descargando el contexto caro de PRO sin tocar la calidad.
- **Diffs visibles**: `edit_file`/`write_file`/`apply_edit` muestran el diff real en la
  consola y se lo devuelven a PRO para auto-revisión.
- **Verificación automática**: tras un turno que tocó código, corre los tests del proyecto
  (pytest / `npm test` detectados) y reinyecta el fallo al loop hasta dejarlo en verde
  (máx 2 intentos). Respeta los permisos: en modo plan o remoto (shell bloqueado) no corre.
- **Guard read-before-edit**: editar un archivo no leído en la sesión se bloquea (anti-alucinación).
- FLASH (`generate_code`/`apply_edit`) hereda el `project_context` (DEEP.md) y las reglas.

## [0.3.0] - 2026-06-17

Escala a proyectos grandes con dos patrones de Claude Code: lista de tareas
persistente y subagentes.

### Added
- **Lista de tareas persistente** (`.deep/tasks.json`): el agente descompone el
  trabajo con `write_tasks` y marca el progreso con `update_task`. Se inyecta al
  arrancar, así un build grande sobrevive al límite de pasos, al `continuá` y al
  reinicio. Comando `/tasks` y vista en vivo en la consola.
- **Subagentes** (`spawn_agent`): el agente delega una parte grande y autocontenida
  a un sub-agente con contexto fresco, que devuelve un resumen compacto — el
  orquestador se mantiene liviano. Comparte cliente (telemetría), workspace y
  permisos; con guardas de profundidad (`max_depth`) y aislamiento del plan global
  (los sub-agentes no tocan `.deep/tasks.json`).

Validado en un build real: una API REST en FastAPI (JWT, SQLite, módulos de
usuarios/proyectos/tareas, tests) — 11/11 tareas, 33 tests en verde, ~$0.05 (95%
de prompt cache hits en el orquestador).

## [0.2.0] - 2026-06-17

`deep` evoluciona de un **generador single-shot** a un **agente de programación
estilo Claude Code**, manteniendo la PWA remota y optimizando con el split de
modelos DeepSeek **PRO (decide) / FLASH (construye)**.

### Added
- **Agente con tool calling** (`deep agent`, y el REPL por defecto): loop
  conversacional donde el modelo decide qué herramientas usar, observa el
  resultado e itera hasta terminar — en vez de generar todo en una sola llamada.
- **Herramientas** (`core/tools/`): `read_file`, `write_file`, `edit_file`
  (edición quirúrgica por reemplazo de string), `list_dir`, `glob`, `grep`,
  `run_command`, `generate_code` y `apply_edit`. Seguridad de paths (no se sale
  del workspace) y errores devueltos como texto para que el agente se recupere.
- **Orquestación PRO/FLASH**: PRO orquesta y decide; `generate_code`/`apply_edit`
  delegan la generación de código a FLASH (más barato y rápido). Comparten el
  mismo cliente, así la telemetría suma ambos modelos.
- **REPL agente-first** (`cli/agent_repl.py`): el texto natural va al agente; los
  `/comando` son slash commands (`/init`, `/mode`, `/model`, `/cost`, `/clear`,
  `/rules`, `/skills`, `/skill`) + passthrough de los comandos legacy.
- **`DEEP.md`** — contexto de proyecto jerárquico (global + del proyecto),
  inyectado como instrucciones autoritativas. `/init` explora el proyecto y lo
  escribe automáticamente.
- **Permisos por modo** (`ask` / `auto` / `plan` / `yolo`) con `/mode`, y la
  opción `a` en el prompt para no volver a preguntar en toda la sesión.
- **PWA con agente en streaming**: endpoint `/api/agent` (SSE) que muestra la
  actividad de herramientas en vivo, con toggle 🤖 en el front. Permiso remoto
  seguro (shell bloqueado salvo `DEEP_REMOTE_SHELL=1`).
- **Compactación de contexto** automática para builds largos (resume el trabajo
  previo con FLASH sin romper los grupos de tool calls).
- **Telemetría de costo por modelo** + aprovechamiento del **prompt caching** de
  DeepSeek (visible en `/cost`).
- **`deep claudejob`** — flujo opcional donde Claude (u otro arquitecto externo)
  planifica y DeepSeek construye y corrige. Un solo archivo fuente (`.deep/job.md`)
  con secciones `PLAN`/`RULES`/`TASKS`; DeepSeek construye módulo por módulo usando
  el plan de Claude y se saltea su propia fase de planificación. Subcomandos:
  `--init` (plantilla; `--force` regenera y guarda copia `.bak`), `--review`
  (vuelca estado + formato para Claude) y `--fix <review.md>` (aplica las
  correcciones de Claude). El estado de cada módulo se guarda en
  `.deep/claudejob/state/`. No modifica el comportamiento de `deep build`.
- Persistencia del historial de chat entre sesiones.
- `config set-lang` — idioma preferido de las respuestas, persistido.

### Changed
- Modelos por defecto migrados a `deepseek-v4-pro` / `deepseek-v4-flash`. Los
  anteriores `deepseek-chat` / `deepseek-reasoner` se deprecan el 2026-07-24 y se
  remapean automáticamente.
- `deep` sin argumentos ahora abre el **REPL agente-first**; el REPL clásico sigue
  disponible con `DEEP_CLASSIC_REPL=1`.

### Fixed
- **PWA — streaming**: el middleware `log_requests` reinyectaba `request._receive`,
  lo que rompía `StreamingResponse` (SSE) y, según la versión de Starlette, también
  los handlers normales (`Unexpected message received: http.request`). Ahora no
  consume el body. Mejora la estabilidad de toda la PWA.
- **Escritura de archivos generados** (`core/writer.py`): el extractor exigía bloques
  con fences ```` ``` ````, pero el modelo emite los archivos como `### archivo: ruta`
  seguido de código crudo. Como consecuencia, algunos `build` no escribían ningún
  archivo (solo `RESPONSE.md`), o tomaban encabezados de sección de un README
  (`Instalación`, `Uso`, `Tests`) como nombres de archivo. Ahora la extracción se
  delimita por los marcadores `### archivo:` y conserva los fences internos del
  contenido. Afecta a todos los comandos que escriben archivos, no solo `claudejob`.
- Crash en la validación posterior al build (`core/postcheck.py` llamaba a
  `FileWriter._extract_named_blocks` sin instancia); ahora es `@staticmethod`.

## [0.1.3]

### Added
- Instalación de la PWA vía Tailscale (HTTPS) y túnel con cloudflared.
- Chequeo de actualización al iniciar.

### Fixed
- `prompt_toolkit` pasa a ser dependencia requerida.
- Flechas e historial habilitados en el modo REPL básico.
- Autodetección de puerto libre en `deep serve`.

## [0.1.1]

### Fixed
- Metadatos de `pyproject.toml` para compatibilidad con PyPI.
- Anchors HTML en los badges del README para evitar problemas de parseo de URL.

## [0.1.0]

### Added
- Primera versión open source: pipeline de generación, heurísticas de evaluación
  y validación del proyecto generado.

[Unreleased]: https://github.com/cynchro/deepseekCLI/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/cynchro/deepseekCLI/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/cynchro/deepseekCLI/compare/v0.8.0...v0.8.1
[0.3.0]: https://github.com/cynchro/deepseekCLI/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/cynchro/deepseekCLI/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/cynchro/deepseekCLI/compare/v0.1.1...v0.1.3
[0.1.1]: https://github.com/cynchro/deepseekCLI/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/cynchro/deepseekCLI/releases/tag/v0.1.0
