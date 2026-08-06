"""Tests del daemon multi-sesión (pwa/main.py + pwa/session_hub.py): auth por
primer frame de WS, attach crea/reusa sesión, fan-out a N suscriptores,
confirm round-trip (aceptar y timeout), y rechazo de turnos concurrentes.
AgentLoop/DeepSeekClient van mockeados — no se pega a la API real ni se abren
threads que hagan trabajo de verdad."""
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("DEEP_APP_PASSWORD", "test-token")

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import pwa.main as main_module
import pwa.session_hub as session_hub
from pwa.session_hub import SessionRegistry

TOKEN = main_module.APP_PASSWORD
AUTH_HEADER = {"Authorization": f"Bearer {TOKEN}"}


class FakeClient:
    """Doble de DeepSeekClient: alcanza con get_stats() (para /cost) y
    complete() (para el resumen de journal en finalize())."""

    def get_stats(self):
        return {"successful_calls": 1, "total_tokens_used": 42,
                "cache_hit_tokens": 0, "estimated_cost_usd": 0.001, "by_model": {}}

    def complete(self, messages, model=None, temperature=0.0, max_tokens=1200):
        return {"success": True,
                "content": '{"hecho": "hizo cosas", "decisiones": "", "proximo_paso": "seguir"}'}


class FakeAgentLoop:
    """Doble de AgentLoop: mismo constructor/atributos que usa SessionRegistry,
    pero `run()` es sincrónico e instantáneo salvo que el test le pida simular
    una confirmación pendiente o un turno lento."""

    def __init__(self, client, workspace, *, rules=None, project_context=None,
                 on_event=None, confirm=None, confirm_plan=None, mode="ask",
                 get_mode=None, model="fake-model"):
        self.client = client
        self.workspace = workspace
        self.on_event = on_event or (lambda k, d: None)
        self.confirm = confirm
        self.confirm_plan = confirm_plan
        self.get_mode = get_mode
        self.model = model
        self.behavior = "simple"
        self.sleep_seconds = 0.0
        self.messages = [{"role": "system", "content": "sys"}]

    def reset(self):
        self.messages = self.messages[:1]
        self.on_event("cleared", {})

    def run(self, text):
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        self.messages.append({"role": "user", "content": text})
        if self.behavior == "confirm":
            self.on_event("tool_call", {"name": "run_command", "args": {"command": "echo hi"}})
            allowed = self.confirm("ejecutar: echo hi")
            self.on_event("tool_result", {"name": "run_command",
                                           "result": "ok" if allowed else "denegado"})
        elif self.behavior == "plan":
            self.on_event("plan_proposed", {"plan": "mi plan de prueba"})
            approved = self.confirm_plan("mi plan de prueba")
            self.on_event("tool_result", {"name": "exit_plan_mode",
                                           "result": "aprobado" if approved else "rechazado"})
        self.messages.append({"role": "assistant", "content": f"echo:{text}"})
        return {"success": True, "content": f"echo:{text}", "steps": 1, "stats": {}}


@pytest.fixture(autouse=True)
def fresh_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(session_hub, "AgentLoop", FakeAgentLoop)
    monkeypatch.setattr(session_hub, "DeepSeekClient", lambda key: FakeClient())
    monkeypatch.setattr(main_module, "REGISTRY", SessionRegistry("test-key", tmp_path))
    yield


@pytest.fixture
def client():
    return TestClient(main_module.app)


def _attach(ws, session_id="", project_dir=None, mode="ask"):
    # Cada sesión NUEVA usa su propio directorio temporal: journal.md vive en
    # el filesystem real, así que reusar un path entre tests haría que un
    # /finalize de un test contamine el recap que lee otro.
    if project_dir is None:
        project_dir = tempfile.mkdtemp(prefix="deep-test-pwa-")
    ws.send_json({"type": "auth", "token": TOKEN})
    ws.send_json({"type": "attach", "session_id": session_id,
                  "project_dir": project_dir, "mode": mode})
    return ws.receive_json()


def _drain_until(ws, type_, max_events=20):
    for _ in range(max_events):
        msg = ws.receive_json()
        if msg.get("type") == type_:
            return msg
    raise AssertionError(f"no llegó un evento de tipo {type_!r} en {max_events} mensajes")


# ── auth ──────────────────────────────────────────────────────────────────────

