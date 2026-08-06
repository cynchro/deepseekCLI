"""Tool de navegador: controla una pestaña de Chrome real. El CLI decide solo
qué backend usar, en este orden:

  1. Extensión de Chrome conectada (`chrome_bridge/`, ver `deep browser
     install-extension`): controla el perfil REAL del usuario (cookies,
     sesión logueada) vía `chrome.debugger` dentro del propio navegador,
     tunelizado por Native Messaging + WS hacia este proceso. Es el único
     backend que puede tocar el perfil default — Chrome moderno (M136+)
     bloquea el puerto CDP remoto ahí por seguridad (ver 2).
  2. Si no hay extensión conectada, Playwright/CDP con el mismo auto-detect
     de siempre:
     a. `DEEPSEEK_CDP_URL` (ej. "http://localhost:9222", con Chrome abierto
        vía `--remote-debugging-port=9222`) — override explícito. Solo
        funciona contra un perfil NO default (`--user-data-dir` propio):
        Chrome rechaza el puerto CDP en el perfil default.
     b. Si no, prueba el puerto CDP por defecto (9222) por si ya hay algo
        escuchando ahí (mismo caveat de perfil no-default).
     c. Si no hay nada, lanza un Chromium propio, visible (no headless) —
        así el usuario ve en vivo lo que el agente hace. Si no hay `$DISPLAY`
        (ej. un server por SSH sin X), cae a headless en vez de romper.

DeepSeek acá es un modelo de solo texto: estas tools devuelven texto (DOM,
consola, red, resultado de JS), nunca imágenes. browser_screenshot guarda a
un archivo para que un humano lo revise; el modelo no puede "verlo".
"""
import atexit
import base64
import json
import os
import time

from core.tools.base import ToolContext, safe_path, rel, truncate

_CDP_ENV = "DEEPSEEK_CDP_URL"
_DEFAULT_CDP_URL = "http://localhost:9222"
_CDP_PROBE_TIMEOUT_MS = 2_000  # no esperar 30s default si no hay nada escuchando
_MAX_LOG = 200  # tope de entradas de consola/red guardadas por sesión
_NAV_TIMEOUT_S = 30  # tope esperando document.readyState == "complete"


class _Session:
    """Estado del navegador para un run del agente (vive en ctx.browser)."""

    def __init__(self):
        self.driver = None  # _PlaywrightDriver | _ExtensionDriver, lazy


def _get_session(ctx: ToolContext) -> _Session:
    if ctx.browser is None:
        ctx.browser = _Session()
    return ctx.browser


def _cap(log: list) -> None:
    del log[:-_MAX_LOG]


# ── Backend 1: extensión de Chrome real (chrome.debugger vía chrome_bridge/) ──

def _unwrap_cdp(result: dict):
    """Extrae el valor Python de un resultado de Runtime.evaluate."""
    r = (result or {}).get("result") or {}
    return r.get("value") if "value" in r else r.get("description")


# ── Cursor visual (click/type) ──
# Versión chica del indicador visual que trae la extensión oficial de Claude
# (ahí es un content script aparte que corre todo el tiempo; acá, para no
# tocar el manifest ni agregar otro archivo, se inyecta con el mismo
# Runtime.evaluate que ya se usa para click/type — solo vive mientras dura
# la acción, no de forma persistente). Un punto se desliza hasta el elemento
# ANTES de tocarlo y pulsa al momento del click/type, así se ve en vivo qué
# está por hacer el agente.
_CURSOR_GLIDE_S = 0.28  # un poco más que la transición CSS de abajo (250ms)
_CURSOR_CSS = (
    "position:fixed;width:18px;height:18px;border-radius:50%;"
    "background:rgba(255,70,70,.85);border:2px solid #fff;"
    "box-shadow:0 0 8px rgba(0,0,0,.6);pointer-events:none;z-index:2147483647;"
    "transition:left .25s ease,top .25s ease,transform .15s ease;"
    "transform:translate(-50%,-50%);left:-100px;top:-100px;"
)
_ENSURE_CURSOR_JS = (
    "var __c=document.getElementById('__dscli_cursor__');"
    f"if(!__c){{__c=document.createElement('div');__c.id='__dscli_cursor__';"
    f"__c.style.cssText={json.dumps(_CURSOR_CSS)};"
    "document.documentElement.appendChild(__c);}"
)


def _move_cursor_js(selector: str) -> str:
    sel = json.dumps(selector)
    return (f"(function(){{var el=document.querySelector({sel});"
            f"if(!el) throw new Error('selector no encontrado: '+{sel});"
            f"{_ENSURE_CURSOR_JS}"
            "var r=el.getBoundingClientRect();"
            "__c.style.left=(r.left+r.width/2)+'px';"
            "__c.style.top=(r.top+r.height/2)+'px';"
            "})()")


