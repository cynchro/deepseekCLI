"""El corazón de deep v2: agente conversacional con tool calling en loop.

PRO (orquestador) decide qué herramientas llamar; las tools determinísticas
(fs/search/shell) ejecutan. La generación de código a gran escala se delegará a
FLASH en la Fase 2 (tools generate_code/apply_edit). Por ahora el loop corre
sobre un único modelo (PRO por default).
"""
import json
from pathlib import Path
from typing import Callable, List

import core.debug as _dbg
from core import tasks as _taskstore
from core.builder import CodeBuilder
from core.client import DeepSeekClient
from core.models import MODEL_FLASH, MODEL_PRO
from core.tools import schemas, dispatch
from core.tools.base import ToolContext

DEFAULT_SYSTEM = """Sos deep, un agente de programación que trabaja en una terminal.
Resolvés la tarea del usuario operando sobre el workspace con herramientas.

Tenés dos clases de herramientas para escribir:
- generate_code / apply_edit → las maneja un modelo de construcción rápido (FLASH).
  USALAS para producir o modificar CÓDIGO real: vos describís qué hacer y FLASH
  escribe los bytes. Es más rápido y barato; no escribas el código vos mismo.
- write_file / edit_file → para contenido EXACTO y trivial que ya tenés resuelto
  (configs cortas, un renombre puntual, un .gitignore).

Para trabajos con varios pasos o proyectos grandes:
- Arrancá usando write_tasks para descomponer el trabajo en una lista de tareas concreta.
- Marcá cada tarea con update_task: in_progress cuando la empezás, completed cuando la
  terminás (o failed si no se pudo). Así no repetís trabajo y se puede retomar si te cortan.
- Si el plan cambia en el camino, volvé a llamar write_tasks con la lista actualizada.
- Para una parte grande y autocontenida (ej. un módulo, un subsistema), delegala con
  spawn_agent: un sub-agente la construye con su propio contexto y te devuelve un resumen.
  Así tu contexto se mantiene liviano. Pasale una tarea clara y completa (no ve tu charla).
  Las tareas chicas hacelas vos directo, sin delegar.

Reglas de trabajo:
- Para crear un archivo con lógica: generate_code con una spec clara.
- Para modificar código existente: apply_edit con instrucciones en lenguaje natural.
- Antes de tocar a mano un archivo con edit_file, leelo con read_file. Nunca inventes su contenido.
- Explorá con list_dir, glob y grep antes de asumir la estructura del proyecto.
- Para correr tests, comandos o git usá run_command.
- Trabajás SOLO dentro del workspace.
- Cuando terminaste, respondé en texto (sin más tool calls) con un resumen breve de lo que hiciste.
- Sé conciso y directo. No pidas permiso: actuá."""


