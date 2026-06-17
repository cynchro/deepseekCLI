marked.setOptions({ breaks: true, gfm: true });

let password   = localStorage.getItem('deep_password')  || '';
let sessionId  = localStorage.getItem('deep_session')   || '';
let workspace  = localStorage.getItem('deep_workspace') || '';

const authScreen     = document.getElementById('auth-screen');
const chatScreen     = document.getElementById('chat-screen');
const passInput      = document.getElementById('password-input');
const authBtn        = document.getElementById('auth-btn');
const authError      = document.getElementById('auth-error');
const messagesEl     = document.getElementById('messages');
const inputEl        = document.getElementById('input');
const sendBtn        = document.getElementById('send-btn');
const newChatBtn     = document.getElementById('new-chat-btn');
const balanceBtn     = document.getElementById('balance-btn');
const agentBtn       = document.getElementById('agent-btn');
const projectsBtn    = document.getElementById('projects-btn');
const workspaceBtn   = document.getElementById('workspace-btn');
const workspaceLabel = document.getElementById('workspace-label');

// ── Panels ────────────────────────────────────────────────────────────────────

const panelOverlay  = document.getElementById('panel-overlay');
const projectsPanel = document.getElementById('projects-panel');
const closePanelBtn = document.getElementById('close-panel-btn');
const projectsList  = document.getElementById('projects-list');

const dirBrowser    = document.getElementById('dir-browser');
const closeDirBtn   = document.getElementById('close-dir-btn');
const dirUpBtn      = document.getElementById('dir-up-btn');
const dirCurrentEl  = document.getElementById('dir-current');
const dirList       = document.getElementById('dir-list');
const dirSelectBtn  = document.getElementById('dir-select-btn');

const logoEl        = document.querySelector('.logo');
const cmdPalette    = document.getElementById('cmd-palette');

// ── Workspace label ───────────────────────────────────────────────────────────

function updateWorkspaceLabel() {
  if (workspaceLabel) {
    workspaceLabel.textContent = workspace
      ? workspace.replace(/^\/home\/\w+/, '~')
      : 'elegir dir';
  }
}
updateWorkspaceLabel();

// ── Comandos reconocidos ──────────────────────────────────────────────────────

const COMMANDS = ['build', 'update', 'fix', 'show', 'history', 'balance', 'doctor', 'upgrade'];

