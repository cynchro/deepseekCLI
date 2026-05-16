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
const workspaceLabel = document.getElementById('workspace-label');

function updateWorkspaceLabel() {
  if (workspaceLabel) {
    workspaceLabel.textContent = workspace
      ? workspace.replace(/^\/home\/\w+/, '~')
      : '';
  }
}
updateWorkspaceLabel();

// ── Comandos reconocidos ──────────────────────────────────────────────────────

const COMMANDS = ['build', 'update', 'fix', 'show', 'history', 'balance', 'doctor', 'upgrade', 'workspace'];

function parseCommand(text) {
  const parts = text.trim().match(/^(\w+)\s*([\s\S]*)$/);
  if (!parts) return null;
  const cmd  = parts[1].toLowerCase();
  const args = parts[2].trim().replace(/^["']|["']$/g, ''); // quitar comillas
  if (COMMANDS.includes(cmd)) return { cmd, args };
  return null;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

function authHeaders()  { return { 'Authorization': `Bearer ${password}` }; }
function jsonHeaders()  { return { ...authHeaders(), 'Content-Type': 'application/json' }; }

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

  // Si es workspace y fue exitoso, guardar en localStorage
  if (cmd === 'workspace' && data.output && !data.output.startsWith('❌')) {
    const match = data.output.match(/`([^`]+)`/);
    if (match) {
      workspace = match[1];
      localStorage.setItem('deep_workspace', workspace);
      updateWorkspaceLabel();
    }
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

// ── Hint de comandos ──────────────────────────────────────────────────────────
// Muestra un tooltip sutil cuando el usuario empieza a escribir un comando

inputEl.addEventListener('input', () => {
  const val  = inputEl.value.trim().toLowerCase();
  const hint = document.getElementById('cmd-hint');
  const map  = {
    'build':     'build "descripción del proyecto"',
    'update':    'update "cambio a aplicar"',
    'fix':       'fix',
    'show':      'show',
    'history':   'history',
    'balance':   'balance',
    'doctor':    'doctor',
    'workspace': 'workspace /ruta/del/directorio',
  };
  const match = Object.keys(map).find(k => val === k || val.startsWith(k + ' '));
  if (hint) {
    hint.textContent = match ? `💡 ${map[match]}` : '';
  }
});

// ── Chips de comandos ─────────────────────────────────────────────────────────

document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    const cmd = chip.textContent.replace(/^\S+\s/, '').trim(); // quitar emoji
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
    // mover cursor al final
    inputEl.selectionStart = inputEl.selectionEnd = inputEl.value.length;
  });
});

// ── PWA ───────────────────────────────────────────────────────────────────────

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => null);
}
