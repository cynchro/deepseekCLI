import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import core.debug as _dbg
from core.build_state import BuildState
from core.client import DeepSeekClient
from core.context_builder import (
    build_generation_context,
    is_scaffold_file,
    is_trivial_file,
    normalize_path,
)
from core.memory import DeepSeekMemory
from core.agent import ReflectiveAgent
from core.models import MODEL_FLASH, MODEL_PRO
from core.planner import (
    PLAN_SYSTEM,
    build_plan_prompt,
    build_replan_prompt,
    merge_plan,
    normalize_plan,
    parse_json_response,
    plan_summary,
    summarize_written_files,
)
from core.writer import FileWriter


_GEN_SYSTEM = (
    "Eres un desarrollador senior. Generás UN solo archivo completo, listo para producción. "
    "Sin explicaciones, sin markdown, sin bloques ```, sin placeholders, sin TODOs. "
    "Salida: solo el código crudo del archivo."
)

_REVIEW_SYSTEM = (
    "Eres un revisor de código estricto y preciso. Encontrás problemas reales con línea y fix concreto. "
    "Respondés ÚNICAMENTE con JSON válido, sin markdown."
)

_PATCH_SYSTEM = (
    "Eres un desarrollador senior. Reescribís el archivo COMPLETO corrigiendo todos los issues. "
    "Sin explicaciones, sin markdown, sin placeholders. Solo código crudo del archivo."
)

_FINAL_REVIEW_SYSTEM = (
    "Eres un arquitecto de software que evalúa integración global del proyecto. "
    "Enfocate en consistencia entre archivos, piezas faltantes e issues de integración. "
    "Evaluá SOLO contra lo que la tarea pide explícitamente: NO exijas ni bajes el score "
    "por requisitos no solicitados (LICENSE, CI/CD, Dockerfile, tests, type hints, "
    "linters, docs extra) salvo que la tarea los mencione. Penalizá únicamente bugs "
    "reales, código roto o incumplimiento de lo pedido, no mejoras opcionales. "
    "Respondé SOLO con JSON válido."
)

REPLAN_EVERY_N = 3
MAX_RETRIES_PER_FILE = 2
PARALLEL_MAX_WORKERS = 4


