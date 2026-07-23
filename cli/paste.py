"""Manejo de texto pegado (bracketed paste) en los REPLs de deep.

Sin esto, prompt_toolkit inserta el texto pegado carácter por carácter vía
`Buffer.insert_text(..., fire_event=True)`, lo que dispara el completer de
slash-commands cada vez que aparece un '/' en el contenido pegado (rutas,
URLs, código). Acá interceptamos `Keys.BracketedPaste` para insertar sin
disparar el completer y, si el pegado es grande, lo colapsamos a un
placeholder tipo "[Pasted text #1 +12 lines]" que se expande recién al leer
la línea completa — igual que en Claude Code.
"""
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

_COLLAPSE_THRESHOLD = 200  # chars: por debajo de esto se inserta tal cual

_pastes: dict = {}
_counter = 0


def reset_pastes() -> None:
    """Limpia los placeholders acumulados. Llamar antes de cada prompt()."""
    global _counter
    _pastes.clear()
    _counter = 0


def _label(data: str) -> str:
    global _counter
    _counter += 1
    n_lines = data.count("\n") + 1
    if n_lines > 1:
        return f"[Pasted text #{_counter} +{n_lines} lines]"
    return f"[Pasted text #{_counter} +{len(data)} chars]"


def paste_key_bindings() -> KeyBindings:
    """Key bindings que reemplazan el manejo default de Keys.BracketedPaste."""
    kb = KeyBindings()

    @kb.add(Keys.BracketedPaste, eager=True)
    def _(event):
        data = event.data.replace("\r\n", "\n").replace("\r", "\n")
        if len(data) > _COLLAPSE_THRESHOLD or "\n" in data:
            label = _label(data)
            _pastes[label] = data
            event.current_buffer.insert_text(label, fire_event=False)
        else:
            event.current_buffer.insert_text(data, fire_event=False)

    return kb


def expand_pastes(text: str) -> str:
    """Sustituye los placeholders de pegado por el texto real de la línea final."""
    for label, data in _pastes.items():
        text = text.replace(label, data)
    return text
