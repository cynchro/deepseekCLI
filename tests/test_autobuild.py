"""Tests de cli/autobuild.py: reanudación autónoma ENTRE procesos. Los
comandos git corren de verdad contra un tmp_path (rápidos e inocuos, sin
tocar la red); lo que se mockea es `run_one_iteration` (evita lanzar un
`deep agent` real, que pegaría a la API de DeepSeek) y `time.sleep`."""
import subprocess

import pytest

import cli.autobuild as autobuild


def _git(tmp_path, *args):
    return subprocess.run(["git", *args], cwd=str(tmp_path), capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(autobuild.time, "sleep", lambda s: None)


def _setup_workspace(tmp_path, prompt_text="PRIMER PROMPT", resume_text="PROMPT DE REANUDACION"):
    (tmp_path / "prompt-autonomous.md").write_text(prompt_text)
    (tmp_path / "prompt-resume.md").write_text(resume_text)
    return tmp_path


# ── is_done() ────────────────────────────────────────────────────────────────

def test_is_done_false_without_done_file_configured():
    assert autobuild.is_done(None, autobuild.DEFAULT_DONE_PATTERN) is False


def test_is_done_false_when_file_missing(tmp_path):
    assert autobuild.is_done(tmp_path / "backlog.md", autobuild.DEFAULT_DONE_PATTERN) is False


def test_is_done_false_with_pending_items(tmp_path):
    f = tmp_path / "backlog.md"
    f.write_text("- [x] hecho\n- [ ] falta esto\n")
    assert autobuild.is_done(f, autobuild.DEFAULT_DONE_PATTERN) is False


def test_is_done_true_without_pending_items(tmp_path):
    f = tmp_path / "backlog.md"
    f.write_text("- [x] todo hecho\n- [x] esto también\n")
    assert autobuild.is_done(f, autobuild.DEFAULT_DONE_PATTERN) is True


# ── estado persistente (.deep/autobuild_state.json) ─────────────────────────

def test_load_state_defaults_when_missing(tmp_path):
    state = autobuild.load_state(tmp_path)
    assert state == {"iterations_run": 0, "stagnant_count": 0, "last_commit": ""}


def test_save_and_load_state_roundtrip(tmp_path):
    autobuild.save_state(tmp_path, {"iterations_run": 5, "stagnant_count": 1, "last_commit": "abc"})
    state = autobuild.load_state(tmp_path)
    assert state["iterations_run"] == 5
    assert state["last_commit"] == "abc"
    assert "updated_at" in state


def test_load_state_ignores_corrupt_json(tmp_path):
    p = autobuild.state_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text("{esto no es json valido")
    state = autobuild.load_state(tmp_path)
    assert state["iterations_run"] == 0


# ── git helpers (git real contra tmp_path, sin mocks) ───────────────────────

def test_ensure_git_repo_inits_if_missing(tmp_path):
    assert not (tmp_path / ".git").exists()
    autobuild.ensure_git_repo(tmp_path)
    assert (tmp_path / ".git").exists()


def test_ensure_git_repo_noop_if_already_repo(tmp_path):
    autobuild.ensure_git_repo(tmp_path)
    marker = tmp_path / ".git" / "MARKER"
    marker.write_text("no tocar")
    autobuild.ensure_git_repo(tmp_path)  # no debe reinicializar
    assert marker.exists()


def test_commit_pending_changes_commits_and_returns_true(tmp_path):
    autobuild.ensure_git_repo(tmp_path)
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "a.txt").write_text("hola")
    assert autobuild.commit_pending_changes(tmp_path, "mensaje") is True
    assert autobuild.git_head(tmp_path) != ""


def test_commit_pending_changes_returns_false_when_clean(tmp_path):
    autobuild.ensure_git_repo(tmp_path)
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "test")
    assert autobuild.commit_pending_changes(tmp_path, "mensaje") is False


def test_git_head_empty_string_without_commits(tmp_path):
    autobuild.ensure_git_repo(tmp_path)
    assert autobuild.git_head(tmp_path) == ""


# ── run_autobuild(): orquestación, con run_one_iteration mockeado ──────────

def test_run_autobuild_stops_immediately_if_done_file_already_satisfied(tmp_path, monkeypatch):
    ws = _setup_workspace(tmp_path)
    done = ws / "backlog.md"
    done.write_text("- [x] todo hecho\n")

    def _boom(*a, **k):
        raise AssertionError("no debería llamar a run_one_iteration si ya está 'done'")

    monkeypatch.setattr(autobuild, "run_one_iteration", _boom)

    result = autobuild.run_autobuild(
        workspace=ws, prompt_file=ws / "prompt-autonomous.md",
        resume_file=ws / "prompt-resume.md", done_file=done,
        on_event=lambda *_: None)

    assert result["reason"] == "done"
    assert result["iterations_run"] == 0