function parseCommand(text) {
  const parts = text.trim().match(/^(\w+)\s*([\s\S]*)$/);
  if (!parts) return null;
  const cmd  = parts[1].toLowerCase();
  const args = parts[2].trim().replace(/^["']|["']$/g, '');
  if (COMMANDS.includes(cmd)) return { cmd, args };
  return null;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

function authHeaders() { return { 'Authorization': `Bearer ${password}` }; }
function jsonHeaders() { return { ...authHeaders(), 'Content-Type': 'application/json' }; }

async function tryLogin() {
  const pwd = passInput.value.trim();
  if (!pwd) return;
  try {
    const res = await fetch('/api/health', { headers: { 'Authorization': `Bearer ${pwd}` } });
    if (res.ok) {
      password = pwd;
      localStorage.setItem('deep_password', pwd);
      showChat();
    } else {
      authError.classList.remove('hidden');
    }
  } catch {
    authError.textContent = 'No se pudo conectar al servidor.';
    authError.classList.remove('hidden');
  }
}

function showChat() {
  authScreen.classList.add('hidden');
  chatScreen.classList.remove('hidden');
  inputEl.focus();
}

function logout() {
  localStorage.removeItem('deep_password');
  location.reload();
}

if (password) {
  fetch('/api/health', { headers: authHeaders() })
    .then(r => r.ok ? showChat() : (localStorage.removeItem('deep_password'), null))
    .catch(() => null);
}

authBtn.addEventListener('click', tryLogin);
passInput.addEventListener('keydown', e => e.key === 'Enter' && tryLogin());

// ── Mensajes ──────────────────────────────────────────────────────────────────

function scrollDown() { messagesEl.scrollTop = messagesEl.scrollHeight; }

function addMessage(role, text, loading = false) {
  const welcome = messagesEl.querySelector('.welcome');
  if (welcome) welcome.remove();

  const div = document.createElement('div');
  div.className = `message ${role}${loading ? ' loading' : ''}`;

  if (role === 'assistant' && !loading) {
    div.innerHTML = marked.parse(text);
  } else {
    div.textContent = text;
  }

  messagesEl.appendChild(div);
  scrollDown();
  return div;
}

function setLoading(el, text) {
  el.className = 'message assistant';
  el.innerHTML = marked.parse(text);
  scrollDown();
}

// ── Enviar ────────────────────────────────────────────────────────────────────

async function send() {
  const text = inputEl.value.trim();
  if (!text || sendBtn.disabled) return;

  inputEl.value = '';
  inputEl.style.height = 'auto';
  sendBtn.disabled = true;

  addMessage('user', text);
  const loading = addMessage('assistant', '...', true);
  const parsed = parseCommand(text);

  try {
    if (parsed) {
      await runCommand(parsed.cmd, parsed.args, loading);
    } else if (agentMode) {
      await runAgent(text, loading);
    } else {
      await runAsk(text, loading);
    }
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

// ── Ask (conversación) ────────────────────────────────────────────────────────

async function runAsk(text, loadingEl) {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ message: text, session_id: sessionId }),
  });

  if (res.status === 401) { logout(); return; }

  const data = await res.json();
  sessionId = data.session_id;
  localStorage.setItem('deep_session', sessionId);
  setLoading(loadingEl, data.response);
}

// ── Agente (loop con tools, streaming SSE) ─────────────────────────────────────

let agentMode = localStorage.getItem('deep_agent') === '1';

function updateAgentBtn() {
  if (agentBtn) agentBtn.classList.toggle('active', agentMode);
  inputEl.placeholder = agentMode
    ? '🤖 Modo agente: pedí lo que querés hacer…'
    : 'Preguntá algo, o escribí build / fix / show…';
}

if (agentBtn) {
  agentBtn.addEventListener('click', () => {
    agentMode = !agentMode;
    localStorage.setItem('deep_agent', agentMode ? '1' : '0');
    updateAgentBtn();
    inputEl.focus();
  });
}
updateAgentBtn();

function fmtAgentArgs(ev) {
  const a = ev.args || {};
  return a.path || a.command || a.pattern || a.spec || '';
}

async function runAgent(text, loadingEl) {
  const res = await fetch('/api/agent', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ message: text, session_id: sessionId, project_dir: workspace }),
  });
  if (res.status === 401) { logout(); return; }
  if (!res.body) { setLoading(loadingEl, '❌ El navegador no soporta streaming.'); return; }

  loadingEl.className = 'message assistant';
  const steps = [];
  const render = (finalText) => {
    let md = '';
    if (steps.length) md += steps.map(s => `\`${s}\``).join('  \n') + (finalText ? '\n\n' : '');
    if (finalText) md += finalText;
    loadingEl.innerHTML = marked.parse(md || '_pensando…_');
    scrollDown();
  };
  render();

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop();
    for (const part of parts) {
      const line = part.replace(/^data:\s?/, '').trim();
      if (!line) continue;
      let ev; try { ev = JSON.parse(line); } catch { continue; }
      if (ev.type === 'start' && ev.session_id) {
        sessionId = ev.session_id;
        localStorage.setItem('deep_session', sessionId);
      } else if (ev.type === 'tool_call') {
        steps.push(`⚙ ${ev.name} ${fmtAgentArgs(ev)}`.trim());
        render();
      } else if (ev.type === 'build') {
        steps.push(`↳ ${ev.action} con flash`);
        render();
      } else if (ev.type === 'done') {
        render(ev.content || (ev.success ? '✅ Listo.' : '⚠️ Terminó con advertencias.'));
      } else if (ev.type === 'fatal') {
        render(`❌ ${ev.error}`);
      }
    }
  }
}

// ── Comandos CLI ──────────────────────────────────────────────────────────────

const SLOW_COMMANDS = ['build', 'update', 'fix'];

async function runCommand(cmd, args, loadingEl) {
  if (SLOW_COMMANDS.includes(cmd)) {
    loadingEl.textContent = `⚙️ Ejecutando ${cmd}... (puede tardar un momento)`;
  }

  const body = { command: cmd, args, project_dir: workspace };

  const res = await fetch('/api/run', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  });

  if (res.status === 401) { logout(); return; }

  const data = await res.json();

  // Después de build, actualizar workspace al nuevo proyecto
  if (cmd === 'build' && data.project_path) {
    workspace = data.project_path;
    localStorage.setItem('deep_workspace', workspace);
    updateWorkspaceLabel();
    log.info && console.log('workspace actualizado a:', workspace);
  }

  setLoading(loadingEl, data.output || '✅ Listo.');
}

// ── Botones del header ────────────────────────────────────────────────────────

newChatBtn.addEventListener('click', async () => {
  const res = await fetch('/api/new', { method: 'POST', headers: jsonHeaders() });
  if (res.status === 401) { logout(); return; }
  const data = await res.json();
  sessionId = data.session_id;
  localStorage.setItem('deep_session', sessionId);
  messagesEl.innerHTML = '<div class="welcome"><p>¿En qué puedo ayudarte?</p></div>';
});