class DeepSeekLearningSystem:
    def __init__(self, api_key: str = None, output_dir: str = "output",
                 model: str = "deepseek-chat", root_is_output_dir: bool = False,
                 rules: List[str] = None,
                 on_progress: Callable[[str], None] = None,
                 on_file: Callable[[str], None] = None,
                 reflect: bool = False,
                 project_name: str = "",
                 replan_interval: int = REPLAN_EVERY_N):
        self._on_progress = on_progress or (lambda msg: None)
        self._on_file = on_file or (lambda path: None)
        self.reflect = reflect
        self.replan_interval = replan_interval
        self._api_lock = threading.Lock()
        self.client = DeepSeekClient(api_key, model=model)
        self.memory = DeepSeekMemory(self.client, model=MODEL_PRO)
        self.reflective_agent = ReflectiveAgent(self.client, model=MODEL_PRO)
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
        _dbg.log("SYSTEM", f"workflow=iterative  pro={MODEL_PRO}  flash={MODEL_FLASH}")

        self._progress("FASE 1 — plan")
        _dbg.log("PHASE", "1 — planificación estructurada")
        plan = self._plan_structured(task)
        _dbg.log_json("PHASE_1", "plan", plan)

        self._progress("FASE 2 — generación por archivo")
        _dbg.log("PHASE", "2 — ejecución iterativa")
        project_dir = self.file_writer.init_project_dir(task)
        self.file_writer.save_plan(project_dir, plan)
        execution = self._execute_iterative(task, plan, project_dir)
        plan = execution.get("plan", plan)
        written_files = execution["files_written"]
        _dbg.log("PHASE_2", f"files_written={len(written_files)}  tokens={execution.get('tokens_used', 0)}")

        self.file_writer.save_build_log(project_dir, execution.get("build_log", ""))
        if execution.get("build_state"):
            self.file_writer.save_build_state(project_dir, execution["build_state"])

        heuristics = self._heuristic_check(written_files, task)
        _dbg.log_json("PHASE_3", "heuristics", heuristics)

        self._progress("FASE 4 — revisión final")
        _dbg.log("PHASE", "4 — evaluación global")
        success, outcome = self._final_review(task, plan, written_files, heuristics)
        _dbg.log("PHASE_4", f"success={success}  structural_ok={heuristics.get('structural_ok')}")

        if not success and heuristics.get("structural_ok"):
            try:
                ev = json.loads(outcome)
                ev["heuristic_override"] = True
                ev["heuristic_note"] = (
                    "Estructura completa según análisis en disco; fallo del evaluador puede ser falso negativo."
                )
                outcome = json.dumps(ev)
                _dbg.log("HEURISTIC", "override aplicado: estructura ok, LLM dice failure")
            except Exception:
                pass

        _dbg.log_block("PHASE_4", "evaluation_outcome", outcome)

        self._progress("FASE 5 — aprendizaje")
        _dbg.log("PHASE", "5 — análisis de experiencia / memoria")
        plan_text = plan_summary(plan)
        analysis = self.memory.analyze_experience(
            context=task, action=plan_text, result=outcome, success=success
        )
        _dbg.log_json("PHASE_5", "experience_analysis", analysis)
        experience = {
            "task": task, "plan": plan_text[:200], "execution": execution.get("summary", "")[:200],
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
            reflection = self.reflective_agent.deep_reflection(
                task=task, plan=plan_text, execution=execution.get("summary", ""),
                outcome=outcome, success=success
            )
            if len(self.memory.experiences) % 5 == 0:
                self._progress("FASE 7")
                metacog = self.reflective_agent.metacognition(self.memory.experiences)
            if len(self.memory.experiences) % 5 == 0:
                self._progress("FASE 8")
                patterns = self.memory.extract_patterns(self.memory.experiences)

        if self.file_writer.last_project_dir:
            self._persist_context(task, plan, success, outcome)

        _dbg.log("SYSTEM", f"execute_and_learn DONE  success={success}  files={len(written_files)}")
        return {
            "success": success,
            "plan": plan_text[:200],
            "plan_structured": plan,
            "outcome": outcome,
            "files_written": written_files,
            "analysis": analysis,
            "reflection": reflection,
            "metacognition": metacog,
            "patterns": patterns,
            "experience_count": len(self.memory.experiences),
            "tokens_used": execution.get("tokens_used", 0),
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
        self._progress("REVISIÓN")
        response = self._chat(
            prompt,
            system_prompt="Eres un senior developer. Corriges código de forma precisa y completa. Sin placeholders.",
            temperature=0.2, max_tokens=8000,
            model_override=MODEL_FLASH,
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
        plan_raw = result.get("plan_structured") or result.get("plan", "")
        success, new_outcome = self._final_review(
            task, plan_raw if isinstance(plan_raw, dict) else {"architecture": str(plan_raw)},
            [str(f) for f in code_files],
        )

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
        _dbg.log("UPDATE", f"change={change[:120]}")
        from core.project_scanner import scan, select_relevant_files

        project_dir = Path(self.file_writer.output_base_dir)

        # Contexto del proyecto: mapa + resumen (del cache de scan, o se escanea ahora).
        pmap, summary = self._load_project_context(project_dir)
        if not pmap:
            pmap = scan(project_dir)

        selected, target_subs = select_relevant_files(project_dir, pmap, change)
        scope = (
            f"Componente afectado: {', '.join(target_subs)}. "
            "Modificá SOLO archivos dentro de ese componente.\n"
            if target_subs else
            "Cambio sin componente específico: tocá solo lo necesario.\n"
        )
        self._progress(
            f"ANALIZANDO ({len(selected)} archivos relevantes"
            + (f" en {', '.join(target_subs)}" if target_subs else "") + ")"
        )

        file_blocks = []
        for f in selected:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                rel = f.relative_to(project_dir)
                file_blocks.append(f"### archivo: {rel}\n```\n{text[:2500]}\n```")
            except Exception:
                pass

        summary_block = f"Resumen del proyecto:\n{summary}\n\n" if summary else ""
        prompt = (
            f"Proyecto actual: {task}\n\n"
            f"{summary_block}"
            f"Estructura ({pmap.get('kind', '?')}): "
            f"{', '.join(s['path'] for s in pmap.get('subprojects', [])) or 'raíz'}\n\n"
            f"{scope}"
            f"Archivos relevantes:\n{''.join(file_blocks)}\n\n"
            f"Cambio solicitado: {change}\n"
            f"{self._rules_block()}\n"
            "Respetá la estructura, convenciones y stack existentes. "
            "Devolvé SOLO los archivos modificados o nuevos con el formato:\n"
            "### archivo: ruta/archivo.ext\n"
            "Código completo. Sin placeholders ni '...'."
        )
        response = self._chat(
            prompt,
            system_prompt="Eres un senior developer. Modificás proyectos existentes con cambios precisos y código completo.",
            temperature=0.3, max_tokens=8000,
            model_override=MODEL_FLASH,
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

    def _load_project_context(self, project_dir: Path) -> Tuple[Optional[Dict], str]:
        """Lee el mapa y el resumen cacheados por `scan` (.deep/context.json)."""
        ctx_file = project_dir / ".deep" / "context.json"
        if not ctx_file.exists():
            return None, ""
        try:
            ctx = json.loads(ctx_file.read_text(encoding="utf-8"))
        except Exception:
            return None, ""
        return ctx.get("project_map"), ctx.get("summary", "")

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

    # ── workflow iterativo adaptativo ─────────────────────────────────────────

    def _chat(self, prompt: str, **kwargs) -> Dict:
        with self._api_lock:
            return self.client.chat(prompt, **kwargs)

    def _inject_state(self, prompt: str, build_state: Optional[BuildState]) -> str:
        if not build_state:
            return prompt
        parts = [prompt]
        state_block = build_state.format_state_block()
        mistakes_block = build_state.format_mistakes_block()
        if state_block:
            parts.append(state_block)
        if mistakes_block:
            parts.append(mistakes_block)
        return "\n\n".join(parts)

    def _plan_structured(self, task: str, build_state: Optional[BuildState] = None) -> Dict:
        similar = self.memory._find_similar(task)
        _dbg.log("PLAN", f"similar_experiences_found={len(similar)}")
        experience_context = ""
        if similar:
            experience_context = "\nExperiencias previas relevantes:\n" + "\n".join(
                f"- {'Éxito' if e['success'] else 'Fracaso'}: {e['lesson'][:100]}"
                for e in similar[:3]
            )
        prompt = build_plan_prompt(task, self._rules_block(), experience_context)
        if build_state:
            prompt = self._inject_state(prompt, build_state)
        response = self._chat(
            prompt,
            system_prompt=PLAN_SYSTEM,
            temperature=0.3,
            max_tokens=8000,
            model_override=MODEL_PRO,
        )
        if not response.get("success"):
            raise RuntimeError(f"Planificación falló: {response.get('content', '')[:200]}")
        try:
            raw_plan = parse_json_response(response["content"])
            plan = normalize_plan(raw_plan)
            if build_state:
                build_state.absorb_plan(plan)
            return plan
        except (json.JSONDecodeError, ValueError) as e:
            _dbg.log("PLAN", f"parse_error={e}")
            raise RuntimeError(f"No se pudo parsear el plan JSON: {e}") from e

    def _replan(self, plan: Dict, written_paths: Dict[str, Path],
                task: str, build_state: BuildState) -> Dict:
        _dbg.log("REPLAN", f"triggered  completed={len(written_paths)}")
        summary = summarize_written_files(written_paths, plan)
        prompt = build_replan_prompt(
            plan, summary, task, build_state.format_state_block()
        )
        response = self._chat(
            prompt,
            system_prompt=PLAN_SYSTEM,
            temperature=0.2,
            max_tokens=8000,
            model_override=MODEL_PRO,
        )
        if not response.get("success"):
            _dbg.log("REPLAN", "API falló — se mantiene plan actual")
            return plan
        try:
            updated = parse_json_response(response["content"])
            merged = merge_plan(plan, updated, list(written_paths.keys()))
            build_state.absorb_plan(merged)
            return merged
        except (json.JSONDecodeError, ValueError) as e:
            _dbg.log("REPLAN", f"parse_error={e}")
            return plan

    def _execute_iterative(self, task: str, plan: Dict, project_dir: Path) -> Dict:
        build_state = BuildState()
        build_state.absorb_rules(self.rules)
        build_state.absorb_plan(plan)

        written_paths: Dict[str, Path] = {}
        written_files: List[str] = []
        failed_paths: set = set()
        log_entries: List[str] = []
        tokens_total = 0
        files_since_replan = 0
        paths_lock = threading.Lock()

        def file_map():
            return {f["path"]: f for f in plan["files"]}

        def pending_in_pass(paths: List[str]) -> List[str]:
            fm = file_map()
            return [
                p for p in paths
                if p not in written_paths and p not in failed_paths and p in fm
                and all(d in written_paths for d in fm[p].get("depends_on", []))
            ]

        fm = file_map()
        scaffold_paths = [p for p in plan["order"] if p in fm and is_scaffold_file(fm[p])]
        impl_paths = [p for p in plan["order"] if p in fm and p not in scaffold_paths]
        passes: List[Tuple[str, List[str], bool]] = []
        if scaffold_paths:
            passes.append(("scaffold", scaffold_paths, True))
        passes.append(("implement", impl_paths or list(plan["order"]), False))

        total = len(plan["order"])
        done = 0

        for pass_name, pass_paths, scaffold_mode in passes:
            while True:
                pending = pending_in_pass(pass_paths)
                if not pending:
                    break

                if files_since_replan >= self.replan_interval and written_paths:
                    self._progress("RE-PLAN")
                    plan = self._replan(plan, written_paths, task, build_state)
                    self.file_writer.save_plan(project_dir, plan)
                    fm = file_map()
                    scaffold_paths = [p for p in plan["order"] if p in fm and is_scaffold_file(fm[p])]
                    impl_paths = [p for p in plan["order"] if p in fm and p not in scaffold_paths]
                    if pass_name == "scaffold":
                        pass_paths = scaffold_paths
                    else:
                        pass_paths = impl_paths or list(plan["order"])
                    files_since_replan = 0
                    log_entries.append(
                        f"## REPLAN (after {done} files)\n"
                        f"- remaining: {len(plan['order']) - len(written_paths)}\n"
                    )
                    pending = pending_in_pass(pass_paths)
                    if not pending:
                        break

                zero_dep = [p for p in pending if not fm[p].get("depends_on")]
                batch = zero_dep if len(zero_dep) > 1 else [pending[0]]

                if len(batch) > 1:
                    self._progress(f"PARALELO {len(batch)} archivos sin deps")
                    batch_results = self._run_parallel_batch(
                        task, plan, project_dir, batch, fm, written_paths,
                        build_state, scaffold_mode, pass_name, paths_lock,
                    )
                else:
                    batch_results = [self._process_file(
                        task, plan, project_dir, batch[0], fm[batch[0]],
                        written_paths, build_state, scaffold_mode, pass_name,
                    )]

                for result in batch_results:
                    done += 1
                    tokens_total += result["tokens"]
                    log_entries.append(self._format_log_entry(result["log"]))
                    if result.get("failed"):
                        with paths_lock:
                            failed_paths.add(result["path"])
                        self._progress(f"{done}/{total}  ⚠️  {result['path']} (falló, se continúa)")
                        continue
                    with paths_lock:
                        written_paths[result["path"]] = Path(result["filepath"])
                        if result["filepath"] not in written_files:
                            written_files.append(result["filepath"])
                    files_since_replan += 1
                    self._progress(f"{done}/{total}  {result['path']}")

        if failed_paths:
            log_entries.append(
                f"## FAILED FILES ({len(failed_paths)})\n"
                + "\n".join(f"- {p}" for p in sorted(failed_paths))
            )

        return {
            "files_written": written_files,
            "failed_files": sorted(failed_paths),
            "tokens_used": tokens_total,
            "build_log": "\n".join(log_entries),
            "build_state": build_state.to_dict(),
            "plan": plan,
            "summary": (
                f"adaptive build: {len(written_files)} files, "
                f"{len(failed_paths)} failed, "
                f"{tokens_total} tokens, {len(build_state.mistakes)} mistakes tracked"
            ),
        }

    def _run_parallel_batch(
        self, task, plan, project_dir, batch, fm, written_paths,
        build_state, scaffold_mode, pass_name, paths_lock,
    ) -> List[Dict]:
        results = []
        with ThreadPoolExecutor(max_workers=min(PARALLEL_MAX_WORKERS, len(batch))) as pool:
            futures = {
                pool.submit(
                    self._process_file,
                    task, plan, project_dir, path, fm[path],
                    dict(written_paths), build_state, scaffold_mode, pass_name,
                ): path
                for path in batch
            }
            for fut in as_completed(futures):
                path = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    _dbg.log("AGENT", f"future_failed  file={path}  error={e}")
                    results.append(self._failed_file_result(path, "?", str(e)))
        return results

    @staticmethod
    def _failed_file_result(path: str, pass_name: str, error: str) -> Dict:
        return {
            "path": path,
            "filepath": None,
            "tokens": 0,
            "log": {
                "path": path,
                "pass": pass_name,
                "review": f"FAILED: {error[:120]}",
                "severity": "high",
                "retries": 0,
                "replan": False,
            },
            "failed": True,
        }

    def _process_file(
        self, task: str, plan: Dict, project_dir: Path,
        rel_path: str, entry: Dict,
        written_paths: Dict[str, Path],
        build_state: BuildState,
        scaffold_mode: bool,
        pass_name: str,
    ) -> Dict:
        _dbg.log("AGENT", f"pass={pass_name}  file={rel_path}")
        try:
            context = build_generation_context(
                task, plan, entry, project_dir, written_paths,
                scaffold_mode=scaffold_mode, build_state=build_state,
            )
            code, tokens = self._generate_file(context, rel_path, build_state)
            filepath = self.file_writer.write_file(project_dir, rel_path, code)

            log = {
                "path": rel_path,
                "pass": pass_name,
                "review": "skipped (trivial)",
                "severity": "-",
                "retries": 0,
                "replan": False,
            }
            extra_tokens = 0

            if not is_trivial_file(rel_path, entry.get("description", "")):
                code, extra_tokens, log = self._apply_review_actions(
                    rel_path, code, entry, task, context, build_state, log,
                )
                filepath = self.file_writer.write_file(project_dir, rel_path, code)

            return {
                "path": rel_path,
                "filepath": str(filepath),
                "tokens": tokens + extra_tokens,
                "log": log,
            }
        except Exception as e:
            # Un fallo en un archivo no debe abortar el build completo.
            _dbg.log("AGENT", f"file_failed  file={rel_path}  error={e}")
            build_state.absorb_review(rel_path, {
                "severity": "high",
                "issues": [{"problem": f"generación falló: {str(e)[:200]}"}],
            })
            return self._failed_file_result(rel_path, pass_name, str(e))

    def _apply_review_actions(
        self, path: str, code: str, entry: Dict, task: str,
        context: str, build_state: BuildState, log: Dict,
    ) -> Tuple[str, int, Dict]:
        extra_tokens = 0
        review, t_rev = self._review_file(path, code, entry, task, build_state)
        extra_tokens += t_rev
        build_state.absorb_review(path, review)

        if not review.get("needs_fix"):
            log["review"] = "ok"
            log["severity"] = review.get("severity", "none")
            return code, extra_tokens, log

        severity = (review.get("severity") or "medium").lower()
        log["severity"] = severity
        issues = review.get("issues", [])

        if severity == "high":
            retries = 0
            while retries < MAX_RETRIES_PER_FILE:
                code, t = self._retry_generation(path, context, issues, task, build_state)
                extra_tokens += t
                retries += 1
                review, t_rev = self._review_file(path, code, entry, task, build_state)
                extra_tokens += t_rev
                build_state.absorb_review(path, review)
                if not review.get("needs_fix") or review.get("severity", "").lower() != "high":
                    break
                issues = review.get("issues", [])
            log["retries"] = retries
            log["review"] = f"retry x{retries} (high)"
        elif severity == "medium":
            code, t = self._patch_file(path, code, issues, task, build_state)
            extra_tokens += t
            log["review"] = "patched (medium)"
        else:
            log["review"] = "accepted (low)"

        return code, extra_tokens, log

    @staticmethod
    def _format_log_entry(log: Dict) -> str:
        lines = [
            f"### {log['path']}",
            f"- pass: {log.get('pass', '?')}",
            f"- review: {log.get('review', '?')}",
        ]
        if log.get("severity") and log["severity"] != "-":
            lines.append(f"- severity: {log['severity']}")
        if log.get("retries"):
            lines.append(f"- retries: {log['retries']}")
        if log.get("replan"):
            lines.append("- replan: yes")
        return "\n".join(lines) + "\n"

    def _generate_file(self, context: str, path: str,
                       build_state: Optional[BuildState] = None) -> Tuple[str, int]:
        prompt = self._inject_state(
            f"{context}\n\nGenerá el contenido COMPLETO de `{path}`. "
            "Salida: solo código crudo del archivo.",
            build_state,
        )
        response = self._chat(
            prompt,
            system_prompt=_GEN_SYSTEM,
            temperature=0.2,
            max_tokens=8192,
            model_override=MODEL_FLASH,
        )
        if not response.get("success"):
            raise RuntimeError(f"Generación falló para {path}: {response.get('content', '')[:200]}")
        tokens = response.get("tokens", {}).get("total_tokens", 0)
        return self._strip_code_response(response["content"]), tokens

    def _retry_generation(
        self, path: str, context: str, issues: List[Dict], task: str,
        build_state: Optional[BuildState] = None,
    ) -> Tuple[str, int]:
        issues_text = json.dumps(issues, ensure_ascii=False, indent=2)
        prompt = self._inject_state(
            f"{context}\n\n"
            f"REGENERÁ desde cero el archivo `{path}` corrigiendo estos problemas críticos:\n"
            f"{issues_text}\n\n"
            f"Tarea: {task[:300]}\n"
            "Salida: solo código crudo completo del archivo.",
            build_state,
        )
        response = self._chat(
            prompt,
            system_prompt=_GEN_SYSTEM,
            temperature=0.25,
            max_tokens=8192,
            model_override=MODEL_FLASH,
        )
        if not response.get("success"):
            return "", 0
        tokens = response.get("tokens", {}).get("total_tokens", 0)
        return self._strip_code_response(response["content"]), tokens

    def _review_file(self, path: str, code: str, file_entry: Dict, task: str,
                     build_state: Optional[BuildState] = None) -> Tuple[Dict, int]:
        prompt = self._inject_state(
            f"""Revisá este archivo de forma estricta y precisa.

Tarea global: {task[:400]}
Archivo: {path}
Descripción esperada: {file_entry.get('description', '')}

CÓDIGO:
```
{code}
```

Respondé SOLO con JSON:
{{
  "needs_fix": true/false,
  "severity": "low|medium|high",
  "issues": [
    {{"line": 1, "problem": "descripción", "fix": "corrección concreta"}}
  ]
}}

severity:
- high: error crítico, archivo inutilizable o rompe integración → debe regenerarse
- medium: problema real pero local → parchear
- low: estilo o mejora menor → aceptar
""",
            build_state,
        )
        response = self._chat(
            prompt,
            system_prompt=_REVIEW_SYSTEM,
            temperature=0.1,
            max_tokens=2000,
            model_override=MODEL_PRO,
        )
        tokens = response.get("tokens", {}).get("total_tokens", 0)
        if not response.get("success"):
            return {"needs_fix": False, "severity": "low", "issues": []}, tokens
        try:
            review = parse_json_response(response["content"])
            review.setdefault("needs_fix", False)
            review.setdefault("severity", "medium" if review["needs_fix"] else "low")
            review.setdefault("issues", [])
            return review, tokens
        except json.JSONDecodeError:
            _dbg.log("REVIEW", f"parse_failed  file={path}")
            return {"needs_fix": False, "severity": "low", "issues": []}, tokens

    def _patch_file(self, path: str, code: str, issues: List[Dict], task: str,
                    build_state: Optional[BuildState] = None) -> Tuple[str, int]:
        issues_text = json.dumps(issues, ensure_ascii=False, indent=2)
        prompt = self._inject_state(
            f"""Reescribí el archivo COMPLETO corrigiendo todos los issues.

Archivo: {path}
Tarea: {task[:300]}

CÓDIGO ACTUAL:
```
{code}
```

ISSUES A CORREGIR:
{issues_text}

Salida: solo el código corregido completo del archivo, sin explicaciones.""",
            build_state,
        )
        response = self._chat(
            prompt,
            system_prompt=_PATCH_SYSTEM,
            temperature=0.2,
            max_tokens=8192,
            model_override=MODEL_FLASH,
        )
        if not response.get("success"):
            return code, 0
        tokens = response.get("tokens", {}).get("total_tokens", 0)
        return self._strip_code_response(response["content"]), tokens

    def _final_review(self, task: str, plan: Dict,
                    written_files: List[str],
                    heuristics: Dict = None) -> Tuple[bool, str]:
        architecture = plan.get("architecture", "") if isinstance(plan, dict) else str(plan)
        planned_paths = [normalize_path(f["path"]) for f in plan.get("files", [])] if isinstance(plan, dict) else []

        file_parts = []
        for fp in written_files[:20]:
            p = Path(fp)
            if ".deep" in p.parts:
                continue
            try:
                rel = p.name
                text = p.read_text(encoding="utf-8")
                from core.context_builder import extract_snippet
                file_parts.append(f"### {rel}\n```\n{extract_snippet(text, max_lines=80)}\n```")
            except Exception:
                pass

        on_disk = [
            normalize_path(str(Path(f).relative_to(self.file_writer.last_project_dir)))
            for f in written_files
            if ".deep" not in Path(f).parts and self.file_writer.last_project_dir
            and Path(f).is_relative_to(self.file_writer.last_project_dir)
        ]
        missing = [p for p in planned_paths if p not in on_disk] if planned_paths else []

        heuristic_note = ""
        if heuristics:
            h_issues = heuristics.get("heuristic_issues", [])
            if h_issues:
                heuristic_note = f"\nProblemas estructurales locales: {'; '.join(h_issues)}\n"

        prompt = f"""EVALUACIÓN GLOBAL DEL PROYECTO

Tarea: {task[:300]}
Arquitectura planificada: {architecture[:800]}
Archivos planificados: {', '.join(planned_paths) if planned_paths else 'N/A'}
Archivos en disco: {', '.join(on_disk) if on_disk else 'N/A'}
Faltantes del plan: {', '.join(missing) if missing else 'ninguno'}
{heuristic_note}

Enfocate en: consistencia entre módulos, integración, piezas faltantes, imports rotos.
Evaluá SOLO contra lo pedido en la tarea. NO restes puntos por requisitos no solicitados
(LICENSE, CI, Docker, tests, type hints, docs). Si el proyecto cumple lo que la tarea pide
y funciona, success=true aunque falten mejoras opcionales.

SNIPPETS:
{chr(10).join(file_parts)}

JSON:
{{"overall_score":1-10,"success":true/false,"issues":[],"positives":[],"suggestions":[]}}
"""
        response = self._chat(
            prompt,
            system_prompt=_FINAL_REVIEW_SYSTEM,
            temperature=0.2,
            max_tokens=2000,
            model_override=MODEL_PRO,
        )
        raw = response.get("content") or ""
        try:
            ev = parse_json_response(raw)
            if missing:
                ev.setdefault("issues", [])
                ev["issues"].insert(0, f"Faltan del plan: {', '.join(missing)}")
                ev["success"] = False
            _dbg.log_json("EVAL", "final_review", ev)
            return ev.get("success", False), json.dumps(ev)
        except Exception as e:
            _dbg.log("EVAL", f"final_review_parse_failed={e}")
            return False, json.dumps({"raw": raw[:300], "parse_error": str(e)})

    @staticmethod
    def _strip_code_response(content: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()
        fence = re.match(r"^```[\w.-]*\n(.*)```\s*$", text, re.DOTALL)
        if fence:
            return fence.group(1).rstrip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 2:
                return "\n".join(lines[1:-1]).rstrip()
        return text

    def _heuristic_check(self, written_files: List[str], task: str) -> Dict:
        issues = []
        names = {Path(f).name for f in written_files if ".deep" not in Path(f).parts}

        _IGNORE_EMPTY = {"__init__.py"}
        _PLACEHOLDER_ONLY = {"pass", "...", "#todo", "# todo", "# placeholder", "todo"}
        for fp in written_files:
            p = Path(fp)
            if ".deep" in p.parts or p.name in _IGNORE_EMPTY:
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

        structural_ok = len(issues) == 0 and len(names) >= 1
        return {
            "heuristic_issues": issues,
            "structural_ok": structural_ok,
            "file_names": sorted(names),
            "files_count": len(names),
        }

    def _persist_context(self, task: str, plan: Dict, success: bool, outcome: str):
        deep_dir = self.file_writer.last_project_dir / ".deep"
        deep_dir.mkdir(exist_ok=True)
        (deep_dir / "context.json").write_text(
            json.dumps({
                "task": task,
                "plan": plan,
                "architecture": plan.get("architecture", ""),
                "model": self.client.model,
                "workflow_models": {"pro": MODEL_PRO, "flash": MODEL_FLASH},
                "workflow": "adaptive_iterative_agent",
                "timestamp": datetime.now().isoformat(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            ev_data = json.loads(outcome)
        except Exception:
            ev_data = {"raw": outcome}
        (deep_dir / "evaluation.json").write_text(
            json.dumps(ev_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
