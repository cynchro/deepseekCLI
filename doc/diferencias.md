# Diferencias con la versión anterior

> *English version: [differences.md](differences.md).*

> Resumen de qué cambió entre la versión vieja (generador **single-shot**) y la actual
> (**agente** con herramientas). Para el detalle por release ver [CHANGELOG.md](CHANGELOG.md).

## En una frase

**Antes:** escribías un comando (`build`/`fix`/`update`) y un modelo generaba todo de una
sola vez. **Ahora:** le hablás en lenguaje natural y un **agente** resuelve la tarea
operando sobre el proyecto con herramientas —lee, busca, escribe, ejecuta y verifica—
iterando hasta terminar, igual que Claude Code.

## Lo que cambió

| Tema | Antes (single-shot) | Ahora (agente) |
|------|---------------------|----------------|
| **Modo de uso** | Comandos fijos que generan archivos de una vez | REPL conversacional en lenguaje natural + `deep agent` |
| **Quién escribe el código** | Un modelo genérico, en una pasada | El modelo fuerte (PRO) escribe directo; FLASH solo lee/resume y hace volumen barato |
| **Edición** | Regeneraba archivos enteros | Edición **quirúrgica** (cambia solo lo necesario) con diffs visibles |
| **Verificación** | Una evaluación al final | Corre tests/lint y **itera hasta dejar todo en verde** (auto-verify) |
| **Modelos** | Uno solo (`deepseek-chat`) | Split PRO/FLASH (`deepseek-v4`), con costo por modelo |
| **Permisos** | No había | Modos `ask` / `auto` / `plan` / `yolo` antes de tocar disco o shell |
| **Contexto del proyecto** | — | `DEEP.md` (estilo CLAUDE.md) + `.deeprules`, con `/init` |

## Capacidades nuevas

- **Búsqueda en el código (`search_code`)** por relevancia (índice local), mucho mejor que
  grep para orientarse en proyectos grandes. Opcional: búsqueda **semántica** con embeddings.
- **Sub-agentes en paralelo**: delega partes independientes y las construye a la vez.
- **Lista de tareas persistente** + **auto-resume**: un build grande sobrevive a cortes,
  reinicios y al límite de pasos (sigue solo).
- **Compactación de contexto fiel**: sesiones largas sin perder rutas, decisiones ni resultados.
- **Control de idioma**: describís en español y el **código sale en inglés** por defecto
  (`DEEP_CODE_LANG`), con comentarios en otro idioma si querés (`DEEP_COMMENT_LANG`).
  La interfaz de la consola también cambia entre español e inglés con `config set-lang`.
- **Skills agénticas**, **PWA con agente en vivo** (streaming) y telemetría de tokens/costo.

## Compatibilidad

Los comandos viejos (`build`, `update`, `fix`, `claudejob`, `serve`) **siguen funcionando**
para scripting y la PWA; no se retiraron. El agente los reemplaza en el uso diario.

## Actualizar

```bash
pip install --upgrade deepseek-builder   # PyPI
# o
deep upgrade                              # desde GitHub
```
