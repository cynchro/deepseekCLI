"""Workspace remoto vía SSH: permite que `deep agent` opere sobre una carpeta en
otra máquina (leer, editar, listar, ejecutar comandos) sin instalar deepseekcli
ahí — solo hace falta `sshd` corriendo y la clave/ssh-agent del usuario ya
configurados (mismo mecanismo que un `ssh` normal).

`SSHPath` implementa el subconjunto de la API de `pathlib.Path` que ya usa el
resto del código (`read_text`, `write_text`, `exists`, `is_dir`, `glob`, `stat`,
etc.). Como todas las tools (`core/tools/fs.py`, `search.py`, ...) y el resto del
motor (`core/tasks.py`, `journal.py`, `context.py`, `rag.py`) solo llaman esos
métodos estándar sobre `ctx.workspace`, pasarles un `SSHPath` en vez de un
`Path` local los hace funcionar contra la remota sin tocar su lógica.
"""
from __future__ import annotations

import getpass
import fnmatch
import os
import posixpath
import re
import shlex
import socket
import stat as _pystat
import threading
import time
from pathlib import PurePosixPath

import core.debug as _dbg
from core.i18n import t

try:
    import paramiko
except ImportError:
    paramiko = None

_HEARTBEAT_INTERVAL = 15
_LIST_CACHE_TTL = 5
_HOST_SPEC_RE = re.compile(r"^(?:([^@]+)@)?([^:@]+)(?::(\d+))?$")


def _parse_host_spec(spec: str):
    m = _HOST_SPEC_RE.match(spec.strip())
    if not m:
        raise ValueError(
            f"Formato de host inválido: {spec!r} (esperado usuario@host[:puerto])")
    user, host, port = m.groups()
    return user, host, int(port) if port else None


def _load_ssh_config_for(host: str) -> dict:
    cfg_path = os.path.expanduser("~/.ssh/config")
    cfg = paramiko.SSHConfig()
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            cfg.parse(f)
    return cfg.lookup(host)


_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _win_to_sftp(p: str) -> str:
    """'C:\\Users\\x' o 'C:/Users/x' -> '/C:/Users/x' (forma interna, la misma
    que expone el sftp-server de Win32-OpenSSH). Normaliza la letra de unidad a
    mayúscula: evita falsos 'fuera del workspace' en safe_path() si el usuario
    tipeó la unidad en minúscula (la comparación de contención es case-sensitive,
    NTFS no lo es)."""
    body = p.replace("\\", "/").lstrip("/")
    return "/" + body[0].upper() + body[1:]


def _sftp_to_win(p: str) -> str:
    """'/C:/Users/x' -> 'C:\\Users\\x' (forma nativa, para exec_command)."""
    return p.lstrip("/").replace("/", "\\")


def _quote_cmd(path: str) -> str:
    """Quoting de cmd.exe para un path (usado en `cd /d "..."`). Duplica los
    backslashes finales antes de la comilla de cierre: sin esto, la raíz de una
    unidad ("C:\\") rompe el parseo de CommandLineToArgvW porque el backslash
    pegado a la comilla la "escapa". No hace falta escapar comillas dobles
    internas: NTFS prohíbe '\"' en nombres de archivo, no puede ocurrir."""
    trailing = len(path) - len(path.rstrip("\\"))
    return '"' + path + "\\" * trailing + '"'


class _FakeStat:
    """Objeto mínimo con la superficie de `os.stat_result` que necesita
    `core/rag.py` (`st_mtime_ns`, `st_size`), sintetizado desde SFTP."""
    __slots__ = ("st_mtime_ns", "st_size", "st_mtime")

    def __init__(self, mtime_ns: int, size: int):
        self.st_mtime_ns = mtime_ns
        self.st_size = size
        self.st_mtime = mtime_ns / 1e9