def _pulse_cursor_js() -> str:
    return (f"(function(){{{_ENSURE_CURSOR_JS}"
            "__c.style.transform='translate(-50%,-50%) scale(1.7)';"
            "setTimeout(function(){__c.style.transform='translate(-50%,-50%) scale(1)';},150);"
            "})()")


class _ExtensionDriver:
    """Habla CDP crudo con la pestaña real del usuario a través de
    `pwa.browser_bridge.BrowserBridge` — mismo protocolo que Playwright usa
    por debajo, tunelizado por la extensión en vez de un puerto TCP. Nunca
    "posee" la ventana: close() solo desadjunta (ver Bridge.detach en
    chrome_bridge/extension/background.js)."""

    def __init__(self, bridge):
        self._bridge = bridge
        self._tab_id = None

    def _ensure_tab(self):
        if self._tab_id is None:
            result = self._bridge.call("Bridge.ensureTab")
            self._tab_id = result.get("tabId")
        return self._tab_id

    def _evaluate(self, expression: str) -> dict:
        tab_id = self._ensure_tab()
        result = self._bridge.call("Runtime.evaluate", {
            "tabId": tab_id, "expression": expression, "returnByValue": True,
        })
        exc = (result or {}).get("exceptionDetails")
        if exc:
            # exceptionDetails.text suele ser un genérico "Uncaught" sin info
            # útil — el mensaje real (incluyendo el del Error de JS) vive en
            # exceptionDetails.exception.description/.value.
            inner = exc.get("exception") or {}
            detail = inner.get("description") or inner.get("value") or exc.get("text") or str(exc)
            raise RuntimeError(detail)
        return result

    def _wait_ready(self, timeout: float = _NAV_TIMEOUT_S, interval: float = 0.2) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _unwrap_cdp(self._evaluate("document.readyState")) == "complete":
                return
            time.sleep(interval)

    def navigate(self, url: str) -> dict:
        tab_id = self._ensure_tab()
        self._bridge.call("Page.navigate", {"tabId": tab_id, "url": url})
        # Sin esta espera, el primer chequeo de _wait_ready() puede leer el
        # documento VIEJO (ej. about:blank, ya "complete") antes de que Chrome
        # arranque la navegación real — título/url quedarían de la página
        # anterior. Confirmado en vivo: navegando desde la pestaña recién
        # creada por Bridge.ensureTab, el título volvía vacío por esta razón.
        time.sleep(0.15)
        self._wait_ready()
        final_url = _unwrap_cdp(self._evaluate("location.href"))
        title = _unwrap_cdp(self._evaluate("document.title"))
        return {"url": final_url, "title": title}

    def read_page(self, selector: str, html: bool) -> str:
        prop = "outerHTML" if html else "innerText"
        if selector:
            sel = json.dumps(selector)
            expr = (f"(function(){{var el=document.querySelector({sel});"
                     f"if(!el) throw new Error('selector no encontrado: '+{sel});"
                     f"return el.{prop};}})()")
        else:
            expr = "document.documentElement.outerHTML" if html else "document.body.innerText"
        return _unwrap_cdp(self._evaluate(expr)) or ""

    def click(self, selector: str) -> None:
        self._evaluate(_move_cursor_js(selector))
        time.sleep(_CURSOR_GLIDE_S)
        self._evaluate(_pulse_cursor_js())
        sel = json.dumps(selector)
        expr = (f"(function(){{var el=document.querySelector({sel});"
                 f"if(!el) throw new Error('selector no encontrado: '+{sel});"
                 f"el.click();}})()")
        self._evaluate(expr)

    def type_text(self, selector: str, text: str, submit: bool) -> None:
        # Simplificación conocida respecto al driver Playwright: escribe el
        # valor directo + eventos input/change en vez de simular tecla por
        # tecla. Para submit, dispatchea Enter (keydown/keyup) en vez de
        # enviar el form — cubre el caso típico (JS que escucha Enter) sin
        # arriesgar un submit duplicado.
        self._evaluate(_move_cursor_js(selector))
        time.sleep(_CURSOR_GLIDE_S)
        self._evaluate(_pulse_cursor_js())
        sel, val = json.dumps(selector), json.dumps(text)
        submit_js = (
            "el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true}));"
            "el.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',bubbles:true}));"
        ) if submit else ""
        expr = (f"(function(){{var el=document.querySelector({sel});"
                 f"if(!el) throw new Error('selector no encontrado: '+{sel});"
                 f"el.focus(); el.value={val};"
                 "el.dispatchEvent(new Event('input',{bubbles:true}));"
                 "el.dispatchEvent(new Event('change',{bubbles:true}));"
                 f"{submit_js}}})()")
        self._evaluate(expr)

    def eval_js(self, script: str):
        return _unwrap_cdp(self._evaluate(script))

    def console(self) -> list:
        if self._tab_id is None:
            return []
        try:
            result = self._bridge.call("Bridge.getConsoleLog", {"tabId": self._tab_id})
        except Exception:
            return []
        return result.get("lines") or []

    def network(self) -> list:
        if self._tab_id is None:
            return []
        try:
            result = self._bridge.call("Bridge.getNetworkLog", {"tabId": self._tab_id})
        except Exception:
            return []
        return result.get("lines") or []

    def screenshot(self, path, full_page: bool) -> None:
        tab_id = self._ensure_tab()
        params = {"tabId": tab_id, "format": "png"}
        if full_page:
            metrics = self._bridge.call("Page.getLayoutMetrics", {"tabId": tab_id})
            size = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
            width, height = int(size.get("width") or 0), int(size.get("height") or 0)
            if width and height:
                params["clip"] = {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}
        result = self._bridge.call("Page.captureScreenshot", params)
        data_b64 = result.get("data")
        if not data_b64:
            raise RuntimeError("la extensión no devolvió datos de screenshot")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(data_b64))

    def close(self) -> bool:
        if self._tab_id is not None:
            try:
                self._bridge.call("Bridge.detach", {"tabId": self._tab_id})
            except Exception:
                pass
            self._tab_id = None
        return False  # nunca posee la ventana real


