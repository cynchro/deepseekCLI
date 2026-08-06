"""Tests de cli/agent_repl.py: solo la lógica de _Repl que no requiere una
sesión interactiva real (resolución de workspace, guard de /scan y /show en
modo remoto). El loop de input()/prompt_toolkit no se testea acá."""
from pathlib import Path

from cli.agent_repl import _Repl


class _FakeRemoteWorkspace:
    """Duck-type mínimo: alcanza con exponer run_command (el discriminador que
    usa _Repl.__init__ para distinguir local de remoto) y __str__/__truediv__
    para que _Repl no rompa si algo más lo toca."""
    def __init__(self, path="/proj"):
        self._path = path
        self.closed = False

    def run_command(self, *a, **kw):
        raise AssertionError("no debería ejecutarse en estos tests")

    def __truediv__(self, other):
        return _FakeRemoteWorkspace(self._path + "/" + str(other))

    def __str__(self):
        return self._path

    def close(self):
        self.closed = True


def test_repl_defaults_to_cwd_when_no_workspace_given():
    repl = _Repl(api_key="k")
    assert repl.cwd == Path.cwd()
    assert repl.is_remote is False


def test_repl_uses_local_path_when_string_given(tmp_path):
    repl = _Repl(api_key="k", workspace=str(tmp_path))
    assert repl.cwd == tmp_path
    assert repl.is_remote is False


def test_repl_detects_remote_workspace_via_run_command():
    ws = _FakeRemoteWorkspace()
    repl = _Repl(api_key="k", workspace=ws)
    assert repl.cwd is ws
    assert repl.is_remote is True


def test_repl_scan_disabled_on_remote_workspace(capsys):
    repl = _Repl(api_key="k", workspace=_FakeRemoteWorkspace())
    cont = repl.slash("/scan", [])
    out = capsys.readouterr().out
    assert cont is True
    assert "no está soportado" in out


def test_repl_show_disabled_on_remote_workspace(capsys):
    repl = _Repl(api_key="k", workspace=_FakeRemoteWorkspace())
    cont = repl.slash("/show", [])
    out = capsys.readouterr().out
    assert cont is True
    assert "no está soportado" in out


# ── /remote: conectar la sesión actual a un workspace SSH paso a paso ──────

