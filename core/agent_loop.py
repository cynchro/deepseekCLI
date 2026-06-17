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
                 max_steps: int = 100, compact_threshold: int = 150000):
        self.client = client
        self.model = model
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.on_event = on_event or (lambda kind, data: None)
        self.max_steps = max_steps
        self.compact_threshold = compact_threshold
        # FLASH construye; comparte el mismo client que PRO para que get_stats()
        # agregue el gasto de ambos modelos.
        self.builder = CodeBuilder(self.client, model=MODEL_FLASH, rules=rules)
        self.ctx = ToolContext(
            workspace=self.workspace,
            on_event=self.on_event,
            confirm=confirm or (lambda desc: True),
            builder=self.builder,
        )
        sys_prompt = system_prompt or DEFAULT_SYSTEM
        sys_prompt += f"\n\nWorkspace: {self.workspace}"
        if rules:
            sys_prompt += "\n\nREGLAS DEL PROYECTO (.deeprules):\n" + \
                "\n".join(f"- {r}" for r in rules)
        if project_context:
            sys_prompt += "\n\n" + project_context
        self.messages: List[dict] = [{"role": "system", "content": sys_prompt}]

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
                tools=schemas(), temperature=0.3, max_tokens=8000,
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
