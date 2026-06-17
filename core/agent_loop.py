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
from core.client import DeepSeekClient
from core.models import MODEL_PRO
from core.tools import schemas, dispatch
from core.tools.base import ToolContext

DEFAULT_SYSTEM = """Sos deep, un agente de programación que trabaja en una terminal.
Resolvés la tarea del usuario operando sobre el workspace con herramientas.

Reglas de trabajo:
- Antes de editar un archivo, leelo con read_file. Nunca inventes su contenido.
- Para cambios chicos usá edit_file (reemplazo de string exacto), NO reescribas el archivo entero.
- Para archivos nuevos usá write_file.
- Explorá con list_dir, glob y grep antes de asumir la estructura del proyecto.
- Para correr tests, comandos o git usá run_command.
- Trabajás SOLO dentro del workspace.
- Cuando terminaste, respondé en texto (sin más tool calls) con un resumen breve de lo que hiciste.
- Sé conciso y directo. No pidas permiso: actuá."""


class AgentLoop:
    def __init__(self, client: DeepSeekClient, workspace, *,
                 model: str = MODEL_PRO, system_prompt: str = None,
                 rules: List[str] = None,
                 on_event: Callable[[str, dict], None] = None,
                 confirm: Callable[[str], bool] = None,
                 max_steps: int = 40):
        self.client = client
        self.model = model
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.on_event = on_event or (lambda kind, data: None)
        self.max_steps = max_steps
        self.ctx = ToolContext(
            workspace=self.workspace,
            on_event=self.on_event,
            confirm=confirm or (lambda desc: True),
        )
        sys_prompt = system_prompt or DEFAULT_SYSTEM
        sys_prompt += f"\n\nWorkspace: {self.workspace}"
        if rules:
            sys_prompt += "\n\nREGLAS DEL PROYECTO (.deeprules):\n" + \
                "\n".join(f"- {r}" for r in rules)
        self.messages: List[dict] = [{"role": "system", "content": sys_prompt}]

    def run(self, user_input: str) -> dict:
        """Procesa un turno del usuario hasta la respuesta final (sin tool calls)."""
        self.messages.append({"role": "user", "content": user_input})
        self.on_event("user", {"content": user_input})
        _dbg.log("AGENT", f"run  task={user_input[:120]}  model={self.model}")

        for step in range(self.max_steps):
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

        self.on_event("error", {"error": "max_steps"})
        return {"success": False,
                "error": f"Se alcanzó el máximo de {self.max_steps} pasos",
                "steps": self.max_steps, "stats": self.client.get_stats()}
