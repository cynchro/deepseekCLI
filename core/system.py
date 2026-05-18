import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from core.client import DeepSeekClient
from core.memory import DeepSeekMemory
from core.agent import ReflectiveAgent
from core.writer import FileWriter


class DeepSeekLearningSystem:
    def __init__(self, api_key: str = None, output_dir: str = "output",
                 model: str = "deepseek-chat", root_is_output_dir: bool = False,
                 rules: List[str] = None,
                 on_progress: Callable[[str], None] = None,
                 on_file: Callable[[str], None] = None):
        self._on_progress = on_progress or (lambda msg: None)
        self._on_file = on_file or (lambda path: None)
        self.client = DeepSeekClient(api_key, model=model)
        self.memory = DeepSeekMemory(self.client)
        self.reflective_agent = ReflectiveAgent(self.client)
        self.file_writer = FileWriter(output_dir, root_is_output_dir=root_is_output_dir,
                                      on_file=self._on_file)
        self.rules = rules or []

    def _progress(self, msg: str):
        self._on_progress(msg)

    def _rules_block(self) -> str:
        if not self.rules:
            return ""
        lines = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(self.rules))
        return f"\nREGLAS OBLIGATORIAS (.deeprules):\n{lines}\n"

    def execute_and_learn(self, task: str) -> Dict:
        self._progress("FASE 1")
        plan = self._plan(task)

        self._progress("FASE 2")
        execution = self._execute(task, plan)

        self._progress("FASE 3")
        written_files = self.file_writer.write_from_response(execution["code"], task)

        self._progress("FASE 4")
        success, outcome = self._evaluate(task, plan, execution)

        self._progress("FASE 5")
        analysis = self.memory.analyze_experience(
            context=task, action=plan, result=outcome, success=success
        )
        experience = {
            "task": task, "plan": plan[:200], "execution": str(execution)[:200],
            "outcome": outcome, "success": success,
            "lesson": analysis.get("lesson", ""), "pattern": analysis.get("pattern", ""),
            "files_written": written_files,
            "timestamp": datetime.now().isoformat(), "context": task,
        }
        self.memory.experiences.append(experience)
        self.memory._save_experiences()

        self._progress("FASE 6")
        reflection = self.reflective_agent.deep_reflection(
            task=task, plan=plan, execution=str(execution), outcome=outcome, success=success
        )

        metacog = None
        if len(self.memory.experiences) % 5 == 0:
            self._progress("FASE 7")
            metacog = self.reflective_agent.metacognition(self.memory.experiences)

        patterns = []
        if len(self.memory.experiences) % 5 == 0:
            self._progress("FASE 8")
            patterns = self.memory.extract_patterns(self.memory.experiences)

        if self.file_writer.last_project_dir:
            self._persist_context(task, plan, success, outcome)

        return {
            "success": success, "plan": plan[:200], "outcome": outcome,
            "files_written": written_files, "analysis": analysis,
            "reflection": reflection, "metacognition": metacog, "patterns": patterns,
            "experience_count": len(self.memory.experiences),
        }

    def review_and_fix(self, task: str, result: Dict) -> Dict:
        code_files = [
            f for f in result.get("files_written", [])
            if ".deep" not in Path(f).parts and Path(f).name != "RESPONSE.md"
        ]
        try:
            ev = json.loads(result.get("outcome", "{}"))
            issues, suggestions = ev.get("issues", []), ev.get("suggestions", [])
        except Exception:
            issues, suggestions = [], []

        file_blocks = []
        for fp in code_files[:10]:
            try:
                text = Path(fp).read_text(encoding="utf-8")
                file_blocks.append(f"### archivo: {Path(fp).name}\n```\n{text[:3000]}\n```")
            except Exception:
                pass

        prompt = f"""
Eres un senior developer. CORRIGE los problemas en este proyecto.

Tarea: {task[:300]}
Problemas: {chr(10).join(f'- {i}' for i in issues) or '- Ver sugerencias'}
Sugerencias: {chr(10).join(f'- {s}' for s in suggestions) or '- Revisar buenas prácticas'}
{self._rules_block()}
Archivos actuales:
{chr(10).join(file_blocks)}

Reescribe SOLO los archivos con problemas. Formato: ### archivo: ruta/archivo.ext
"""
        self._progress("REVISIÓN")
        response = self.client.chat(
            prompt,
            system_prompt="Eres un senior developer. Corriges código de forma precisa y completa. Sin placeholders.",
            temperature=0.2, max_tokens=8000,
        )
        if not response.get("success"):
            return {"success": False, "files_fixed": [], "error": response.get("content", "")}

        project_dir: Optional[Path] = next(
            (Path(f).parent for f in code_files if Path(f).exists()), None
        )
        if not project_dir:
            return {"success": False, "files_fixed": [], "error": "Directorio no encontrado"}

        fixed_files = []
        for filename, code in self.file_writer._extract_named_blocks(response["content"]):
            safe = [p for p in Path(filename).parts if p not in ("..", ".", "~")]
            if not safe:
                continue
            filepath = project_dir.joinpath(*safe)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(code, encoding="utf-8")
            fixed_files.append(str(filepath))
            self._on_file(str(filepath))

        self._progress("RE-EVALUANDO")
        success, new_outcome = self._evaluate(task, result.get("plan", ""),
                                              {"code": response["content"]})

        if self.file_writer.root_is_output_dir and self.file_writer.last_project_dir:
            deep_dir = self.file_writer.last_project_dir / ".deep"
            deep_dir.mkdir(exist_ok=True)
            try:
                eval_data = json.loads(new_outcome)
            except Exception:
                eval_data = {"raw": new_outcome}
            eval_data["fixed_files"] = fixed_files
            (deep_dir / "evaluation.json").write_text(
                json.dumps(eval_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        return {"success": success, "files_fixed": fixed_files, "outcome": new_outcome}

    def execute_update(self, change: str, task: str) -> Dict:
        project_dir = Path(self.file_writer.output_dir)

        file_blocks = []
        for f in sorted(project_dir.rglob("*")):
            if not f.is_file() or ".deep" in f.parts or f.name.startswith("."):
                continue
            try:
                text = f.read_text(encoding="utf-8")
                rel = f.relative_to(project_dir)
                file_blocks.append(f"### archivo: {rel}\n```\n{text[:2000]}\n```")
            except Exception:
                pass

        self._progress("ANALIZANDO")
        prompt = (
            f"Proyecto actual: {task}\n\n"
            f"Archivos existentes:\n{''.join(file_blocks)}\n\n"
            f"Cambio solicitado: {change}\n"
            f"{self._rules_block()}\n"
            "Devolvé SOLO los archivos modificados o nuevos con el formato:\n"
            "### archivo: ruta/archivo.ext\n"
            "Código completo. Sin placeholders ni '...'."
        )
        response = self.client.chat(
            prompt,
            system_prompt="Eres un senior developer. Modificás proyectos existentes con cambios precisos y código completo.",
            temperature=0.3, max_tokens=8000,
        )
        if not response.get("success"):
            return {"success": False, "files_updated": [], "error": response.get("content", "")}

        self._progress("APLICANDO")
        updated_files = []
        for filename, code in self.file_writer._extract_named_blocks(response["content"]):
            safe = [p for p in Path(filename).parts if p not in ("..", ".", "~")]
            if not safe:
                continue
            filepath = project_dir.joinpath(*safe)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(code, encoding="utf-8")
            updated_files.append(str(filepath))
            self._on_file(str(filepath))

        ctx_file = project_dir / ".deep" / "context.json"
        if ctx_file.exists():
            try:
                ctx = json.loads(ctx_file.read_text())
                ctx["last_update"] = change
                ctx["updated_at"] = datetime.now().isoformat()
                ctx_file.write_text(json.dumps(ctx, ensure_ascii=False, indent=2))
            except Exception:
                pass

        return {"success": True, "files_updated": updated_files}

    def demonstrate_learning(self) -> Dict:
        if not self.memory.experiences:
            return {"status": "Sin experiencias aún"}
        successes = [e["success"] for e in self.memory.experiences]
        half = len(successes) // 2
        first_rate = sum(successes[:half]) / half if half else 0
        second_rate = sum(successes[half:]) / (len(successes) - half) if half else 0
        overall = sum(successes) / len(successes)
        recent = sum(successes[-5:]) / min(5, len(successes))
        return {
            "total_experiences": len(self.memory.experiences),
            "overall_success_rate": f"{overall*100:.1f}%",
            "recent_success_rate": f"{recent*100:.1f}%",
            "improvement": f"{(second_rate - first_rate)*100:+.1f}%",
            "learning_trajectory": "📈 Mejorando" if second_rate > first_rate else "📉 Necesita mejorar",
            "client_stats": self.client.get_stats(),
        }

    # ── privados ──────────────────────────────────────────────────────────────

    def _plan(self, task: str) -> str:
        similar = self.memory._find_similar(task)
        context = ""
        if similar:
            context = "\nExperiencias previas relevantes:\n" + "\n".join(
                f"- {'Éxito' if e['success'] else 'Fracaso'}: {e['lesson'][:100]}"
                for e in similar[:3]
            )
        response = self.client.chat(
            f"Crea un plan detallado para:\n{task}\n{context}\n{self._rules_block()}\n"
            "Incluye: arquitectura, archivos a crear (rutas relativas), dependencias, posibles problemas.",
            system_prompt="Eres un arquitecto de software senior. Creas planes claros y accionables.",
            temperature=0.5, max_tokens=1000,
        )
        return response["content"]

    def _execute(self, task: str, plan: str) -> Dict:
        response = self.client.chat(
            f"IMPLEMENTA este plan generando TODOS los archivos.\n\nTarea: {task}\nPlan:\n{plan}\n"
            f"{self._rules_block()}\n"
            "FORMATO: antes de cada bloque escribe ### archivo: ruta/archivo.ext\n"
            "Código completo y funcional. Sin '...' ni placeholders.",
            system_prompt="Eres un desarrollador senior. Código limpio, completo. Siempre indicás el nombre del archivo.",
            temperature=0.3, max_tokens=8000,
        )
        return {"code": response["content"],
                "tokens_used": response.get("tokens", {}).get("total_tokens", 0)}

    def _evaluate(self, task: str, plan: str, execution: Dict) -> Tuple[bool, str]:
        response = self.client.chat(
            f"EVALÚA esta implementación:\nTarea: {task[:200]}\nPlan: {plan[:200]}\n"
            f"Código: {str(execution.get('code', ''))[:500]}\n\n"
            'JSON: {"overall_score":1-10,"success":true/false,"issues":[],"positives":[],"suggestions":[]}',
            system_prompt="Eres un revisor de código experto. Evalúas con criterios objetivos.",
            temperature=0.2, max_tokens=400,
        )
        try:
            ev = json.loads(re.sub(r"```json\n?|```\n?", "", response["content"]))
            return ev.get("success", False), json.dumps(ev)
        except Exception:
            return True, response["content"][:200]

    def _persist_context(self, task: str, plan: str, success: bool, outcome: str):
        deep_dir = self.file_writer.last_project_dir / ".deep"
        deep_dir.mkdir(exist_ok=True)
        (deep_dir / "context.json").write_text(
            json.dumps({"task": task, "plan": plan, "model": self.client.model,
                        "timestamp": datetime.now().isoformat()},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            ev_data = json.loads(outcome)
        except Exception:
            ev_data = {"raw": outcome}
        (deep_dir / "evaluation.json").write_text(
            json.dumps(ev_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
