import json
import re
from datetime import datetime
from typing import Dict, List

from core.client import DeepSeekClient
from core.models import MODEL_FLASH


class ReflectiveAgent:
    def __init__(self, client: DeepSeekClient, model: str = MODEL_FLASH):
        self.client = client
        self.model = model
        self.reflection_history: List[Dict] = []
        self.personality = {"curiosity": 0.8, "caution": 0.6,
                            "creativity": 0.7, "precision": 0.75}

    def deep_reflection(self, task: str, plan: str, execution: str,
                        outcome: str, success: bool) -> Dict:
        prompt = f"""
        Reflexiona profundamente sobre este ciclo de desarrollo:
        TAREA: {task}
        PLAN: {plan[:300]}
        EJECUCIÓN: {execution[:300]}
        RESULTADO: {outcome[:300]}
        ÉXITO: {'SÍ' if success else 'NO'}

        JSON con: key_insight, cognitive_biases, wrong_assumptions,
        better_approach, generalizable_lesson, missed_questions,
        emotional_state, growth_percentage (0-100).
        """
        response = self.client.chat(
            prompt,
            system_prompt="Eres un agente con capacidad de introspección profunda. Sé honesto.",
            temperature=0.7, max_tokens=600,
            model_override=self.model,
        )
        try:
            reflection = json.loads(re.sub(r"```json\n?|```\n?", "", response["content"]))
        except Exception:
            reflection = {"key_insight": response["content"][:200],
                          "cognitive_biases": [], "growth_percentage": 50}
        self._update_personality(reflection, success)
        self.reflection_history.append({
            "timestamp": datetime.now().isoformat(),
            "reflection": reflection,
            "success": success,
        })
        return reflection

    def _update_personality(self, reflection: Dict, success: bool):
        growth = reflection.get("growth_percentage", 50) / 100
        if success:
            self.personality["precision"] = min(1.0, self.personality["precision"] + 0.01 * growth)
        else:
            self.personality["caution"] = min(1.0, self.personality["caution"] + 0.02 * growth)
            self.personality["curiosity"] = min(1.0, self.personality["curiosity"] + 0.01 * growth)

    def metacognition(self, recent_experiences: List[Dict]) -> Dict:
        summary = "\n".join(
            f"- {exp['task'][:80]} | éxito={exp['success']}"
            for exp in recent_experiences[-5:]
        )
        response = self.client.chat(
            f"METACOGNICIÓN: Analiza cómo estoy aprendiendo.\nExperiencias:\n{summary}\n\nJSON con insights accionables.",
            system_prompt="Eres un experto en metacognición. Responde JSON.",
            temperature=0.5, max_tokens=400,
            model_override=self.model,
        )
        try:
            return json.loads(re.sub(r"```json\n?|```\n?", "", response["content"]))
        except Exception:
            return {"insight": response["content"][:200]}