def test_remote_empty_host_cancels(monkeypatch, tmp_path, capsys):
    repl = _Repl(api_key="k", workspace=str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    repl.slash("/remote", [])
    assert repl.cwd == tmp_path  # no cambió
    assert repl.is_remote is False
    assert "Cancelado" in capsys.readouterr().out


def test_remote_eof_during_host_prompt_cancels_gracefully(monkeypatch, tmp_path):
    repl = _Repl(api_key="k", workspace=str(tmp_path))

    def _raise(prompt=""):
        raise EOFError()

    monkeypatch.setattr("builtins.input", _raise)
    repl.slash("/remote", [])  # no debe levantar
    assert repl.cwd == tmp_path
    assert repl.is_remote is False


def test_remote_success_switches_workspace_and_resets_agent(monkeypatch, tmp_path):
    import cli.agent_repl as repl_mod

    repl = _Repl(api_key="k", workspace=str(tmp_path))
    repl.agent = object()  # simula una sesión previa en curso

    monkeypatch.setattr("builtins.input", lambda prompt="": "alexis@servidor")
    new_ws = _FakeRemoteWorkspace("/C:/Users/alexis/proyecto")
    new_ws.host_spec = "alexis@servidor"
    monkeypatch.setattr(repl_mod, "_finalize_session", lambda r: None)

    import core.ssh_workspace as sw
    monkeypatch.setattr(sw, "resolve_remote_workspace", lambda host, path=None: new_ws)

    repl.slash("/remote", [])
    assert repl.cwd is new_ws
    assert repl.is_remote is True
    assert repl.agent is None  # fuerza un agente nuevo apuntando a la remota


def test_remote_browse_cancelled_leaves_session_untouched(monkeypatch, tmp_path, capsys):
    repl = _Repl(api_key="k", workspace=str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda prompt="": "alexis@servidor")

    import core.ssh_workspace as sw

    def _raise_cancelled(host, path=None):
        raise sw.RemoteBrowseCancelled()

    monkeypatch.setattr(sw, "resolve_remote_workspace", _raise_cancelled)
    repl.slash("/remote", [])
    assert repl.cwd == tmp_path
    assert repl.is_remote is False
    assert "Cancelado" in capsys.readouterr().out


def test_remote_connection_error_shown_and_session_untouched(monkeypatch, tmp_path, capsys):
    repl = _Repl(api_key="k", workspace=str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda prompt="": "alexis@servidor")

    import core.ssh_workspace as sw

    def _raise_error(host, path=None):
        raise RuntimeError("no se pudo autenticar")

    monkeypatch.setattr(sw, "resolve_remote_workspace", _raise_error)
    repl.slash("/remote", [])
    assert repl.cwd == tmp_path
    assert repl.is_remote is False
    assert "no se pudo autenticar" in capsys.readouterr().out


# ── /disconnect (alias /logout): inverso de /remote ────────────────────────

def test_disconnect_when_not_remote_shows_message(capsys):
    repl = _Repl(api_key="k")
    repl.slash("/disconnect", [])
    assert "no estás conectado" in capsys.readouterr().out.lower()


def test_disconnect_closes_connection_and_returns_to_local(monkeypatch):
    import cli.agent_repl as repl_mod

    ws = _FakeRemoteWorkspace("/proj")
    repl = _Repl(api_key="k", workspace=ws)
    repl.agent = object()  # sesión remota en curso
    monkeypatch.setattr(repl_mod, "_finalize_session", lambda r: None)

    repl.slash("/disconnect", [])
    assert ws.closed is True
    assert repl.cwd == Path.cwd()
    assert repl.is_remote is False
    assert repl.agent is None


def test_logout_is_an_alias_of_disconnect(monkeypatch):
    import cli.agent_repl as repl_mod

    ws = _FakeRemoteWorkspace("/proj")
    repl = _Repl(api_key="k", workspace=ws)
    monkeypatch.setattr(repl_mod, "_finalize_session", lambda r: None)

    repl.slash("/logout", [])
    assert ws.closed is True
    assert repl.is_remote is False


# ── /exit y /quit también deben cerrar la conexión SSH si hay una activa ───
# (sin esto el hilo de paramiko no es daemon y el proceso queda colgado tras
# imprimir "goodbye", forzando a cerrar la terminal a mano).

def test_exit_closes_remote_connection():
    ws = _FakeRemoteWorkspace("/proj")
    repl = _Repl(api_key="k", workspace=ws)

    cont = repl.slash("/exit", [])
    assert cont is False
    assert ws.closed is True


def test_quit_closes_remote_connection():
    ws = _FakeRemoteWorkspace("/proj")
    repl = _Repl(api_key="k", workspace=ws)

    cont = repl.slash("/quit", [])
    assert cont is False
    assert ws.closed is True


def test_exit_does_not_touch_close_when_local():
    repl = _Repl(api_key="k")  # cwd local: Path, sin close()
    cont = repl.slash("/exit", [])
    assert cont is False


# ── i18n: los mensajes nuevos respetan el idioma configurado ───────────────

def test_remote_messages_switch_to_english(monkeypatch, tmp_path, capsys):
    import core.i18n as i18n_mod

    monkeypatch.setattr(i18n_mod, "load_language", lambda: "en")
    repl = _Repl(api_key="k", workspace=str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    repl.slash("/remote", [])
    assert "Cancelled" in capsys.readouterr().out


def test_disconnect_not_connected_message_in_english(monkeypatch, capsys):
    import core.i18n as i18n_mod

    monkeypatch.setattr(i18n_mod, "load_language", lambda: "en")
    repl = _Repl(api_key="k")
    repl.slash("/disconnect", [])
    assert "not connected" in capsys.readouterr().out.lower()


# ── _run_task: SSH sigue local, workspace local pasa por el daemon ─────────
# (Fase 2: la terminal es cliente del daemon salvo sobre un workspace SSH,
# que sigue ejecutando el AgentLoop en el propio proceso sin cambios.)

def test_run_task_on_ssh_workspace_never_touches_daemon(monkeypatch):
    import cli.agent_repl as repl_mod

    def _boom(*a, **kw):
        raise AssertionError("no debería llamarse ensure_daemon sobre SSH")

    monkeypatch.setattr(repl_mod, "ensure_daemon", _boom)
    monkeypatch.setattr(repl_mod, "run_turn", lambda agent, text: {"success": True})

    repl = _Repl(api_key="k", workspace=_FakeRemoteWorkspace())
    monkeypatch.setattr(repl, "_get_agent", lambda: object())

    repl._run_task("hola")  # no debe reventar ni tocar el daemon
    assert repl.daemon is None


def test_run_task_on_local_workspace_goes_through_send_turn(monkeypatch):
    repl = _Repl(api_key="k")
    calls = []
    monkeypatch.setattr(repl, "_send_turn", lambda text: calls.append(text))

    repl._run_task("hola")

    assert calls == ["hola"]


def test_send_turn_reports_daemon_error_without_crashing(monkeypatch, capsys):
    import cli.agent_repl as repl_mod
    from cli.daemon_client import DaemonError

    repl = _Repl(api_key="k")

    def _fail():
        raise DaemonError("no se pudo levantar el daemon local")

    monkeypatch.setattr(repl, "_get_daemon", _fail)

    repl._send_turn("hola")  # no debe propagar la excepción

    assert "no se pudo levantar el daemon local" in capsys.readouterr().out


# ── reconexión ante conexión caída (BrokenPipeError, etc.) ─────────────────
# El daemon es server-first: el AgentLoop y su historial viven ahí, así que
# una conexión caída se resuelve reatacheando a la MISMA sesión, no perdiendo
# la conversación. Y si esa sesión sigue "busy" tras reatachear, no hay que
# reenviar el texto — duplicaría el turno y quemaría tokens de nuevo.

def test_send_turn_reconnects_and_resends_when_connection_drops(monkeypatch, capsys):
    from cli.daemon_client import DaemonError

    repl = _Repl(api_key="k")

    class _DeadDaemon:
        def run_turn(self, text, on_event, ask_confirm):
            raise DaemonError("se perdió la conexión con el daemon: broken pipe")

    reconnected = _FakeDaemonSession()
    reconnected.busy = False
    sent = []

    def _run_turn(text, on_event, ask_confirm):
        sent.append(text)
        return {"success": True, "content": "listo", "steps": 1, "stats": {}}
    reconnected.run_turn = _run_turn

    monkeypatch.setattr(repl, "_get_daemon", lambda: _DeadDaemon())
    monkeypatch.setattr(repl, "_reconnect_daemon", lambda: reconnected)

    repl._send_turn("hola")

    out = capsys.readouterr().out
    assert "reconectando" in out
    assert sent == ["hola"]
    assert "listo" in out


def test_send_turn_waits_without_resending_when_reconnected_session_still_busy(monkeypatch, capsys):
    """Si el turno anterior seguía corriendo server-side (busy=True tras
    reatachear), no sabemos si ya terminó o no: escuchamos su resultado en
    vez de mandar el mismo texto de nuevo."""
    from cli.daemon_client import DaemonError

    repl = _Repl(api_key="k")

    class _DeadDaemon:
        def run_turn(self, text, on_event, ask_confirm):
            raise DaemonError("se perdió la conexión con el daemon")

    reconnected = _FakeDaemonSession()
    reconnected.busy = True
    calls = {"run_turn": 0, "wait_turn": 0}

    def _run_turn(text, on_event, ask_confirm):
        calls["run_turn"] += 1
        return {"success": True, "content": "NO debería pasar", "steps": 0, "stats": {}}

    def _wait_turn(on_event, ask_confirm):
        calls["wait_turn"] += 1
        return {"success": True, "content": "resultado del turno original",
                "steps": 5, "stats": {}}
    reconnected.run_turn = _run_turn
    reconnected.wait_turn = _wait_turn

    monkeypatch.setattr(repl, "_get_daemon", lambda: _DeadDaemon())
    monkeypatch.setattr(repl, "_reconnect_daemon", lambda: reconnected)

    repl._send_turn("hola")

    assert calls == {"run_turn": 0, "wait_turn": 1}
    assert "resultado del turno original" in capsys.readouterr().out


def test_send_turn_reports_error_and_clears_daemon_when_reconnect_fails(monkeypatch, capsys):
    from cli.daemon_client import DaemonError

    repl = _Repl(api_key="k")

    class _DeadDaemon:
        def run_turn(self, text, on_event, ask_confirm):
            raise DaemonError("se perdió la conexión con el daemon")

    repl.daemon = _DeadDaemon()
    monkeypatch.setattr(repl, "_get_daemon", lambda: repl.daemon)

    def _reconnect_fail():
        raise DaemonError("no se pudo conectar al daemon: connection refused")
    monkeypatch.setattr(repl, "_reconnect_daemon", _reconnect_fail)

    repl._send_turn("hola")

    out = capsys.readouterr().out
    assert "no se pudo reconectar" in out
    assert repl.daemon is None


class _FakeDaemonSession:
    """Duck-type mínimo de DaemonSession para probar el dispatch de _Repl sin
    abrir sockets ni arrancar un daemon de verdad."""
    def __init__(self):
        self.session_id = "sid1"
        self.workspace = "/proj"
        self.mode = "ask"
        self.model = None
        self.busy = False
        self.closed = False
        self.reset_called = False
        self.set_mode_calls = []

    def close(self):
        self.closed = True

    def reset(self):
        self.reset_called = True

    def set_mode(self, mode):
        self.set_mode_calls.append(mode)
        self.mode = mode


def test_exit_closes_daemon_connection_when_attached():
    repl = _Repl(api_key="k")
    repl.daemon = _FakeDaemonSession()

    cont = repl.slash("/exit", [])

    assert cont is False
    assert repl.daemon.closed is True


def test_mode_command_uses_daemon_session_when_attached():
    repl = _Repl(api_key="k")
    repl.daemon = _FakeDaemonSession()

    repl.slash("/mode", ["auto"])

    assert repl.daemon.set_mode_calls == ["auto"]
    assert repl.prefs["mode"] == "auto"


def test_clear_resets_daemon_session_when_attached(monkeypatch):
    import cli.agent_repl as repl_mod

    monkeypatch.setattr(repl_mod, "_finalize_session", lambda r: None)
    repl = _Repl(api_key="k")
    repl.daemon = _FakeDaemonSession()

    repl.slash("/clear", [])

    assert repl.daemon.reset_called is True


def test_remote_closes_daemon_session_before_switching_to_ssh(monkeypatch, tmp_path):
    import cli.agent_repl as repl_mod

    repl = _Repl(api_key="k", workspace=str(tmp_path))
    fake_daemon = _FakeDaemonSession()
    repl.daemon = fake_daemon

    monkeypatch.setattr("builtins.input", lambda prompt="": "alexis@servidor")
    new_ws = _FakeRemoteWorkspace("/proj")
    new_ws.host_spec = "alexis@servidor"
    monkeypatch.setattr(repl_mod, "_finalize_session", lambda r: None)

    import core.ssh_workspace as sw
    monkeypatch.setattr(sw, "resolve_remote_workspace", lambda host, path=None: new_ws)

    repl.slash("/remote", [])

    assert fake_daemon.closed is True
    assert repl.daemon is None
    assert repl.is_remote is True
