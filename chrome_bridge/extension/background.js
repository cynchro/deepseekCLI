// Service worker de "deepseekcli Browser Bridge". Relay entre el daemon local
// (via Native Messaging) y el chrome.debugger de la pestaña que el agente controla.
//
// Envelope de mensajes (mismo shape en los 3 hops del bridge, ver
// chrome_bridge/native_host.py y pwa/browser_bridge.py):
//   {id, type: "cdp_call", method, params}          -> pedido
//   {id, type: "cdp_result", result}                -> respuesta ok
//   {id, type: "cdp_error", error}                  -> respuesta con error
//
// "method" es un método CDP real (Page.navigate, Runtime.evaluate, ...) o un
// pseudo-método Bridge.* que maneja este archivo directamente (no CDP real).

const HOST_NAME = "com.deepseekcli.browser_bridge";
const MAX_LOG = 200; // mismo tope que _MAX_LOG en core/tools/browser.py

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30000;

let nativePort = null;
let reconnectDelay = RECONNECT_MIN_MS;

// Ring buffers de consola/red, por tabId adjuntado. No sobreviven un reinicio
// del service worker (limitación conocida de Fase 1, ver plan).
const consoleLogs = new Map(); // tabId -> string[]
const networkLogs = new Map(); // tabId -> string[]

function pushLog(map, tabId, line) {
  let arr = map.get(tabId);
  if (!arr) { arr = []; map.set(tabId, arr); }
  arr.push(line);
  if (arr.length > MAX_LOG) arr.splice(0, arr.length - MAX_LOG);
}

async function getCurrentTabId() {
  const stored = await chrome.storage.session.get("tabId");
  return stored.tabId ?? null;
}

async function setCurrentTabId(tabId) {
  await chrome.storage.session.set({ tabId });
}

async function clearCurrentTabId() {
  await chrome.storage.session.remove("tabId");
}

// Adjunta el debugger a `tabId` de forma idempotente: si ya estaba adjunto
// POR NOSOTROS, Chrome tira "Already attached" y lo ignoramos. Si el mensaje
// es otro (típicamente "Another debugger is already attached..."), puede ser
// un attachment nuestro que quedó colgado de un service worker anterior (el
// tabId persiste en chrome.storage.session entre sesiones del daemon, pero
// el service worker puede haberse reiniciado sin avisar) — forzamos detach y
// reintentamos una vez antes de rendirnos.
async function attachDebugger(tabId) {
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
  } catch (e) {
    if (String(e && e.message).includes("Already attached")) {
      // nada que hacer, seguimos
    } else {
      try { await chrome.debugger.detach({ tabId }); } catch (_) {}
      try {
        await chrome.debugger.attach({ tabId }, "1.3");
      } catch (e2) {
        throw new Error(
          "no se pudo adjuntar el debugger a la pestaña (¿tenés DevTools abierto "
          + "ahí? cerralo e intentá de nuevo): " + ((e2 && e2.message) || e2));
      }
    }
  }
  // Dominios necesarios para consola/red — habilitar es idempotente. Solo
  // Runtime.enable para consola (no Log.enable): Chrome espeja las llamadas
  // a console.* en AMBOS dominios (Log.entryAdded y Runtime.consoleAPICalled)
  // — escuchar los dos duplicaba cada línea, confirmado en vivo.
  try { await chrome.debugger.sendCommand({ tabId }, "Runtime.enable"); } catch (_) {}
  try { await chrome.debugger.sendCommand({ tabId }, "Network.enable"); } catch (_) {}
  try { await chrome.debugger.sendCommand({ tabId }, "Page.enable"); } catch (_) {}
}

// Bridge.ensureTab — equivalente a context.new_page() del driver Playwright:
// resuelve la pestaña activa a controlar (o crea una) y se adjunta.
async function bridgeEnsureTab() {
  let tabId = await getCurrentTabId();
  if (tabId !== null) {
    try {
      await chrome.tabs.get(tabId); // sigue existiendo?
      await attachDebugger(tabId);
      return { tabId };
    } catch (_) {
      tabId = null; // la pestaña vieja ya no existe, resolver una nueva
    }
  }
  let [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) {
    tab = await chrome.tabs.create({ url: "about:blank" });
  }
  await attachDebugger(tab.id);
  await setCurrentTabId(tab.id);
  return { tabId: tab.id };
}