balanceBtn.addEventListener('click', async () => {
  const loading = addMessage('assistant', '...', true);
  await runCommand('balance', '', loading);
});

// ── Logo toggle paleta de comandos ────────────────────────────────────────────

if (logoEl && cmdPalette) {
  logoEl.addEventListener('click', () => cmdPalette.classList.toggle('hidden'));
}

// ── Chips de comandos ─────────────────────────────────────────────────────────

document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    const cmd = chip.textContent.replace(/^\S+\s/, '').trim();
    const templates = {
      'ask':     'ask ',
      'build':   'build "',
      'fix':     'fix',
      'update':  'update "',
      'show':    'show',
      'history': 'history',
      'balance': 'balance',
    };
    inputEl.value = templates[cmd] || cmd + ' ';
    inputEl.focus();
    inputEl.dispatchEvent(new Event('input'));
    inputEl.selectionStart = inputEl.selectionEnd = inputEl.value.length;
    if (cmdPalette) cmdPalette.classList.add('hidden');
  });
});

// ── Input events ──────────────────────────────────────────────────────────────

sendBtn.addEventListener('click', send);

inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + 'px';
});

inputEl.addEventListener('input', () => {
  const val  = inputEl.value.trim().toLowerCase();
  const hint = document.getElementById('cmd-hint');
  const map  = {
    'build':   'build "descripción del proyecto"',
    'update':  'update "cambio a aplicar"',
    'fix':     'fix',
    'show':    'show',
    'history': 'history',
    'balance': 'balance',
    'doctor':  'doctor',
  };
  const match = Object.keys(map).find(k => val === k || val.startsWith(k + ' '));
  if (hint) hint.textContent = match ? `💡 ${map[match]}` : '';
});

// ── Panel overlay ─────────────────────────────────────────────────────────────

panelOverlay?.addEventListener('click', closeAllPanels);

function closeAllPanels() {
  projectsPanel?.classList.add('hidden');
  dirBrowser?.classList.add('hidden');
  panelOverlay?.classList.add('hidden');
}

// ── Panel de proyectos (historial) ────────────────────────────────────────────

projectsBtn?.addEventListener('click', () => {
  dirBrowser?.classList.add('hidden');
  projectsPanel?.classList.remove('hidden');
  panelOverlay?.classList.remove('hidden');
  loadProjects();
});

closePanelBtn?.addEventListener('click', closeAllPanels);

async function loadProjects() {
  projectsList.innerHTML = '<p class="panel-empty">Cargando...</p>';
  try {
    const res = await fetch('/api/projects', { headers: authHeaders() });
    if (res.status === 401) { logout(); return; }
    const data = await res.json();
    renderProjects(data.projects);
  } catch {
    projectsList.innerHTML = '<p class="panel-empty">Error al cargar proyectos.</p>';
  }
}

function fmtDate(iso) {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}

function truncate(str, n) {
  return str.length > n ? str.slice(0, n) + '…' : str;
}

function renderProjects(projects) {
  if (!projects.length) {
    projectsList.innerHTML = '<p class="panel-empty">No hay proyectos todavía.<br>Usá <code>build</code> para crear uno.</p>';
    return;
  }
  projectsList.innerHTML = '';
  for (const p of projects) {
    const date = fmtDate(p.updated_at || p.timestamp);
    const card = document.createElement('div');
    card.className = 'proj-card';
    card.innerHTML = `
      <div class="proj-info">
        <div class="proj-name">${p.name}</div>
        <div class="proj-task">${truncate(p.task, 90)}</div>
        ${p.last_update ? `<div class="proj-update">🔧 ${truncate(p.last_update, 60)}</div>` : ''}
        <div class="proj-meta">${p.file_count} archivos · ${date}</div>
      </div>
      <div class="proj-actions">
        <button class="proj-select-btn">Abrir</button>
        <button class="proj-delete-btn">🗑</button>
      </div>
    `;
    card.querySelector('.proj-select-btn').addEventListener('click', () => selectProject(p));
    card.querySelector('.proj-delete-btn').addEventListener('click', (e) => deleteProject(p.path, p.name, e.currentTarget, card));
    projectsList.appendChild(card);
  }
}

