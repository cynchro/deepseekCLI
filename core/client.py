import os
import subprocess
import json
import time
from datetime import datetime
from typing import Dict, List

import core.debug as _dbg

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


class DeepSeekClient:
    def __init__(self, api_key: str = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model
        self.max_retries = 3
        self.retry_delay = 1
        self.call_history = []

    def chat(self, prompt: str, system_prompt: str = None,
             temperature: float = 0.7, max_tokens: int = 2000,
             model_override: str = None) -> Dict:
        model = model_override or self.model
        _dbg.log("API_CALL", f"model={model}  temp={temperature}  max_tokens={max_tokens}")
        if system_prompt:
            _dbg.log_block("API_SYS", "system_prompt", system_prompt)
        _dbg.log_block("API_USER", "user_prompt", prompt)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        for attempt in range(self.max_retries):
            t0 = time.time()
            try:
                response = self._call_api(payload)
                latency = time.time() - t0
                usage = response.get("usage", {})
                msg = response["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content", "")
                _dbg.log("API_OK", f"attempt={attempt+1}  latency={latency:.2f}s  "
                         f"tokens_in={usage.get('prompt_tokens','?')}  "
                         f"tokens_out={usage.get('completion_tokens','?')}  "
                         f"total={usage.get('total_tokens','?')}")
                _dbg.log_block("API_RESP", "response_content", content)
                self.call_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "tokens_used": usage.get("total_tokens", 0),
                    "success": True,
                })
                return {
                    "success": True,
                    "content": content,
                    "tokens": usage,
                    "model": self.model,
                }
            except Exception as e:
                latency = time.time() - t0
                _dbg.log("API_ERR", f"attempt={attempt+1}  latency={latency:.2f}s  error={e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    self.call_history.append({"timestamp": datetime.now().isoformat(),
                                              "error": str(e), "success": False})
                    return {
                        "success": False,
                        "content": f"Error después de {self.max_retries} intentos: {str(e)[:200]}",
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
        return {
            "total_calls": len(self.call_history),
            "successful_calls": len(successful),
            "failed_calls": len(self.call_history) - len(successful),
            "total_tokens_used": total_tokens,
            "average_tokens_per_call": total_tokens / max(len(successful), 1),
        }