# ── Backend 2: Playwright/CDP (comportamiento preexistente, sin cambios) ──

def _cleanup_playwright(d: "_PlaywrightDriver") -> None:
    try:
        if d.owns_browser and d.browser:
            d.browser.close()
        if d.playwright:
            d.playwright.stop()
    except Exception:
        pass


class _PlaywrightDriver:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None
        self.owns_browser = False  # True si lo lanzamos nosotros (lo cerramos al terminar)
        self.console_log = []
        self.network_log = []

    def _ensure_page(self):
        if self.page is not None and not self.page.is_closed():
            return self.page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "playwright no está instalado. Instalá con: pip install playwright "
                "&& playwright install chromium"
            )
        self.playwright = sync_playwright().start()
        cdp_url = os.getenv(_CDP_ENV)
        if cdp_url:
            self.browser = self.playwright.chromium.connect_over_cdp(cdp_url)
        else:
            try:
                self.browser = self.playwright.chromium.connect_over_cdp(
                    _DEFAULT_CDP_URL, timeout=_CDP_PROBE_TIMEOUT_MS
                )
            except Exception:
                self.browser = None

        if self.browser is not None:
            self.owns_browser = False
            context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        else:
            try:
                self.browser = self.playwright.chromium.launch(headless=False)
            except Exception:
                # sin display (ej. server por SSH sin X): caer a headless en vez de romper
                self.browser = self.playwright.chromium.launch(headless=True)
            self.owns_browser = True
            context = self.browser.new_context()
        page = context.new_page()
        page.on("console", lambda msg: (self.console_log.append(f"[{msg.type}] {msg.text}"), _cap(self.console_log)))
        page.on("request", lambda req: (self.network_log.append(f"-> {req.method} {req.url}"), _cap(self.network_log)))
        page.on("response", lambda res: (self.network_log.append(f"<- {res.status} {res.url}"), _cap(self.network_log)))
        self.page = page
        atexit.register(_cleanup_playwright, self)
        return page

    def navigate(self, url: str) -> dict:
        page = self._ensure_page()
        page.goto(url, wait_until="load", timeout=30_000)
        return {"url": page.url, "title": page.title()}

    def read_page(self, selector: str, html: bool) -> str:
        page = self._ensure_page()
        if selector:
            loc = page.locator(selector).first
            return loc.inner_html() if html else loc.inner_text()
        return page.content() if html else page.inner_text("body")

    def _show_cursor(self, page, selector: str) -> None:
        # Best-effort: Playwright acepta selectores que no son CSS puro
        # (text=, role=, etc.) que document.querySelector no entiende — si el
        # cursor visual falla, nunca debe romper el click/type real.
        try:
            page.evaluate(_move_cursor_js(selector))
            time.sleep(_CURSOR_GLIDE_S)
            page.evaluate(_pulse_cursor_js())
        except Exception:
            pass

    def click(self, selector: str) -> None:
        page = self._ensure_page()
        self._show_cursor(page, selector)
        page.locator(selector).first.click(timeout=10_000)

    def type_text(self, selector: str, text: str, submit: bool) -> None:
        page = self._ensure_page()
        self._show_cursor(page, selector)
        loc = page.locator(selector).first
        loc.fill(text, timeout=10_000)
        if submit:
            loc.press("Enter")

    def eval_js(self, script: str):
        page = self._ensure_page()
        return page.evaluate(script)

    def console(self) -> list:
        return list(self.console_log)

    def network(self) -> list:
        return list(self.network_log)

    def screenshot(self, path, full_page: bool) -> None:
        page = self._ensure_page()
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=full_page)

    def close(self) -> bool:
        was_owned = self.owns_browser
        _cleanup_playwright(self)
        self.page = None
        return was_owned


