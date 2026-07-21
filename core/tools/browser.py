"""Tool de navegador: controla una pestaña de Chrome real vía Playwright/CDP.

MVP para debugging y scraping de frontend. Por defecto lanza un Chromium
headless aislado; si se define la env var DEEPSEEK_CDP_URL (ej.
"http://localhost:9222", con Chrome abierto vía `--remote-debugging-port=9222`)
se conecta a esa instancia real en vez de lanzar una nueva — así se ve la
sesión logueada del usuario (cookies, perfil) sin construir una extensión.

DeepSeek acá es un modelo de solo texto: estas tools devuelven texto (DOM,
consola, red, resultado de JS), nunca imágenes. browser_screenshot guarda a
un archivo para que un humano lo revise; el modelo no puede "verlo".
"""
import atexit
import os

from core.tools.base import ToolContext, safe_path, rel, truncate

_CDP_ENV = "DEEPSEEK_CDP_URL"
_MAX_LOG = 200  # tope de entradas de consola/red guardadas por sesión


class _Session:
    """Estado del navegador para un run del agente (vive en ctx.browser)."""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None
        self.owns_browser = False  # True si lo lanzamos nosotros (headless)
        self.console_log = []
        self.network_log = []


def _get_session(ctx: ToolContext) -> _Session:
    if ctx.browser is None:
        ctx.browser = _Session()
    return ctx.browser


def _cap(log: list) -> None:
    del log[:-_MAX_LOG]


def _ensure_page(ctx: ToolContext):
    s = _get_session(ctx)
    if s.page is not None and not s.page.is_closed():
        return s.page
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright no está instalado. Instalá con: pip install playwright "
            "&& playwright install chromium"
        )
    s.playwright = sync_playwright().start()
    cdp_url = os.getenv(_CDP_ENV)
    if cdp_url:
        s.browser = s.playwright.chromium.connect_over_cdp(cdp_url)
        s.owns_browser = False
        context = s.browser.contexts[0] if s.browser.contexts else s.browser.new_context()
    else:
        s.browser = s.playwright.chromium.launch(headless=True)
        s.owns_browser = True
        context = s.browser.new_context()
    page = context.new_page()
    page.on("console", lambda msg: (s.console_log.append(f"[{msg.type}] {msg.text}"), _cap(s.console_log)))
    page.on("request", lambda req: (s.network_log.append(f"-> {req.method} {req.url}"), _cap(s.network_log)))
    page.on("response", lambda res: (s.network_log.append(f"<- {res.status} {res.url}"), _cap(s.network_log)))
    s.page = page
    atexit.register(_cleanup, s)
    return page


def _cleanup(s: _Session) -> None:
    try:
        if s.owns_browser and s.browser:
            s.browser.close()
        if s.playwright:
            s.playwright.stop()
    except Exception:
        pass


def browser_navigate(ctx: ToolContext, url: str) -> str:
    try:
        page = _ensure_page(ctx)
        page.goto(url, wait_until="load", timeout=30_000)
    except Exception as e:
        return f"ERROR navegando a {url}: {e}"
    return f"OK: navegado a {page.url}\ntítulo: {page.title()}"


def browser_read_page(ctx: ToolContext, selector: str = None, html: bool = False) -> str:
    try:
        page = _ensure_page(ctx)
        if selector:
            loc = page.locator(selector).first
            content = loc.inner_html() if html else loc.inner_text()
        else:
            content = page.content() if html else page.inner_text("body")
    except Exception as e:
        return f"ERROR leyendo la página: {e}"
    return truncate(content)


def browser_click(ctx: ToolContext, selector: str) -> str:
    try:
        page = _ensure_page(ctx)
        page.locator(selector).first.click(timeout=10_000)
    except Exception as e:
        return f"ERROR haciendo click en {selector}: {e}"
    return f"OK: click en {selector}"


def browser_type(ctx: ToolContext, selector: str, text: str, submit: bool = False) -> str:
    try:
        page = _ensure_page(ctx)
        loc = page.locator(selector).first
        loc.fill(text, timeout=10_000)
        if submit:
            loc.press("Enter")
    except Exception as e:
        return f"ERROR escribiendo en {selector}: {e}"
    return f"OK: texto escrito en {selector}" + (" + Enter" if submit else "")


