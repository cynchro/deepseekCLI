import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from core.client import DeepSeekClient
from core.models import MODEL_FLASH

_EXPERIENCES_FILE = Path.home() / ".config" / "deep" / "experiences.json"
_MAX_STORED = 100


class DeepSeekMemory:
    def __init__(self, client: DeepSeekClient, model: str = MODEL_FLASH):
        self.client = client
        self.model = model
        self.experiences: List[Dict] = []
        self.patterns = defaultdict(list)
        self._load_experiences()

    def _load_experiences(self):
        if _EXPERIENCES_FILE.exists():
            try:
                self.experiences = json.loads(
                    _EXPERIENCES_FILE.read_text(encoding="utf-8")
                ).get("experiences", [])
            except Exception:
                pass

    def _save_experiences(self):
        _EXPERIENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
        _EXPERIENCES_FILE.write_text(
            json.dumps({"experiences": self.experiences[-_MAX_STORED:]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def analyze_experience(self, context: str, action: str,
                           result: str, success: bool) -> Dict:
        prompt = f"""
        Analiza esta experiencia de desarrollo y responde SOLO con JSON válido:

        CONTEXTO: {context}
        ACCIÓN: {action}
        RESULTADO: {result}
        ÉXITO: {'SÍ' if success else 'NO'}

        JSON con campos: lesson, root_cause, pattern, generalization, confidence (0-1), related_concepts.
        """
        response = self.client.chat(
            prompt,
            system_prompt="Eres un sistema experto en análisis de patrones. Responde SIEMPRE con JSON estructurado.",
            temperature=0.3, max_tokens=500,
            model_override=self.model,
        )
        try:
            raw = response.get("content") or ""
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            raw = re.sub(r"```json\n?|```\n?", "", raw).strip()
            return json.loads(raw)
        except Exception:
            return {"lesson": (response.get("content") or "")[:200], "root_cause": "No determinado",
                    "pattern": "Desconocido", "generalization": "", "confidence": 0.5,
                    "related_concepts": []}

    def extract_patterns(self, experiences: List[Dict]) -> List[Dict]:
        if len(experiences) < 2:
            return []
        summary = "\n".join(
            f"Exp {i+1}: {exp['context'][:80]} | éxito={exp['success']} | {exp.get('lesson','')[:80]}"
            for i, exp in enumerate(experiences[-10:])
        )
        response = self.client.chat(
            f"Identifica patrones en estas experiencias de desarrollo:\n{summary}\n\nResponde JSON con lista de patrones.",
            system_prompt="Eres un detector de patrones experto. Responde JSON.",
            temperature=0.3, max_tokens=400,
            model_override=self.model,
        )
        try:
            patterns = json.loads(re.sub(r"```json\n?|```\n?", "", response["content"]))
            return patterns if isinstance(patterns, list) else [patterns]
        except Exception:
            return [{"pattern": "No se pudieron identificar patrones"}]

    def _find_similar(self, context: str, top_k: int = 5) -> List[Dict]:
        if not self.experiences:
            return []
        ctx_words = set(context.lower().split())
        scored = []
        for exp in self.experiences:
            exp_words = set(exp["context"].lower().split())
            if exp_words:
                sim = len(ctx_words & exp_words) / len(ctx_words | exp_words)
                scored.append((sim, exp))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [e for _, e in scored[:top_k]]
