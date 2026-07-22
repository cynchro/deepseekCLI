"""Tests del backend SSH (core/ssh_workspace.py). Todo mockeado, sin red real:
conexión (paramiko.SSHClient), SFTP (fake en memoria) y canal de exec_command.
Verificación manual contra un sshd real: ver plan / README."""
import io
import posixpath
import threading
from pathlib import PurePosixPath
from unittest.mock import MagicMock

import pytest

import core.ssh_workspace as sw
from core.ssh_workspace import SSHPath
from core.tools.base import ToolContext, safe_path


# ── parseo de host spec ──────────────────────────────────────────────────────

def test_parse_host_spec_user_host_port():
    assert sw._parse_host_spec("user@host:2222") == ("user", "host", 2222)


def test_parse_host_spec_host_only():
    assert sw._parse_host_spec("host") == (None, "host", None)


def test_parse_host_spec_user_host_no_port():
    assert sw._parse_host_spec("user@host") == ("user", "host", None)


def test_parse_host_spec_invalid_raises():
    with pytest.raises(ValueError):
        sw._parse_host_spec("")


# ── conexión: auth por clave/ssh-agent solamente, nunca password ────────────
# (estos dos necesitan el módulo paramiko real para parchear sus excepciones;
# el resto del archivo no lo necesita instalado, ver core/ssh_workspace.py)

@pytest.mark.skipif(sw.paramiko is None, reason="paramiko no instalado (extra opcional 'ssh')")
def test_connection_auth_failure_clear_message_no_password(monkeypatch):
    class _FakeClient:
        def load_system_host_keys(self):
            pass

        def load_host_keys(self, path):
            pass

        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, **kwargs):
            assert "password" not in kwargs, "no debe intentar password"
            raise sw.paramiko.AuthenticationException("denied")

    monkeypatch.setattr(sw.paramiko, "SSHClient", lambda: _FakeClient())
    monkeypatch.setattr(sw, "_load_ssh_config_for", lambda host: {})

    with pytest.raises(RuntimeError) as exc:
        sw.SSHConnection("user@host")
    assert "autenticar" in str(exc.value).lower()


@pytest.mark.skipif(sw.paramiko is None, reason="paramiko no instalado (extra opcional 'ssh')")
def test_connection_unknown_host_key_clear_message(monkeypatch):
    class _FakeClient:
        def load_system_host_keys(self):
            pass

        def load_host_keys(self, path):
            pass

        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, **kwargs):
            raise sw.paramiko.SSHException("host key rejected")

    monkeypatch.setattr(sw.paramiko, "SSHClient", lambda: _FakeClient())
    monkeypatch.setattr(sw, "_load_ssh_config_for", lambda host: {})

    with pytest.raises(RuntimeError) as exc:
        sw.SSHConnection("user@host")
    assert "ssh " in str(exc.value).lower()  # sugiere correr `ssh host` a mano


# ── SSHPath: navegación, resolve(), glob/rglob ──────────────────────────────

class _FakeConnResolve:
    """Fake mínimo para probar navegación/resolve() sin tocar SFTP real."""

    def resolve_path(self, path):
        return posixpath.normpath(path)


def test_sshpath_truediv_and_str():
    conn = _FakeConnResolve()
    ws = SSHPath(conn, PurePosixPath("/proj"))
    p = ws / "src" / "main.py"
    assert str(p) == "/proj/src/main.py"
    assert p.name == "main.py"
    assert p.suffix == ".py"


def test_sshpath_resolve_normalizes_traversal():
    conn = _FakeConnResolve()
    ws = SSHPath(conn, PurePosixPath("/proj"))
    escaped = (ws / "../../etc/passwd").resolve()
    assert str(escaped) == "/etc/passwd"


def test_sshpath_is_relative_to():
    conn = _FakeConnResolve()
    ws = SSHPath(conn, PurePosixPath("/proj"))
    inside = SSHPath(conn, PurePosixPath("/proj/src/main.py"))
    outside = SSHPath(conn, PurePosixPath("/etc/passwd"))
    assert inside.is_relative_to(ws)
    assert not outside.is_relative_to(ws)