// Bridge.detach — usado por browser_close: nunca cierra la ventana real.
async function bridgeDetach() {
  const tabId = await getCurrentTabId();
  if (tabId !== null) {
    try { await chrome.debugger.detach({ tabId }); } catch (_) {}
    consoleLogs.delete(tabId);
    networkLogs.delete(tabId);
    await clearCurrentTabId();
  }
  return { detached: true };
}

function bridgeGetConsoleLog(tabId) {
  return { lines: consoleLogs.get(tabId) || [] };
}

function bridgeGetNetworkLog(tabId) {
  return { lines: networkLogs.get(tabId) || [] };
}

async function handleCall(method, params) {
  if (method === "Bridge.ensureTab") return bridgeEnsureTab();
  if (method === "Bridge.detach") return bridgeDetach();

  // Todo lo demás requiere una pestaña ya adjuntada.
  const tabId = (params && params.tabId) ?? await getCurrentTabId();
  if (tabId === null) throw new Error("no hay pestaña adjuntada; llamá Bridge.ensureTab primero");

  if (method === "Bridge.getConsoleLog") return bridgeGetConsoleLog(tabId);
  if (method === "Bridge.getNetworkLog") return bridgeGetNetworkLog(tabId);

  // No re-adjuntamos acá: Bridge.ensureTab (llamado siempre primero por el
  // driver Python, ver core/tools/browser.py::_ExtensionDriver._ensure_tab)
  // ya garantiza el attach + los dominios habilitados. Repetirlo en cada
  // comando CDP era puro overhead — re-habilitar Runtime/Log en caliente
  // mientras hay eventos en vuelo es además la sospecha más probable de la
  // duplicación de arriba.
  const cdpParams = { ...(params || {}) };
  delete cdpParams.tabId;
  return await chrome.debugger.sendCommand({ tabId }, method, cdpParams);
}

function sendToNative(msg) {
  if (nativePort) {
    try { nativePort.postMessage(msg); } catch (_) { /* puerto ya cerrado */ }
  }
}

async function onNativeMessage(msg) {
  const { id, method, params } = msg || {};
  try {
    const result = await handleCall(method, params);
    sendToNative({ id, type: "cdp_result", result: result ?? {} });
  } catch (e) {
    sendToNative({ id, type: "cdp_error", error: String((e && e.message) || e) });
  }
}

function connectNative() {
  if (nativePort) return;
  try {
    nativePort = chrome.runtime.connectNative(HOST_NAME);
  } catch (e) {
    scheduleReconnect();
    return;
  }
  nativePort.onMessage.addListener((msg) => {
    if (msg && msg.type === "cdp_call") onNativeMessage(msg);
  });
  nativePort.onDisconnect.addListener(() => {
    nativePort = null;
    scheduleReconnect();
  });
  reconnectDelay = RECONNECT_MIN_MS; // conexión ok, resetear backoff
}

function scheduleReconnect() {
  setTimeout(connectNative, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
}

// chrome.debugger.onEvent: acumula consola/red mientras está adjuntado.
// Solo Runtime.consoleAPICalled para consola (ver attachDebugger) — evita
// duplicar cada línea con Log.entryAdded.
chrome.debugger.onEvent.addListener((source, method, params) => {
  const tabId = source.tabId;
  if (tabId === undefined) return;
  if (method === "Runtime.consoleAPICalled") {
    const text = (params.args || []).map((a) => a.value ?? a.description ?? "").join(" ");
    pushLog(consoleLogs, tabId, `[${params.type}] ${text}`);
  } else if (method === "Network.requestWillBeSent") {
    pushLog(networkLogs, tabId, `-> ${params.request.method} ${params.request.url}`);
  } else if (method === "Network.responseReceived") {
    pushLog(networkLogs, tabId, `<- ${params.response.status} ${params.response.url}`);
  }
});

chrome.debugger.onDetach.addListener(async (source) => {
  const tabId = source.tabId;
  if (tabId === undefined) return;
  const current = await getCurrentTabId();
  if (current === tabId) await clearCurrentTabId();
  consoleLogs.delete(tabId);
  networkLogs.delete(tabId);
});

chrome.runtime.onStartup.addListener(connectNative);
chrome.runtime.onInstalled.addListener(connectNative);
connectNative();