class SSHConnection:
    """Una conexión SSH/SFTP compartida por todo el run del agente (incluidos
    sub-agentes en paralelo, que reusan la misma instancia vía el mismo
    `SSHPath`). Se conecta de forma EAGER al construirse: si falla, el error
    aparece antes de arrancar el agente, no a mitad de una tarea."""

    def __init__(self, host_spec: str, connect_timeout: float = 15):
        if paramiko is None:
            raise RuntimeError(
                "El backend SSH necesita 'paramiko'. Instalalo con: "
                "pip install 'deepseek-builder[ssh]'")
        self.host_spec = host_spec
        user_arg, host_arg, port_arg = _parse_host_spec(host_spec)
        cfg = _load_ssh_config_for(host_arg)
        hostname = cfg.get("hostname", host_arg)
        username = user_arg or cfg.get("user") or getpass.getuser()
        port = port_arg or int(cfg.get("port", 22))
        identity_files = cfg.get("identityfile") or []

        sock = None
        proxycmd = cfg.get("proxycommand")
        if proxycmd:
            sock = paramiko.ProxyCommand(proxycmd)

        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        known_hosts = os.path.expanduser("~/.ssh/known_hosts")
        if os.path.exists(known_hosts):
            self.client.load_host_keys(known_hosts)
        # RejectPolicy (no AutoAddPolicy): no bajamos la vara de seguridad
        # respecto a un `ssh` normal. Host desconocido -> falla con mensaje claro.
        self.client.set_missing_host_key_policy(paramiko.RejectPolicy())

        connect_kwargs = dict(
            hostname=hostname, port=port, username=username,
            timeout=connect_timeout, allow_agent=True, look_for_keys=True,
            sock=sock,
        )
        if identity_files:
            connect_kwargs["key_filename"] = [os.path.expanduser(p) for p in identity_files]
        try:
            self.client.connect(**connect_kwargs)
        except paramiko.AuthenticationException as e:
            raise RuntimeError(
                f"No se pudo autenticar por clave/ssh-agent contra {host_spec}. "
                f"Verificá 'ssh-add -l' o que el host acepte tu clave pública. "
                f"No se intenta autenticación por password.") from e
        except paramiko.SSHException as e:
            raise RuntimeError(
                f"Error SSH / host key rechazada conectando a {host_spec}: {e}. "
                f"Si es la primera conexión a este host, corré 'ssh {host_spec}' a mano "
                f"una vez para agregarlo a known_hosts.") from e
        except (socket.timeout, OSError) as e:
            raise RuntimeError(f"No se pudo conectar a {host_spec}: {e}") from e

        transport = self.client.get_transport()
        transport.set_keepalive(15)
        self.sftp = self.client.open_sftp()
        self._sftp_lock = threading.Lock()
        self._list_cache: dict = {}
        self._list_cache_lock = threading.Lock()
        self.is_windows, self._remote_shell = self._detect_remote_os()
        if self.is_windows:
            self._verify_windows_path_hypothesis()
            self._oem_codepage = self._detect_oem_codepage()
        # No se saltean para hosts Windows aunque vayan a fallar ahí: un solo
        # invariante (is_windows) usado solo donde hace falta, en vez de atar
        # "optimización" a "corrección" — y cubre gratis un sshd Cygwin/MSYS2/WSL
        # sobre Windows donde estas herramientas sí existen.
        self._has_bash = self._check_remote_tool("bash")
        self._has_timeout_cmd = self._check_remote_tool("timeout")
        self._has_find = self._check_remote_tool("find")

    def _detect_remote_os(self):
        """Cascada de 3 probes para distinguir posix/cmd/powershell, una sola
        vez al conectar. `%OS%` lo expande SOLO cmd.exe (siempre a 'Windows_NT',
        sin depender del locale); ningún shell POSIX interpreta '%...%', así que
        no hay falso positivo desde ese lado. Si ninguno de los dos matchea,
        `$env:OS` lo expande SOLO PowerShell (cmd.exe lo imprime literal)."""
        _, out, _ = self.run_command("echo %OS%", timeout=10)
        if "Windows_NT" in out:
            return True, "cmd"
        _, out, _ = self.run_command("uname -s", timeout=10)
        if out.strip():
            return False, "posix"
        _, out, _ = self.run_command("echo $env:OS", timeout=10)
        if "Windows_NT" in out:
            raise RuntimeError(
                f"Shell remoto PowerShell detectado en {self.host_spec} — no soportado "
                f"todavía (PowerShell 5.1, el default en la mayoría de instalaciones, ni "
                f"siquiera soporta '&&' como separador de comandos). Configurá 'DefaultShell' "
                f"a cmd.exe en el server, o pedile a deep que agregue soporte de PowerShell.")
        return False, "posix"

    def _verify_windows_path_hypothesis(self):
        """El diseño asume que el sftp-server de Win32-OpenSSH expone las
        unidades como '/C:/Users/...' (spec SFTP: paths absolutos empiezan con
        '/'). Falla acá, claro y temprano, si la hipótesis está rota — en vez de
        un IOError de SFTP genérico varios pasos después."""
        home = self.home_dir()
        if not re.match(r"^/[A-Za-z]:", home):
            raise RuntimeError(
                f"SO Windows detectado pero el home SFTP no matchea el formato esperado "
                f"'/X:/...': {home!r}. El sftp-server probablemente no es Win32-OpenSSH "
                f"nativo (¿Cygwin/MSYS2?) — revisar _win_to_sftp/_sftp_to_win en "
                f"core/ssh_workspace.py.")
        print(t("remote.windows.detected", home=home))
        _dbg.log("SSH", f"windows=True  home={home}  remote_shell={self._remote_shell}")

    def _detect_oem_codepage(self) -> str:
        """Codepage real que usa cmd.exe para su salida cuando NO hay una consola
        de verdad atada (nuestro caso: exec_command sin PTY). Verificado en vivo:
        `chcp 65001` NO cambia esto para salida redirigida/en pipe — sigue
        saliendo en el codepage OEM del sistema pese a que `chcp` reporta 65001
        como "activo". Se lee del registro (fuente confiable, no depende de
        adivinar el locale), con fallback a cp437 si algo falla."""
        try:
            _, out, _ = self.run_command(
                'reg query "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Nls\\CodePage" /v OEMCP',
                timeout=10)
            m = re.search(r"OEMCP\s+REG_SZ\s+(\d+)", out)
            if m:
                return f"cp{m.group(1)}"
        except Exception:
            pass
        return "cp437"

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass

    # ── primitivas de archivo (SFTP) ─────────────────────────────────────────
    def _stat_safe(self, path: str):
        with self._sftp_lock:
            try:
                return self.sftp.stat(path)
            except (FileNotFoundError, IOError, OSError):
                return None

    def exists(self, path: str) -> bool:
        return self._stat_safe(path) is not None

    def is_dir(self, path: str) -> bool:
        st = self._stat_safe(path)
        return st is not None and _pystat.S_ISDIR(st.st_mode)

    def is_file(self, path: str) -> bool:
        st = self._stat_safe(path)
        return st is not None and _pystat.S_ISREG(st.st_mode)

    def stat(self, path: str) -> _FakeStat:
        with self._sftp_lock:
            st = self.sftp.stat(path)
        return _FakeStat(int(st.st_mtime * 1e9), st.st_size)

    def read_bytes(self, path: str) -> bytes:
        with self._sftp_lock:
            with self.sftp.open(path, "rb") as f:
                return f.read()

    def write_bytes(self, path: str, data: bytes):
        with self._sftp_lock:
            with self.sftp.open(path, "wb") as f:
                f.write(data)
        self._invalidate_list_cache()

    def listdir(self, path: str) -> list:
        with self._sftp_lock:
            return self.sftp.listdir(path)

    def listdir_dirs(self, path: str) -> list:
        """Nombres de subdirectorios directos de `path` (ocultos aparte), en un
        solo roundtrip (listdir_attr trae el modo, no hace falta stat() por hijo).
        Usado por el picker interactivo (`browse_remote_directory`)."""
        with self._sftp_lock:
            entries = self.sftp.listdir_attr(path)
        return sorted(e.filename for e in entries
                      if _pystat.S_ISDIR(e.st_mode) and not e.filename.startswith("."))

    def home_dir(self) -> str:
        """Directorio por default de la sesión SFTP (típicamente el home del
        usuario remoto) — punto de partida del picker interactivo."""
        with self._sftp_lock:
            return self.sftp.normalize(".")

    def mkdir(self, path: str, parents: bool = False, exist_ok: bool = False):
        if self._stat_safe(path) is not None:
            if exist_ok:
                return
            raise FileExistsError(path)
        if not parents:
            with self._sftp_lock:
                self.sftp.mkdir(path)
            return
        to_create = []
        cur = PurePosixPath(path)
        while self._stat_safe(str(cur)) is None:
            to_create.append(cur)
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
        with self._sftp_lock:
            for d in reversed(to_create):
                try:
                    self.sftp.mkdir(str(d))
                except IOError:
                    pass  # carrera con otro hilo/proceso creando el mismo dir: no es fatal
        self._invalidate_list_cache()

    def resolve_path(self, path: str) -> str:
        """Análogo a Path.resolve(): normaliza léxicamente y resuelve symlinks
        del prefijo que sí existe en el servidor (vía SFTP normalize, que en el
        sftp-server de OpenSSH hace realpath). El tramo que todavía no existe
        (típico al crear un archivo nuevo) se concatena tal cual, igual que
        pathlib en modo no estricto."""
        lexical = posixpath.normpath(path)
        pp = PurePosixPath(lexical)
        trailing = []
        existing = pp
        while self._stat_safe(str(existing)) is None:
            parent = existing.parent
            if parent == existing:
                break
            trailing.append(existing.name)
            existing = parent
        with self._sftp_lock:
            try:
                resolved_prefix = self.sftp.normalize(str(existing))
            except (IOError, OSError):
                resolved_prefix = str(existing)
        for name in reversed(trailing):
            resolved_prefix = resolved_prefix.rstrip("/") + "/" + name
        return resolved_prefix

    # ── listado recursivo (find en una sola llamada, con cache corto) ───────
    def list_files(self, root: str) -> dict:
        now = time.time()
        with self._list_cache_lock:
            cached = self._list_cache.get(root)
            if cached and now - cached[0] < _LIST_CACHE_TTL:
                return cached[1]
        entries = self._list_via_find(root) if self._has_find else self._list_via_sftp_walk(root)
        with self._list_cache_lock:
            self._list_cache[root] = (now, entries)
        return entries

    def _invalidate_list_cache(self):
        with self._list_cache_lock:
            self._list_cache.clear()

    def _list_via_find(self, root: str) -> dict:
        cmd = f"find {shlex.quote(root)} -type f -printf '%P\\t%T@\\t%s\\n' 2>/dev/null"
        try:
            exit_code, out, _err = self.run_command(cmd, timeout=30)
        except Exception:
            return self._list_via_sftp_walk(root)
        if exit_code != 0:  # None (timeout/error) o exit != 0: fallback a SFTP puro
            return self._list_via_sftp_walk(root)
        result = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            relp, mtime_s, size_s = parts
            try:
                result[relp] = (int(float(mtime_s) * 1e9), int(size_s))
            except ValueError:
                continue
        return result

    def _list_via_sftp_walk(self, root: str) -> dict:
        result = {}

        def _walk(cur: str):
            with self._sftp_lock:
                try:
                    entries = self.sftp.listdir_attr(cur)
                except IOError:
                    return
            for e in entries:
                full = cur.rstrip("/") + "/" + e.filename
                if _pystat.S_ISDIR(e.st_mode):
                    _walk(full)
                elif _pystat.S_ISREG(e.st_mode):
                    rel = full[len(root):].lstrip("/")
                    result[rel] = (int(e.st_mtime * 1e9), e.st_size)

        _walk(root)
        return result

    # ── ejecución de comandos (exec_command con heartbeat + timeout duro) ──
    def _check_remote_tool(self, name: str) -> bool:
        try:
            exit_code, _out, _err = self.run_command(f"command -v {shlex.quote(name)}", timeout=10)
            return exit_code == 0
        except Exception:
            return False

    def run_command(self, command: str, cwd: str = None, timeout: int = 60, on_wait=None):
        """Corre `command` en la remota. Con heartbeat (`on_wait(elapsed)` cada
        ~15s) y timeout duro: si el remoto tiene `timeout`+`bash`, envolvemos el
        comando para que se mate solo del lado remoto aunque el canal SSH se
        corte sin matar el proceso; si no, cerramos el canal al vencer el plazo
        (mismo espíritu que el timeout duro de `core/tools/shell.py` en local)."""
        if getattr(self, "is_windows", False):
            # Sin wrap timeout+bash (no hay equivalente útil en cmd.exe; ya sale
            # gratis porque _has_bash/_has_timeout_cmd dan False ahí). SIN chcp:
            # verificado en vivo que no cambia nada para salida redirigida/en
            # pipe (sigue en el codepage OEM pese a que chcp reporta 65001) — el
            # fix real es decodificar con ese codepage, no intentar cambiarlo.
            cd_part = f"cd /d {_quote_cmd(_sftp_to_win(cwd))} && " if cwd else ""
            full = f"{cd_part}{command}"
        else:
            if getattr(self, "_has_timeout_cmd", False) and getattr(self, "_has_bash", False):
                inner = f"timeout {int(timeout)}s bash -c {shlex.quote(command)}"
            else:
                inner = command
            full = f"cd {shlex.quote(cwd)} && {inner}" if cwd else inner

        chan = self.client.get_transport().open_session(timeout=15)
        chan.settimeout(0.5)
        chan.exec_command(full)

        t0 = time.time()
        last_hb = t0
        out_chunks, err_chunks = [], []
        hard_cap = timeout + 5  # margen por si el wrap remoto de `timeout` no estaba disponible

        while True:
            active = self._drain(chan, out_chunks, err_chunks)
            if chan.exit_status_ready():
                break
            elapsed = time.time() - t0
            if elapsed >= hard_cap:
                chan.close()
                # Mismo sentinel que core/tools/shell.py::_run_local: exit_code=None
                # + el mensaje de error completo en stderr, listo para mostrar tal cual.
                return None, "", f"ERROR: timeout tras {timeout}s (canal SSH cerrado a la fuerza)"
            if on_wait and time.time() - last_hb >= _HEARTBEAT_INTERVAL:
                on_wait(int(elapsed))
                last_hb = time.time()
            if not active:
                time.sleep(0.2)

        self._drain(chan, out_chunks, err_chunks)
        exit_code = chan.recv_exit_status()
        # Windows: codepage OEM del sistema (ver _detect_oem_codepage), no UTF-8.
        encoding = getattr(self, "_oem_codepage", None) or "utf-8"
        stdout = b"".join(out_chunks).decode(encoding, "replace")
        stderr = b"".join(err_chunks).decode(encoding, "replace")
        return exit_code, stdout, stderr

    @staticmethod
    def _drain(chan, out_chunks, err_chunks) -> bool:
        active = False
        try:
            while chan.recv_ready():
                out_chunks.append(chan.recv(65536))
                active = True
        except Exception:
            pass
        try:
            while chan.recv_stderr_ready():
                err_chunks.append(chan.recv_stderr(65536))
                active = True
        except Exception:
            pass
        return active