def test_sshpath_host_spec_delegates_to_connection():
    class _FakeConnWithHost(_FakeConnResolve):
        host_spec = "user@servidor:2222"

    ws = SSHPath(_FakeConnWithHost(), PurePosixPath("/proj"))
    assert ws.host_spec == "user@servidor:2222"


class _FakeConnList:
    def __init__(self, files):
        self._files = files  # {rel_posix: (mtime_ns, size)}

    def list_files(self, root):
        return self._files


def test_sshpath_glob_direct_children_only():
    conn = _FakeConnList({"a.py": (1, 10), "src/b.py": (2, 20), "readme.md": (3, 5)})
    ws = SSHPath(conn, PurePosixPath("/proj"))
    names = {p.name for p in ws.glob("*.py")}
    assert names == {"a.py"}


def test_sshpath_rglob_recursive():
    conn = _FakeConnList({"a.py": (1, 10), "src/b.py": (2, 20),
                          "src/sub/c.py": (3, 30), "readme.md": (4, 5)})
    ws = SSHPath(conn, PurePosixPath("/proj"))
    paths = {str(p) for p in ws.rglob("*.py")}
    assert paths == {"/proj/a.py", "/proj/src/b.py", "/proj/src/sub/c.py"}


# ── safe_path() del contrato de tools contra un workspace remoto ────────────

def test_safe_path_allows_file_inside_remote_workspace():
    conn = _FakeConnResolve()
    ctx = ToolContext(workspace=SSHPath(conn, PurePosixPath("/proj")))
    p = safe_path(ctx, "src/main.py")
    assert isinstance(p, SSHPath)
    assert str(p) == "/proj/src/main.py"


def test_safe_path_blocks_traversal_on_remote_workspace():
    conn = _FakeConnResolve()
    ctx = ToolContext(workspace=SSHPath(conn, PurePosixPath("/proj")))
    with pytest.raises(ValueError):
        safe_path(ctx, "../../etc/passwd")


def test_safe_path_absolute_path_reanchors_to_remote_backend():
    """Sin with_absolute(), esta rama construiría un pathlib.Path LOCAL y
    rompería la comparación contra un workspace remoto (el bug que motivó
    el ajuste en core/tools/base.py::safe_path)."""
    conn = _FakeConnResolve()
    ctx = ToolContext(workspace=SSHPath(conn, PurePosixPath("/proj")))
    p = safe_path(ctx, "/proj/src/main.py")
    assert isinstance(p, SSHPath)
    assert str(p) == "/proj/src/main.py"


def test_safe_path_absolute_path_outside_remote_workspace_blocked():
    conn = _FakeConnResolve()
    ctx = ToolContext(workspace=SSHPath(conn, PurePosixPath("/proj")))
    with pytest.raises(ValueError):
        safe_path(ctx, "/etc/passwd")


# ── SSHConnection: primitivas de archivo sobre un SFTP fake en memoria ──────

class _FakeSFTP:
    def __init__(self):
        self._dirs = {"/"}
        self._files = {}

    def stat(self, path):
        st = MagicMock()
        if path in self._dirs:
            st.st_mode, st.st_size, st.st_mtime = 0o040755, 0, 1700000000.0
            return st
        if path in self._files:
            st.st_mode = 0o100644
            st.st_size = len(self._files[path])
            st.st_mtime = 1700000000.0
            return st
        raise FileNotFoundError(path)

    def mkdir(self, path):
        if path in self._dirs:
            raise IOError("ya existe")
        self._dirs.add(path)

    def open(self, path, mode):
        if "r" in mode:
            return io.BytesIO(self._files[path])
        buf = io.BytesIO()
        buf.close = lambda: self._files.__setitem__(path, buf.getvalue())
        return buf

    def listdir_attr(self, path):
        prefix = path.rstrip("/") + "/"
        names = set()
        for d in self._dirs:
            if d.startswith(prefix) and d != path:
                rest = d[len(prefix):]
                if rest and "/" not in rest:
                    names.add(rest)
        for f in self._files:
            if f.startswith(prefix):
                rest = f[len(prefix):]
                if rest and "/" not in rest:
                    names.add(rest)
        attrs = []
        for name in names:
            full = prefix + name
            a = MagicMock()
            a.filename = name
            a.st_mode = 0o040755 if full in self._dirs else 0o100644
            attrs.append(a)
        return attrs

    def normalize(self, path):
        if path == ".":
            return "/home/fakeuser"  # simula el home que resuelve un sftp-server real
        return posixpath.normpath(path)


