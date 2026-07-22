"""El corazón de deep v2: agente conversacional con tool calling en loop.

PRO (orquestador) decide qué herramientas llamar; las tools determinísticas
(fs/search/shell) ejecutan. La generación de código a gran escala se delegará a
FLASH en la Fase 2 (tools generate_code/apply_edit). Por ahora el loop corre
sobre un único modelo (PRO por default).
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, List

import core.debug as _dbg
from core import compaction as _compaction
from core import journal as _journal
from core import tasks as _taskstore
from core.builder import CodeBuilder
from core.client import DeepSeekClient
from core.models import MODEL_FLASH, MODEL_PRO
from core.tools import schemas, dispatch, tool_names
from core.tools import shell as _shell
from core.tools.base import ToolContext

# Investigador read-only (FLASH): solo lee, nunca escribe ni ejecuta.
_EXPLORE_READONLY = {"read_file", "grep", "list_dir", "glob", "search_code"}

EXPLORE_SYSTEM = """Sos un investigador de código de solo lectura. Otro agente te hace
una pregunta sobre este proyecto y vos la respondés explorando el workspace.

- Usá read_file, grep, list_dir y glob para encontrar la respuesta. No tenés más herramientas:
  no escribís, no editás, no ejecutás nada.
- Sé factual y concreto: signaturas de funciones/clases, rutas con archivo:línea, cómo se
  usa o se conecta algo, convenciones que detectes. Citá ubicaciones exactas.
- No opines ni propongas cambios; solo reportá lo que ES.
- Cuando tengas la respuesta, respondé en texto (sin más tool calls) con un resumen COMPACTO
  y autosuficiente: quien te preguntó no ve los archivos, solo tu resumen. Nada de volcar
  archivos enteros; extraé lo relevante."""

DEFAULT_SYSTEM = """Sos deep, un agente de programación senior que trabaja en una terminal.
Resolvés la tarea del usuario operando sobre el workspace con herramientas.

# Antes de actuar
En tu primera respuesta de cada turno (junto con tu primera tool call), escribí UNA línea
breve de contexto: qué entendiste del pedido y qué vas a hacer. Si el usuario pegó un log,
stack trace o salida de un comando (p.ej. un build que falló), esa línea tiene que nombrar
el error real que identificaste ahí adentro (no "voy a revisar el log": decí CUÁL es el
error). Esto no es pedir permiso — es una frase de contexto y seguís directo a actuar.

# Cómo escribís código
VOS escribís el código. Sos el modelo más capaz del sistema: no delegues la parte
que importa.
- write_file → crear un archivo nuevo, con su contenido completo escrito por vos.
- edit_file → modificar un archivo existente. Es tu herramienta principal de edición:
  un reemplazo de string exacto y QUIRÚRGICO. Tocás solo las líneas que cambian, nunca
  reescribís el archivo entero. Antes de editar, LEÉ el archivo con read_file; el
  old_string debe coincidir carácter por carácter (con contexto suficiente para ser único).
- generate_code / apply_edit → delegan a un modelo rápido y más barato (FLASH). Son la
  EXCEPCIÓN, no la regla. Usalos SOLO para volumen mecánico y de bajo riesgo donde la
  calidad fina no importa: boilerplate repetitivo, scaffolding, datos de fixture, traducir
  un formato a otro. NUNCA para lógica de negocio, algoritmos, APIs públicas, o cualquier
  código donde un detalle sutil importe. Si dudás, escribilo vos con write_file/edit_file.

# Disciplina de código (no negociable)
- Antes de escribir, ENTENDÉ el entorno: leé los archivos cercanos y seguí sus convenciones
  (estilo, naming, imports, manejo de errores). El código nuevo debe leerse como si lo
  hubiera escrito quien mantiene el proyecto.
- No inventes APIs, librerías, funciones ni rutas. Si no estás seguro de que algo existe,
  verificalo con grep/read_file. Usá solo dependencias ya presentes salvo que te pidan agregar.
- Nada de placeholders, TODOs ni "...": entregá código completo y funcional.
- No agregues comentarios obvios ni docstrings de relleno; comentá solo lo no evidente.
- Sé quirúrgico: cambiá lo mínimo necesario. No reformatees ni reordenes código no relacionado.

