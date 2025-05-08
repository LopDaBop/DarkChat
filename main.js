// main.js - GlowChat frontend logic
// Handles auth, chat, friends, groups, profile, websocket, navigation

const API = '';
let token = localStorage.getItem('token') || '';
let currentUser = null;
let currentChatId = 'general';
let ws = null;

// --- Utility ---
function setToken(t) {
  token = t;
  if (t) localStorage.setItem('token', t);
  else localStorage.removeItem('token');
}
function api(path, opts = {}) {
  opts.headers = opts.headers || {};
  if (token) opts.headers['Authorization'] = 'Bearer ' + token;
  return fetch(API + path, opts).then(r => {
    if (r.status === 401) logout();
    return r.json();
  });
}
function formatTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString([], { hour: '2-digit', minute: '2-digit', month:'short', day:'numeric' });
}

// --- Navigation ---
function showNav(loggedIn) {
  document.getElementById('nav-login')?.style.setProperty('display', loggedIn ? 'none' : '');
  document.getElementById('nav-register')?.style.setProperty('display', loggedIn ? 'none' : '');
  document.getElementById('nav-logout')?.style.setProperty('display', loggedIn ? '' : 'none');
  document.getElementById('nav-chat')?.style.setProperty('display', loggedIn ? '' : 'none');
  document.getElementById('nav-profile')?.style.setProperty('display', loggedIn ? '' : 'none');
}
function logout() {
  setToken('');
  currentUser = null;
  showNav(false);
  window.location.href = '/login';
}

