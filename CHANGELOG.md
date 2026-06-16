# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto adhiere a [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

### Added
- **Generación por manifiesto en `deep build`.** Antes de escribir, el modelo
  devuelve la lista de archivos del proyecto (manifiesto). Si son más de 8, se
  generan **uno por uno** (cada archivo es una llamada independiente), lo que
  permite construir proyectos grandes sin que la respuesta se trunque. Los
  proyectos chicos siguen en una sola respuesta. Flag `--single-shot` para
  forzar el modo anterior.
- **Auto-continuación ante truncación.** Si una respuesta se corta por el límite
  de tokens (`finish_reason=length`), `deep` reenvía el contenido parcial y pide
  continuar hasta terminar. Aplica a build, fix y update.
- **`deep fix` completa lo que falta.** Detecta referencias rotas
  (imports/includes a archivos inexistentes) mediante un **registro extensible de
  detectores por lenguaje** (TS/TSX y PHP de fábrica) y **autogenera** los
  archivos faltantes —además de los declarados en el manifiesto que no se hayan
  creado— en vez de solo reportarlos.
- **navigator v2 — contrato fuerte.** El `job.md` suma `## STACK` (deps
  permitidas) y `## CONTRACTS` (firmas/esquemas compartidos), y cada módulo de
  `## TASKS` admite campos estructurados `files:` / `uses:` / `done:`. Al
  construir, cada módulo recibe el contrato **más el código real de los módulos
  ya construidos**, para que DeepSeek no reinvente APIs entre módulos. Un **gate
  automático** verifica que se hayan creado exactamente los archivos declarados
  (faltante → se autocompleta; no declarado → se marca como posible invención).
  `deep navigator --review` ahora **embebe el código** (no solo nombres) para que
  un arquitecto sin acceso al disco pueda revisar; `--module <nombre>` acota el
  volcado a un módulo.
- **`deep navigator`** — flujo opcional donde un LLM navigator externo (Claude,
  ChatGPT, Gemini, etc.) planifica y DeepSeek construye y corrige. Un solo archivo
  fuente (`.deep/job.md`) con secciones `PLAN`/`RULES`/`TASKS`; DeepSeek construye
  módulo por módulo usando ese plan y se saltea su propia fase de planificación.
  Subcomandos: `--init` (plantilla; `--force` regenera y guarda copia `.bak`),
  `--review` (vuelca estado + formato para el navigator) y `--fix <review.md>`
  (aplica las correcciones). El estado de cada módulo se guarda en
  `.deep/navigator/state/`. No modifica el comportamiento de `deep build`.
- Persistencia del historial de chat entre sesiones.
- `config set-lang` — idioma preferido de las respuestas, persistido.

### Changed
- **`max_tokens` se limita al tope real del modelo (8192).** Antes se pedían
  12000, que la API recortaba en silencio. Combinado con la auto-continuación, el
  build deja de cortarse a mitad.
- **Reporte honesto de completitud.** Si la generación queda truncada o faltan
  archivos del manifiesto, el resultado se marca como fallido (antes podía
  reportar "✅ código aprobado" sobre un proyecto incompleto).
- **`deep claudejob` → `deep navigator`.** El comando se renombró porque el LLM
  navigator no tiene por qué ser Claude (cualquier modelo puede llenar el
  `job.md`). `claudejob` sigue funcionando como **alias deprecado** (oculto del
  `--help`, con aviso). El directorio de estado pasó de `.deep/claudejob/` a
  `.deep/navigator/`, y el módulo interno de `core/claudejob.py` a `core/navigator.py`.

### Fixed
- **Truncación silenciosa del `build`.** El proyecto entero se generaba en una
  sola llamada por encima del tope de tokens; la respuesta se cortaba a mitad
  (dejando archivos sin escribir) pero el CLI reportaba éxito porque nunca leía
  `finish_reason`. Ahora se detecta, se continúa automáticamente y, si aún queda
  incompleto, se reporta como tal.
- **`deep navigator` no dejaba rastro de los errores por módulo.** Las excepciones del
  loop de build/fix solo se imprimían y se descartaban con `continue` — ni con
  `--debug` quedaban en `debug.log`. Ahora se registra el traceback completo (tag
  `NAVIGATOR`) y el módulo que falla se guarda como estado `success=False` (antes
  aparecía como "no construido" en `--review`).
- **Escritura de archivos generados** (`core/writer.py`): el extractor exigía bloques
  con fences ```` ``` ````, pero el modelo emite los archivos como `### archivo: ruta`
  seguido de código crudo. Como consecuencia, algunos `build` no escribían ningún
  archivo (solo `RESPONSE.md`), o tomaban encabezados de sección de un README
  (`Instalación`, `Uso`, `Tests`) como nombres de archivo. Ahora la extracción se
  delimita por los marcadores `### archivo:` y conserva los fences internos del
  contenido. Afecta a todos los comandos que escriben archivos, no solo `deep navigator`.
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

[Unreleased]: https://github.com/cynchro/deepseekCLI/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/cynchro/deepseekCLI/compare/v0.1.1...v0.1.3
[0.1.1]: https://github.com/cynchro/deepseekCLI/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/cynchro/deepseekCLI/releases/tag/v0.1.0