class AgentLoop:
    def __init__(self, client: DeepSeekClient, workspace, *,
                 model: str = MODEL_PRO, system_prompt: str = None,
                 rules: List[str] = None, project_context: str = None,
                 on_event: Callable[[str, dict], None] = None,
                 confirm: Callable[[str], bool] = None,
                 max_steps: int = 100, compact_threshold: int = 150000,
                 depth: int = 0, max_depth: int = 2, is_subagent: bool = False):
        self.client = client
        self.model = model
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
        self.builder = CodeBuilder(self.client, model=MODEL_FLASH, rules=rules)
        self.ctx = ToolContext(
            workspace=self.workspace,
            on_event=self.on_event,
            confirm=confirm or (lambda desc: True),
            builder=self.builder,
            spawn=self._spawn_subagent,
        )
        # Tools excluidas: los sub-agentes no tocan el plan global (.deep/tasks.json)
        # y no anidan más allá de max_depth.
        self.tools_exclude = set()
        if is_subagent:
            self.tools_exclude |= {"write_tasks", "update_task"}
        if depth >= max_depth:
            self.tools_exclude.add("spawn_agent")

        sys_prompt = system_prompt or DEFAULT_SYSTEM
        sys_prompt += f"\n\nWorkspace: {self.workspace}"
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
        self.messages: List[dict] = [{"role": "system", "content": sys_prompt}]

    def _spawn_subagent(self, task: str, context_files=None) -> str:
        """Lanza un AgentLoop hijo con contexto fresco para una tarea autocontenida.
        Comparte client (telemetría), workspace y permisos. Devuelve un resumen
        compacto a PRO — no su transcript — para mantener liviano el contexto del padre."""
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
            on_event=child_event, confirm=self.ctx.confirm,
            max_steps=self.max_steps, compact_threshold=self.compact_threshold,
            depth=self.depth + 1, max_depth=self.max_depth, is_subagent=True,
        )
        seed = task
        if context_files:
            seed += "\n\nArchivos relevantes para leer primero: " + ", ".join(context_files)
        self.on_event("subagent_start", {"task": task[:160], "depth": self.depth + 1})
        _dbg.log("AGENT", f"spawn subagent  depth={self.depth + 1}  task={task[:100]}")
        res = child.run(seed)
        files = list(dict.fromkeys(t for t in touched if t))
        self.on_event("subagent_done", {"success": res.get("success"),
                                         "files": files, "depth": self.depth + 1})
        head = "Sub-agente completó la tarea." if res.get("success") else \
            "Sub-agente NO completó la tarea (revisá)."
        summary = head + "\n" + (res.get("content") or "")[:1500]
        if files:
            summary += "\nArchivos tocados: " + ", ".join(files)
        return summary

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
        """Si el historial supera el umbral, resume el trabajo previo con FLASH y
        lo reemplaza por una nota, preservando system + cola reciente. Corta en un
        boundary seguro, así funciona también a mitad de un build largo."""
        if self._approx_tokens() < self.compact_threshold:
            return
        cut = self._safe_cut()
        if not cut or cut <= 1:
            return
        head = self.messages[1:cut]
        convo = "\n".join(
            f"{m['role'].upper()}: {(m.get('content') or '')[:1500]}"
            for m in head if m.get("content")
        )
        if not convo:
            return
        res = self.client.complete(
            [{"role": "system", "content":
              "Resumí el trabajo hecho hasta acá preservando: la tarea/objetivo, los "
              "archivos creados/modificados con sus rutas, las decisiones de arquitectura, "
              "lo que se probó y su resultado, y lo que queda pendiente. Conciso pero completo."},
             {"role": "user", "content": convo}],
            model=MODEL_FLASH, temperature=0.2, max_tokens=1200,
        )
        if not res.get("success"):
            return
        before = self._approx_tokens()
        summary = {"role": "assistant",
                   "content": "[Resumen del trabajo previo en esta tarea]\n" + res["content"]}
        self.messages = [self.messages[0], summary] + self.messages[cut:]
        self.on_event("compact", {"tokens_before": before, "tokens_after": self._approx_tokens()})
        _dbg.log("AGENT", f"compactado  {before} -> {self._approx_tokens()} tokens aprox")

    def run(self, user_input: str) -> dict:
        """Procesa un turno del usuario hasta la respuesta final (sin tool calls)."""
        self.messages.append({"role": "user", "content": user_input})
        self.on_event("user", {"content": user_input})
        _dbg.log("AGENT", f"run  task={user_input[:120]}  model={self.model}")

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
            assistant = {"role": "assistant", "content": resp.get("content") or ""}
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            self.messages.append(assistant)

            if resp.get("finish_reason") == "tool_calls" and tool_calls:
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}
                    self.on_event("tool_call", {"name": name, "args": args})
                    _dbg.log("AGENT", f"tool={name}  args={raw_args[:200]}")
                    result = dispatch(name, args, self.ctx)
                    self.on_event("tool_result", {"name": name, "result": result})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
                continue

            # respuesta final (sin tool calls)
            content = resp.get("content", "")
            self.on_event("assistant", {"content": content})
            _dbg.log("AGENT", f"done  steps={step + 1}")
            return {"success": True, "content": content,
                    "steps": step + 1, "stats": self.client.get_stats()}

        msg = (f"Se alcanzó el máximo de {self.max_steps} pasos. La tarea quedó a "
               f"medias — escribí 'continuá' para que siga desde donde estaba.")
        self.on_event("error", {"error": "max_steps", "message": msg})
        return {"success": False, "error": msg, "max_steps_reached": True,
                "steps": self.max_steps, "stats": self.client.get_stats()}
