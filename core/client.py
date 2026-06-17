import os
import subprocess
import json
import time
from datetime import datetime
from typing import Dict, List

import core.debug as _dbg
from core.models import MODEL_FLASH, estimate_cost
from core.router import resolve_model

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


class DeepSeekClient:
    def __init__(self, api_key: str = None, model: str = MODEL_FLASH):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = resolve_model(model)
        self.max_retries = 3
        self.retry_delay = 1
        self.call_history = []

    def chat(self, prompt: str, system_prompt: str = None,
             temperature: float = 0.7, max_tokens: int = 2000,
             model_override: str = None, tools: List[Dict] = None,
             tool_choice=None) -> Dict:
        """Conveniencia: un turno (system + user) sobre complete()."""
        if system_prompt:
            _dbg.log_block("API_SYS", "system_prompt", system_prompt)
        _dbg.log_block("API_USER", "user_prompt", prompt)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.complete(
            messages, model=model_override or self.model,
            temperature=temperature, max_tokens=max_tokens,
            tools=tools, tool_choice=tool_choice,
        )

    def complete(self, messages: List[Dict], model: str = None,
                 temperature: float = 0.7, max_tokens: int = 2000,
                 tools: List[Dict] = None, tool_choice=None) -> Dict:
        """Chat completion de bajo nivel sobre una lista de mensajes completa.

        Soporta function calling nativo: pasá `tools` (schema OpenAI) y leé
        `tool_calls` / `finish_reason` del resultado. Mantiene retry + debug.
        El retorno es un superconjunto del de chat(): se preservan las claves
        existentes (success, content, tokens, model) y se agregan tool_calls /
        finish_reason / message.
        """
        model = resolve_model(model or self.model)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice if tool_choice is not None else "auto"
        _dbg.log("API_CALL", f"model={model}  temp={temperature}  "
                 f"max_tokens={max_tokens}  msgs={len(messages)}  "
                 f"tools={len(tools) if tools else 0}")
        for attempt in range(self.max_retries):
            t0 = time.time()
            try:
                response = self._call_api(payload)
                latency = time.time() - t0
                usage = response.get("usage", {})
                choice = response["choices"][0]
                msg = choice.get("message", {})
                content = msg.get("content") or msg.get("reasoning_content", "") or ""
                tool_calls = msg.get("tool_calls")
                finish_reason = choice.get("finish_reason")
                _dbg.log("API_OK", f"attempt={attempt+1}  latency={latency:.2f}s  "
                         f"finish={finish_reason}  "
                         f"tokens_in={usage.get('prompt_tokens','?')}  "
                         f"tokens_out={usage.get('completion_tokens','?')}  "
                         f"total={usage.get('total_tokens','?')}  "
                         f"tool_calls={len(tool_calls) if tool_calls else 0}")
                if content:
                    _dbg.log_block("API_RESP", "response_content", content)
                self.call_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "model": model,
                    "tokens_used": usage.get("total_tokens", 0),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "success": True,
                })
                return {
                    "success": True,
                    "content": content,
                    "tool_calls": tool_calls,
                    "finish_reason": finish_reason,
                    "message": msg,
                    "tokens": usage,
                    "model": model,
                }
            except Exception as e:
                latency = time.time() - t0
                _dbg.log("API_ERR", f"attempt={attempt+1}  latency={latency:.2f}s  error={e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    self.call_history.append({"timestamp": datetime.now().isoformat(),
                                              "model": model, "error": str(e),
                                              "success": False})
                    return {
                        "success": False,
                        "content": f"Error después de {self.max_retries} intentos: {str(e)[:200]}",
                        "tool_calls": None,
                        "finish_reason": "error",
                        "error": str(e),
                    }

    def _call_api(self, payload: Dict) -> Dict:
        if _HAS_REQUESTS:
            r = _requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=(10, 120),
            )
            r.raise_for_status()
            return r.json()
        result = subprocess.run(
            ["curl", "-s", "--max-time", "120", "-X", "POST",
             "https://api.deepseek.com/v1/chat/completions",
             "-H", f"Authorization: Bearer {self.api_key}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True,
            timeout=125,
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl falló: {result.stderr[:200]}")
        return json.loads(result.stdout)

    def chat_with_context(self, messages: List[Dict], **kwargs) -> Dict:
        try:
            return self._call_api({"model": self.model, "messages": messages, **kwargs})
        except Exception as e:
            print(f"\n⚠️  Fallback: contexto completo no disponible ({e.__class__.__name__}). Enviando resumen.")
            context = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in messages)
            return self.chat(context, **kwargs)

    def compact_history(self, messages: List[Dict], keep_last: int = 6) -> tuple:
        """Summarize old messages when approaching the context limit.
        Returns (compacted_messages, did_compact)."""
        _CTX_LIMIT_TOKENS = 52_000  # ~80% of deepseek-chat 64K limit
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if total_chars // 4 < _CTX_LIMIT_TOKENS:
            return messages, False

        system_msgs = [m for m in messages if m["role"] == "system"]
        turns = [m for m in messages if m["role"] != "system"]

        if len(turns) <= keep_last:
            return messages, False

        to_summarize = turns[:-keep_last]
        recent = turns[-keep_last:]

        convo_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in to_summarize
        )
        result = self.chat(
            f"Resume esta conversación de forma concisa preservando todos los "
            f"datos técnicos, código y decisiones importantes:\n\n{convo_text}",
            system_prompt=(
                "Sos un asistente que resume conversaciones técnicas. "
                "Respondé solo con el resumen, sin preámbulos ni explicaciones."
            ),
            temperature=0.3,
            max_tokens=1000,
        )
        if not result.get("success") or not result.get("content"):
            return messages, False

        summary_msg = {
            "role": "assistant",
            "content": f"[Resumen de conversación anterior]\n{result['content']}",
        }
        return system_msgs + [summary_msg] + recent, True

    def get_stats(self) -> Dict:
        successful = [c for c in self.call_history if c.get("success")]
        total_tokens = sum(c.get("tokens_used", 0) for c in successful)
        by_model: Dict[str, Dict] = {}
        total_cost = 0.0
        for c in successful:
            m = c.get("model", "?")
            cost = estimate_cost(m, c.get("prompt_tokens", 0), c.get("completion_tokens", 0))
            total_cost += cost
            entry = by_model.setdefault(m, {"calls": 0, "tokens": 0, "cost_usd": 0.0})
            entry["calls"] += 1
            entry["tokens"] += c.get("tokens_used", 0)
            entry["cost_usd"] = round(entry["cost_usd"] + cost, 6)
        return {
            "total_calls": len(self.call_history),
            "successful_calls": len(successful),
            "failed_calls": len(self.call_history) - len(successful),
            "total_tokens_used": total_tokens,
            "average_tokens_per_call": total_tokens / max(len(successful), 1),
            "estimated_cost_usd": round(total_cost, 6),
            "by_model": by_model,
        }
