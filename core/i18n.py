"""Lightweight i18n for the console interface.

The UI speaks two languages: Spanish (``es``) and English (the international
default). The saved ``language`` setting drives both the model responses and
the console: if it is ``es`` the interface is in Spanish, otherwise it falls
back to English so users worldwide get an understandable console.
"""

from core.config import load_language

# UI strings keyed by id, then by language. English is the fallback for any
# language that is not Spanish.
_STRINGS = {
    "banner.commands": {
        "es": "  Comandos: agent  build  update  claudejob  ask  fix  show  doctor  upgrade  balance  history  reset  help  exit\n",
        "en": "  Commands: agent  build  update  claudejob  ask  fix  show  doctor  upgrade  balance  history  reset  help  exit\n",
    },
    "help": {
        "es": """
  agent <tarea>          Agente con herramientas (loop estilo Claude Code; conversacional)
  agent <tarea> --auto   Igual, sin pedir permiso para escribir/ejecutar
  build <tarea>          Genera un proyecto completo
  build -t <archivo>     Carga la tarea desde un archivo de texto
  build <tarea> -f       Genera y corrige automáticamente si falla
  build <tarea> --model deepseek-reasoner
  update <cambio>        Modifica el proyecto del directorio actual
  claudejob              Claude planifica (job.md), DeepSeek construye
  claudejob --init       Crea la plantilla job.md para completar con Claude
  claudejob --init --force  Regenera la plantilla aunque exista (guarda .bak)
  claudejob --review     Vuelca estado para que Claude revise el proyecto
  claudejob --fix <md>   Aplica las correcciones que escribió Claude
  ask <pregunta>         Hace una pregunta sin generar proyecto
  fix                    Corrige errores del proyecto actual
  show                   Muestra contexto y archivos del proyecto actual
  serve                  Inicia el servidor web para usar deep desde el celular
  serve --https          Activa HTTPS para instalar la app en el celular
  doctor                 Verifica que todo esté configurado correctamente
  upgrade                Actualiza deep CLI desde GitHub
  balance                Muestra el crédito disponible
  history                Muestra las experiencias acumuladas
  config                 Muestra la configuración guardada
  config set-key         Guarda una nueva API key
  config set-lang        Cambia el idioma (respuestas + interfaz)
  help                   Esta ayuda
  reset / new            Reinicia la conversación actual
  exit / quit / Ctrl+D   Salir
""",
        "en": """
  agent <task>           Tool-using agent (Claude Code-style loop; conversational)
  agent <task> --auto    Same, without asking permission to write/run
  build <task>           Generate a full project
  build -t <file>        Load the task from a text file
  build <task> -f        Generate and auto-fix on failure
  build <task> --model deepseek-reasoner
  update <change>        Modify the project in the current directory
  claudejob              Claude plans (job.md), DeepSeek builds
  claudejob --init       Create the job.md template to fill in with Claude
  claudejob --init --force  Regenerate the template even if it exists (keeps .bak)
  claudejob --review     Dump state for Claude to review the project
  claudejob --fix <md>   Apply the fixes Claude wrote
  ask <question>         Ask a question without generating a project
  fix                    Fix errors in the current project
  show                   Show context and files of the current project
  serve                  Start the web server to use deep from your phone
  serve --https          Enable HTTPS to install the app on your phone
  doctor                 Check that everything is configured correctly
  upgrade                Update deep CLI from GitHub
  balance                Show available credit
  history                Show accumulated experiences
  config                 Show saved configuration
  config set-key         Save a new API key
  config set-lang        Change the language (responses + interface)
  help                   This help
  reset / new            Restart the current conversation
  exit / quit / Ctrl+D   Quit
""",
    },
    "goodbye": {"es": "👋 Hasta luego!", "en": "👋 See you!"},
    "conversation.reset": {
        "es": "  Conversación reiniciada.",
        "en": "  Conversation reset.",
    },
    "conversation.restored": {
        "es": "  💬 Conversación anterior restaurada ({n} {word}). Escribí 'reset' para limpiarla.\n",
        "en": "  💬 Previous conversation restored ({n} {word}). Type 'reset' to clear it.\n",
    },
    "word.message.singular": {"es": "mensaje", "en": "message"},
    "word.message.plural": {"es": "mensajes", "en": "messages"},
    "usage.ask": {"es": "  Uso: ask <pregunta>", "en": "  Usage: ask <question>"},
    "usage.update": {
        "es": "  Uso: update <descripción del cambio>",
        "en": "  Usage: update <change description>",
    },
    "usage.build": {
        "es": "  Uso: build <descripción del proyecto>",
        "en": "  Usage: build <project description>",
    },
    "usage.build.taskfile": {
        "es": "       build -t <archivo>  (carga tarea desde archivo)",
        "en": "       build -t <file>  (load task from file)",
    },
    "usage.agent": {
        "es": "  Uso: agent <tarea>   (conversacional; 'reset' reinicia el agente)",
        "en": "  Usage: agent <task>   (conversational; 'reset' restarts the agent)",
    },
    "usage.skill": {"es": "  Uso: {cmd} <pregunta>", "en": "  Usage: {cmd} <question>"},
    "build.file.notfound": {
        "es": "  ❌ Archivo no encontrado: {path}",
        "en": "  ❌ File not found: {path}",
    },
    "build.file.empty": {
        "es": "  ❌ El archivo está vacío: {path}",
        "en": "  ❌ The file is empty: {path}",
    },
    "build.file.loaded": {
        "es": "  📄 Tarea cargada desde: {path}",
        "en": "  📄 Task loaded from: {path}",
    },
    "unknown.command": {
        "es": "  Comando desconocido: '{cmd}'. Escribí 'help'.",
        "en": "  Unknown command: '{cmd}'. Type 'help'.",
    },
    "prompt_toolkit.missing": {
        "es": "⚠️  prompt_toolkit no encontrado. Instalá con: pip install prompt_toolkit\n   Usando modo básico.\n",
        "en": "⚠️  prompt_toolkit not found. Install with: pip install prompt_toolkit\n   Using basic mode.\n",
    },
    # --- skill meta ---
    "skill.none": {
        "es": "  Sin skills instalados. Creá uno con: skill new <nombre>",
        "en": "  No skills installed. Create one with: skill new <name>",
    },
    "skill.available": {
        "es": "\n  📦 Skills disponibles ({n}):\n",
        "en": "\n  📦 Available skills ({n}):\n",
    },
    "skill.new.name": {"es": "  Nombre del skill: ", "en": "  Skill name: "},
    "skill.new.desc": {"es": "  Descripción breve: ", "en": "  Short description: "},
    "skill.new.prompt": {
        "es": "  System prompt (terminá con una línea que solo diga FIN):",
        "en": "  System prompt (end with a line that only says END):",
    },
    "skill.new.end": {"es": "FIN", "en": "END"},
    "skill.new.empty": {
        "es": "  El system prompt no puede estar vacío.",
        "en": "  The system prompt cannot be empty.",
    },
    "skill.new.local": {
        "es": "  ¿Local al proyecto? [s/N]: ",
        "en": "  Project-local? [y/N]: ",
    },
    "skill.new.saved": {
        "es": "  ✅ Skill '{name}' guardado en {path}",
        "en": "  ✅ Skill '{name}' saved to {path}",
    },
    "skill.unknown.sub": {
        "es": "  Subcomando desconocido: skill {sub}  (list | new)",
        "en": "  Unknown subcommand: skill {sub}  (list | new)",
    },
    "cancelled": {"es": "\n  Cancelado.", "en": "\n  Cancelled."},
    # --- config ---
    "config.api_key": {"es": "  API key : {masked}", "en": "  API key : {masked}"},
    "config.file": {"es": "  Archivo : {path}", "en": "  File    : {path}"},
    "config.nokey": {
        "es": "  No hay API key guardada.",
        "en": "  No API key saved.",
    },
    "config.nokey.hint": {
        "es": "  Usá 'deep config set-key' para guardar una.",
        "en": "  Use 'deep config set-key' to save one.",
    },
    "config.lang": {
        "es": "  Idioma  : {name} ({code})  →  'config set-lang' para cambiar",
        "en": "  Language: {name} ({code})  →  'config set-lang' to change",
    },
    "lang.picker.title": {
        "es": "\n🌐 Idioma (respuestas + interfaz) / Language (responses + interface):\n",
        "en": "\n🌐 Idioma (respuestas + interfaz) / Language (responses + interface):\n",
    },
    "lang.picker.option": {"es": "   Opción [1]: ", "en": "   Option [1]: "},
    "lang.picker.invalid": {"es": "   Opción inválida.", "en": "   Invalid option."},
    "lang.saved": {"es": "   ✅ Idioma guardado: {name}\n", "en": "   ✅ Language saved: {name}\n"},
    # --- agent REPL (agent_repl.py) ---
    "agent.banner.subtitle": {
        "es": "deep · agente DeepSeek",
        "en": "deep · DeepSeek agent",
    },
    "agent.banner.tagline": {
        "es": "Escribí lo que querés hacer en lenguaje natural.",
        "en": "Type what you want to do in natural language.",
    },
    "agent.banner.commands": {
        "es": "Comandos:",
        "en": "Commands:",
    },
    "agent.help": {
        "es": """
  {b}Uso{r}: escribí la tarea en lenguaje natural y el agente la resuelve con sus tools.

  {b}Slash commands{r}
    /init            Explora el proyecto y escribe/actualiza DEEP.md
    /tasks           Muestra el plan de tareas persistente (.deep/tasks.json)
    /mode [m]        Permisos: {modes}  (sin arg muestra el actual)
    /model [pro|flash]  Modelo orquestador del loop (default: pro)
    /lang            Cambia el idioma (respuestas + interfaz)
    /skills          Lista los skills disponibles
    /skill <n> <t>   Corre una tarea aplicando el skill <n>
    /rules           Muestra DEEP.md y .deeprules cargados
    /cost            Tokens y costo estimado por modelo de esta sesión
    /clear /new      Reinicia la conversación del agente
    /balance /history /doctor /show /serve /upgrade   Comandos legacy
    /help            Esta ayuda
    /exit /quit      Salir
""",
        "en": """
  {b}Usage{r}: type the task in natural language and the agent solves it with its tools.

  {b}Slash commands{r}
    /init            Explore the project and write/update DEEP.md
    /tasks           Show the persistent task plan (.deep/tasks.json)
    /mode [m]        Permissions: {modes}  (no arg shows the current one)
    /model [pro|flash]  Loop orchestrator model (default: pro)
    /lang            Change the language (responses + interface)
    /skills          List available skills
    /skill <n> <t>   Run a task applying skill <n>
    /rules           Show loaded DEEP.md and .deeprules
    /cost            Tokens and estimated cost per model this session
    /clear /new      Restart the agent conversation
    /balance /history /doctor /show /serve /upgrade   Legacy commands
    /help            This help
    /exit /quit      Quit
""",
    },
    "agent.unknown.command": {
        "es": "  Comando desconocido: {cmd}. Probá /help",
        "en": "  Unknown command: {cmd}. Try /help",
    },
    "agent.mode.current": {
        "es": "  Modo actual: {b}{mode}{r} — {desc}",
        "en": "  Current mode: {b}{mode}{r} — {desc}",
    },
    "agent.mode.list": {"es": "  Modos: {modes}", "en": "  Modes: {modes}"},
    "agent.mode.invalid": {
        "es": "  Modo inválido. Opciones: {modes}",
        "en": "  Invalid mode. Options: {modes}",
    },
    "agent.mode.set": {"es": "  Modo → {b}{mode}{r} ({desc})", "en": "  Mode → {b}{mode}{r} ({desc})"},
    "agent.model.current": {
        "es": "  Modelo orquestador: {model}",
        "en": "  Orchestrator model: {model}",
    },
    "agent.model.options": {"es": "  Opciones: pro | flash", "en": "  Options: pro | flash"},
    "agent.model.set": {
        "es": "  Modelo orquestador → {model}",
        "en": "  Orchestrator model → {model}",
    },
    "agent.cost.empty": {"es": "  Sin actividad todavía.", "en": "  No activity yet."},
    "agent.cost.summary": {
        "es": "  Llamadas: {calls}  ·  tokens: {tokens}  ·  cache hits: {cache}  ·  costo estimado: ${cost:.4f}",
        "en": "  Calls: {calls}  ·  tokens: {tokens}  ·  cache hits: {cache}  ·  estimated cost: ${cost:.4f}",
    },
    "agent.cost.model": {
        "es": "    {model}: {calls} llamadas · {tokens} tok · {cache} cacheados · ${cost:.4f}",
        "en": "    {model}: {calls} calls · {tokens} tok · {cache} cached · ${cost:.4f}",
    },
    "agent.rules.none": {
        "es": "  Sin DEEP.md ni .deeprules. Creá uno con /init.",
        "en": "  No DEEP.md or .deeprules. Create one with /init.",
    },
    "agent.skills.none": {
        "es": "  Sin skills. Creá uno con: skill new (modo legacy) o agregá un .skill",
        "en": "  No skills. Create one with: skill new (legacy mode) or add a .skill",
    },
    "agent.skills.list": {"es": "  Skills ({n}):", "en": "  Skills ({n}):"},
    "agent.skill.usage": {
        "es": "  Uso: /skill <nombre> <tarea>",
        "en": "  Usage: /skill <name> <task>",
    },
    "agent.skill.notfound": {
        "es": "  Skill '{name}' no encontrado. Ver /skills",
        "en": "  Skill '{name}' not found. See /skills",
    },
    "agent.skill.usage.named": {
        "es": "  Uso: /skill {name} <tarea>",
        "en": "  Usage: /skill {name} <task>",
    },
}