function selectProject(p) {
  workspace = p.path;
  localStorage.setItem('deep_workspace', p.path);
  updateWorkspaceLabel();
  closeAllPanels();

  const date = fmtDate(p.updated_at || p.timestamp);
  const createdDate = fmtDate(p.timestamp);
  let msg = `**📂 ${p.name}**\n\n`;
  msg += `**Tarea original:** ${p.task}\n\n`;
  if (p.last_update) msg += `**Último update:** ${p.last_update}\n\n`;
  msg += `**Archivos:** ${p.file_count}`;
  if (createdDate) msg += `  ·  **Creado:** ${createdDate}`;
  if (p.updated_at) msg += `  ·  **Modificado:** ${fmtDate(p.updated_at)}`;
  msg += `\n\n---\n**Workspace activo.** Ahora podés:\n- \`update "lo que querés cambiar"\` para modificar el proyecto\n- \`fix\` para corregir errores\n- \`show\` para ver los archivos\n- O simplemente preguntame algo sobre el proyecto`;

  addMessage('assistant', msg);
  inputEl.focus();
}

async function deleteProject(path, name, btn, card) {
  if (!confirm(`¿Eliminar el proyecto "${name}"?\nEsta acción no se puede deshacer.`)) return;
  btn.disabled = true;
  try {
    const res = await fetch('/api/projects', {
      method: 'DELETE',
      headers: jsonHeaders(),
      body: JSON.stringify({ path }),
    });
    if (res.status === 401) { logout(); return; }
    if (res.ok) {
      card.remove();
      if (!projectsList.querySelector('.proj-card')) {
        projectsList.innerHTML = '<p class="panel-empty">No hay proyectos todavía.<br>Usá <code>build</code> para crear uno.</p>';
      }
    } else {
      const data = await res.json();
      alert(data.detail || 'Error al eliminar el proyecto.');
      btn.disabled = false;
    }
  } catch {
    alert('Error de conexión.');
    btn.disabled = false;
  }
}

// ── Explorador de directorios ─────────────────────────────────────────────────

let currentBrowsePath = '';

workspaceBtn?.addEventListener('click', openDirBrowser);
closeDirBtn?.addEventListener('click', closeAllPanels);

function openDirBrowser() {
  projectsPanel?.classList.add('hidden');
  dirBrowser?.classList.remove('hidden');
  panelOverlay?.classList.remove('hidden');
  browseTo(workspace || '~');
}

dirUpBtn?.addEventListener('click', () => {
  if (dirUpBtn.dataset.parent) browseTo(dirUpBtn.dataset.parent);
});

dirSelectBtn?.addEventListener('click', () => {
  if (!currentBrowsePath) return;
  workspace = currentBrowsePath;
  localStorage.setItem('deep_workspace', workspace);
  updateWorkspaceLabel();
  closeAllPanels();
  addMessage('assistant',
    `📂 Workspace: \`${workspace}\`\n\nPodés usar \`build "descripción"\` para crear un proyecto aquí.`);
  inputEl.focus();
});

async function browseTo(path) {
  dirList.innerHTML = '<p class="panel-empty">Cargando...</p>';
  try {
    const params = path ? `?path=${encodeURIComponent(path)}` : '';
    const res = await fetch(`/api/ls${params}`, { headers: authHeaders() });
    if (res.status === 401) { logout(); return; }
    const data = await res.json();

    currentBrowsePath = data.current;
    dirCurrentEl.textContent = data.current.replace(/^\/home\/\w+/, '~');

    if (data.parent) {
      dirUpBtn.dataset.parent = data.parent;
      dirUpBtn.disabled = false;
    } else {
      dirUpBtn.dataset.parent = '';
      dirUpBtn.disabled = true;
    }

    if (!data.dirs.length) {
      dirList.innerHTML = '<p class="panel-empty">Sin subdirectorios.</p>';
      return;
    }

    dirList.innerHTML = '';
    for (const d of data.dirs) {
      const item = document.createElement('div');
      item.className = 'dir-item';
      item.innerHTML = `
        <span class="dir-item-icon">${d.has_project ? '📦' : '📁'}</span>
        <span class="dir-item-name">${d.name}</span>
        ${d.has_project ? '<span class="dir-item-badge">proyecto</span>' : ''}
      `;
      item.addEventListener('click', () => browseTo(d.path));
      dirList.appendChild(item);
    }
  } catch (err) {
    dirList.innerHTML = `<p class="panel-empty">Error al cargar.</p>`;
  }
}

// ── Service worker ────────────────────────────────────────────────────────────

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => null);
  navigator.serviceWorker.getRegistrations().then(regs => {
    regs.forEach(reg => reg.update());
  });
}

// ── PWA install prompt ────────────────────────────────────────────────────────

let deferredPrompt = null;
const installBtn = document.getElementById('install-btn');

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  installBtn?.classList.remove('hidden');
});

installBtn?.addEventListener('click', async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  deferredPrompt = null;
  if (outcome === 'accepted') installBtn?.classList.add('hidden');
});

window.addEventListener('appinstalled', () => {
  installBtn?.classList.add('hidden');
  deferredPrompt = null;
});