class SSHPath:
    """Objeto 'path-like' que duck-tipea la superficie de `pathlib.Path` que ya
    usa el resto del código (`read_text`, `write_text`, `exists`, `glob`, `stat`,
    `/`, ...), respaldado por SFTP/exec sobre una `SSHConnection` en vez del
    filesystem local. Inmutable: cada operación de navegación devuelve una
    instancia nueva, igual que `pathlib.Path`."""

    __slots__ = ("_conn", "_pp")

    def __init__(self, conn: SSHConnection, pure: PurePosixPath):
        self._conn = conn
        self._pp = pure

    # ── navegación ───────────────────────────────────────────────────────────
    def __truediv__(self, other) -> "SSHPath":
        other_str = other if isinstance(other, str) else os.fspath(other)
        return SSHPath(self._conn, self._pp / other_str)

    def with_absolute(self, absolute_posix_path: str) -> "SSHPath":
        """Reancla como ruta ABSOLUTA remota bajo la MISMA conexión. Lo usa
        `core/tools/base.py::safe_path()` cuando el argumento de la tool ya es
        una ruta absoluta: sin esto, ese caso construiría un `pathlib.Path`
        LOCAL en vez de un `SSHPath`, rompiendo la comparación posterior contra
        el workspace remoto."""
        return SSHPath(self._conn, PurePosixPath(absolute_posix_path))

    def is_absolute(self) -> bool:
        return self._pp.is_absolute()

    @property
    def host_spec(self) -> str:
        """'usuario@host[:puerto]' de la conexión — para mostrarle al usuario
        a qué máquina está conectado (banner del REPL, mensajes de error)."""
        return self._conn.host_spec

    @property
    def is_windows(self) -> bool:
        return self._conn.is_windows

    @property
    def name(self) -> str:
        return self._pp.name

    @property
    def suffix(self) -> str:
        return self._pp.suffix

    @property
    def parts(self):
        return self._pp.parts

    @property
    def parent(self) -> "SSHPath":
        return SSHPath(self._conn, self._pp.parent)

    def __str__(self) -> str:
        return str(self._pp)

    def __fspath__(self) -> str:
        return str(self._pp)

    def __repr__(self) -> str:
        return f"SSHPath({self._conn.host_spec!r}, {str(self._pp)!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, SSHPath) and self._conn is other._conn and self._pp == other._pp

    def __hash__(self) -> int:
        return hash((id(self._conn), self._pp))

    def resolve(self) -> "SSHPath":
        return SSHPath(self._conn, PurePosixPath(self._conn.resolve_path(str(self._pp))))

    def relative_to(self, other) -> PurePosixPath:
        other_pp = other._pp if isinstance(other, SSHPath) else PurePosixPath(other)
        return self._pp.relative_to(other_pp)

    def is_relative_to(self, other) -> bool:
        other_pp = other._pp if isinstance(other, SSHPath) else PurePosixPath(other)
        try:
            self._pp.relative_to(other_pp)
            return True
        except ValueError:
            return False

    # ── I/O ──────────────────────────────────────────────────────────────────
    def exists(self) -> bool:
        return self._conn.exists(str(self._pp))

    def is_dir(self) -> bool:
        return self._conn.is_dir(str(self._pp))

    def is_file(self) -> bool:
        return self._conn.is_file(str(self._pp))

    def stat(self):
        return self._conn.stat(str(self._pp))

    def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self._conn.read_bytes(str(self._pp)).decode(encoding, errors)

    def write_text(self, content: str, encoding: str = "utf-8"):
        self._conn.write_bytes(str(self._pp), content.encode(encoding))

    def mkdir(self, parents: bool = False, exist_ok: bool = False):
        self._conn.mkdir(str(self._pp), parents=parents, exist_ok=exist_ok)

    def iterdir(self):
        for name in self._conn.listdir(str(self._pp)):
            yield SSHPath(self._conn, self._pp / name)

    def glob(self, pattern: str):
        yield from self._match(pattern, recursive=False)

    def rglob(self, pattern: str):
        yield from self._match(pattern, recursive=True)

    def _match(self, pattern: str, recursive: bool):
        # Aproximación vía listado plano + fnmatch: no es 100% idéntica a
        # pathlib para patrones exóticos con múltiples '**', pero cubre bien
        # los casos típicos de un agente ("**/*.py", "src/*.ts", "*"). Límite
        # conocido y documentado.
        entries = self._conn.list_files(str(self._pp))
        for rel_str in sorted(entries):
            if not recursive and "/" in rel_str:
                continue
            if fnmatch.fnmatch(rel_str, pattern):
                yield SSHPath(self._conn, self._pp / rel_str)

    # ── ejecución (no es parte de la API de pathlib.Path — extensión propia,
    #    usada por core/tools/shell.py y core/agent_loop.py para despachar) ──
    def run_command(self, command: str, timeout: int = 60, on_wait=None):
        return self._conn.run_command(command, cwd=str(self._pp), timeout=timeout, on_wait=on_wait)

    def close(self):
        """Cierra la conexión SSH subyacente (usado por /disconnect del REPL,
        o al reemplazar este workspace por otro)."""
        self._conn.close()


