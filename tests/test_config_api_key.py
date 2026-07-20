"""Test de prompt_and_save() (core/config.py): exportar la key al rc del shell debe
ser opt-in — por default (Enter/EOF) NO debe escribir en ~/.bashrc ni ~/.zshrc, ya que
deep siempre lee la key desde el config.json (0600) guardado por save_api_key()."""
from unittest.mock import patch

from core import config


def _run_prompt(answers):
    """answers: [api_key, respuesta_al_prompt_de_export]"""
    with patch("builtins.input", side_effect=answers), \
         patch.object(config, "save_api_key") as mock_save, \
         patch.object(config, "_add_to_shell") as mock_shell:
        key = config.prompt_and_save()
    return key, mock_save, mock_shell


def test_default_answer_does_not_touch_shell_rc():
    key, mock_save, mock_shell = _run_prompt(["sk-test123", ""])
    assert key == "sk-test123"
    mock_save.assert_called_once_with("sk-test123")
    mock_shell.assert_not_called()


def test_explicit_no_does_not_touch_shell_rc():
    _, _, mock_shell = _run_prompt(["sk-test123", "n"])
    mock_shell.assert_not_called()


def test_explicit_yes_exports_to_shell_rc():
    key, _, mock_shell = _run_prompt(["sk-test123", "y"])
    mock_shell.assert_called_once_with(key)


def test_eof_on_export_prompt_does_not_crash_or_export():
    with patch("builtins.input", side_effect=["sk-test123", EOFError()]), \
         patch.object(config, "save_api_key"), \
         patch.object(config, "_add_to_shell") as mock_shell:
        key = config.prompt_and_save()
    assert key == "sk-test123"
    mock_shell.assert_not_called()
