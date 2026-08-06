# Estado de sesión: extensión de Chrome como backend real del navegador

## Tarea actual

El usuario preguntó si el proyecto tenía Playwright/Chrome, y la conversación derivó en:
probar el auto-detect de CDP existente contra su Chrome real (falló: Chrome M136+ bloquea el
puerto CDP remoto en el perfil default por seguridad) → investigar cómo lo resuelve la
extensión oficial "Claude in Chrome" (permiso `debugger` + Native Messaging, no CDP-por-TCP) →
diseñar (plan mode) y construir el mismo mecanismo para `deepseekcli`: `chrome_bridge/`
(extensión Manifest V3 + native host) + `pwa/browser_bridge.py` (puente sync↔async) +
`core/tools/browser.py` con selección de backend en runtime.

## Progreso

**Completo y verificado end-to-end contra un Chrome real del usuario** (no solo mocks/tests).
Suite completa: 257 passed, 2 skipped.

- **`chrome_bridge/`** (nuevo paquete): `extension/` (manifest.json MV3 con permiso `debugger`,
  `key` fija para ID reproducible — `hgjekbbfnfopnhdgjgmmlncejahjbmcp` —, `background.js` relay
  hacia `chrome.debugger`, íconos generados desde `chinese.png`), `native_host.py` (relay puro
  stdio↔WebSocket vía Native Messaging), `install.py` (detecta navegadores Chromium instalados
  y registra el manifest de Native Messaging Host + launcher ejecutable).
- **`pwa/browser_bridge.py`** (nuevo): `BrowserBridge`, puente sync↔async — mismo patrón que
  `SessionHub._pending_confirms` (dict `id -> (threading.Event, slot)` +
  `asyncio.run_coroutine_threadsafe`). Endpoint nuevo `/ws/browser-bridge` en `pwa/main.py`.
- **`core/tools/browser.py`**: refactor a `_PlaywrightDriver`/`_ExtensionDriver` detrás de
  `_ensure_driver()` — extensión conectada tiene prioridad; si no, cae a la cadena Playwright/CDP
  existente (`DEEPSEEK_CDP_URL` → puerto 9222 → Chromium propio visible). Los 8 nombres de tool
  no cambiaron. `browser_click`/`browser_type` muestran un cursor visual (punto rojo inyectado
  vía `Runtime.evaluate`, se desliza y pulsa) — aplica a ambos drivers.
- **`deep browser install-extension [--port]`**: nuevo comando (`cli/commands.py` +
  subcomando en `deep.py`).
- **Documentación**: README (sección "Navegador" + fila en la tabla de tools),
  `doc/CHANGELOG.md`, `doc/arquitectura.md` (sección 11.4).

## Decisiones clave

- **Por qué no alcanza con CDP por TCP**: Chrome M136+ bloquea `--remote-debugging-port` en el
  perfil default por seguridad (verificado en vivo: el flag se acepta pero el puerto nunca
  abre). Solo una extensión instalada con permiso `debugger` otorgado por el usuario puede tocar
  ese perfil — por eso el mecanismo de Native Messaging + `chrome.debugger`, no un enfoque más
  simple.
- **`BRIDGE` es un singleton de proceso** (un solo Chrome/tab compartido entre todas las
  sesiones del daemon) — aceptado a propósito para esta fase, documentado como limitación.
- **Sin streaming de eventos CDP**: `browser_console`/`browser_network` siguen siendo *pull*
  (el service worker acumula ring buffers de 200 líneas, igual que el driver Playwright).
- **Extensión no publicada en la Chrome Web Store**: se carga "descomprimida", una vez por
  navegador — el `key` fijo en el manifest asegura que el ID no cambie entre recargas.

## Bugs reales encontrados y corregidos en el camino (todos solo aparecían contra un Chrome real)

1. `native_host.py`: `websocket.create_connection(..., timeout=10)` dejaba el timeout puesto
   también para `recv()` → la conexión moría cada 10s de inactividad. Fix: `ws.settimeout(None)`
   después de conectar.
2. `manifest.json`: faltaba el permiso `"storage"` → `chrome.storage.session` tiraba
   `undefined`.
3. `background.js`: `chrome.debugger.attach` a veces da "Another debugger is already attached"
   (attachment obsoleto de una sesión anterior) en vez de "Already attached" → detach forzado +
   reintento.
4. `core/tools/browser.py::_ExtensionDriver.navigate()`: `_wait_ready()` arrancaba a pollear
   `document.readyState` inmediatamente después de `Page.navigate`, podía leer el documento
   VIEJO (ej. `about:blank`, ya "complete") → título/url de la página anterior. Fix: sleep de
   150ms antes de empezar a pollear.
5. `background.js`: `Log.entryAdded` y `Runtime.consoleAPICalled` capturan el MISMO
   `console.log` (Chrome espeja console.\* en ambos dominios CDP) → cada línea aparecía
   duplicada. Fix: solo escuchar `Runtime.consoleAPICalled`.
6. `_move_cursor_js`/`_pulse_cursor_js` (cursor visual): último string literal `"}})()"` sin
   prefijo `f` tenía DOS llaves de cierre en vez de una (el código viejo escondía esto porque
   estaba en un f-string, donde `}}` colapsa a una sola llave) → `SyntaxError` en el navegador.
   Validado con `node --check` después de este bug — hacerlo desde el principio lo hubiera
   evitado.
7. `_evaluate()`: `exceptionDetails.text` de CDP suele ser un genérico "Uncaught" sin info —
   ahora se extrae `exceptionDetails.exception.description` para el mensaje real.

## Próximos pasos

Ninguno pendiente del pedido original. Fuera de alcance, mencionado para contexto futuro:
indicador visual persistente con content script propio (el actual es por-acción, inyectado en
cada click/type); publicación en la Chrome Web Store con ID estable sin "cargar descomprimida";
flag de config persistente para forzar Playwright vs extensión; soporte multi-pestaña/
multi-sesión (reemplazar el `BRIDGE` singleton); chunking de mensajes Native Messaging para
screenshots muy grandes (~1MB de límite por mensaje).

## Contexto importante

- **El árbol de trabajo tenía cambios sin commitear de 4 sesiones distintas** (picker remoto
  SSH, daemon multi-sesión + plan mode + selector de modo, autobuild, y esta) acumulados desde
  hacía rato. Se separaron en 5 commits — uno por feature, más un catch-up de docs que se había
  olvidado en el commit del daemon (`b112bfc`, `15054c5`, `40d1a6a`, `780a613`, y este). La
  extracción quirúrgica de hunks mezclados en el mismo archivo (`core/agent_loop.py`,
  `pwa/main.py`, `cli/commands.py`, `deep.py`, `pyproject.toml`, `README.md`, `doc/CHANGELOG.md`,
  `doc/arquitectura.md`) se hizo reconstruyendo una versión "sin mis cambios" de cada archivo y
  diffeándola contra `HEAD` con `git diff --no-index` (más confiable que armar patches de hunks
  a mano contando líneas).
- Suite de tests: 257 passed, 2 skipped (`python3 -m pytest` desde la raíz del repo).
- `deep serve` quedó corriendo en el puerto 8000 durante la sesión, con la extensión conectada
  — si se retoma esta sesión, puede seguir corriendo o haber sido reiniciado por el usuario.
