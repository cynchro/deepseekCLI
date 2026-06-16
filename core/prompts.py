"""Bloques de instrucciones reutilizables para build y update."""

BUILD_COMPLETENESS = """
COMPLETITUD OBLIGATORIA:
- Generá TODOS los archivos que el código importa (cada from '../modulo' debe tener archivo o index.ts en disco).
- No dejes módulos referenciados sin implementar.
- Si la respuesta se corta por límite de tokens, priorizá archivos de entrada (index, main) y dependencias directas.
- Antes de cada bloque: ### archivo: ruta/relativa.ext
"""

DOCKER_NPM = """
DOCKER / NODE (si aplica Dockerfile o package.json):
- Si usás `npm ci`, incluí siempre `package-lock.json` (generado con npm install) en el mismo cambio.
- Alternativa sin lockfile: `RUN npm install` (no npm ci).
- En Dockerfile copiá cada carpeta a su ruta: `COPY core ./core` — NUNCA `COPY core inference ... ./` (aplasta directorios).
- Copiá package.json y package-lock.json antes de npm ci/install.
- docker-compose v2: no uses la clave `version:` (obsoleta).
- No expongas puertos HTTP si el proyecto no levanta un servidor en ese puerto.
"""

UPDATE_DOCKER_HINT = """
Si el cambio involucra Docker: alinear con el repo real (archivos existentes, package-lock si hay npm ci).
"""

# ── Generación por manifiesto (Nivel 2: escala a proyectos grandes) ──────────

MANIFEST_INSTRUCTIONS = """
Listá TODOS los archivos que hay que crear para implementar el plan completo.
Incluí TODO: código, configs, Dockerfiles, vistas/templates, SQL, assets, tests.
No omitas archivos que el código vaya a importar o referenciar (controllers,
templates, módulos, etc.). Pensá en el proyecto terminado y funcionando.

Respondé SOLO con JSON válido, sin texto alrededor, con esta forma exacta:
{"files": [{"path": "ruta/relativa.ext", "purpose": "para qué sirve, en una línea"}]}
"""

FILE_GEN_INSTRUCTIONS = """
Generá el contenido COMPLETO y funcional de UN solo archivo: {path}
Propósito: {purpose}

Reglas:
- Devolvé SOLO el contenido del archivo, sin explicaciones ni comentarios fuera del código.
- Sin '...' ni placeholders ni TODOs: código real y completo.
- Respetá rutas e imports según el manifiesto (los demás archivos existen en esas rutas).
- No envuelvas la respuesta en un bloque markdown ``` salvo que el archivo sea markdown.
"""