def _bare_connection() -> sw.SSHConnection:
    """SSHConnection sin pasar por __init__ (que conecta de verdad): para
    probar sus métodos aislados con un SFTP fake."""
    conn = sw.SSHConnection.__new__(sw.SSHConnection)
    conn.sftp = _FakeSFTP()
    conn._sftp_lock = threading.Lock()
    conn._list_cache = {}
    conn._list_cache_lock = threading.Lock()
    return conn


def test_connection_mkdir_parents_and_write_read_roundtrip():
    conn = _bare_connection()
    conn.mkdir("/proj/src/sub", parents=True, exist_ok=True)
    assert conn.is_dir("/proj/src/sub")
    assert conn.is_dir("/proj/src")
    assert conn.is_dir("/proj")

    conn.write_bytes("/proj/src/sub/file.txt", b"hola")
    assert conn.exists("/proj/src/sub/file.txt")
    assert conn.is_file("/proj/src/sub/file.txt")
    assert conn.read_bytes("/proj/src/sub/file.txt") == b"hola"


def test_connection_mkdir_exist_ok_false_raises_if_present():
    conn = _bare_connection()
    conn.mkdir("/proj", parents=True, exist_ok=True)
    with pytest.raises(FileExistsError):
        conn.mkdir("/proj", exist_ok=False)


def test_connection_listdir_dirs_filters_files_and_hidden():
    conn = _bare_connection()
    conn.mkdir("/proj/src", parents=True, exist_ok=True)
    conn.mkdir("/proj/.git", parents=True, exist_ok=True)
    conn.write_bytes("/proj/readme.md", b"hi")
    assert conn.listdir_dirs("/proj") == ["src"]


def test_connection_home_dir_uses_sftp_normalize():
    conn = _bare_connection()
    assert conn.home_dir() == "/home/fakeuser"


# ── picker interactivo (browse_remote_directory) ────────────────────────────

class _FakeConnBrowse:
    def __init__(self, tree, home="/home/user"):
        self.tree = tree  # {path: [subdirs]}
        self._home = home

    def home_dir(self):
        return self._home

    def listdir_dirs(self, path):
        return sorted(self.tree.get(path, []))

    def is_dir(self, path):
        return path in self.tree