def test_run_autobuild_uses_prompt_file_then_resume_file_across_iterations(tmp_path, monkeypatch):
    ws = _setup_workspace(tmp_path)
    seen_prompts = []

    def _fake_iteration(workspace, prompt_text, debug, log_file, timeout):
        seen_prompts.append(prompt_text)
        return 0

    monkeypatch.setattr(autobuild, "run_one_iteration", _fake_iteration)
    monkeypatch.setattr(autobuild, "commit_pending_changes", lambda *a, **k: False)

    result = autobuild.run_autobuild(
        workspace=ws, prompt_file=ws / "prompt-autonomous.md",
        resume_file=ws / "prompt-resume.md", done_file=None,
        max_iterations=3, max_stagnant=99, on_event=lambda *_: None)

    assert result["reason"] == "max_iterations"
    assert result["iterations_run"] == 3
    assert seen_prompts == ["PRIMER PROMPT", "PROMPT DE REANUDACION", "PROMPT DE REANUDACION"]


def test_run_autobuild_stops_when_done_file_satisfied_mid_loop(tmp_path, monkeypatch):
    ws = _setup_workspace(tmp_path)
    done = ws / "backlog.md"
    done.write_text("- [ ] pendiente\n")
    calls = {"n": 0}

    def _fake_iteration(workspace, prompt_text, debug, log_file, timeout):
        calls["n"] += 1
        if calls["n"] == 2:
            done.write_text("- [x] listo\n")  # la 2da iteración "completa" el backlog
        return 0

    monkeypatch.setattr(autobuild, "run_one_iteration", _fake_iteration)
    monkeypatch.setattr(autobuild, "commit_pending_changes", lambda *a, **k: False)

    result = autobuild.run_autobuild(
        workspace=ws, prompt_file=ws / "prompt-autonomous.md",
        resume_file=ws / "prompt-resume.md", done_file=done,
        max_iterations=10, max_stagnant=99, on_event=lambda *_: None)

    assert result["reason"] == "done"
    assert result["iterations_run"] == 2
    assert calls["n"] == 2


def test_run_autobuild_stops_on_stop_file_without_running_iteration(tmp_path, monkeypatch):
    ws = _setup_workspace(tmp_path)
    sp = autobuild.stop_path(ws)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text("")

    def _boom(*a, **k):
        raise AssertionError("no debería correr ninguna iteración")

    monkeypatch.setattr(autobuild, "run_one_iteration", _boom)

    result = autobuild.run_autobuild(
        workspace=ws, prompt_file=ws / "prompt-autonomous.md",
        resume_file=ws / "prompt-resume.md", done_file=None,
        on_event=lambda *_: None)

    assert result["reason"] == "stopped"
    assert not sp.exists()  # se borra al consumirlo


def test_run_autobuild_stops_on_stagnation(tmp_path, monkeypatch):
    ws = _setup_workspace(tmp_path)
    monkeypatch.setattr(autobuild, "run_one_iteration", lambda *a, **k: 0)
    monkeypatch.setattr(autobuild, "commit_pending_changes", lambda *a, **k: False)
    monkeypatch.setattr(autobuild, "git_head", lambda workspace: "sameHASH")  # nunca cambia

    result = autobuild.run_autobuild(
        workspace=ws, prompt_file=ws / "prompt-autonomous.md",
        resume_file=ws / "prompt-resume.md", done_file=None,
        max_iterations=50, max_stagnant=2, on_event=lambda *_: None)

    assert result["reason"] == "stagnant"
    assert result["iterations_run"] == 2  # corta apenas llega al tope de estancamiento


def test_run_autobuild_missing_prompt_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        autobuild.run_autobuild(
            workspace=tmp_path, prompt_file=tmp_path / "prompt-autonomous.md",
            resume_file=tmp_path / "prompt-resume.md", done_file=None,
            on_event=lambda *_: None)


def test_run_autobuild_resumes_iteration_count_from_saved_state(tmp_path, monkeypatch):
    """Si ya había 4 iteraciones corridas en un proceso anterior (persistidas
    en .deep/autobuild_state.json), un run_autobuild nuevo arranca en la 5ta
    y usa resume_file, no prompt_file -- así funciona la reanudación entre
    procesos/sesiones."""
    ws = _setup_workspace(tmp_path)
    autobuild.save_state(ws, {"iterations_run": 4, "stagnant_count": 0, "last_commit": ""})
    seen_prompts = []

    def _fake_iteration(workspace, prompt_text, debug, log_file, timeout):
        seen_prompts.append(prompt_text)
        return 0

    monkeypatch.setattr(autobuild, "run_one_iteration", _fake_iteration)
    monkeypatch.setattr(autobuild, "commit_pending_changes", lambda *a, **k: False)

    result = autobuild.run_autobuild(
        workspace=ws, prompt_file=ws / "prompt-autonomous.md",
        resume_file=ws / "prompt-resume.md", done_file=None,
        max_iterations=5, max_stagnant=99, on_event=lambda *_: None)

    assert result["iterations_run"] == 5
    assert seen_prompts == ["PROMPT DE REANUDACION"]
