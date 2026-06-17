# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto adhiere a [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

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

[Unreleased]: https://github.com/cynchro/deepseekCLI/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/cynchro/deepseekCLI/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/cynchro/deepseekCLI/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/cynchro/deepseekCLI/compare/v0.1.1...v0.1.3
[0.1.1]: https://github.com/cynchro/deepseekCLI/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/cynchro/deepseekCLI/releases/tag/v0.1.0