# Verificá tu trabajo (esto es lo que separa código que anda de código que parece andar)
- Después de escribir o modificar código, EJECUTALO: corré los tests, el linter, el
  type-checker o el programa con run_command.
- Si algo falla, leé el error, arreglalo e iterá hasta que pase en verde. No declares
  terminado con tests en rojo o errores sin resolver.
- Si no hay tests para lo que tocaste, escribilos o al menos corré el código una vez para
  confirmar que importa/ejecuta sin romper.

# Exploración y flujo
- Explorá con list_dir, glob, grep y read_file antes de asumir la estructura del proyecto.
- En un codebase grande, para ubicar "dónde se hace X" usá search_code (recuperación por
  relevancia, mejor que grep): te devuelve los fragmentos más pertinentes con archivo:línea.
  Después abrí los archivos puntuales con read_file.
- Para entender un área grande o desconocida sin llenar tu contexto, usá explore: le hacés
  una pregunta a un agente lector (FLASH) que lee/grepea por vos y te devuelve un resumen
  compacto. Ideal antes de editar código ajeno; vos seguís decidiendo y escribiendo.
- Trabajás SOLO dentro del workspace.

# Navegador (debugging y scraping de frontend)
- Tenés browser_navigate, browser_read_page, browser_click, browser_type, browser_eval,
  browser_console, browser_network, browser_screenshot y browser_close para inspeccionar
  una página real en Chromium. Usalas cuando el trabajo toca frontend: verificar que un
  cambio de UI se ve/rompe, scrapear contenido o estructura de una página, o diagnosticar
  un bug reproduciéndolo en el navegador en vez de asumir por lectura de código.
- Sos texto puro: NO podés ver imágenes. browser_screenshot guarda un archivo para que el
  usuario lo revise; a vos no te sirve para diagnosticar. Para diagnosticar de verdad usá
  browser_read_page (texto/HTML del DOM), browser_console (errores JS) y browser_network
  (requests/responses fallidas) — ahí está la señal real.
- Flujo típico: browser_navigate a la URL → reproducí la acción con browser_click/
  browser_type → leé browser_console y browser_network para ver qué falló → si necesitás
  algo puntual del DOM que no salió en el texto plano, browser_eval con una expresión JS.
- Por defecto se lanza un Chromium headless aislado (sin login, sin cookies del usuario).
  Si necesitás la sesión real del usuario (logueada en algún servicio), pedile que abra su
  Chrome con `--remote-debugging-port=9222` y setee DEEPSEEK_CDP_URL=http://localhost:9222;
  ahí browser_navigate se conecta a ESA instancia en vez de crear una nueva.
- Cerrá con browser_close cuando termines de inspeccionar, sobre todo si te conectaste a un
  Chrome real vía CDP (así lo dejás disponible, sin quedar "enganchado").

# Trabajos grandes
- Para varios pasos o proyectos grandes: arrancá con write_tasks descomponiendo el trabajo
  en tareas concretas. Marcá cada una con update_task (in_progress al empezar, completed al
  terminar, failed si no se pudo). Así no repetís trabajo y se puede retomar si te cortan.
  Si el plan cambia, volvé a llamar write_tasks con la lista actualizada.
- Para una parte grande y autocontenida (un módulo, un subsistema), podés delegarla con
  spawn_agent: un sub-agente la construye con su propio contexto y te devuelve un resumen.
  Pasale una tarea clara y completa (no ve tu charla). Las tareas chicas hacelas vos directo.
- Si hay varias partes INDEPENDIENTES entre sí (no se pisan archivos ni dependen una de
  otra), emití varios spawn_agent en el MISMO turno: corren en paralelo y es más rápido.
  Si una parte depende del resultado de otra, hacelas en turnos separados (secuencial).

# Cierre
- Antes de declarar terminado, repasá tu propio diff (lo ves en el resultado de cada
  edición): ¿quedó algún print de debug, TODO, import sin usar, o un caso sin cubrir?
  Si sí, arreglalo antes de cerrar.
- Cuando terminaste Y verificaste, respondé en texto (sin más tool calls) con un resumen
  breve de lo que hiciste y cómo lo probaste.
