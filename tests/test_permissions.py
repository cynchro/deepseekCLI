"""Tests de cli.agent_runner.Permissions: el gate de permisos por modo y el ciclo
de vida nuevo de plan mode (set_mode recuerda el modo previo, confirm_plan pregunta
siempre y vuelve a ese modo previo al aprobar)."""
from cli.agent_runner import Permissions


def test_call_denies_everything_in_plan_mode_without_asking():
    asked = []
    perms = Permissions(mode="plan", ask=lambda desc, is_shell, kind="confirm": asked.append(desc) or "s")

    assert perms("escribir a.py (10 chars)") is False
    assert perms("ejecutar: echo hi") is False
    assert asked == []  # nunca llega a preguntar: se deniega por el modo


def test_set_mode_remembers_previous_mode_on_entering_plan():
    perms = Permissions(mode="auto")
    perms.set_mode("plan")
    assert perms.mode == "plan"
    assert perms._pre_plan_mode == "auto"


def test_set_mode_noop_when_same_mode():
    perms = Permissions(mode="auto")
    perms.set_mode("auto")
    assert perms.mode == "auto"
    assert perms._pre_plan_mode is None


def test_set_mode_notifies_on_mode_change_callback():
    changes = []
    perms = Permissions(mode="ask", on_mode_change=changes.append)
    perms.set_mode("yolo")
    assert changes == ["yolo"]


def test_confirm_plan_approved_returns_to_previous_mode_and_notifies():
    notified = []
    changes = []
    perms = Permissions(mode="auto", ask=lambda desc, is_shell, kind="confirm": "s",
                         notify=notified.append, on_mode_change=changes.append)
    perms.set_mode("plan")

    approved = perms.confirm_plan("mi plan")

    assert approved is True
    assert perms.mode == "auto"          # vuelve al modo previo, NO a "ask" fijo
    assert perms._pre_plan_mode is None  # se limpia tras usarse
    assert changes == ["plan", "auto"]
    assert any("aprobado" in msg for msg in notified)


def test_confirm_plan_approved_falls_back_to_ask_when_no_previous_mode():
    perms = Permissions(mode="plan", ask=lambda desc, is_shell, kind="confirm": "s")
    approved = perms.confirm_plan("mi plan")
    assert approved is True
    assert perms.mode == "ask"


def test_confirm_plan_rejected_stays_in_plan_mode():
    perms = Permissions(mode="auto", ask=lambda desc, is_shell, kind="confirm": "n")
    perms.set_mode("plan")

    approved = perms.confirm_plan("mi plan")

    assert approved is False
    assert perms.mode == "plan"
    assert perms._pre_plan_mode == "auto"  # se mantiene: todavía no se aprobó


def test_confirm_plan_passes_plan_kind_to_ask_callback():
    seen = {}

    def ask(desc, is_shell, kind="confirm"):
        seen["kind"] = kind
        return "s"

    perms = Permissions(mode="plan", ask=ask)
    perms.confirm_plan("mi plan")
    assert seen["kind"] == "plan"


def test_confirm_plan_non_interactive_denies_without_asking():
    calls = []
    perms = Permissions(mode="plan", interactive=False,
                         ask=lambda desc, is_shell, kind="confirm": calls.append(1) or "s")
    assert perms.confirm_plan("mi plan") is False
    assert calls == []


def test_always_response_uses_set_mode_and_keeps_pre_plan_semantics():
    """Regresión: la escalada 'a' -> auto/yolo debe seguir funcionando, y como no pasa
    por 'plan', no debe tocar _pre_plan_mode."""
    perms = Permissions(mode="ask", ask=lambda desc, is_shell, kind="confirm": "a")
    assert perms("escribir a.py (10 chars)") is True
    assert perms.mode == "auto"
    assert perms._pre_plan_mode is None
