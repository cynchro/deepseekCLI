"""Test de safe_path() (core/tools/base.py): la frontera de seguridad que evita que
una tool escape del workspace vía '../', paths absolutos o symlinks."""
import os

import pytest

from core.tools.base import ToolContext, safe_path


def _ctx(workspace):
    return ToolContext(workspace=workspace)


def test_relative_path_inside_workspace_resolves(tmp_path):
    ctx = _ctx(tmp_path)
    p = safe_path(ctx, "sub/file.txt")
    assert p == (tmp_path / "sub" / "file.txt").resolve()


def test_workspace_root_itself_is_allowed(tmp_path):
    ctx = _ctx(tmp_path)
    assert safe_path(ctx, ".") == tmp_path.resolve()


def test_dotdot_that_stays_inside_workspace_is_allowed(tmp_path):
    (tmp_path / "sub").mkdir()
    ctx = _ctx(tmp_path)
    p = safe_path(ctx, "sub/../file.txt")
    assert p == (tmp_path / "file.txt").resolve()


def test_dotdot_escape_is_blocked(tmp_path):
    ctx = _ctx(tmp_path)
    with pytest.raises(ValueError, match="fuera del workspace"):
        safe_path(ctx, "../escape.txt")


def test_deep_dotdot_escape_is_blocked(tmp_path):
    ctx = _ctx(tmp_path)
    with pytest.raises(ValueError, match="fuera del workspace"):
        safe_path(ctx, "../../../etc/passwd")


def test_absolute_path_outside_workspace_is_blocked(tmp_path):
    ctx = _ctx(tmp_path)
    with pytest.raises(ValueError, match="fuera del workspace"):
        safe_path(ctx, "/etc/passwd")


def test_absolute_path_inside_workspace_is_allowed(tmp_path):
    ctx = _ctx(tmp_path)
    target = tmp_path / "file.txt"
    assert safe_path(ctx, str(target)) == target.resolve()


def test_sibling_dir_with_shared_prefix_is_not_confused_as_inside(tmp_path):
    """workspace='/x/proj' no debe aceptar '/x/proj_evil/file' solo por el prefijo
    de string (is_relative_to() compara componentes de path, no substrings)."""
    workspace = tmp_path / "proj"
    workspace.mkdir()
    sibling = tmp_path / "proj_evil"
    sibling.mkdir()
    ctx = _ctx(workspace)
    with pytest.raises(ValueError, match="fuera del workspace"):
        safe_path(ctx, str(sibling / "file.txt"))


def test_symlink_escaping_workspace_is_blocked(tmp_path):
    workspace = tmp_path / "proj"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secreto")
    link = workspace / "link"
    os.symlink(outside, link)
    ctx = _ctx(workspace)
    with pytest.raises(ValueError, match="fuera del workspace"):
        safe_path(ctx, "link/secret.txt")


def test_symlink_pointing_inside_workspace_is_allowed(tmp_path):
    workspace = tmp_path / "proj"
    workspace.mkdir()
    real_dir = workspace / "real"
    real_dir.mkdir()
    link = workspace / "link"
    os.symlink(real_dir, link)
    ctx = _ctx(workspace)
    p = safe_path(ctx, "link/file.txt")
    assert p == (real_dir / "file.txt").resolve()
