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
