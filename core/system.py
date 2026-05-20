import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import core.debug as _dbg
from core.client import DeepSeekClient
from core.memory import DeepSeekMemory
from core.agent import ReflectiveAgent
from core.writer import FileWriter


class DeepSeekLearningSystem:
    def __init__(self, api_key: str = None, output_dir: str = "output",
                 model: str = "deepseek-chat", root_is_output_dir: bool = False,
                 rules: List[str] = None,
                 on_progress: Callable[[str], None] = None,
                 on_file: Callable[[str], None] = None,
                 reflect: bool = False,
                 project_name: str = ""):
        self._on_progress = on_progress or (lambda msg: None)
        self._on_file = on_file or (lambda path: None)
        self.reflect = reflect
        self.client = DeepSeekClient(api_key, model=model)
        self.memory = DeepSeekMemory(self.client)
        self.reflective_agent = ReflectiveAgent(self.client)
        self.file_writer = FileWriter(output_dir, root_is_output_dir=root_is_output_dir,
                                      on_file=self._on_file, project_name=project_name)
        self.rules = rules or []

    def _progress(self, msg: str):
        self._on_progress(msg)

    def _rules_block(self) -> str:
        if not self.rules:
            return ""
        lines = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(self.rules))
        return f"\nREGLAS OBLIGATORIAS (.deeprules):\n{lines}\n"

    def execute_and_learn(self, task: str) -> Dict:
        _dbg.log("SYSTEM", f"execute_and_learn  task={task[:120]}")
        _dbg.log("SYSTEM", f"model={self.client.model}  rules={len(self.rules)}")

        self._progress("FASE 1")
        _dbg.log("PHASE", "1 — planificación")
        plan = self._plan(task)
        _dbg.log_block("PHASE_1", "plan", plan)

        self._progress("FASE 2")
        _dbg.log("PHASE", "2 — ejecución / generación de código")
        execution = self._execute(task, plan)
        _dbg.log("PHASE_2", f"tokens_used={execution.get('tokens_used', 0)}  "
                 f"code_chars={len(execution.get('code', ''))}")

        self._progress("FASE 3")
        _dbg.log("PHASE", "3 — escritura de archivos")
        written_files = self.file_writer.write_from_response(execution["code"], task)
        _dbg.log("PHASE_3", f"files_written={len(written_files)}  paths={written_files}")

        heuristics = self._heuristic_check(written_files, task)
        _dbg.log_json("PHASE_3", "heuristics", heuristics)

        self._progress("FASE 4")
        _dbg.log("PHASE", "4 — evaluación")
        success, outcome = self._evaluate(task, plan, execution, written_files, heuristics)
        _dbg.log("PHASE_4", f"success={success}  structural_ok={heuristics.get('structural_ok')}")

        # Override: si la heurística confirma estructura completa pero el LLM dice failure,
        # inyectar heuristic_override en el outcome para que review_and_fix sepa que no es crítico
        if not success and heuristics.get("structural_ok"):
            try:
                ev = json.loads(outcome)
                ev["heuristic_override"] = True
                ev["heuristic_note"] = "Estructura completa según análisis en disco; fallo LLM puede ser falso negativo."
                outcome = json.dumps(ev)
                _dbg.log("HEURISTIC", "override aplicado: estructura ok, LLM dice failure")
            except Exception:
                pass

        _dbg.log_block("PHASE_4", "evaluation_outcome", outcome)

        self._progress("FASE 5")
        _dbg.log("PHASE", "5 — análisis de experiencia / memoria")
        analysis = self.memory.analyze_experience(
            context=task, action=plan, result=outcome, success=success
        )
        _dbg.log_json("PHASE_5", "experience_analysis", analysis)
        experience = {
            "task": task, "plan": plan[:200], "execution": str(execution)[:200],
            "outcome": outcome, "success": success,
            "lesson": analysis.get("lesson", ""), "pattern": analysis.get("pattern", ""),
            "files_written": written_files,
            "timestamp": datetime.now().isoformat(), "context": task,
        }
        self.memory.experiences.append(experience)
        self.memory._save_experiences()

        reflection = None
        metacog = None
        patterns = []
        if self.reflect:
            self._progress("FASE 6")
            _dbg.log("PHASE", "6 — reflexión profunda")
            reflection = self.reflective_agent.deep_reflection(
                task=task, plan=plan, execution=str(execution), outcome=outcome, success=success
            )
            _dbg.log_json("PHASE_6", "reflection", reflection)
            if len(self.memory.experiences) % 5 == 0:
                self._progress("FASE 7")
                _dbg.log("PHASE", "7 — metacognición")
                metacog = self.reflective_agent.metacognition(self.memory.experiences)
            if len(self.memory.experiences) % 5 == 0:
                self._progress("FASE 8")
                _dbg.log("PHASE", "8 — extracción de patrones")
                patterns = self.memory.extract_patterns(self.memory.experiences)

        if self.file_writer.last_project_dir:
            self._persist_context(task, plan, success, outcome)

        _dbg.log("SYSTEM", f"execute_and_learn DONE  success={success}  "
                 f"files={len(written_files)}  experiences={len(self.memory.experiences)}")
        return {
            "success": success, "plan": plan[:200], "outcome": outcome,
            "files_written": written_files, "analysis": analysis,
            "reflection": reflection, "metacognition": metacog, "patterns": patterns,
            "experience_count": len(self.memory.experiences),
        }

    def review_and_fix(self, task: str, result: Dict) -> Dict:
        _dbg.log("FIX", f"review_and_fix  task={task[:80]}")
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
        _dbg.log("FIX", f"code_files={len(code_files)}  issues={issues}  suggestions={suggestions}")
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
            safe = [p for p in Path(filename.lstrip("/")).parts if p not in ("..", ".", "~", "/")]
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

        _dbg.log("FIX", f"DONE  success={success}  files_fixed={len(fixed_files)}")
        return {"success": success, "files_fixed": fixed_files, "outcome": new_outcome}

    def execute_update(self, change: str, task: str) -> Dict:
        _dbg.log("UPDATE", f"change={change[:120]}")
        project_dir = Path(self.file_writer.output_dir)

        file_blocks = []
        all_files = sorted(
            f for f in project_dir.rglob("*")
            if f.is_file() and ".deep" not in f.parts and not f.name.startswith(".")
        )
        for f in all_files[:15]:
            try:
                text = f.read_text(encoding="utf-8")
                rel = f.relative_to(project_dir)
                file_blocks.append(f"### archivo: {rel}\n```\n{text[:2000]}\n```")
            except Exception:
                pass
        if len(all_files) > 15:
            self._progress(f"ANALIZANDO ({len(all_files)} archivos, enviando 15)")

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
            safe = [p for p in Path(filename.lstrip("/")).parts if p not in ("..", ".", "~", "/")]
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
        _dbg.log("PLAN", f"similar_experiences_found={len(similar)}")
        context = ""
        if similar:
            context = "\nExperiencias previas relevantes:\n" + "\n".join(
                f"- {'Éxito' if e['success'] else 'Fracaso'}: {e['lesson'][:100]}"
                for e in similar[:3]
            )
            _dbg.log_block("PLAN", "similar_context", context)
        response = self.client.chat(
            f"Crea un plan detallado para:\n{task}\n{context}\n{self._rules_block()}\n"
            "Incluye: arquitectura, archivos a crear (rutas relativas), dependencias, posibles problemas.",
            system_prompt="Eres un arquitecto de software senior. Creas planes claros y accionables.",
            temperature=0.5, max_tokens=10000,
        )
        return response["content"]

    def _execute(self, task: str, plan: str) -> Dict:
        response = self.client.chat(
            f"IMPLEMENTA este plan generando TODOS los archivos.\n\nTarea: {task}\nPlan:\n{plan}\n"
            f"{self._rules_block()}\n"
            "FORMATO: antes de cada bloque escribe ### archivo: ruta/archivo.ext\n"
            "Código completo y funcional. Sin '...' ni placeholders.",
            system_prompt="Eres un desarrollador senior. Código limpio, completo. Siempre indicás el nombre del archivo.",
            temperature=0.3, max_tokens=12000,
        )
        tokens = response.get("tokens", {}).get("total_tokens", 0)
        _dbg.log("EXEC", f"response_success={response.get('success')}  tokens={tokens}")
        return {"code": response["content"], "tokens_used": tokens}

    def _evaluate(self, task: str, plan: str, execution: Dict,
                  written_files: List[str] = None,
                  heuristics: Dict = None) -> Tuple[bool, str]:
        if written_files:
            file_parts = []
            for fp in written_files[:15]:
                p = Path(fp)
                if ".deep" in p.parts or p.name == "RESPONSE.md":
                    continue
                try:
                    text = p.read_text(encoding="utf-8")
                    if len(text) <= 1200:
                        snippet = text
                    else:
                        head = text[:900]
                        omitted = len(text) - 900 - 200
                        tail_lines = text.rstrip().splitlines()[-4:]
                        tail = "\n".join(tail_lines)
                        separator = f"\n# ─── {omitted} chars omitidos ───\n"
                        snippet = f"{head}{separator}{tail}"
                    file_parts.append(f"### {p.name} ({len(text)} chars)\n```\n{snippet}\n```")
                except Exception:
                    pass
            names = [Path(f).name for f in written_files if ".deep" not in Path(f).parts]
            code_block = (
                f"Archivos en disco ({len(names)}): {', '.join(names)}\n"
                f"NOTA: snippets largos se muestran como inicio + últimas líneas con '[...]' en medio. "
                f"Eso NO indica archivo incompleto — indica que el archivo tiene más contenido entre esas secciones.\n\n"
                + "\n".join(file_parts)
            )
        else:
            code_block = f"Código (primeros 3000 chars):\n{str(execution.get('code', ''))[:3000]}"

        heuristic_note = ""
        if heuristics:
            h_issues = heuristics.get("heuristic_issues", [])
            if h_issues:
                heuristic_note = f"\nProblemas estructurales detectados automáticamente: {'; '.join(h_issues)}\n"
            else:
                heuristic_note = "\nAnálisis estructural automático: todos los archivos presentes y sin placeholders.\n"

        # La evaluación es output estructurado: no necesita reasoning, siempre usa chat
        eval_model = "deepseek-chat" if "reasoner" in self.client.model else self.client.model
        response = self.client.chat(
            f"EVALÚA la calidad del código de esta implementación.\n"
            f"Tarea: {task[:200]}\nPlan: {plan[:200]}\n"
            f"{heuristic_note}"
            f"NOTA: la lista de archivos presentes en disco es exacta, NO reportes archivos como faltantes si están en la lista.\n"
            f"{code_block}\n\n"
            'JSON: {"overall_score":1-10,"success":true/false,"issues":[],"positives":[],"suggestions":[]}',
            system_prompt="Eres un revisor de código experto. Evalúas calidad del código, arquitectura y completitud. No inventes archivos faltantes si la lista los incluye. Responde SOLO con JSON válido.",
            temperature=0.2, max_tokens=1500,
            model_override=eval_model,
        )
        raw = response.get("content") or ""
        try:
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            raw = re.sub(r"```json\n?|```\n?", "", raw).strip()
            ev = json.loads(raw)
            _dbg.log_json("EVAL", "evaluation_parsed", ev)
            return ev.get("success", False), json.dumps(ev)
        except Exception as e:
            _dbg.log("EVAL", f"json_parse_failed={e}  raw={raw[:200]}")
            return False, json.dumps({"raw": raw[:300], "parse_error": str(e)})

    def _heuristic_check(self, written_files: List[str], task: str) -> Dict:
        issues = []
        names = {Path(f).name for f in written_files if ".deep" not in Path(f).parts
                 and Path(f).name != "RESPONSE.md"}

        # __init__.py vacío es patrón válido de Python, no es un problema
        _IGNORE_EMPTY = {"__init__.py"}
        _PLACEHOLDER_ONLY = {"pass", "...", "#todo", "# todo", "# placeholder", "todo"}
        for fp in written_files:
            p = Path(fp)
            if ".deep" in p.parts or p.name == "RESPONSE.md" or p.name in _IGNORE_EMPTY:
                continue
            try:
                text = p.read_text(encoding="utf-8").strip()
                if not text or len(text) < 20:
                    issues.append(f"{p.name}: archivo vacío o casi vacío")
                else:
                    non_empty = [ln.strip() for ln in text.splitlines() if ln.strip()]
                    if non_empty and all(ln.lower() in _PLACEHOLDER_ONLY or ln.startswith("#")
                                        for ln in non_empty):
                        issues.append(f"{p.name}: contiene solo placeholders/comentarios")
            except Exception:
                pass

        task_lower = task.lower()
        if any(w in task_lower for w in ("docker", "contenedor", "container", "dockerfile")):
            if "Dockerfile" not in names and "dockerfile" not in {n.lower() for n in names}:
                issues.append("Dockerfile ausente (requerido por la tarea)")
        if any(w in task_lower for w in ("requirements", "pip install", "python")):
            if "requirements.txt" not in names:
                issues.append("requirements.txt ausente")
        if any(w in task_lower for w in ("test", "prueba", "unittest", "pytest")):
            if not any("test" in n.lower() for n in names):
                issues.append("No se generaron archivos de test")
        if any(w in task_lower for w in ("docker-compose", "compose")):
            if not any("compose" in n.lower() for n in names):
                issues.append("docker-compose.yml ausente")

        structural_ok = len(issues) == 0 and len(names) >= 2
        _dbg.log("HEURISTIC", f"structural_ok={structural_ok}  issues={issues}  files={sorted(names)}")
        return {
            "heuristic_issues": issues,
            "structural_ok": structural_ok,
            "file_names": sorted(names),
            "files_count": len(names),
        }

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
