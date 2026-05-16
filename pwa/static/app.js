marked.setOptions({ breaks: true, gfm: true });

let password = localStorage.getItem('deep_password') || '';
let sessionId = localStorage.getItem('deep_session') || '';

const authScreen  = document.getElementById('auth-screen');
const chatScreen  = document.getElementById('chat-screen');
const passInput   = document.getElementById('password-input');
const authBtn     = document.getElementById('auth-btn');
const authError   = document.getElementById('auth-error');
const messagesEl  = document.getElementById('messages');
const inputEl     = document.getElementById('input');
const sendBtn     = document.getElementById('send-btn');
const newChatBtn  = document.getElementById('new-chat-btn');
const balanceBtn  = document.getElementById('balance-btn');

// ── Auth ──────────────────────────────────────────────────────────────────────

function authHeaders() {
  return { 'Authorization': `Bearer ${password}` };
}

function jsonHeaders() {
  return { ...authHeaders(), 'Content-Type': 'application/json' };
}

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

// Auto-login si hay password guardada
if (password) {
  fetch('/api/health', { headers: authHeaders() })
    .then(r => r.ok ? showChat() : (localStorage.removeItem('deep_password'), null))
    .catch(() => null);
}

authBtn.addEventListener('click', tryLogin);
passInput.addEventListener('keydown', e => e.key === 'Enter' && tryLogin());

// ── Mensajes ──────────────────────────────────────────────────────────────────

function scrollDown() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addMessage(role, text, loading = false) {
  // Ocultar bienvenida al primer mensaje
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

// ── Send ──────────────────────────────────────────────────────────────────────

async function send() {
  const text = inputEl.value.trim();
  if (!text || sendBtn.disabled) return;

  inputEl.value = '';
  inputEl.style.height = 'auto';
  sendBtn.disabled = true;

  addMessage('user', text);
  const loading = addMessage('assistant', '...', true);

  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ message: text, session_id: sessionId }),
    });

    if (res.status === 401) { logout(); return; }

    const data = await res.json();
    sessionId = data.session_id;
    localStorage.setItem('deep_session', sessionId);

    loading.className = 'message assistant';
    loading.innerHTML = marked.parse(data.response);
    scrollDown();
  } catch {
    loading.className = 'message assistant';
    loading.textContent = '❌ Error al conectar con el servidor.';
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

// ── Nueva conversación ────────────────────────────────────────────────────────

async function newChat() {
  try {
    const res = await fetch('/api/new', { method: 'POST', headers: jsonHeaders() });
    if (res.status === 401) { logout(); return; }
    const data = await res.json();
    sessionId = data.session_id;
    localStorage.setItem('deep_session', sessionId);
    messagesEl.innerHTML = '<div class="welcome"><p>¿En qué puedo ayudarte?</p></div>';
  } catch {
    addMessage('assistant', '❌ No se pudo crear una nueva conversación.');
  }
}

// ── Balance ───────────────────────────────────────────────────────────────────

async function showBalance() {
  try {
    const res = await fetch('/api/balance', { headers: authHeaders() });
    if (res.status === 401) { logout(); return; }
    const data = await res.json();
    const total    = data.balance?.total_balance    ?? data.balance?.available ?? '?';
    const currency = data.balance?.currency ?? 'USD';
    addMessage('assistant', `**Crédito disponible:** ${total} ${currency}`);
  } catch {
    addMessage('assistant', '❌ No se pudo obtener el balance.');
  }
}

// ── Eventos ───────────────────────────────────────────────────────────────────

sendBtn.addEventListener('click', send);
newChatBtn.addEventListener('click', newChat);
balanceBtn.addEventListener('click', showBalance);

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

// ── PWA service worker ────────────────────────────────────────────────────────

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => null);
}
