# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto adhiere a [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

### Added
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

### Fixed
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

[Unreleased]: https://github.com/cynchro/deepseekCLI/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/cynchro/deepseekCLI/compare/v0.1.1...v0.1.3
[0.1.1]: https://github.com/cynchro/deepseekCLI/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/cynchro/deepseekCLI/releases/tag/v0.1.0