def browser_eval(ctx: ToolContext, script: str) -> str:
    try:
        page = _ensure_page(ctx)
        result = page.evaluate(script)
    except Exception as e:
        return f"ERROR evaluando JS: {e}"
    return truncate(str(result))


def browser_console(ctx: ToolContext) -> str:
    s = _get_session(ctx)
    if not s.console_log:
        return "(sin mensajes de consola todavía; navegá primero con browser_navigate)"
    return truncate("\n".join(s.console_log))


def browser_network(ctx: ToolContext) -> str:
    s = _get_session(ctx)
    if not s.network_log:
        return "(sin actividad de red todavía; navegá primero con browser_navigate)"
    return truncate("\n".join(s.network_log))


def browser_screenshot(ctx: ToolContext, path: str = "screenshot.png", full_page: bool = True) -> str:
    try:
        page = _ensure_page(ctx)
        p = safe_path(ctx, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(p), full_page=full_page)
    except Exception as e:
        return f"ERROR sacando screenshot: {e}"
    return (f"OK: screenshot guardado en {rel(ctx, p)} "
            "(es para revisión humana; el modelo no puede ver imágenes)")


def browser_close(ctx: ToolContext) -> str:
    s = ctx.browser
    if s is None or s.page is None:
        return "(no había navegador abierto)"
    was_owned = s.owns_browser
    _cleanup(s)
    ctx.browser = None
    return "OK: navegador cerrado" if was_owned else "OK: desconectado (el Chrome real sigue abierto)"


TOOLS = {
    "browser_navigate": {
        "impl": browser_navigate,
        "schema": {
            "name": "browser_navigate",
            "description": ("Navega una pestaña de navegador a una URL. Lanza un Chromium headless "
                             "aislado por defecto, o se conecta a un Chrome real si DEEPSEEK_CDP_URL "
                             "está configurada. Usalo para debuggear o scrapear frontend."),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL a la que navegar"},
                },
                "required": ["url"],
            },
        },
    },
    "browser_read_page": {
        "impl": browser_read_page,
        "schema": {
            "name": "browser_read_page",
            "description": "Lee el texto visible (o HTML) de la página actual o de un elemento puntual.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "Selector CSS (opcional; default toda la página)"},
                    "html": {"type": "boolean", "description": "Devolver HTML en vez de texto plano"},
                },
            },
        },
    },
    "browser_click": {
        "impl": browser_click,
        "schema": {
            "name": "browser_click",
            "description": "Hace click en un elemento de la página actual por selector CSS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "Selector CSS del elemento"},
                },
                "required": ["selector"],
            },
        },
    },
    "browser_type": {
        "impl": browser_type,
        "schema": {
            "name": "browser_type",
            "description": "Escribe texto en un input/textarea de la página actual por selector CSS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "Selector CSS del campo"},
                    "text": {"type": "string", "description": "Texto a escribir"},
                    "submit": {"type": "boolean", "description": "Presionar Enter después de escribir"},
                },
                "required": ["selector", "text"],
            },
        },
    },
    "browser_eval": {
        "impl": browser_eval,
        "schema": {
            "name": "browser_eval",
            "description": "Ejecuta JavaScript en la página actual y devuelve el resultado (serializado a texto).",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "Expresión o función JS a evaluar"},
                },
                "required": ["script"],
            },
        },
    },
    "browser_console": {
        "impl": browser_console,
        "schema": {
            "name": "browser_console",
            "description": "Devuelve los mensajes de consola (log/warn/error) capturados desde que se abrió la página.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "browser_network": {
        "impl": browser_network,
        "schema": {
            "name": "browser_network",
            "description": "Devuelve las requests/responses de red capturadas desde que se abrió la página.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "browser_screenshot": {
        "impl": browser_screenshot,
        "schema": {
            "name": "browser_screenshot",
            "description": ("Guarda una captura de pantalla de la página actual en el workspace. Es solo "
                             "para revisión humana: el modelo no puede ver imágenes."),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa al workspace (default: screenshot.png)"},
                    "full_page": {"type": "boolean", "description": "Capturar toda la página, no solo el viewport visible"},
                },
            },
        },
    },
    "browser_close": {
        "impl": browser_close,
        "schema": {
            "name": "browser_close",
            "description": "Cierra la sesión de navegador actual (o la desconecta, si era un Chrome real vía CDP).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
}
