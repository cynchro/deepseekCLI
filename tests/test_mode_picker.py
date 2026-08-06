"""Tests del selector interactivo de /mode (cli/agent_repl.py::_pick_mode): a
diferencia del resto de tests de agent_repl (que evitan el loop real de
prompt_toolkit), acá sí se ejercita una Application real, pero con un input/output
falsos (create_pipe_input/DummyOutput) para no depender de una terminal de verdad."""
import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

import cli.agent_repl as agent_repl
from cli.agent_runner import MODES


def _run_picker(current: str, keys: str):
    with create_pipe_input() as pipe_input:
        with create_app_session(input=pipe_input, output=DummyOutput()):
            pipe_input.send_text(keys)
            return agent_repl._pick_mode(current)


def test_enter_immediately_keeps_current_mode():
    assert _run_picker("auto", "\r") == "auto"


def test_arrow_down_moves_to_next_mode():
    idx = MODES.index("ask")
    expected = MODES[(idx + 1) % len(MODES)]
    assert _run_picker("ask", "\x1b[B\r") == expected


def test_arrow_up_wraps_to_last_mode():
    assert _run_picker("ask", "\x1b[A\r") == MODES[-1]


def test_navigating_across_all_modes_and_back():
    # 2 abajo desde 'ask' cae en 'plan' (índice 2 de 4).
    assert _run_picker("ask", "\x1b[B\x1b[B\r") == "plan"


def test_escape_cancels_without_choosing():
    assert _run_picker("yolo", "\x1b") is None


def test_ctrl_c_cancels_without_choosing():
    assert _run_picker("auto", "\x03") is None


def test_mode_command_with_no_args_uses_picker_and_applies_choice(monkeypatch, tmp_path):
    from cli.agent_repl import _Repl

    repl = _Repl(api_key="k", workspace=str(tmp_path))
    monkeypatch.setattr(agent_repl, "_pick_mode", lambda current: "plan")

    class _FakeAgent:
        class permissions:
            mode = "ask"

            @staticmethod
            def set_mode(m):
                _FakeAgent.permissions.mode = m

    repl.agent = _FakeAgent()
    repl._mode([])

    assert _FakeAgent.permissions.mode == "plan"


def test_mode_command_with_no_args_does_nothing_when_picker_cancelled(monkeypatch, tmp_path):
    from cli.agent_repl import _Repl

    repl = _Repl(api_key="k", workspace=str(tmp_path))
    monkeypatch.setattr(agent_repl, "_pick_mode", lambda current: None)

    calls = []

    class _FakeAgent:
        class permissions:
            mode = "ask"

            @staticmethod
            def set_mode(m):
                calls.append(m)

    repl.agent = _FakeAgent()
    repl._mode([])

    assert calls == []
