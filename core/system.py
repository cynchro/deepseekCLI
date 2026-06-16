import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import core.debug as _dbg
from core.client import DeepSeekClient
from core.config import get_language_instruction
from core.memory import DeepSeekMemory
from core.agent import ReflectiveAgent
from core.writer import FileWriter
from core.prompts import (BUILD_COMPLETENESS, DOCKER_NPM, UPDATE_DOCKER_HINT,
                          MANIFEST_INSTRUCTIONS, FILE_GEN_INSTRUCTIONS)
from core.postcheck import analyze_project, apply_remediations, merge_into_heuristics


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

    # Si el manifiesto supera este umbral, se genera archivo por archivo en vez
    # de en una sola respuesta (que no entraría en el tope de tokens del modelo).
    SINGLE_SHOT_MAX_FILES = 8

    def execute_and_learn(self, task: str, plan: str = None,
                          manifest: bool = False) -> Dict:
        _dbg.log("SYSTEM", f"execute_and_learn  task={task[:120]}  manifest={manifest}")
        _dbg.log("SYSTEM", f"model={self.client.model}  rules={len(self.rules)}")

        self._progress("FASE 1")
        if plan is None:
            # Camino normal: DeepSeek planifica.
            _dbg.log("PHASE", "1 — planificación")
            plan = self._plan(task)
            _dbg.log_block("PHASE_1", "plan", plan)
        else:
            # Plan provisto externamente (ej. deep navigator): se saltea el planner de DeepSeek.
            _dbg.log("PHASE", "1 — planificación (plan externo, se saltea _plan)")
            _dbg.log_block("PHASE_1", "plan_external", plan)

        self._progress("FASE 2")
        _dbg.log("PHASE", "2 — ejecución / generación de código")
        execution = self._execute(task, plan, manifest_mode=manifest)
        _dbg.log("PHASE_2", f"tokens_used={execution.get('tokens_used', 0)}  "
                 f"code_chars={len(execution.get('code', ''))}")

        self._progress("FASE 3")
        _dbg.log("PHASE", "3 — escritura de archivos")
        written_files = self.file_writer.write_from_response(execution["code"], task)
        _dbg.log("PHASE_3", f"files_written={len(written_files)}  paths={written_files}")

        heuristics = self._heuristic_check(written_files, task)
        heuristics, postcheck_fixes, postcheck_report = self._run_postcheck(
            heuristics, response_text=execution.get("code", "")
        )
        _dbg.log_json("PHASE_3", "heuristics", heuristics)
        if postcheck_fixes:
            _dbg.log("POSTCHECK", f"fixes={postcheck_fixes}")

        self._progress("FASE 4")
        _dbg.log("PHASE", "4 — evaluación")
        success, outcome = self._evaluate(task, plan, execution, written_files, heuristics)
        _dbg.log("PHASE_4", f"success={success}  structural_ok={heuristics.get('structural_ok')}")

        # Incompletitud: si la generación se cortó por tokens, o el manifiesto declaró
        # archivos que no se pudieron generar, el proyecto está incompleto. Fail honesto.
        truncated = execution.get("truncated", False)
        missing_files = execution.get("missing_files", []) or []
        if truncated or missing_files:
            success = False
            try:
                ev = json.loads(outcome)
            except Exception:
                ev = {"raw": outcome}
            ev["success"] = False
            ev["truncated"] = truncated
            issues = []
            if truncated:
                issues.append(
                    "La respuesta del modelo se truncó por límite de tokens tras agotar las "
                    "continuaciones automáticas: faltan archivos.")
            if missing_files:
                ev["missing_files"] = missing_files
                issues.append(
                    f"{len(missing_files)} archivo(s) del manifiesto no se generaron: "
                    f"{', '.join(missing_files[:8])}{'…' if len(missing_files) > 8 else ''}. "
                    f"Corré 'deep fix' para completarlos.")
            ev["issues"] = issues + ev.get("issues", [])
            outcome = json.dumps(ev)
            _dbg.log("INCOMPLETE", f"truncated={truncated}  missing={len(missing_files)} "
                     "— success forzado a False")

        # Override: si la heurística confirma estructura completa pero el LLM dice failure,
        # inyectar heuristic_override en el outcome para que review_and_fix sepa que no es crítico
        if (not success and not truncated and not missing_files
                and heuristics.get("structural_ok")):
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
            self._persist_context(task, plan, success, outcome,
                                  manifest=execution.get("manifest", []))

        _dbg.log("SYSTEM", f"execute_and_learn DONE  success={success}  "
                 f"files={len(written_files)}  experiences={len(self.memory.experiences)}")
        return {
            "success": success, "plan": plan[:200], "outcome": outcome,
            "files_written": written_files, "analysis": analysis,
            "reflection": reflection, "metacognition": metacog, "patterns": patterns,
            "experience_count": len(self.memory.experiences),
            "postcheck": postcheck_report,
            "postcheck_fixes": postcheck_fixes,
            "truncated": truncated,
            "missing_files": missing_files,
            "manifest": execution.get("manifest", []),
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
            ev, issues, suggestions = {}, [], []

        # Raíz del proyecto: en modo fix sobre disco es el output_base_dir; si no,
        # el ancestro común de los archivos escritos.
        if self.file_writer.root_is_output_dir:
            project_dir: Optional[Path] = Path(self.file_writer.output_base_dir)
        else:
            project_dir = next((Path(f).parent for f in code_files if Path(f).exists()), None)
        if not project_dir or not project_dir.is_dir():
            return {"success": False, "files_fixed": [], "error": "Directorio no encontrado"}

        # ── 1) Completar archivos faltantes (manifiesto + referencias rotas) ──────
        plan = result.get("plan", "") or ev.get("plan", "")
        manifest = result.get("manifest", []) or ev.get("manifest", [])
        missing = list(result.get("missing_files", []) or ev.get("missing_files", []))
        report = analyze_project(project_dir)
        for ref in report.get("missing_refs", []):
            if ref not in missing:
                missing.append(ref)

        completed_files = []
        if missing:
            _dbg.log("FIX", f"completando {len(missing)} archivo(s) faltante(s): {missing}")
            completed_files = self.complete_missing(task, plan, manifest, missing, project_dir)

        # ── 2) Corrección de calidad sobre issues reportados ─────────────────────
        # (los strings de 'archivo faltante' ya se atendieron arriba; filtrarlos)
        quality_issues = [i for i in issues
                          if "no se generaron" not in i and "se truncó" not in i]
        fixed_files = []
        if quality_issues or suggestions:
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
Problemas: {chr(10).join(f'- {i}' for i in quality_issues) or '- Ver sugerencias'}
Sugerencias: {chr(10).join(f'- {s}' for s in suggestions) or '- Revisar buenas prácticas'}
{self._rules_block()}
Archivos actuales:
{chr(10).join(file_blocks)}

Reescribe SOLO los archivos con problemas. Formato: ### archivo: ruta/archivo.ext
"""
            _dbg.log("FIX", f"code_files={len(code_files)}  issues={quality_issues}  suggestions={suggestions}")
            lang = get_language_instruction()
            self._progress("REVISIÓN")
            response = self.client.chat(
                prompt,
                system_prompt=f"Eres un senior developer. Corriges código de forma precisa y completa. Sin placeholders. {lang}",
                temperature=0.2, max_tokens=8192,
                auto_continue=True, max_continuations=4,
            )
            if response.get("success"):
                for filename, code in self.file_writer._extract_named_blocks(response["content"]):
                    safe = [p for p in Path(filename.lstrip("/")).parts if p not in ("..", ".", "~", "/")]
                    if not safe:
                        continue
                    filepath = project_dir.joinpath(*safe)
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    filepath.write_text(code, encoding="utf-8")
                    fixed_files.append(str(filepath))
                    self._on_file(str(filepath))

        # ── 3) Re-evaluación honesta contra lo que quedó en disco ────────────────
        self._progress("RE-EVALUANDO")
        on_disk = [str(p) for p in project_dir.rglob("*")
                   if p.is_file() and ".deep" not in p.parts and not p.name.startswith(".")]
        success, new_outcome = self._evaluate(task, plan, {"code": ""}, written_files=on_disk)

        # Si todavía hay referencias rotas, el fix no terminó: fail honesto.
        report2 = analyze_project(project_dir)
        if report2.get("missing_refs"):
            success = False
            try:
                eo = json.loads(new_outcome)
            except Exception:
                eo = {"raw": new_outcome}
            eo["success"] = False
            eo["missing_refs"] = report2["missing_refs"]
            new_outcome = json.dumps(eo)

        deep_dir = project_dir / ".deep"
        if deep_dir.is_dir() or self.file_writer.root_is_output_dir:
            deep_dir.mkdir(exist_ok=True)
            try:
                eval_data = json.loads(new_outcome)
            except Exception:
                eval_data = {"raw": new_outcome}
            eval_data["fixed_files"] = fixed_files
            eval_data["completed_files"] = completed_files
            (deep_dir / "evaluation.json").write_text(
                json.dumps(eval_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        _dbg.log("FIX", f"DONE  success={success}  fixed={len(fixed_files)}  completed={len(completed_files)}")
        return {
            "success": success,
            "files_fixed": fixed_files,
            "files_completed": completed_files,
            "outcome": new_outcome,
        }

    def complete_missing(self, task: str, plan: str, manifest_paths: List[str],
                         missing_paths: List[str], project_dir: Path) -> List[str]:
        """Genera y escribe los archivos faltantes (uno por llamada). Devuelve las
        rutas creadas. Reusa el generador por-archivo del modo manifiesto."""
        project_dir = Path(project_dir)
        manifest_paths = manifest_paths or missing_paths
        created = []
        total = len(missing_paths)
        for idx, path in enumerate(missing_paths, 1):
            self._progress(f"COMPLETANDO {idx}/{total}  {path}")
            content, truncated, _ = self._generate_file(
                task, plan, manifest_paths, path, purpose="archivo referenciado por el resto del proyecto")
            if not content.strip():
                _dbg.log("FIX", f"  ✗ {path} — no se pudo generar")
                continue
            safe = [p for p in Path(path.lstrip("/")).parts if p not in ("..", ".", "~", "/")]
            if not safe:
                continue
            filepath = project_dir.joinpath(*safe)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")
            created.append(str(filepath))
            self._on_file(str(filepath))
            _dbg.log("FIX", f"  ✓ {path}  ({len(content)} chars)")
        return created

    def execute_update(self, change: str, task: str) -> Dict:
        _dbg.log("UPDATE", f"change={change[:120]}")
        project_dir = Path(self.file_writer.output_base_dir)

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

        lang = get_language_instruction()
        self._progress("ANALIZANDO")
        docker_extra = ""
        if any(w in change.lower() for w in ("docker", "dockerizar", "dockerize", "container", "compose")):
            docker_extra = DOCKER_NPM + UPDATE_DOCKER_HINT

        prompt = (
            f"Proyecto actual: {task}\n\n"
            f"Archivos existentes:\n{''.join(file_blocks)}\n\n"
            f"Cambio solicitado: {change}\n"
            f"{self._rules_block()}"
            f"{docker_extra}\n"
            "Devolvé SOLO los archivos modificados o nuevos con el formato:\n"
            "### archivo: ruta/archivo.ext\n"
            "Código completo. Sin placeholders ni '...'."
        )
        response = self.client.chat(
            prompt,
            system_prompt=(
                f"Eres un senior developer. Modificás proyectos existentes con cambios precisos y código completo. "
                f"{lang}"
            ),
            temperature=0.3, max_tokens=8192,
            auto_continue=True, max_continuations=4,
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

        _, postcheck_fixes, postcheck_report = self._run_postcheck(
            {"heuristic_issues": [], "structural_ok": True, "files_count": len(updated_files)},
            response_text=response.get("content", ""),
        )
        return {
            "success": True,
            "files_updated": updated_files,
            "postcheck": postcheck_report,
            "postcheck_fixes": postcheck_fixes,
        }

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
        lang = get_language_instruction()
        response = self.client.chat(
            f"Crea un plan detallado para:\n{task}\n{context}\n{self._rules_block()}\n"
            "Incluye: arquitectura, archivos a crear (rutas relativas), dependencias, posibles problemas.",
            system_prompt=f"Eres un arquitecto de software senior. Creas planes claros y accionables. {lang}",
            temperature=0.5, max_tokens=10000,
        )
        return response["content"]

    def _execute(self, task: str, plan: str, manifest_mode: bool = False) -> Dict:
        """Genera el código. Con manifest_mode, primero pide el manifiesto de archivos
        y, si el proyecto es grande, genera archivo por archivo (no se trunca)."""
        if not manifest_mode:
            return self._execute_single_shot(task, plan)

        self._progress("MANIFIESTO")
        files = self._build_manifest(task, plan)
        _dbg.log("MANIFEST", f"files={len(files)}  paths={[f['path'] for f in files]}")

        # Proyecto chico o manifiesto vacío → un solo tiro (con auto-continuación ya
        # no se trunca y ahorramos N llamadas).
        if len(files) <= self.SINGLE_SHOT_MAX_FILES:
            _dbg.log("MANIFEST", f"≤{self.SINGLE_SHOT_MAX_FILES} archivos → single-shot")
            out = self._execute_single_shot(task, plan)
            out["manifest"] = [f["path"] for f in files]
            return out

        return self._execute_by_manifest(task, plan, files)

    def _execute_single_shot(self, task: str, plan: str) -> Dict:
        lang = get_language_instruction()
        docker_extra = ""
        if any(w in task.lower() for w in ("docker", "dockerizar", "dockerize", "container", "compose")):
            docker_extra = DOCKER_NPM
        response = self.client.chat(
            f"IMPLEMENTA este plan generando TODOS los archivos.\n\nTarea: {task}\nPlan:\n{plan}\n"
            f"{self._rules_block()}"
            f"{BUILD_COMPLETENESS}"
            f"{docker_extra}\n"
            "FORMATO: antes de cada bloque escribe ### archivo: ruta/archivo.ext\n"
            "Código completo y funcional. Sin '...' ni placeholders.",
            system_prompt=f"Eres un desarrollador senior. Código limpio, completo. Siempre indicás el nombre del archivo. {lang}",
            temperature=0.3, max_tokens=8192,
            auto_continue=True, max_continuations=6,
        )
        tokens = response.get("tokens", {}).get("total_tokens", 0)
        truncated = response.get("truncated", False)
        _dbg.log("EXEC", f"response_success={response.get('success')}  tokens={tokens}  "
                 f"truncated={truncated}  continuations={response.get('continuations', 0)}")
        return {
            "code": response["content"],
            "tokens_used": tokens,
            "truncated": truncated,
        }

    def _build_manifest(self, task: str, plan: str) -> List[Dict]:
        """Pide al modelo la lista explícita de archivos a crear (JSON)."""
        lang = get_language_instruction()
        response = self.client.chat(
            f"Tarea: {task}\n\nPlan:\n{plan}\n{self._rules_block()}\n{MANIFEST_INSTRUCTIONS}",
            system_prompt=f"Eres un arquitecto de software. Respondés SOLO con JSON válido. {lang}",
            temperature=0.2, max_tokens=4000, auto_continue=True, max_continuations=2,
        )
        raw = (response.get("content") or "").strip()
        raw = re.sub(r"```json\n?|```\n?", "", raw).strip()
        try:
            data = json.loads(raw)
            files = data.get("files", []) if isinstance(data, dict) else data
        except Exception as e:
            _dbg.log("MANIFEST", f"json_parse_failed={e}  raw={raw[:200]}")
            return []

        seen, clean = set(), []
        for f in files:
            if isinstance(f, str):
                f = {"path": f, "purpose": ""}
            path = str(f.get("path", "")).strip().lstrip("/")
            if not path or path in seen or ".." in Path(path).parts:
                continue
            seen.add(path)
            clean.append({"path": path, "purpose": str(f.get("purpose", "")).strip()})
        return clean

    def _generate_file(self, task: str, plan: str, manifest_paths: List[str],
                       path: str, purpose: str) -> Tuple[str, bool, int]:
        """Genera el contenido de un único archivo. Devuelve (contenido, truncado, tokens)."""
        lang = get_language_instruction()
        instr = FILE_GEN_INSTRUCTIONS.format(path=path, purpose=purpose or "(sin descripción)")
        response = self.client.chat(
            f"Tarea global: {task}\n\n"
            f"Plan (resumen):\n{plan[:1800]}\n{self._rules_block()}\n"
            f"Manifiesto del proyecto (todos los archivos que existen):\n"
            + "\n".join(f"  - {p}" for p in manifest_paths)
            + f"\n\n{instr}",
            system_prompt=f"Eres un desarrollador senior. Generás un archivo completo y funcional. {lang}",
            temperature=0.3, max_tokens=8192, auto_continue=True, max_continuations=4,
        )
        tokens = response.get("tokens", {}).get("total_tokens", 0)
        if not response.get("success"):
            return "", True, tokens
        content = response["content"]
        # Si el modelo igual usó el formato "### archivo:" o envolvió en fences, lo limpiamos.
        blocks = self.file_writer._extract_named_blocks(content)
        if blocks:
            content = blocks[0][1]
        else:
            content = self.file_writer._strip_outer_fence(content)
        return content.strip("\n"), response.get("truncated", False), tokens

    def _execute_by_manifest(self, task: str, plan: str, files: List[Dict]) -> Dict:
        """Genera el proyecto archivo por archivo según el manifiesto. No se trunca:
        cada archivo es una llamada independiente (con auto-continuación)."""
        manifest_paths = [f["path"] for f in files]
        total = len(files)
        parts, missing = [], []
        tokens_total = 0
        any_truncated = False

        for idx, f in enumerate(files, 1):
            path, purpose = f["path"], f["purpose"]
            self._progress(f"GENERANDO {idx}/{total}  {path}")
            content, truncated, tokens = self._generate_file(
                task, plan, manifest_paths, path, purpose)
            tokens_total += tokens
            if not content.strip():
                _dbg.log("MANIFEST", f"  ✗ {path} — generación vacía")
                missing.append(path)
                continue
            if truncated:
                any_truncated = True
                _dbg.log("MANIFEST", f"  ⚠ {path} — truncado aun con continuaciones")
            _dbg.log("MANIFEST", f"  ✓ {path}  ({len(content)} chars)")
            # Formato que entiende el writer: "### archivo: ruta" + contenido crudo.
            parts.append(f"### archivo: {path}\n{content}\n")

        code = "\n".join(parts)
        _dbg.log("EXEC", f"manifest mode: generated={len(parts)}/{total}  "
                 f"missing={len(missing)}  truncated={any_truncated}")
        return {
            "code": code,
            "tokens_used": tokens_total,
            "truncated": any_truncated,
            "missing_files": missing,
            "manifest": manifest_paths,
        }

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

    def _run_postcheck(self, heuristics: Dict, response_text: str = "") -> Tuple[Dict, List[str], Dict]:
        project_dir = self.file_writer.last_project_dir
        if not project_dir and self.file_writer.root_is_output_dir:
            project_dir = self.file_writer.output_base_dir
        if not project_dir:
            return heuristics, [], {"issues": [], "warnings": [], "ok": True}

        self._progress("VALIDANDO")
        report = analyze_project(Path(project_dir), response_text or None)
        fixes = apply_remediations(Path(project_dir), report)
        if fixes:
            report = analyze_project(Path(project_dir), response_text or None)
        return merge_into_heuristics(heuristics, report), fixes, report

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

    def _persist_context(self, task: str, plan: str, success: bool, outcome: str,
                         manifest: List[str] = None):
        deep_dir = self.file_writer.last_project_dir / ".deep"
        deep_dir.mkdir(exist_ok=True)
        (deep_dir / "context.json").write_text(
            json.dumps({"task": task, "plan": plan, "model": self.client.model,
                        "manifest": manifest or [],
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