def test_browse_pick_by_number_then_confirm(monkeypatch):
    tree = {"/home/user": ["proj1", "proj2"], "/home/user/proj1": []}
    conn = _FakeConnBrowse(tree)
    inputs = iter(["1", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    assert sw.browse_remote_directory(conn) == "/home/user/proj1"


def test_browse_up_navigation(monkeypatch):
    tree = {"/home/user": ["proj1"], "/home/user/proj1": ["src"],
            "/home/user/proj1/src": []}
    conn = _FakeConnBrowse(tree)
    inputs = iter(["1", "1", "..", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    assert sw.browse_remote_directory(conn) == "/home/user/proj1"


def test_browse_absolute_path_direct(monkeypatch):
    tree = {"/home/user": [], "/var/www/app": []}
    conn = _FakeConnBrowse(tree)
    inputs = iter(["/var/www/app", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    assert sw.browse_remote_directory(conn) == "/var/www/app"


def test_browse_folder_name_typed_directly(monkeypatch):
    tree = {"/home/user": ["proj1"], "/home/user/proj1": []}
    conn = _FakeConnBrowse(tree)
    inputs = iter(["proj1", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    assert sw.browse_remote_directory(conn) == "/home/user/proj1"


def test_browse_invalid_name_reprompts(monkeypatch):
    tree = {"/home/user": ["proj1"], "/home/user/proj1": []}
    conn = _FakeConnBrowse(tree)
    inputs = iter(["no-existe", "1", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    assert sw.browse_remote_directory(conn) == "/home/user/proj1"


def test_browse_cancel_on_eof(monkeypatch):
    conn = _FakeConnBrowse({"/home/user": []})

    def _raise(prompt=""):
        raise EOFError()

    monkeypatch.setattr("builtins.input", _raise)
    assert sw.browse_remote_directory(conn) is None


# ── resolve_remote_workspace: rutas dadas vs. picker interactivo ────────────

class _FakeConnForResolve:
    def __init__(self, dirs):
        self._dirs = set(dirs)
        self.closed = False

    def is_dir(self, path):
        return path in self._dirs

    def close(self):
        self.closed = True


def test_resolve_remote_workspace_with_valid_path(monkeypatch):
    fake = _FakeConnForResolve({"/proj"})
    monkeypatch.setattr(sw, "SSHConnection", lambda host_spec: fake)
    ws = sw.resolve_remote_workspace("user@host", "/proj")
    assert isinstance(ws, SSHPath)
    assert str(ws) == "/proj"
    assert not fake.closed


def test_resolve_remote_workspace_rejects_relative_path(monkeypatch):
    fake = _FakeConnForResolve({"/proj"})
    monkeypatch.setattr(sw, "SSHConnection", lambda host_spec: fake)
    with pytest.raises(ValueError):
        sw.resolve_remote_workspace("user@host", "relative/path")
    assert fake.closed


def test_resolve_remote_workspace_rejects_missing_dir(monkeypatch):
    fake = _FakeConnForResolve({"/proj"})
    monkeypatch.setattr(sw, "SSHConnection", lambda host_spec: fake)
    with pytest.raises(RuntimeError):
        sw.resolve_remote_workspace("user@host", "/no/existe")
    assert fake.closed


def test_resolve_remote_workspace_none_path_browses_and_can_cancel(monkeypatch):
    fake = _FakeConnForResolve(set())
    monkeypatch.setattr(sw, "SSHConnection", lambda host_spec: fake)
    monkeypatch.setattr(sw, "browse_remote_directory", lambda conn, start=None: None)
    with pytest.raises(sw.RemoteBrowseCancelled):
        sw.resolve_remote_workspace("user@host", None)
    assert fake.closed


def test_resolve_remote_workspace_none_path_uses_browse_result(monkeypatch):
    fake = _FakeConnForResolve({"/proj"})
    monkeypatch.setattr(sw, "SSHConnection", lambda host_spec: fake)
    monkeypatch.setattr(sw, "browse_remote_directory", lambda conn, start=None: "/proj")
    ws = sw.resolve_remote_workspace("user@host", None)
    assert str(ws) == "/proj"


# ── SSHConnection.run_command: heartbeat + timeout duro con canal fake ─────

class _FakeChannel:
    def __init__(self):
        self.closed = False
        self.cmd = None

    def settimeout(self, t):
        pass

    def exec_command(self, cmd):
        self.cmd = cmd

    def recv_ready(self):
        return False

    def recv_stderr_ready(self):
        return False

    def exit_status_ready(self):
        return False  # nunca termina -> fuerza el path de timeout

    def close(self):
        self.closed = True


def test_run_command_timeout_closes_channel_and_reports_clearly(monkeypatch):
    fake_time = {"t": 1000.0}
    monkeypatch.setattr(sw.time, "time", lambda: fake_time["t"])
    monkeypatch.setattr(sw.time, "sleep", lambda s: fake_time.__setitem__("t", fake_time["t"] + s))
    monkeypatch.setattr(sw, "_HEARTBEAT_INTERVAL", 2)

    conn = sw.SSHConnection.__new__(sw.SSHConnection)
    chan = _FakeChannel()
    transport = MagicMock()
    transport.open_session.return_value = chan
    conn.client = MagicMock()
    conn.client.get_transport.return_value = transport
    conn._has_timeout_cmd = False
    conn._has_bash = False

    heartbeats = []
    exit_code, stdout, stderr = conn.run_command("sleep 100", timeout=5, on_wait=heartbeats.append)

    assert exit_code is None
    assert "timeout tras 5s" in stderr
    assert chan.closed is True
    assert heartbeats  # el heartbeat alcanzó a dispararse antes del corte


def test_list_via_find_parses_tab_separated_output():
    conn = sw.SSHConnection.__new__(sw.SSHConnection)
    conn.run_command = lambda cmd, timeout=30: (
        0, "a.py\t1700000000.0\t123\nsrc/b.py\t1700000001.5\t456\n", "")
    result = conn._list_via_find("/proj")
    assert result["a.py"] == (int(1700000000.0 * 1e9), 123)
    assert result["src/b.py"] == (int(1700000001.5 * 1e9), 456)


def test_list_via_find_falls_back_to_sftp_walk_on_nonzero_exit(monkeypatch):
    conn = sw.SSHConnection.__new__(sw.SSHConnection)
    conn.run_command = lambda cmd, timeout=30: (None, "", "ERROR: timeout tras 30s")
    called = {}

    def _fake_walk(root):
        called["root"] = root
        return {"x": (1, 1)}

    conn._list_via_sftp_walk = _fake_walk
    result = conn._list_via_find("/proj")
    assert result == {"x": (1, 1)}
    assert called["root"] == "/proj"


# ── soporte Windows: funciones puras de traducción de paths y quoting ──────

def test_win_to_sftp_backslash_form():
    assert sw._win_to_sftp("C:\\Users\\alexis") == "/C:/Users/alexis"


def test_win_to_sftp_forward_slash_form():
    assert sw._win_to_sftp("C:/Users/alexis") == "/C:/Users/alexis"


def test_win_to_sftp_lowercase_drive_normalized_to_upper():
    assert sw._win_to_sftp("c:\\users\\x") == "/C:/users/x"


def test_win_to_sftp_drive_root():
    assert sw._win_to_sftp("C:\\") == "/C:/"


def test_sftp_to_win_round_trip():
    assert sw._sftp_to_win("/C:/Users/alexis") == "C:\\Users\\alexis"


def test_sftp_to_win_drive_root():
    assert sw._sftp_to_win("/C:/") == "C:\\"


def test_quote_cmd_no_trailing_backslash():
    path = "C:\\Users\\alexis"
    assert sw._quote_cmd(path) == f'"{path}"'


def test_quote_cmd_with_spaces():
    path = "C:\\Program Files\\app"
    assert sw._quote_cmd(path) == f'"{path}"'


def test_quote_cmd_drive_root_doubles_trailing_backslash():
    path = "C:\\"  # una sola backslash al final
    result = sw._quote_cmd(path)
    # sin el fix, "C:\"" quedaría con la comilla de cierre "escapada" por el
    # backslash pegado — CommandLineToArgvW rompería el parseo.
    assert result == '"' + path + "\\" + '"'
    assert result.count("\\") == 2


# ── soporte Windows: detección de SO remoto (cascada de 3 probes) ─────────

class _ScriptedChannel:
    """Fake channel que devuelve una salida fija según el comando recibido —
    simula varios exec_command en secuencia (uno por probe de _detect_remote_os)."""

    def __init__(self, response_map):
        self.response_map = response_map  # substring del cmd -> (exit_code, stdout)
        self.cmd = None
        self._out = b""
        self._exit_code = 1
        self._sent = False

    def settimeout(self, t):
        pass

    def exec_command(self, cmd):
        self.cmd = cmd
        for key, (code, out) in self.response_map.items():
            if key in cmd:
                self._exit_code, self._out = code, out.encode()
                return

    def recv_ready(self):
        return not self._sent

    def recv(self, n):
        self._sent = True
        return self._out

    def recv_stderr_ready(self):
        return False

    def recv_stderr(self, n):
        return b""

    def exit_status_ready(self):
        return True

    def recv_exit_status(self):
        return self._exit_code

    def close(self):
        pass


def _conn_with_scripted_exec(response_map):
    """SSHConnection sin __init__ real, con exec_command respondiendo según
    `response_map` (substring de comando -> (exit_code, stdout)). Cada canal
    abierto queda en conn._channels, para poder inspeccionar el comando exacto
    armado por run_command."""
    conn = sw.SSHConnection.__new__(sw.SSHConnection)
    conn.host_spec = "user@host"
    channels = []

    def _new_session(timeout=None):
        ch = _ScriptedChannel(response_map)
        channels.append(ch)
        return ch

    transport = MagicMock()
    transport.open_session.side_effect = _new_session
    conn.client = MagicMock()
    conn.client.get_transport.return_value = transport
    conn._channels = channels
    return conn


def test_detect_remote_os_cmd():
    conn = _conn_with_scripted_exec({"echo %OS%": (0, "Windows_NT\r\n")})
    is_windows, shell = conn._detect_remote_os()
    assert is_windows is True
    assert shell == "cmd"


def test_detect_remote_os_posix():
    conn = _conn_with_scripted_exec({
        "echo %OS%": (0, "%OS%\n"),   # ningún shell POSIX expande %OS%
        "uname -s": (0, "Linux\n"),
    })
    is_windows, shell = conn._detect_remote_os()
    assert is_windows is False
    assert shell == "posix"


def test_detect_remote_os_powershell_raises_clear_error():
    conn = _conn_with_scripted_exec({
        "echo %OS%": (0, "%OS%\n"),
        "uname -s": (127, ""),
        "echo $env:OS": (0, "Windows_NT\r\n"),
    })
    with pytest.raises(RuntimeError, match="PowerShell"):
        conn._detect_remote_os()


def test_verify_windows_path_hypothesis_passes_on_expected_format(capsys):
    conn = sw.SSHConnection.__new__(sw.SSHConnection)
    conn.home_dir = lambda: "/C:/Users/alexis"
    conn._remote_shell = "cmd"
    conn._verify_windows_path_hypothesis()  # no debe levantar
    assert "Windows detectado" in capsys.readouterr().out


def test_verify_windows_path_hypothesis_fails_clearly_on_unexpected_format():
    conn = sw.SSHConnection.__new__(sw.SSHConnection)
    conn.home_dir = lambda: "/cygdrive/c/Users/alexis"  # no matchea /X:/...
    conn._remote_shell = "cmd"
    with pytest.raises(RuntimeError, match="no matchea"):
        conn._verify_windows_path_hypothesis()


def test_detect_oem_codepage_parses_reg_query_output():
    conn = _conn_with_scripted_exec({
        "reg query": (0, "\r\nHKEY_LOCAL_MACHINE\\...\\CodePage\r\n"
                         "    OEMCP    REG_SZ    850\r\n\r\n"),
    })
    assert conn._detect_oem_codepage() == "cp850"


def test_detect_oem_codepage_falls_back_on_unparseable_output():
    conn = _conn_with_scripted_exec({"reg query": (0, "salida inesperada sin el patrón")})
    assert conn._detect_oem_codepage() == "cp437"


def test_detect_oem_codepage_falls_back_on_error():
    conn = sw.SSHConnection.__new__(sw.SSHConnection)
    conn.run_command = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("canal roto"))
    assert conn._detect_oem_codepage() == "cp437"


# ── soporte Windows: run_command arma el comando cmd.exe correcto ──────────
# Nota: SIN chcp — verificado en vivo contra un Win32-OpenSSH real que no tiene
# ningún efecto sobre la salida redirigida/en pipe (sigue en el codepage OEM
# pese a que chcp reporta 65001 como "activo"); el fix real es decodificar con
# el codepage correcto (ver _detect_oem_codepage / tests de abajo), no intentar
# cambiarlo.

def test_run_command_windows_branch_builds_cd():
    conn = _conn_with_scripted_exec({"dir": (0, "")})
    conn.is_windows = True
    conn.run_command("dir", cwd="/C:/Users/alexis/proyecto", timeout=30)
    sent = conn._channels[-1].cmd
    assert sent == 'cd /d "C:\\Users\\alexis\\proyecto" && dir'


def test_run_command_windows_branch_no_cwd():
    conn = _conn_with_scripted_exec({"dir": (0, "")})
    conn.is_windows = True
    conn.run_command("dir", timeout=30)
    sent = conn._channels[-1].cmd
    assert sent == "dir"


def test_run_command_windows_branch_quotes_drive_root_safely():
    conn = _conn_with_scripted_exec({"dir": (0, "")})
    conn.is_windows = True
    conn.run_command("dir", cwd="/C:/", timeout=30)
    sent = conn._channels[-1].cmd
    quoted_root = '"C:' + "\\" + "\\" + '"'  # el trailing se duplica antes del cierre
    assert sent == f"cd /d {quoted_root} && dir"


def test_run_command_windows_decodes_with_oem_codepage_not_utf8():
    # bytes de "café" en cp850 (el escenario real verificado en vivo): la 'é'
    # es 0x82 en cp850, un byte inválido para UTF-8 -> antes rompía/mojibake.
    cafe_cp850 = "café".encode("cp850")
    conn = sw.SSHConnection.__new__(sw.SSHConnection)
    conn.is_windows = True
    conn._oem_codepage = "cp850"
    chan = _ScriptedChannel({})
    chan._exit_code, chan._out = 0, cafe_cp850
    transport = MagicMock()
    transport.open_session.return_value = chan
    conn.client = MagicMock()
    conn.client.get_transport.return_value = transport
    _, stdout, _ = conn.run_command("echo café", timeout=10)
    assert stdout == "café"


def test_run_command_posix_ignores_oem_codepage_uses_utf8():
    conn = _conn_with_scripted_exec({"echo": (0, "café")})  # ascii + utf-8 ya-codificado por _ScriptedChannel
    conn.is_windows = False
    conn._has_bash = conn._has_timeout_cmd = False
    _, stdout, _ = conn.run_command("echo café", timeout=10)
    assert stdout == "café"


def test_run_command_posix_branch_unchanged_when_not_windows():
    conn = _conn_with_scripted_exec({"ls": (0, "")})
    conn.is_windows = False
    conn._has_bash = conn._has_timeout_cmd = False
    conn.run_command("ls", cwd="/home/user/proj", timeout=30)
    sent = conn._channels[-1].cmd
    assert sent == "cd /home/user/proj && ls"


# ── soporte Windows: safe_path acepta backslash igual que '/' ─────────────

class _FakeConnResolveWindows(_FakeConnResolve):
    is_windows = True


def test_safe_path_windows_backslash_equivalent_to_forward_slash():
    conn = _FakeConnResolveWindows()
    ctx = ToolContext(workspace=SSHPath(conn, PurePosixPath("/C:/proj")))
    p_backslash = safe_path(ctx, "src\\main.py")
    p_forward = safe_path(ctx, "src/main.py")
    assert str(p_backslash) == str(p_forward) == "/C:/proj/src/main.py"


def test_safe_path_windows_still_blocks_traversal():
    conn = _FakeConnResolveWindows()
    ctx = ToolContext(workspace=SSHPath(conn, PurePosixPath("/C:/proj")))
    with pytest.raises(ValueError):
        safe_path(ctx, "..\\..\\Windows\\System32")


# ── soporte Windows: resolve_remote_workspace / picker con rutas nativas ──

def test_resolve_remote_workspace_accepts_native_windows_path(monkeypatch):
    fake = _FakeConnForResolve({"/C:/Users/alexis/proyecto"})
    monkeypatch.setattr(sw, "SSHConnection", lambda host_spec: fake)
    ws = sw.resolve_remote_workspace("user@host", "C:\\Users\\alexis\\proyecto")
    assert str(ws) == "/C:/Users/alexis/proyecto"


def test_browse_accepts_native_windows_path_typed_directly(monkeypatch):
    tree = {"/C:/Users/alexis": [], "/D:/proyectos/app": []}
    conn = _FakeConnBrowse(tree, home="/C:/Users/alexis")
    inputs = iter(["D:\\proyectos\\app", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    assert sw.browse_remote_directory(conn) == "/D:/proyectos/app"
