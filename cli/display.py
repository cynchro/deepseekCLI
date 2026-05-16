import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import core.balance as bal


def _credit_bar(pct: int, width: int = 24) -> str:
    filled = int(width * pct / 100)
    color = "\033[92m" if pct > 50 else ("\033[93m" if pct > 20 else "\033[91m")
    return f"{color}{'█' * filled}{'░' * (width - filled)}\033[0m"


def show_balance(api_key: str, label: str = "Crédito DeepSeek",
                 before: Optional[Dict] = None, tokens: int = 0) -> Dict:
    """Consulta, muestra el saldo y retorna snapshot para comparar después."""
    data = bal.fetch(api_key)
    if "error" in data:
        print(f"   ⚠️  No se pudo consultar el saldo: {data['error']}")
        return {}

    infos = data.get("balance_infos", [])
    if not infos:
        print("   ⚠️  Respuesta de balance vacía.")
        return {}

    ref = bal.get_ref()
    ref_updated = False
    result_snapshot = {}

    print(f"\n💳 {label}")
    for info in infos:
        currency = info.get("currency", "?")
        total = float(info.get("total_balance", 0))
        granted = float(info.get("granted_balance", 0))
        topped = float(info.get("topped_up_balance", 0))
        ref_key = f"max_{currency}"
        if total > ref.get(ref_key, 0.0):
            ref[ref_key] = total
            ref_updated = True
        ref_max = ref.get(ref_key, total) or total
        pct = int(total / ref_max * 100) if ref_max > 0 else 0
        print(f"   {_credit_bar(pct)} {pct:3d}%  {total:.4f} {currency}")
        print(f"   Bonificado: {granted:.4f}  |  Recargado: {topped:.4f}")
        if before:
            prev = before.get(currency, {}).get("total")
            if prev is not None and prev - total > 0:
                print(f"   Costo esta corrida: -{prev - total:.6f} {currency}")
        result_snapshot[currency] = {"total": total, "granted": granted, "topped": topped}

    if tokens:
        print(f"   Tokens usados (sesión): {tokens:,}")
    if ref_updated:
        bal.save_ref(ref)
    return result_snapshot


def show_files(files: List[str], title: str = "✅ Archivos creados:"):
    visible = [f for f in files if ".deep" not in Path(f).parts]
    if not visible:
        return
    print(title)
    for f in visible:
        try:
            display = "~/" + str(Path(f).relative_to(Path.home()))
        except ValueError:
            display = f
        print(f"   {display}")


def show_evaluation(result: Dict):
    if result.get("success"):
        print("\n✅ Evaluación: código aprobado.")
        return
    print("\n⚠️  Evaluación: puede necesitar ajustes.")
    try:
        ev = json.loads(result.get("outcome", "{}"))
        score = ev.get("overall_score")
        if score:
            print(f"   Score: {score}/10")
        for issue in ev.get("issues", []):
            print(f"   • {issue}")
        for s in ev.get("suggestions", []):
            print(f"   → {s}")
    except Exception:
        pass


def show_project_summary(project_dir: Path, ctx: Dict, evaluation: Dict):
    task = ctx.get("task", "Desconocido")
    model = ctx.get("model", "?")
    timestamp = ctx.get("timestamp", "")
    date_str = ""
    if timestamp:
        try:
            date_str = datetime.fromisoformat(timestamp).strftime("%d/%m/%Y %H:%M")
        except Exception:
            date_str = timestamp[:16]
    files = [f for f in project_dir.rglob("*")
             if f.is_file() and ".deep" not in f.parts and not f.name.startswith(".")]
    score = evaluation.get("overall_score")
    if evaluation.get("success") is True:
        status = f"✅ Aprobado{f'  (score {score}/10)' if score else ''}"
    elif evaluation.get("success") is False:
        status = f"⚠️  Necesita ajustes{f'  (score {score}/10)' if score else ''}"
    else:
        status = "❓ Sin evaluar"

    W = 56
    print("\n" + "─" * W)
    print(f"📁 {project_dir}")
    print("─" * W)
    short = task[:W - 12]
    print(f"  Tarea:    {short}{'…' if len(task) > len(short) else ''}")
    print(f"  Modelo:   {model}")
    if date_str:
        print(f"  Fecha:    {date_str}")
    print(f"  Archivos: {len(files)}")
    print(f"  Estado:   {status}")
    for issue in evaluation.get("issues", [])[:3]:
        print(f"  • {issue[:W - 4]}")
    print("─" * W)


def show_history(experiences: List[Dict]):
    if not experiences:
        print("   Sin experiencias acumuladas todavía.")
        return
    print(f"\n📚 Historial ({len(experiences)} experiencias)\n")
    for i, exp in enumerate(experiences[-20:], 1):
        icon = "✅" if exp.get("success") else "❌"
        task = exp.get("task", "")[:55]
        lesson = exp.get("lesson", "")[:60]
        ts = exp.get("timestamp", "")[:10]
        print(f"  {i:2}. {icon} [{ts}] {task}")
        if lesson:
            print(f"       → {lesson}")
    print()