- Sé conciso y directo. No pidas permiso: actuá."""


def _code_language_directive() -> str:
    """Directiva de idioma. El CÓDIGO (identificadores) va por defecto en inglés (estándar,
    facilita soporte/reventa). Los COMENTARIOS/docstrings pueden ir en otro idioma de forma
    independiente. Configurable con DEEP_CODE_LANG y DEEP_COMMENT_LANG (este último cae al
    idioma del código si no se setea)."""
    code_lang = (os.getenv("DEEP_CODE_LANG") or "inglés").strip()
    comment_lang = (os.getenv("DEEP_COMMENT_LANG") or code_lang).strip()
    out = ("\n\n# Idioma\n"
           "- Conversá y explicá al usuario en SU idioma (el del pedido).\n")
    if comment_lang.lower() == code_lang.lower():
        out += (
            f"- TODO EL CÓDIGO va en {code_lang}, sin importar en qué idioma te hablen: nombres "
            f"de variables, funciones, clases, módulos y archivos; comentarios; docstrings; y "
            f"mensajes de commit y de log.\n")
    else:
        out += (
            f"- Los IDENTIFICADORES van SIEMPRE en {code_lang}: nombres de variables, funciones, "
            f"clases, módulos y archivos, y los mensajes de commit/log. No los traduzcas.\n"
            f"- Los COMENTARIOS y DOCSTRINGS van en {comment_lang}, PERO referenciando los "
            f"identificadores por su nombre REAL en {code_lang}, tal cual (nunca traduzcas un "
            f"nombre adentro del comentario). Ejemplo: la función se llama `getSeller()` y la "
            f"variable `seller` (en {code_lang}); el comentario en {comment_lang} dice algo como "
            f"«getSeller() asigna un vendedor en la variable seller y lo retorna».\n")
    out += ("- Excepción: los textos visibles al usuario final (UI, i18n, mensajes de la app) "
            "seguí lo que pida el proyecto/DEEP.md.\n"
            "- El código en inglés es el estándar y facilita el soporte y la reventa.")
    return out


class AgentLoop:
    def __init__(self, client: DeepSeekClient, workspace, *,
                 model: str = MODEL_PRO, system_prompt: str = None,
                 rules: List[str] = None, project_context: str = None,
                 on_event: Callable[[str, dict], None] = None,
                 confirm: Callable[[str], bool] = None,
                 max_steps: int = 100, compact_threshold: int = 150000,
                 depth: int = 0, max_depth: int = 2, is_subagent: bool = False,
                 auto_verify: bool = True, parallel_subagents: bool = True,
                 max_parallel: int = 4, max_auto_resume: int = 3):
        self.client = client
        self.model = model
        self.auto_verify = auto_verify
        self.max_auto_resume = max_auto_resume
        self._verify_attempts = 0
        self.parallel_subagents = parallel_subagents
        self.max_parallel = max_parallel
        # Serializa los pedidos de permiso cuando varios sub-agentes corren en paralelo,
        # así no se pisan los prompts interactivos.
        self._confirm_lock = threading.Lock()
        if hasattr(workspace, "run_command"):
            # Ya es un backend remoto (SSHPath): no re-envolver con Path() ni crear
            # directorios locales — resolve_remote_workspace() ya validó que existe.
            self.workspace = workspace
        else:
            self.workspace = Path(workspace)
            self.workspace.mkdir(parents=True, exist_ok=True)
        self.on_event = on_event or (lambda kind, data: None)
        self.max_steps = max_steps
        self.compact_threshold = compact_threshold
        self.depth = depth
        self.max_depth = max_depth
        self.is_subagent = is_subagent
        self._rules = rules
        self._project_context = project_context
        # FLASH construye; comparte el mismo client que PRO para que get_stats()
        # agregue el gasto de ambos modelos.
        self.builder = CodeBuilder(self.client, model=MODEL_FLASH, rules=rules,
                                   project_context=project_context)
        self.ctx = ToolContext(
            workspace=self.workspace,
            on_event=self.on_event,
            confirm=confirm or (lambda desc: True),
            builder=self.builder,
            spawn=self._spawn_subagent,
            explore=self._explore,
        )
        # Tools excluidas: los sub-agentes no tocan el plan global (.deep/tasks.json)
        # y no anidan más allá de max_depth.
        self.tools_exclude = set()
        if is_subagent:
            self.tools_exclude |= {"write_tasks", "update_task"}
        if depth >= max_depth:
            self.tools_exclude |= {"spawn_agent", "explore"}

        sys_prompt = system_prompt or DEFAULT_SYSTEM
        if system_prompt is None:           # solo el agente de trabajo; no el de explore
            sys_prompt += _code_language_directive()
        sys_prompt += f"\n\nWorkspace: {self.workspace}"
        if getattr(self.workspace, "is_windows", False):
            sys_prompt += (
                "\n\nEste workspace es un REMOTO WINDOWS (vía SSH). Dos reglas separadas, "
                "no las mezcles:\n"
                "- run_command corre en cmd.exe: usá dir, type, findstr, del, copy, etc. "
                "Nunca ls, grep, cat, rm (no existen ahí).\n"
                "- Los argumentos path de las tools de archivo (read_file, write_file, "
                "edit_file, list_dir, glob) siguen en formato POSIX-con-'/' (relativos, o "
                "absolutos tipo /C:/Users/...) — NUNCA con backslash, aunque los comandos "
                "de run_command sí usen sintaxis Windows.")
        if rules:
            sys_prompt += "\n\nREGLAS DEL PROYECTO (.deeprules):\n" + \
                "\n".join(f"- {r}" for r in rules)
        if project_context:
            sys_prompt += "\n\n" + project_context
        if not is_subagent:
            td = _taskstore.load_tasks(self.workspace)
            if _taskstore.has_open(td):
                sys_prompt += ("\n\nTAREAS EN CURSO (de una sesión anterior, .deep/tasks.json) — "
                               "continuá desde acá, no rehagas lo completado:\n"
                               + _taskstore.render(td))
            recap = _journal.load_recap(self.workspace)
            if recap:
                sys_prompt += ("\n\nBITÁCORA — última sesión en este proyecto (.deep/journal.md). "
                               "Si el usuario pide continuar ('seguí', 'dale', etc.), retomá desde acá. "
                               "Es SOLO LECTURA para vos: NO edites ni escribas .deep/journal.md, "
                               "se actualiza solo al cerrar la sesión.\n"
                               + recap)
        self.messages: List[dict] = [{"role": "system", "content": sys_prompt}]

    def _locked_confirm(self, desc: str) -> bool:
        """Pide permiso bajo lock: si hay varios sub-agentes en paralelo, los prompts
        no se interleavan (uno a la vez)."""
        with self._confirm_lock:
            return self.ctx.confirm(desc)

    def _spawn_subagent(self, task: str, context_files=None) -> str:
        """Lanza un AgentLoop hijo con contexto fresco para una tarea autocontenida.
        Comparte client (telemetría), workspace y permisos. Devuelve un resumen
        compacto a PRO — no su transcript — para mantener liviano el contexto del padre.
        Thread-safe: se puede invocar en paralelo con otros sub-agentes."""
        if self.depth >= self.max_depth:
            return "ERROR: no se pueden anidar más sub-agentes (max_depth)"
        touched = []

        def child_event(kind, data):
            if kind in ("file_write", "file_edit"):
                touched.append(data.get("path"))
            self.on_event(kind, data)   # se muestran anidados entre los brackets

        child = AgentLoop(
            self.client, self.workspace, model=self.model,
            rules=self._rules, project_context=self._project_context,
            on_event=child_event, confirm=self._locked_confirm,
            max_steps=self.max_steps, compact_threshold=self.compact_threshold,
            depth=self.depth + 1, max_depth=self.max_depth, is_subagent=True,
            parallel_subagents=self.parallel_subagents, max_parallel=self.max_parallel,
            # Los sub-agentes no corren los tests (evita N pytest concurrentes sobre el
            # mismo workspace): reportan lo que tocaron y el PADRE verifica una sola vez.
            auto_verify=False,
        )
        seed = task
        if context_files:
            seed += "\n\nArchivos relevantes para leer primero: " + ", ".join(context_files)
        self.on_event("subagent_start", {"task": task[:160], "depth": self.depth + 1})
        _dbg.log("AGENT", f"spawn subagent  depth={self.depth + 1}  task={task[:100]}")
        res = child.run(seed)
        files = list(dict.fromkeys(t for t in touched if t))
        # El padre toma nota de lo que tocó el hijo, para auto-verificar una vez al cerrar
        # (set.update es atómico bajo el GIL, así que es seguro desde threads paralelos).
        if res.get("success") and files:
            self._touched.update(files)
        self.on_event("subagent_done", {"success": res.get("success"),
                                         "files": files, "depth": self.depth + 1})
        head = "Sub-agente completó la tarea." if res.get("success") else \
            "Sub-agente NO completó la tarea (revisá)."
        summary = head + "\n" + (res.get("content") or "")[:1500]
        if files:
            summary += "\nArchivos tocados: " + ", ".join(files)
        return summary

    def _explore(self, question: str, paths=None) -> str:
        """Investigación read-only delegada a FLASH: un mini-agente lee/grepea el
        workspace (sin escribir ni ejecutar) y devuelve un resumen compacto. Mantiene
        liviano —y barato— el contexto de PRO, sin tocar la calidad: PRO sigue decidiendo
        y escribiendo todo el código."""
        if self.depth >= self.max_depth:
            return "ERROR: no se puede explorar más profundo (max_depth)"
        self.on_event("explore_start", {"question": question[:160], "depth": self.depth + 1})
        _dbg.log("AGENT", f"explore (flash)  depth={self.depth + 1}  q={question[:100]}")
        child = AgentLoop(
            self.client, self.workspace, model=MODEL_FLASH,
            system_prompt=EXPLORE_SYSTEM, project_context=self._project_context,
            on_event=self.on_event, confirm=lambda desc: False,  # read-only: nada que confirmar
            max_steps=20, compact_threshold=self.compact_threshold,
            depth=self.depth + 1, max_depth=self.max_depth, is_subagent=True,
            auto_verify=False,
        )
        # Solo herramientas de lectura: no escribe, no edita, no ejecuta, no delega.
        child.tools_exclude = set(tool_names()) - _EXPLORE_READONLY
        seed = question
        if paths:
            seed += "\n\nEmpezá mirando: " + ", ".join(paths)
        res = child.run(seed)
        self.on_event("explore_done", {"success": res.get("success"), "depth": self.depth + 1})
        return (res.get("content") or "").strip() or "(el investigador no devolvió nada)"

    def _detect_verify_cmd(self):
        """Comando de verificación del proyecto, si se puede inferir. Conservador:
        solo devuelve algo cuando hay una señal clara (tests pytest, script npm test)."""
        ws = self.workspace
        if (any(ws.glob("test_*.py")) or any(ws.glob("*_test.py"))
                or (ws / "tests").is_dir() or (ws / "pytest.ini").exists()
                or (ws / "conftest.py").exists()):
            return "python3 -m pytest -q"
        pkg = ws / "package.json"
        if pkg.exists():
            try:
                scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
                if "test" in scripts:
                    return "npm test --silent"
            except Exception:
                pass
        return None

    def _auto_verify(self):
        """Tras un turno que tocó código, corre los tests del proyecto (si los detecta)
        y devuelve el fallo para reinyectarlo al loop; None si pasa o no aplica. Hace el
        loop de verificación menos dependiente de que el modelo se acuerde de correrlos."""
        if not self.auto_verify or not self._touched or self._verify_attempts >= 2:
            return None
        cmd = self._detect_verify_cmd()
        if not cmd:
            return None
        # Pasa por el mismo gate que la shell tool: en modo plan o en remoto (shell
        # bloqueado) esto se deniega y no corremos nada.
        if not self.ctx.confirm(f"ejecutar: {cmd}  (verificación automática)"):
            return None
        self._verify_attempts += 1
        self.on_event("verify", {"command": cmd})

        def on_wait(elapsed):
            self.on_event("shell_wait", {"command": cmd, "elapsed": elapsed})

        try:
            exit_code, stdout, stderr = _shell.execute(self.workspace, cmd, 180, on_wait)
        except Exception:
            return None  # no bloquear el cierre por un problema del runner de tests
        self.on_event("verify_result", {"command": cmd, "exit": exit_code})
        if exit_code == 0:
            return None
        out = (stdout or "")[-2500:]
        if stderr:
            out += "\n[stderr]\n" + stderr[-1000:]
        return (f"VERIFICACIÓN AUTOMÁTICA: `{cmd}` falló (exit={exit_code}). "
                f"No declares terminado: arreglá el código hasta dejarlo en verde.\n{out}")

    def reset(self):
        """Reinicia la conversación preservando el system prompt."""
        self.messages = self.messages[:1]

    def _approx_tokens(self) -> int:
        return sum(len(m.get("content") or "") for m in self.messages) // 4

    def _safe_cut(self, keep_tail: int = 12):
        """Índice de corte seguro: el tail (messages[cut:]) arranca en un boundary
        —un 'user' o un 'assistant' con tool_calls— para no partir un grupo
        tool_calls/tool. Sirve tanto entre turnos como DENTRO de un run largo."""
        n = len(self.messages)
        for i in range(max(2, n - keep_tail), 1, -1):
            m = self.messages[i]
            if m["role"] == "user" or (m["role"] == "assistant" and m.get("tool_calls")):
                return i
        return None

    def _compact_if_needed(self):
        """Si el historial supera el umbral, resume el trabajo previo de forma FIEL
        (map-reduce, sin pre-truncar) y lo reemplaza por una nota, preservando system +
        cola reciente. Corta en un boundary seguro, así funciona también a mitad de un
        build largo. Ver core/compaction.py."""
        if self._approx_tokens() < self.compact_threshold:
            return
        cut = self._safe_cut()
        if not cut or cut <= 1:
            return
        head = self.messages[1:cut]
        summary_text = _compaction.summarize_head(self.client, head)
        if not summary_text:
            return
        before = self._approx_tokens()
        summary = {"role": "assistant",
                   "content": _compaction.SUMMARY_MARKER + "\n" + summary_text}
        self.messages = [self.messages[0], summary] + self.messages[cut:]
        self.on_event("compact", {"tokens_before": before, "tokens_after": self._approx_tokens()})
        _dbg.log("AGENT", f"compactado  {before} -> {self._approx_tokens()} tokens aprox")

    def run(self, user_input: str) -> dict:
        """Procesa un turno del usuario hasta la respuesta final (sin tool calls)."""
        self.messages.append({"role": "user", "content": user_input})
        self.on_event("user", {"content": user_input})
        _dbg.log("AGENT", f"run  task={user_input[:120]}  model={self.model}")
        self._touched = set()
        self._verify_attempts = 0
        resumes = 0
        while True:
            res = self._run_steps()
            # Si se agotaron los pasos pero el plan tiene tareas abiertas, seguimos solos
            # (acotado por max_auto_resume) en vez de cortar y pedir 'continuá' a mano.
            if (res.get("max_steps_reached") and not self.is_subagent
                    and resumes < self.max_auto_resume
                    and _taskstore.has_open(_taskstore.load_tasks(self.workspace))):
                resumes += 1
                self.on_event("auto_resume", {"attempt": resumes, "max": self.max_auto_resume})
                _dbg.log("AGENT", f"auto-resume {resumes}/{self.max_auto_resume}")
                self.messages.append({"role": "user", "content": (
                    "Alcanzaste el límite de pasos pero quedan tareas pendientes en el plan. "
                    "Continuá desde donde estabas y seguí hasta completarlas; si alguna no se "
                    "puede, marcala con update_task: failed y explicá por qué.")})
                continue
            return res

    def _run_steps(self) -> dict:
        """Corre hasta max_steps pasos de tool calling sobre el historial actual. Devuelve
        la respuesta final, o un dict con max_steps_reached=True si se agotó el presupuesto."""
        _WRITE_TOOLS = {"write_file", "edit_file", "generate_code", "apply_edit"}

        for step in range(self.max_steps):
            self._compact_if_needed()   # también a mitad de un build largo
            resp = self.client.complete(
                self.messages, model=self.model,
                tools=schemas(exclude=self.tools_exclude),
                temperature=0.3, max_tokens=8000,
            )
            if not resp.get("success"):
                self.on_event("error", {"error": resp.get("error", "?")})
                return {"success": False, "error": resp.get("content"),
                        "steps": step + 1, "stats": self.client.get_stats()}

            tool_calls = resp.get("tool_calls")
            # Si el modelo cortó por límite de tokens emitiendo tool_calls, el batch
            # viene truncado (arguments JSON incompletos). Adjuntar ese assistant con
            # tool_calls deja un grupo sin sus mensajes 'tool' → la API rechaza con 400
            # ("must be followed by tool messages") en la PRÓXIMA llamada. Lo descartamos
            # y reintentamos el turno en vez de persistir un historial inválido.
            truncated = resp.get("finish_reason") == "length"
            if tool_calls and truncated:
                self.messages.append({"role": "assistant",
                                      "content": resp.get("content") or ""})
                self.messages.append({"role": "user", "content": (
                    "Tu respuesta anterior se cortó por límite de tokens con tool_calls "
                    "incompletos. Reintentá ese paso emitiendo menos llamadas a la vez "
                    "(idealmente una sola) y argumentos más chicos.")})
                self.on_event("truncated", {"finish_reason": "length"})
                continue

            assistant = {"role": "assistant", "content": resp.get("content") or ""}
            if tool_calls:
                assistant["tool_calls"] = tool_calls
                # Texto que el modelo manda junto con las tool_calls (p.ej. "detecté X,
                # voy a hacer Y"): sin esto se pierde y el usuario solo ve las tool
                # calls ejecutarse sin ningún contexto previo.
                if assistant["content"].strip():
                    self.on_event("thinking", {"text": assistant["content"].strip()})
            self.messages.append(assistant)

            # Ejecutar SIEMPRE que haya tool_calls (no gatear por finish_reason): todo
            # assistant con tool_calls debe recibir sus respuestas 'tool' o el historial
            # queda mal formado.
            if tool_calls:
                # Parseo de todas las llamadas del batch.
                parsed = []
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}
                    parsed.append((tc, name, args))

                spawn_calls = [(tc, n, a) for tc, n, a in parsed if n == "spawn_agent"]
                results = {}  # tc_id -> resultado

                # Si el modelo pidió 2+ sub-agentes en el mismo turno, los corremos en
                # PARALELO (cada uno es un AgentLoop independiente con su propio contexto).
                if self.parallel_subagents and len(spawn_calls) >= 2:
                    for tc, name, args in spawn_calls:
                        self.on_event("tool_call", {"name": name, "args": args})
                    self.on_event("parallel_start", {"count": len(spawn_calls)})
                    _dbg.log("AGENT", f"spawn paralelo  n={len(spawn_calls)}")
                    workers = min(len(spawn_calls), self.max_parallel)
                    with ThreadPoolExecutor(max_workers=workers) as ex:
                        fut_to_id = {ex.submit(dispatch, n, a, self.ctx): tc["id"]
                                     for tc, n, a in spawn_calls}
                        for fut, tcid in fut_to_id.items():
                            results[tcid] = fut.result()
                            self.on_event("tool_result", {"name": "spawn_agent",
                                                           "result": results[tcid]})
                    self.on_event("parallel_done", {"count": len(spawn_calls)})
                    # El resto de las tools (no spawn) van secuenciales.
                    rest = [(tc, n, a) for tc, n, a in parsed if n != "spawn_agent"]
                else:
                    rest = parsed

                for tc, name, args in rest:
                    self.on_event("tool_call", {"name": name, "args": args})
                    _dbg.log("AGENT", f"tool={name}  args={json.dumps(args)[:200]}")
                    result = dispatch(name, args, self.ctx)
                    if name in _WRITE_TOOLS and result.startswith("OK") and args.get("path"):
                        self._touched.add(args["path"])
                    self.on_event("tool_result", {"name": name, "result": result})
                    results[tc["id"]] = result

                # Mensajes 'tool' en el ORDEN original que espera la API.
                for tc, name, args in parsed:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": results[tc["id"]],
                    })
                continue

            # respuesta final (sin tool calls): antes de cerrar, verificación automática
            content = resp.get("content", "")
            verify_fail = self._auto_verify()
            if verify_fail:
                self.on_event("verify_reinject", {"attempt": self._verify_attempts})
                self.messages.append({"role": "user", "content": verify_fail})
                continue
            self.on_event("assistant", {"content": content})
            _dbg.log("AGENT", f"done  steps={step + 1}")
            return {"success": True, "content": content,
                    "steps": step + 1, "stats": self.client.get_stats()}

        msg = (f"Se alcanzó el máximo de {self.max_steps} pasos. La tarea quedó a "
               f"medias — escribí 'continuá' para que siga desde donde estaba.")
        self.on_event("error", {"error": "max_steps", "message": msg})
        return {"success": False, "error": msg, "max_steps_reached": True,
                "steps": self.max_steps, "stats": self.client.get_stats()}
