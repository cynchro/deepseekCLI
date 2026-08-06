"""Tests de cli/daemon_client.py: DaemonSession contra un transporte WS fake
(sin abrir sockets reales) y ensure_daemon() con subprocess/requests
mockeados (sin lanzar procesos ni pegarle a la red real)."""
import json
import queue
import sys

import pytest

import cli.daemon_client as daemon_client
from cli.daemon_client import DaemonError, DaemonSession


class FakeTransport:
    """Duck-type de websocket.WebSocket: alcanza con send/recv/close."""

    def __init__(self):
        self.sent = []
        self.closed = False
        self._inbox = queue.Queue()

    def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def push(self, payload: dict) -> None:
        self._inbox.put(json.dumps(payload))

    def recv(self) -> str:
        return self._inbox.get()

    def close(self) -> None:
        self.closed = True


def _connected():
    """DaemonSession ya conectada y atacheada, lista para mandar turnos."""
    t = FakeTransport()
    t.push({"type": "attached", "session_id": "sid1", "workspace": "/ws",
            "mode": "ask", "model": "m1", "busy": False})
    sess = DaemonSession("http://127.0.0.1:8000", "tok", ws_factory=lambda url: t)
    sess.attach(project_dir="/ws")
    t.sent.clear()  # nos interesan solo los mensajes de acá en adelante
    return sess, t


# ── auth / attach ─────────────────────────────────────────────────────────────

def test_init_sends_auth_frame_first():
    t = FakeTransport()
    t.push({"type": "attached", "session_id": "s", "workspace": "/w",
            "mode": "ask", "model": "m", "busy": False})
    DaemonSession("http://127.0.0.1:8000", "tok123", ws_factory=lambda url: t)
    assert t.sent == [{"type": "auth", "token": "tok123"}]


def test_ws_factory_receives_ws_url_derived_from_base_url():
    seen = {}

    def factory(url):
        seen["url"] = url
        t = FakeTransport()
        t.push({"type": "attached", "session_id": "s", "workspace": "/w",
                "mode": "ask", "model": "m", "busy": False})
        return t

    DaemonSession("http://127.0.0.1:8000", "tok", ws_factory=factory)
    assert seen["url"] == "ws://127.0.0.1:8000/ws/session"


def test_attach_updates_session_state():
    t = FakeTransport()
    t.push({"type": "attached", "session_id": "sid1", "workspace": "/ws",
            "mode": "auto", "model": "m1", "busy": True})
    sess = DaemonSession("http://x", "tok", ws_factory=lambda url: t)
    attached = sess.attach(session_id="", project_dir="/ws", mode="ask")
    assert attached["type"] == "attached"
    assert sess.session_id == "sid1"
    assert sess.workspace == "/ws"
    assert sess.mode == "auto"
    assert sess.model == "m1"
    assert sess.busy is True
    assert t.sent[-1] == {"type": "attach", "session_id": "",
                          "project_dir": "/ws", "mode": "ask", "model": None}


# ── run_turn: eventos, confirm round-trip, mode/model sync, busy ──────────────

def test_run_turn_forwards_events_and_returns_done():
    sess, t = _connected()
    t.push({"type": "thinking", "text": "pensando"})
    t.push({"type": "tool_call", "name": "read_file", "args": {"path": "x.py"}})
    t.push({"type": "done", "session_id": "sid1", "success": True,
            "content": "listo", "steps": 3, "stats": {"cost": 1}})

    events = []
    result = sess.run_turn("hola", on_event=lambda k, d: events.append((k, d)),
                           ask_confirm=lambda d, s: "s")

    assert t.sent[0] == {"type": "message", "text": "hola"}
    assert events == [
        ("thinking", {"text": "pensando"}),
        ("tool_call", {"name": "read_file", "args": {"path": "x.py"}}),
    ]
    assert result == {"session_id": "sid1", "success": True, "content": "listo",
                      "steps": 3, "stats": {"cost": 1}}
    assert sess.did_work is True


