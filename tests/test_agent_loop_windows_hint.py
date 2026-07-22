"""Test del hint de SO Windows en el system prompt (core/agent_loop.py): si el
workspace es un SSHPath remoto sobre Windows, el agente necesita que se le diga
explícitamente que run_command usa sintaxis cmd.exe pero los paths de las tools
de archivo siguen siendo POSIX-con-'/' — si no, por default genera comandos
POSIX (ls/grep/cat) que fallan contra cmd.exe."""
from core.agent_loop import AgentLoop


class _FakeClient:
    def get_stats(self):
        return {}


class _FakeWindowsWorkspace:
    """Duck-type mínimo: is_windows=True + lo justo para que AgentLoop.__init__
    no rompa (run_command lo marca como remoto, __truediv__/exists cubren las
    consultas de tasks/journal que se hacen siempre al construir)."""
    is_windows = True

    def run_command(self, *a, **kw):
        raise AssertionError("no debería ejecutarse en este test")

    def __truediv__(self, other):
        return self

    def exists(self):
        return False

    def __str__(self):
        return "/C:/Users/alexis/proyecto"


def test_system_prompt_includes_windows_hint_for_remote_windows_workspace():
    loop = AgentLoop(_FakeClient(), _FakeWindowsWorkspace())
    sys_prompt = loop.messages[0]["content"]
    assert "REMOTO WINDOWS" in sys_prompt
    assert "cmd.exe" in sys_prompt
    assert "ls, grep, cat" in sys_prompt


def test_system_prompt_no_windows_hint_for_local_workspace(tmp_path):
    loop = AgentLoop(_FakeClient(), tmp_path)
    sys_prompt = loop.messages[0]["content"]
    assert "REMOTO WINDOWS" not in sys_prompt