def _ensure_driver(ctx: ToolContext):
    s = _get_session(ctx)
    if s.driver is not None:
        return s.driver
    try:
        from pwa.browser_bridge import BRIDGE
    except ImportError:
        # core/tools se importa siempre, incluso sin el extra [serve]/fastapi
        # instalado, y hay caminos reales (deep.py modo "agent", cli/repl.py)
        # donde el AgentLoop corre sin `pwa` disponible — el fallback a
        # Playwright debe seguir andando ahí.
        BRIDGE = None
    if BRIDGE is not None and BRIDGE.is_connected():
        s.driver = _ExtensionDriver(BRIDGE)
    else:
        s.driver = _PlaywrightDriver()
    return s.driver


# ── Tools expuestas al modelo (mismos 8 nombres/schemas de siempre) ──

def browser_navigate(ctx: ToolContext, url: str) -> str:
    try:
        driver = _ensure_driver(ctx)
        info = driver.navigate(url)
    except Exception as e:
        return f"ERROR navegando a {url}: {e}"
    return f"OK: navegado a {info['url']}\ntítulo: {info['title']}"


def browser_read_page(ctx: ToolContext, selector: str = None, html: bool = False) -> str:
    try:
        driver = _ensure_driver(ctx)
        content = driver.read_page(selector, html)
    except Exception as e:
        return f"ERROR leyendo la página: {e}"
    return truncate(content)


def browser_click(ctx: ToolContext, selector: str) -> str:
    try:
        driver = _ensure_driver(ctx)
        driver.click(selector)
    except Exception as e:
        return f"ERROR haciendo click en {selector}: {e}"
    return f"OK: click en {selector}"


def browser_type(ctx: ToolContext, selector: str, text: str, submit: bool = False) -> str:
    try:
        driver = _ensure_driver(ctx)
        driver.type_text(selector, text, submit)
    except Exception as e:
        return f"ERROR escribiendo en {selector}: {e}"
    return f"OK: texto escrito en {selector}" + (" + Enter" if submit else "")


def browser_eval(ctx: ToolContext, script: str) -> str:
    try:
        driver = _ensure_driver(ctx)
        result = driver.eval_js(script)
    except Exception as e:
        return f"ERROR evaluando JS: {e}"
    return truncate(str(result))


def browser_console(ctx: ToolContext) -> str:
    s = _get_session(ctx)
    lines = s.driver.console() if s.driver is not None else []
    if not lines:
        return "(sin mensajes de consola todavía; navegá primero con browser_navigate)"
    return truncate("\n".join(lines))


def browser_network(ctx: ToolContext) -> str:
    s = _get_session(ctx)
    lines = s.driver.network() if s.driver is not None else []
    if not lines:
        return "(sin actividad de red todavía; navegá primero con browser_navigate)"
    return truncate("\n".join(lines))


def browser_screenshot(ctx: ToolContext, path: str = "screenshot.png", full_page: bool = True) -> str:
    try:
        driver = _ensure_driver(ctx)
        p = safe_path(ctx, path)
        driver.screenshot(p, full_page)
    except Exception as e:
        return f"ERROR sacando screenshot: {e}"
    return (f"OK: screenshot guardado en {rel(ctx, p)} "
            "(es para revisión humana; el modelo no puede ver imágenes)")


def browser_close(ctx: ToolContext) -> str:
    s = ctx.browser
    if s is None or s.driver is None:
        return "(no había navegador abierto)"
    was_owned = s.driver.close()
    ctx.browser = None
    return "OK: navegador cerrado" if was_owned else "OK: desconectado (el Chrome real sigue abierto)"


TOOLS = {
    "browser_navigate": {
        "impl": browser_navigate,
        "schema": {
            "name": "browser_navigate",
            "description": ("Navega una pestaña de navegador a una URL. Prioriza una extensión de "
                             "Chrome conectada (controla el perfil REAL del usuario, logueado — ver "
                             "`deep browser install-extension`); si no hay ninguna, se conecta a un "
                             "Chrome real vía CDP si DEEPSEEK_CDP_URL está configurada o si ya hay uno "
                             "escuchando en el puerto 9222; si no encuentra nada, lanza un Chromium "
                             "propio y visible. Usalo para debuggear o scrapear frontend."),
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
            "description": "Cierra la sesión de navegador actual (o la desconecta, si era un Chrome real).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
}