class RemoteBrowseCancelled(Exception):
    """El usuario canceló el picker interactivo de carpeta remota (Ctrl-C/Ctrl-D)."""


def browse_remote_directory(conn: SSHConnection, start: str = None):
    """Picker interactivo por texto: lista subdirectorios y deja navegar hasta
    elegir la carpeta del proyecto, sin tener que conocer de antemano la ruta
    absoluta. Arranca en `start` (o el home remoto si no se pasa). Devuelve la
    ruta absoluta elegida, o None si el usuario canceló (Ctrl-C/Ctrl-D)."""
    cur = start or conn.home_dir()
    while True:
        dirs = conn.listdir_dirs(cur)
        print(t("remote.browse.header", path=cur))
        for i, d in enumerate(dirs, 1):
            print(f"  {i}. {d}/")
        try:
            choice = input(t("remote.browse.help")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if choice == "":
            return cur
        if choice == "..":
            cur = str(PurePosixPath(cur).parent)
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(dirs):
            cur = posixpath.join(cur.rstrip("/") or "/", dirs[int(choice) - 1])
            continue
        if _WIN_DRIVE_RE.match(choice):
            choice = _win_to_sftp(choice)
        candidate = choice if choice.startswith("/") else posixpath.join(cur.rstrip("/") or "/", choice)
        if conn.is_dir(candidate):
            cur = candidate
        else:
            print(t("remote.browse.invalid", choice=choice))


def resolve_remote_workspace(host_spec: str, remote_path: str = None) -> SSHPath:
    """Conecta a `host_spec` ('usuario@host[:puerto]') y devuelve un `SSHPath`
    listo para usar como `ctx.workspace`. Conecta EAGER: si falla la conexión,
    autenticación o el directorio no existe, levanta acá mismo — antes de
    arrancar el agente, no a mitad de una tarea.

    Si `remote_path` es None, abre un picker interactivo (`browse_remote_directory`)
    para elegir la carpeta navegando desde el home remoto, en vez de exigir de
    antemano la ruta absoluta."""
    conn = SSHConnection(host_spec)
    if remote_path:
        if _WIN_DRIVE_RE.match(remote_path):
            remote_path = _win_to_sftp(remote_path)
        elif not remote_path.startswith("/"):
            conn.close()
            raise ValueError(
                "La ruta remota (--workspace) debe ser absoluta, ej: /home/user/proyecto "
                "(o 'C:\\ruta\\al\\proyecto' si el remoto es Windows)")
        if not conn.is_dir(remote_path):
            conn.close()
            raise RuntimeError(f"{remote_path} no existe o no es un directorio en {host_spec}")
    else:
        picked = browse_remote_directory(conn)
        if picked is None:
            conn.close()
            raise RemoteBrowseCancelled()
        remote_path = picked
    return SSHPath(conn, PurePosixPath(remote_path))