def test_run_turn_answers_confirm_request_with_ask_confirm_callback():
    sess, t = _connected()
    t.push({"type": "confirm_request", "request_id": "r1",
            "desc": "ejecutar: rm -rf /tmp/x", "is_shell": True})
    t.push({"type": "done", "success": True, "content": "ok", "steps": 1, "stats": {}})

    calls = []

    def ask(desc, is_shell, kind="confirm"):
        calls.append((desc, is_shell, kind))
        return "s"

    sess.run_turn("hola", on_event=lambda k, d: None, ask_confirm=ask)

    assert calls == [("ejecutar: rm -rf /tmp/x", True, "confirm")]
    confirm_msgs = [m for m in t.sent if m["type"] == "confirm_response"]
    assert confirm_msgs == [{"type": "confirm_response", "request_id": "r1", "answer": "s"}]


def test_run_turn_forwards_plan_kind_to_ask_confirm_callback():
    sess, t = _connected()
    t.push({"type": "confirm_request", "request_id": "r1",
            "desc": "el plan propuesto arriba", "is_shell": False, "kind": "plan"})
    t.push({"type": "done", "success": True, "content": "ok", "steps": 1, "stats": {}})

    calls = []

    def ask(desc, is_shell, kind="confirm"):
        calls.append(kind)
        return "s"

    sess.run_turn("hola", on_event=lambda k, d: None, ask_confirm=ask)

    assert calls == ["plan"]


def test_run_turn_forwards_unexpected_plan_proposed_event_to_on_event():
    sess, t = _connected()
    t.push({"type": "plan_proposed", "plan": "1. hacer X"})
    t.push({"type": "done", "success": True, "content": "ok", "steps": 1, "stats": {}})

    events = []
    sess.run_turn("hola", on_event=lambda k, d: events.append((k, d)),
                  ask_confirm=lambda d, s, kind="confirm": "s")

    assert ("plan_proposed", {"plan": "1. hacer X"}) in events


def test_run_turn_updates_mode_and_model_from_broadcast_events():
    sess, t = _connected()
    t.push({"type": "mode_changed", "mode": "yolo"})
    t.push({"type": "model_changed", "model": "deepseek-flash"})
    t.push({"type": "done", "success": True, "content": "ok", "steps": 1, "stats": {}})

    sess.run_turn("hola", on_event=lambda k, d: None, ask_confirm=lambda d, s: "s")

    assert sess.mode == "yolo"
    assert sess.model == "deepseek-flash"


def test_run_turn_returns_busy_without_touching_did_work_flag_semantics():
    sess, t = _connected()
    t.push({"type": "busy", "reason": "turn_in_progress"})

    result = sess.run_turn("hola", on_event=lambda k, d: None, ask_confirm=lambda d, s: "s")

    assert result == {"busy": True, "reason": "turn_in_progress"}
    # se intentó mandar el turno igual (para eso está did_work: aunque lo
    # rechacen por "busy", hubo intención real de trabajar en la sesión).
    assert sess.did_work is True


def test_wait_turn_does_not_resend_message_and_returns_done():
    """wait_turn se usa al reatachear a una sesión que ya estaba `busy`: no
    hay que reenviar el texto (duplicaría el turno), solo escuchar."""
    sess, t = _connected()
    t.push({"type": "thinking", "text": "retomando"})
    t.push({"type": "done", "success": True, "content": "listo", "steps": 2, "stats": {}})

    events = []
    result = sess.wait_turn(on_event=lambda k, d: events.append((k, d)),
                            ask_confirm=lambda d, s: "s")

    assert t.sent == []  # no mandó "message": solo escuchó eventos existentes
    assert events == [("thinking", {"text": "retomando"})]
    assert result == {"success": True, "content": "listo", "steps": 2, "stats": {}}


# ── conexión caída: send/recv/connect deben mapear a DaemonError ──────────────

def test_send_raises_daemon_error_on_broken_transport():
    sess, t = _connected()

    def _raise(raw):
        raise BrokenPipeError("broken pipe")
    t.send = _raise

    with pytest.raises(DaemonError):
        sess.run_turn("hola", on_event=lambda k, d: None, ask_confirm=lambda d, s: "s")


def test_recv_raises_daemon_error_on_broken_transport():
    sess, t = _connected()

    def _raise():
        raise ConnectionResetError("connection reset")
    t.recv = _raise

    with pytest.raises(DaemonError):
        sess.run_turn("hola", on_event=lambda k, d: None, ask_confirm=lambda d, s: "s")


def test_init_raises_daemon_error_when_factory_connection_fails():
    def factory(url):
        raise OSError("connection refused")

    with pytest.raises(DaemonError):
        DaemonSession("http://127.0.0.1:8000", "tok", ws_factory=factory)


