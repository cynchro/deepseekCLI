import os
import subprocess
import json
import time
from datetime import datetime
from typing import Dict, List

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
             temperature: float = 0.7, max_tokens: int = 2000) -> Dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        for attempt in range(self.max_retries):
            try:
                response = self._call_api(payload)
                self.call_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "tokens_used": response.get("usage", {}).get("total_tokens", 0),
                    "success": True,
                })
                return {
                    "success": True,
                    "content": response["choices"][0]["message"]["content"],
                    "tokens": response.get("usage", {}),
                    "model": self.model,
                }
            except Exception as e:
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
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "https://api.deepseek.com/v1/chat/completions",
             "-H", f"Authorization: Bearer {self.api_key}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl falló: {result.stderr[:200]}")
        return json.loads(result.stdout)

    def chat_with_context(self, messages: List[Dict], **kwargs) -> Dict:
        try:
            return self._call_api({"model": self.model, "messages": messages, **kwargs})
        except Exception:
            context = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in messages)
            return self.chat(context, **kwargs)

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