_MODE_HELP = {
    "ask": {
        "es": "pide permiso para escribir y ejecutar (default)",
        "en": "asks permission to write and run (default)",
    },
    "auto": {
        "es": "acepta ediciones de archivos; pregunta para shell",
        "en": "accepts file edits; asks for shell",
    },
    "plan": {
        "es": "solo lectura: bloquea escrituras y shell",
        "en": "read-only: blocks writes and shell",
    },
    "yolo": {
        "es": "acepta todo sin preguntar",
        "en": "accepts everything without asking",
    },
}

_AFFIRMATIVE = {"s", "si", "sí", "y", "yes"}


def ui_lang() -> str:
    """Return the UI language code: 'es' for Spanish, 'en' otherwise."""
    return "es" if (load_language() or "es") == "es" else "en"


def t(key: str, **kwargs) -> str:
    """Translate ``key`` into the current UI language, formatting with kwargs."""
    entry = _STRINGS.get(key, {})
    template = entry.get(ui_lang()) or entry.get("en") or key
    return template.format(**kwargs) if kwargs else template


def is_affirmative(raw: str) -> bool:
    """True if the user typed a 'yes'-like answer (Spanish or English)."""
    return raw.strip().lower() in _AFFIRMATIVE


def mode_help(mode: str) -> str:
    """Translated one-line description of a permission mode."""
    entry = _MODE_HELP.get(mode, {})
    return entry.get(ui_lang()) or entry.get("en") or mode