# ── stats / finalize ──────────────────────────────────────────────────────────

def test_get_stats_skips_unrelated_broadcasts_until_stats_reply():
    sess, t = _connected()
    t.push({"type": "thinking", "text": "de otro cliente atacheado"})
    t.push({"type": "stats", "successful_calls": 2, "total_tokens_used": 99})

    stats = sess.get_stats()
    assert stats == {"successful_calls": 2, "total_tokens_used": 99}
    assert t.sent[-1] == {"type": "get_stats"}


def test_finalize_waits_for_finalized_reply():
    sess, t = _connected()
    t.push({"type": "info", "text": "algo intermedio"})
    t.push({"type": "finalized"})

    sess.finalize()  # no debe colgarse ni levantar
    assert t.sent[-1] == {"type": "finalize"}


# ── close ─────────────────────────────────────────────────────────────────────

def test_close_closes_underlying_transport():
    sess, t = _connected()
    sess.close()
    assert t.closed is True


def test_close_swallows_transport_errors():
    t = FakeTransport()
    t.push({"type": "attached", "session_id": "s", "workspace": "/w",
            "mode": "ask", "model": "m", "busy": False})

    def _raise():
        raise OSError("socket ya cerrado")
    t.close = _raise

    sess = DaemonSession("http://x", "tok", ws_factory=lambda url: t)
    sess.close()  # no debe levantar


# ── ensure_daemon(): subprocess/requests mockeados, sin red ni procesos reales ─

def test_ensure_daemon_returns_immediately_if_already_alive(monkeypatch):
    monkeypatch.setattr(daemon_client, "ensure_daemon_token", lambda: "tok")
    monkeypatch.setattr(daemon_client, "_is_alive", lambda url, token: True)
    popen_calls = []
    monkeypatch.setattr(daemon_client.subprocess, "Popen",
                        lambda *a, **k: popen_calls.append((a, k)))

    base_url, token = daemon_client.ensure_daemon(port=9999)

    assert base_url == "http://127.0.0.1:9999"
    assert token == "tok"
    assert popen_calls == []  # no hizo falta lanzar nada


def test_ensure_daemon_spawns_deep_serve_and_polls_until_alive(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon_client, "ensure_daemon_token", lambda: "tok")
    monkeypatch.setattr(daemon_client, "_LOG_FILE", tmp_path / "serve.log")
    monkeypatch.setattr(daemon_client.time, "sleep", lambda s: None)

    calls = {"n": 0}

    def fake_is_alive(url, token):
        calls["n"] += 1
        return calls["n"] > 2  # las primeras dos veces "todavía no levantó"

    monkeypatch.setattr(daemon_client, "_is_alive", fake_is_alive)
    popen_calls = []
    monkeypatch.setattr(daemon_client.subprocess, "Popen",
                        lambda *a, **k: popen_calls.append((a, k)))

    base_url, token = daemon_client.ensure_daemon(port=9999)

    assert base_url == "http://127.0.0.1:9999"
    assert len(popen_calls) == 1
    cmd = popen_calls[0][0][0]
    assert cmd[:3] == [sys.executable, "-m", "deep"]
    assert "serve" in cmd
    assert popen_calls[0][1]["start_new_session"] is True


def test_ensure_daemon_raises_daemon_error_if_never_comes_alive(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon_client, "ensure_daemon_token", lambda: "tok")
    monkeypatch.setattr(daemon_client, "_LOG_FILE", tmp_path / "serve.log")
    monkeypatch.setattr(daemon_client, "_is_alive", lambda url, token: False)
    monkeypatch.setattr(daemon_client, "_START_TIMEOUT", 0.05)
    monkeypatch.setattr(daemon_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(daemon_client.subprocess, "Popen", lambda *a, **k: None)

    with pytest.raises(DaemonError):
        daemon_client.ensure_daemon(port=9999)


def test_list_sessions_calls_api_with_auth_header(monkeypatch):
    captured = {}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"sessions": [{"id": "s1"}]}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResp()

    monkeypatch.setattr(daemon_client.requests, "get", fake_get)

    sessions = daemon_client.list_sessions("http://127.0.0.1:8000", "tok")

    assert sessions == [{"id": "s1"}]
    assert captured["url"] == "http://127.0.0.1:8000/api/sessions"
    assert captured["headers"] == {"Authorization": "Bearer tok"}