// --- Auth (Login/Register) ---
function handleLogin() {
  const form = document.getElementById('login-form');
  if (!form) return;
  form.onsubmit = async e => {
    e.preventDefault();
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    try {
      const r = await fetch('/token', {
        method: 'POST',
        body: new URLSearchParams({ username, password }),
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      const data = await r.json();
      if (data.access_token) {
        setToken(data.access_token);
        await fetchCurrentUser();
        showNav(true);
        window.location.href = '/chat';
      } else {
        document.getElementById('login-error').textContent = data.detail || 'Login failed.';
      }
    } catch (e) {
      document.getElementById('login-error').textContent = 'Network error.';
    }
  };
}
function handleRegister() {
  const form = document.getElementById('register-form');
  if (!form) return;
  form.onsubmit = async e => {
    e.preventDefault();
    const username = document.getElementById('register-username').value.trim();
    const password = document.getElementById('register-password').value;
    try {
      const r = await fetch('/register', {
        method: 'POST',
        body: new URLSearchParams({ username, password }),
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      const data = await r.json();
      if (r.ok) {
        window.location.href = '/login';
      } else {
        document.getElementById('register-error').textContent = data.detail || 'Register failed.';
      }
    } catch (e) {
      document.getElementById('register-error').textContent = 'Network error.';
    }
  };
}

// --- Profile ---
async function fetchCurrentUser() {
  try {
    const data = await api('/me');
    currentUser = data;
    return data;
  } catch (e) {
    currentUser = null;
    return null;
  }
}
function handleProfile() {
  if (!document.getElementById('profile-avatar')) return;
  fetchCurrentUser().then(user => {
    if (!user) return logout();
    document.getElementById('profile-avatar').src = user.avatar || 'https://api.dicebear.com/7.x/thumbs/svg?seed=' + encodeURIComponent(user.username);
    document.getElementById('profile-display').textContent = user.display_name || user.username;
    document.getElementById('profile-bio').textContent = user.bio || '';
    document.getElementById('edit-display-name').value = user.display_name || '';
    document.getElementById('edit-bio').value = user.bio || '';
    document.getElementById('edit-avatar').value = user.avatar || '';
  });
  document.getElementById('edit-profile-btn').onclick = () => {
    document.getElementById('profile-edit-form').style.display = '';
    document.getElementById('edit-profile-btn').style.display = 'none';
  };
  document.getElementById('cancel-edit').onclick = () => {
    document.getElementById('profile-edit-form').style.display = 'none';
    document.getElementById('edit-profile-btn').style.display = '';
  };
  document.getElementById('profile-edit-form').onsubmit = async e => {
    e.preventDefault();
    const display_name = document.getElementById('edit-display-name').value;
    const bio = document.getElementById('edit-bio').value;
    const avatar = document.getElementById('edit-avatar').value;
    try {
      const r = await api('/profile/update', {
        method: 'POST',
        body: new URLSearchParams({ display_name, bio, avatar }),
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      document.getElementById('profile-msg').textContent = 'Profile updated!';
      setTimeout(() => document.getElementById('profile-msg').textContent = '', 2000);
      document.getElementById('profile-edit-form').style.display = 'none';
      document.getElementById('edit-profile-btn').style.display = '';
      handleProfile();
    } catch (e) {
      document.getElementById('profile-msg').textContent = 'Update failed.';
    }
  };
}

// --- Chat UI ---
function renderMessage(msg) {
  const div = document.createElement('div');
  div.className = 'message' + (msg.own ? ' own' : '') + (msg.deleted ? ' deleted' : '');
  div.dataset.id = msg.id;
  div.innerHTML = `<span>${msg.deleted ? '[deleted]' : msg.content}</span>
    <span class="meta">${msg.sender} • ${formatTime(msg.timestamp)}${msg.own && !msg.deleted ? ' <button class="delete-btn" title="Delete">×</button>' : ''}</span>`;
  if (msg.own && !msg.deleted) {
    div.querySelector('.delete-btn').onclick = e => {
      e.stopPropagation();
      deleteMessage(msg.id);
    };
  }
  return div;
}
function scrollChatToBottom() {
  const el = document.getElementById('chat-messages');
  if (el) el.scrollTop = el.scrollHeight;
}
function renderMessages(msgs) {
  const box = document.getElementById('chat-messages');
  box.innerHTML = '';
  msgs.forEach(m => box.appendChild(renderMessage(m)));
  scrollChatToBottom();
}
function addMessage(msg) {
  const box = document.getElementById('chat-messages');
  box.appendChild(renderMessage(msg));
  scrollChatToBottom();
}
function removeMessage(msgId) {
  const el = document.querySelector('.message[data-id="' + msgId + '"]');
  if (el) el.classList.add('deleted');
}

// --- Chat logic ---
async function fetchMessages(chatId) {
  const data = await api('/messages/' + encodeURIComponent(chatId));
  return data.map(m => ({ ...m, own: m.sender_id === currentUser?.id }));
}
function connectWS(chatId) {
  if (ws) ws.close();
  ws = new WebSocket(`ws://${window.location.host}/ws/${encodeURIComponent(chatId)}?token=${token}`);
  ws.onmessage = e => {
    const data = JSON.parse(e.data);
    if (data.type === 'message') addMessage({ ...data.message, own: data.message.sender_id === currentUser?.id });
    if (data.type === 'delete') removeMessage(data.id);
  };
}
function sendMessage(chatId, content) {
  if (!ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ type: 'message', content }));
}
function deleteMessage(id) {
  if (!ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ type: 'delete', id }));
}

// --- Sidebar (Chats, Friends, Groups) ---
async function loadSidebar() {
  // Chats
  const chats = await api('/chats/list');
  const chatBox = document.getElementById('sidebar-chats');
  chatBox.innerHTML = '';
  chats.forEach(c => {
    const d = document.createElement('div');
    d.className = 'friend';
    d.textContent = c.name;
    d.onclick = () => switchChat(c.chat_id, c.name);
    chatBox.appendChild(d);
  });
  // Friends
  const friends = await api('/friends/list');
  const friendsBox = document.getElementById('sidebar-friends');
  friendsBox.innerHTML = '';
  friends.forEach(f => {
    const d = document.createElement('div');
    d.className = 'friend';
    d.textContent = f.display_name || f.username;
    d.onclick = () => switchChat(`private_${[currentUser.id, f.id].sort((a,b)=>a-b).join('_')}`, f.display_name || f.username);
    friendsBox.appendChild(d);
  });
  // Groups
  const groups = chats.filter(c => c.type === 'group');
  const groupBox = document.getElementById('sidebar-groups');
  groupBox.innerHTML = '';
  groups.forEach(g => {
    const d = document.createElement('div');
    d.className = 'group';
    d.textContent = g.name;
    d.onclick = () => switchChat(g.chat_id, g.name);
    groupBox.appendChild(d);
  });
}
function switchChat(chatId, name) {
  currentChatId = chatId;
  document.getElementById('chat-header').textContent = name;
  fetchMessages(chatId).then(renderMessages);
  connectWS(chatId);
}

// --- Friends: Search/Add ---
function handleFriendSearch() {
  const form = document.getElementById('friend-search-form');
  if (!form) return;
  form.onsubmit = async e => {
    e.preventDefault();
    const q = document.getElementById('friend-search-input').value.trim();
    if (!q) return;
    const results = await api('/users/search?q=' + encodeURIComponent(q));
    const box = document.getElementById('friend-search-results');
    box.innerHTML = '';
    results.forEach(u => {
      const d = document.createElement('div');
      d.className = 'friend';
      d.innerHTML = `<span>${u.display_name || u.username}</span> <button class="btn" style="margin-left:1rem;">Add</button>`;
      d.querySelector('button').onclick = async ev => {
        ev.stopPropagation();
        await api('/friends/add', {
          method: 'POST',
          body: new URLSearchParams({ friend_id: u.id }),
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
        });
        box.innerHTML = 'Friend request sent!';
      };
      box.appendChild(d);
    });
  };
}

// --- Groups: Create ---
function handleGroupCreate() {
  const form = document.getElementById('group-create-form');
  if (!form) return;
  form.onsubmit = async e => {
    e.preventDefault();
    const name = document.getElementById('group-create-input').value.trim();
    if (!name) return;
    await api('/groups/create', {
      method: 'POST',
      body: new URLSearchParams({ name }),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    });
    form.reset();
    loadSidebar();
  };
}

// --- Chat Input ---
function handleChatInput() {
  const form = document.getElementById('chat-input-form');
  if (!form) return;
  form.onsubmit = e => {
    e.preventDefault();
    const input = document.getElementById('chat-input');
    if (input.value.trim()) {
      sendMessage(currentChatId, input.value.trim());
      input.value = '';
    }
  };
}

// --- On Page Load ---
document.addEventListener('DOMContentLoaded', async () => {
  // Nav
  document.getElementById('nav-logout')?.addEventListener('click', e => { e.preventDefault(); logout(); });
  showNav(!!token);
  // Routing logic for SPA-like experience
  const path = window.location.pathname;
  if (path === '/login') handleLogin();
  else if (path === '/register') handleRegister();
  else if (path === '/profile') { await fetchCurrentUser(); showNav(true); handleProfile(); }
  else if (path === '/chat') {
    await fetchCurrentUser();
    showNav(true);
    await loadSidebar();
    switchChat('general', 'General Chat');
    handleChatInput();
    handleFriendSearch();
    handleGroupCreate();
  }
});