def test_ws_closes_if_first_frame_is_not_auth(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": "attach", "session_id": ""})
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_closes_on_wrong_token(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": "auth", "token": "not-the-token"})
            ws.receive_json()
    assert exc.value.code == 4401


def test_rest_endpoints_require_auth(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 401


# ── attach / sesiones ─────────────────────────────────────────────────────────

def test_attach_creates_session_visible_in_api_sessions(client):
    with client.websocket_connect("/ws/session") as ws:
        attached = _attach(ws)
        assert attached["type"] == "attached"
        sid = attached["session_id"]

    resp = client.get("/api/sessions", headers=AUTH_HEADER)
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()["sessions"]]
    assert sid in ids


def test_attach_with_existing_session_id_reuses_hub(client):
    with client.websocket_connect("/ws/session") as ws1:
        sid = _attach(ws1)["session_id"]
    with client.websocket_connect("/ws/session") as ws2:
        attached2 = _attach(ws2, session_id=sid)
        assert attached2["session_id"] == sid

    resp = client.get("/api/sessions", headers=AUTH_HEADER)
    ids = [s["id"] for s in resp.json()["sessions"]]
    assert ids.count(sid) == 1


# ── fan-out ───────────────────────────────────────────────────────────────────

def test_message_broadcasts_to_all_attached_clients(client):
    with client.websocket_connect("/ws/session") as ws1:
        sid = _attach(ws1)["session_id"]
        with client.websocket_connect("/ws/session") as ws2:
            _attach(ws2, session_id=sid)

            ws1.send_json({"type": "message", "text": "hola"})

            done1 = _drain_until(ws1, "done")
            done2 = _drain_until(ws2, "done")
            assert done1["content"] == "echo:hola"
            assert done2["content"] == "echo:hola"


# ── confirm round-trip ───────────────────────────────────────────────────────

def test_confirm_roundtrip_accept_allows_tool(client):
    with client.websocket_connect("/ws/session") as ws:
        sid = _attach(ws)["session_id"]
        hub = main_module.REGISTRY.get(sid)
        hub.loop.behavior = "confirm"

        ws.send_json({"type": "message", "text": "hola"})
        confirm_req = _drain_until(ws, "confirm_request")
        assert confirm_req["is_shell"] is True

        ws.send_json({"type": "confirm_response",
                      "request_id": confirm_req["request_id"], "answer": "s"})

        tool_result = _drain_until(ws, "tool_result")
        assert tool_result["result"] == "ok"
        _drain_until(ws, "done")


def test_confirm_roundtrip_timeout_denies(client, monkeypatch):
    monkeypatch.setattr(session_hub, "CONFIRM_TIMEOUT", 0.2)
    with client.websocket_connect("/ws/session") as ws:
        sid = _attach(ws)["session_id"]
        hub = main_module.REGISTRY.get(sid)
        hub.loop.behavior = "confirm"

        ws.send_json({"type": "message", "text": "hola"})
        _drain_until(ws, "confirm_request")
        # nadie contesta: debe denegar sola por timeout y terminar el turno.
        tool_result = _drain_until(ws, "tool_result")
        assert tool_result["result"] == "denegado"


# ── turno en curso ───────────────────────────────────────────────────────────

def test_second_message_while_busy_gets_busy_event(client):
    with client.websocket_connect("/ws/session") as ws:
        sid = _attach(ws)["session_id"]
        hub = main_module.REGISTRY.get(sid)
        hub.loop.sleep_seconds = 0.3

        ws.send_json({"type": "message", "text": "primero"})
        time.sleep(0.05)  # dar tiempo a que el worker tome el turn_lock
        ws.send_json({"type": "message", "text": "segundo"})

        busy = _drain_until(ws, "busy")
        assert busy["reason"] == "turn_in_progress"
        done = _drain_until(ws, "done")
        assert done["content"] == "echo:primero"


# ── stats / finalize ──────────────────────────────────────────────────────────

def test_get_stats_returns_client_stats(client):
    with client.websocket_connect("/ws/session") as ws:
        _attach(ws)
        ws.send_json({"type": "get_stats"})
        stats = ws.receive_json()
        assert stats["type"] == "stats"
        assert stats["successful_calls"] == 1
        assert stats["total_tokens_used"] == 42


def test_finalize_writes_journal_entry(client):
    with client.websocket_connect("/ws/session") as ws:
        sid = _attach(ws)["session_id"]
        ws.send_json({"type": "message", "text": "hola"})
        _drain_until(ws, "done")

        ws.send_json({"type": "finalize"})
        finalized = _drain_until(ws, "finalized")
        assert finalized["type"] == "finalized"

    hub = main_module.REGISTRY.get(sid)
    from core import journal as _journal
    recap = _journal.load_recap(Path(hub.workspace))
    assert "hizo cosas" in recap


def test_finalize_without_turns_does_not_write_journal(client):
    with client.websocket_connect("/ws/session") as ws:
        sid = _attach(ws)["session_id"]
        ws.send_json({"type": "finalize"})
        _drain_until(ws, "finalized")

    hub = main_module.REGISTRY.get(sid)
    from core import journal as _journal
    assert _journal.load_recap(Path(hub.workspace)) == ""


# ── plan mode ─────────────────────────────────────────────────────────────────

def test_set_mode_broadcasts_mode_changed_exactly_once(client):
    with client.websocket_connect("/ws/session") as ws:
        _attach(ws)
        ws.send_json({"type": "set_mode", "mode": "plan"})
        changed = _drain_until(ws, "mode_changed")
        assert changed["mode"] == "plan"

        hub_sid = main_module.REGISTRY.list()[0].id
        hub = main_module.REGISTRY.get(hub_sid)
        assert hub.permissions.mode == "plan"

        # No debería llegar un SEGUNDO mode_changed duplicado para el mismo cambio
        # (regresión: pwa/main.py ya no hace un broadcast manual además del que
        # dispara Permissions.set_mode vía on_mode_change).
        ws.send_json({"type": "get_stats"})
        next_msg = ws.receive_json()
        assert next_msg["type"] == "stats"


def test_plan_confirm_request_carries_kind_and_approving_switches_mode(client):
    with client.websocket_connect("/ws/session") as ws:
        sid = _attach(ws, mode="plan")["session_id"]
        hub = main_module.REGISTRY.get(sid)
        hub.loop.behavior = "plan"

        ws.send_json({"type": "message", "text": "proponeme algo"})
        proposed = _drain_until(ws, "plan_proposed")
        assert proposed["plan"] == "mi plan de prueba"

        confirm_req = _drain_until(ws, "confirm_request")
        assert confirm_req["kind"] == "plan"

        ws.send_json({"type": "confirm_response",
                      "request_id": confirm_req["request_id"], "answer": "s"})

        tool_result = _drain_until(ws, "tool_result")
        assert tool_result["result"] == "aprobado"
        _drain_until(ws, "done")
        assert hub.permissions.mode == "ask"  # confirm_plan hizo el cambio real


