// OSRS AFK Roulette — static page, no backend.
// Levels: Wise Old Man API (CORS ok), fallback official hiscores via CORS proxy.
// History/streak/skip tracking lives in this browser's localStorage, keyed per username.

const $ = (id) => document.getElementById(id);

const els = {
  nick: $('nick'), fetchBtn: $('fetch-btn'), f2pOnly: $('f2p-only'),
  fetchStatus: $('fetch-status'), skillsPanel: $('skills-panel'), skillsTitle: $('skills-title'),
  skillsGrid: $('skills-grid'), eligibleCount: $('eligible-count'),
  wheelSection: $('wheel-section'), wheel: $('wheel'), spinBtn: $('spin-btn'),
  resultPanel: $('result-panel'), resultCard: $('result-card'),
  doneBtn: $('done-btn'), discordBtn: $('discord-btn'), rerollBtn: $('reroll-btn'), discordStatus: $('discord-status'),
  statsPanel: $('stats-panel'), statsGrid: $('stats-grid'), skillStats: $('skill-stats'), historyList: $('history-list'),
  leaderboardPanel: $('leaderboard-panel'), leaderboard: $('leaderboard'),
  suggestionsList: $('suggestions-list'), suggestToggle: $('suggest-toggle'), suggestForm: $('suggest-form'),
  sugName: $('sug-name'), sugSkill: $('sug-skill'), sugAfk: $('sug-afk'), sugUrl: $('sug-url'),
  sugNotes: $('sug-notes'), sugF2p: $('sug-f2p'), sugReqs: $('sug-reqs'), sugSubmit: $('sug-submit'),
  suggestStatus: $('suggest-status'), voteStatus: $('vote-status'),
};

let approvedTasks = []; // community-approved suggestions, merged into the pool
function allTasks() { return TASKS.concat(approvedTasks); }

// Shared leaderboard API (Flask + SQLite on afk.rosu.fi). If it's unreachable,
// everything falls back to this browser's localStorage.
const API_BASE = 'https://afk-api.rosu.fi';
let serverStats = null; // own row from the leaderboard, when the API is reachable

async function apiGet(path) {
  const r = await fetch(API_BASE + path);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}
async function apiPost(path, body) {
  const r = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}
function normKey(n) { return n.toLowerCase().replace(/[_-]/g, ' '); }

let playerLevels = null;   // { attack: 60, ... }
let playerName = '';
let wheelTasks = [];       // tasks currently on the wheel
let currentTask = null;
let spinning = false;

// ---------- Helpers ----------

function setStatus(el, msg, kind) {
  el.textContent = msg;
  el.className = 'status ' + kind;
  el.classList.remove('hidden');
}
function clearStatus(el) { el.classList.add('hidden'); }

function todayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function taskUrl(task) {
  if (!task.url) return null;
  return task.url.startsWith('http') ? task.url : WIKI_BASE + task.url;
}
function iconUrl(skill) { return new URL(SKILL_META[skill].icon, location.href).href; }
function iconImg(skill) { return `<img class="skill-icon" src="${SKILL_META[skill].icon}" alt="${SKILL_META[skill].name}">`; }

// ---------- History / highscores (localStorage) ----------

function getHistory() {
  try { return JSON.parse(localStorage.getItem('afk_history') || '[]'); }
  catch (_) { return []; }
}
function saveHistory(h) { localStorage.setItem('afk_history', JSON.stringify(h)); }

function logEntry(status, task) {
  const h = getHistory();
  h.push({ d: todayKey(), nick: playerName, task: task.name, skill: task.skill, status });
  saveHistory(h);
}

// Log locally (offline backup) + push to the shared API, then refresh views.
function recordEvent(status, task) {
  logEntry(status, task);
  apiPost('/api/events', { nick: playerName, date: todayKey(), task: task.name, skill: task.skill, status })
    .catch(() => {})
    .finally(() => { renderStats(); renderLeaderboard(); });
}

// One-time upload of pre-backend localStorage history so streaks carry over.
async function syncLocalHistory() {
  if (localStorage.getItem('afk_synced')) return;
  const h = getHistory();
  if (!h.length) { localStorage.setItem('afk_synced', '1'); return; }
  try {
    await apiPost('/api/events/bulk', {
      events: h.map((e) => ({ nick: e.nick, date: e.d, task: e.task, skill: e.skill, status: e.status })),
    });
    localStorage.setItem('afk_synced', '1');
  } catch (_) { /* retry next visit */ }
}

function doneToday() {
  return getHistory().some((e) => e.d === todayKey() && e.nick === playerName && e.status === 'done');
}

function computeStats(nick) {
  const entries = getHistory().filter((e) => e.nick === nick);
  const done = entries.filter((e) => e.status === 'done');
  const skips = entries.filter((e) => e.status === 'skipped').length;

  // Streaks over unique days with a completed task
  const days = [...new Set(done.map((e) => e.d))].sort();
  let best = 0, run = 0, prev = null;
  const dayMs = 86400000;
  for (const d of days) {
    const t = new Date(d + 'T00:00:00').getTime();
    run = (prev !== null && t - prev === dayMs) ? run + 1 : 1;
    best = Math.max(best, run);
    prev = t;
  }
  // Current streak: consecutive days ending today (or yesterday if today isn't done yet)
  let current = 0;
  if (days.length) {
    const today = new Date(todayKey() + 'T00:00:00').getTime();
    const last = new Date(days[days.length - 1] + 'T00:00:00').getTime();
    if (today - last <= dayMs) {
      current = 1;
      for (let i = days.length - 1; i > 0; i--) {
        const a = new Date(days[i] + 'T00:00:00').getTime();
        const b = new Date(days[i - 1] + 'T00:00:00').getTime();
        if (a - b === dayMs) current++; else break;
      }
    }
  }

  const bySkill = {};
  for (const e of done) bySkill[e.skill] = (bySkill[e.skill] || 0) + 1;

  return { doneCount: done.length, skips, current, best, bySkill, entries };
}

async function renderStats() {
  if (!playerName) return;
  let s, hist;
  try {
    const [lb, h] = await Promise.all([
      apiGet('/api/leaderboard'),
      apiGet(`/api/history?nick=${encodeURIComponent(playerName)}&limit=15`),
    ]);
    const own = lb.players.find((p) => normKey(p.nick) === normKey(playerName));
    serverStats = own || { current: 0, best: 0, done: 0, skips: 0, bySkill: {} };
    s = { current: serverStats.current, best: serverStats.best, doneCount: serverStats.done, skips: serverStats.skips, bySkill: serverStats.bySkill || {} };
    hist = h.entries;
  } catch (_) {
    // API unreachable — fall back to this browser's local history
    serverStats = null;
    const local = computeStats(playerName);
    s = local;
    hist = local.entries.slice(-15).reverse();
  }

  els.statsGrid.innerHTML = `
    <div class="stat-card"><div class="stat-value">🔥 ${s.current}</div><div class="stat-label">Current streak (days)</div></div>
    <div class="stat-card"><div class="stat-value">🏅 ${s.best}</div><div class="stat-label">Best streak</div></div>
    <div class="stat-card"><div class="stat-value">✅ ${s.doneCount}</div><div class="stat-label">Tasks done</div></div>
    <div class="stat-card"><div class="stat-value">⏭️ ${s.skips}</div><div class="stat-label">Skips used</div></div>`;

  const skills = Object.entries(s.bySkill).sort((a, b) => b[1] - a[1]);
  els.skillStats.innerHTML = skills.length
    ? skills.map(([sk, n]) => `<span class="skill-stat-chip">${iconImg(sk)} ${SKILL_META[sk].name} <b>${n}</b></span>`).join('')
    : '<span class="hint">Nothing completed yet — get AFKing!</span>';

  els.historyList.innerHTML = hist.length
    ? hist.map((e) => `
        <div class="history-row ${e.status}">
          <span class="h-date">${e.d}</span>
          ${iconImg(e.skill)}
          <span class="h-task">${e.task}</span>
          <span class="h-status">${e.status === 'done' ? '✅ done' : '⏭️ skipped'}</span>
        </div>`).join('')
    : '<span class="hint">No history yet.</span>';

  els.statsPanel.classList.remove('hidden');
}

async function renderLeaderboard() {
  try {
    const lb = await apiGet('/api/leaderboard');
    if (!lb.players.length) {
      els.leaderboard.innerHTML = '<span class="hint">No players yet — be the first!</span>';
    } else {
      const medal = (i) => ['🥇', '🥈', '🥉'][i] || `${i + 1}.`;
      els.leaderboard.innerHTML = `
        <table class="lb-table">
          <thead><tr><th class="lb-rank">#</th><th>Player</th><th class="lb-num">🔥 Streak</th><th class="lb-num">🏅 Best</th><th class="lb-num">✅ Done</th><th class="lb-num">⏭️ Skips</th></tr></thead>
          <tbody>
            ${lb.players.map((p, i) => `
              <tr class="${playerName && normKey(p.nick) === normKey(playerName) ? 'me' : ''}">
                <td class="lb-rank">${medal(i)}</td>
                <td>${p.nick}</td>
                <td class="lb-num">${p.current}</td>
                <td class="lb-num">${p.best}</td>
                <td class="lb-num">${p.done}</td>
                <td class="lb-num">${p.skips}</td>
              </tr>`).join('')}
          </tbody>
        </table>`;
    }
    els.leaderboardPanel.classList.remove('hidden');
  } catch (_) {
    els.leaderboardPanel.classList.add('hidden'); // API down — hide quietly
  }
}

// ---------- Level fetching ----------

const WOM_SKILL_MAP = { runecrafting: 'runecraft' }; // WOM uses a different key

async function fetchFromWOM(nick) {
  const enc = encodeURIComponent(nick);
  let res = await fetch(`https://api.wiseoldman.net/v2/players/${enc}`);
  if (res.status === 404) {
    // Not tracked yet — ask WOM to look the player up on the hiscores
    res = await fetch(`https://api.wiseoldman.net/v2/players/${enc}`, { method: 'POST' });
  }
  if (!res.ok) throw new Error(`WOM ${res.status}`);
  const data = await res.json();
  const skills = data.latestSnapshot && data.latestSnapshot.data && data.latestSnapshot.data.skills;
  if (!skills) throw new Error('WOM: no snapshot');
  const levels = {};
  for (const [key, val] of Object.entries(skills)) {
    const norm = WOM_SKILL_MAP[key] || key;
    if (SKILL_META[norm] && typeof val.level === 'number') levels[norm] = Math.max(1, val.level);
  }
  return levels;
}

async function fetchFromHiscores(nick) {
  const target = `https://secure.runescape.com/m=hiscore_oldschool/index_lite.json?player=${encodeURIComponent(nick)}`;
  const res = await fetch(`https://api.allorigins.win/raw?url=${encodeURIComponent(target)}`);
  if (!res.ok) throw new Error(`Hiscores ${res.status}`);
  const data = await res.json();
  if (!data.skills) throw new Error('Hiscores: no skills');
  const levels = {};
  for (const s of data.skills) {
    const key = s.name.toLowerCase().replace(/\s+/g, '');
    if (SKILL_META[key]) levels[key] = Math.max(1, s.level);
  }
  return levels;
}

async function fetchLevels() {
  const nick = els.nick.value.trim();
  if (!nick) { setStatus(els.fetchStatus, 'Enter a username first!', 'error'); return; }

  els.fetchBtn.disabled = true;
  setStatus(els.fetchStatus, `Fetching levels for ${nick}…`, 'info');

  try {
    playerLevels = await fetchFromWOM(nick);
  } catch (e1) {
    try {
      setStatus(els.fetchStatus, 'Wise Old Man did not respond, trying the official hiscores…', 'info');
      playerLevels = await fetchFromHiscores(nick);
    } catch (e2) {
      console.error(e1, e2);
      setStatus(els.fetchStatus, `Player "${nick}" was not found on the hiscores. Check the name (hiscores only list players with at least one skill in the top 2M).`, 'error');
      els.fetchBtn.disabled = false;
      return;
    }
  }

  playerName = nick;
  localStorage.setItem('afk_nick', nick);
  els.fetchBtn.disabled = false;
  clearStatus(els.fetchStatus);
  renderSkills();
  updateEligible();
  checkExistingDaily();
  await syncLocalHistory();
  renderStats();
  renderLeaderboard();
  loadSuggestions(); // re-render with own votes highlighted
}

// ---------- UI ----------

function renderSkills() {
  els.skillsTitle.textContent = `${playerName} — levels`;
  els.skillsGrid.innerHTML = '';
  for (const [key, meta] of Object.entries(SKILL_META)) {
    if (!(key in playerLevels)) continue;
    const cell = document.createElement('div');
    cell.className = 'skill-cell';
    cell.innerHTML = `${iconImg(key)}<span>${meta.name}</span><span class="lvl">${playerLevels[key]}</span>`;
    els.skillsGrid.appendChild(cell);
  }
  els.skillsPanel.classList.remove('hidden');
  els.wheelSection.classList.remove('hidden');
}

function eligibleTasks() {
  if (!playerLevels) return [];
  const f2p = els.f2pOnly.checked;
  return allTasks().filter((t) => {
    if (f2p && !t.f2p) return false;
    return Object.entries(t.reqs).every(([skill, lvl]) => (playerLevels[skill] || 1) >= lvl);
  });
}

function updateEligible() {
  const n = eligibleTasks().length;
  els.eligibleCount.textContent = `${allTasks().length} tasks in the pool — available to you: ${n}`;
  els.spinBtn.disabled = n === 0;
  if (playerLevels) drawIdleWheel();
}

// ---------- Roulette wheel ----------

const WHEEL_COLORS = ['#8e44ad', '#c0392b', '#27ae60', '#2980b9', '#d35400', '#16a085', '#7f6000', '#5b2c6f', '#a04000', '#1e8449', '#884ea0', '#b03a2e', '#1f618d', '#9c640c'];
const MAX_SEGMENTS = 14;

// Preload skill icons for canvas drawing
const ICON_IMGS = {};
{
  let loaded = 0;
  const keys = Object.keys(SKILL_META);
  for (const key of keys) {
    const img = new Image();
    img.onload = img.onerror = () => { if (++loaded === keys.length && playerLevels) drawIdleWheel(); };
    img.src = SKILL_META[key].icon;
    ICON_IMGS[key] = img;
  }
}

function pickWheelTasks() {
  const pool = [...eligibleTasks()];
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  return pool.slice(0, MAX_SEGMENTS);
}

function drawWheel(tasks, rotation) {
  const ctx = els.wheel.getContext('2d');
  const W = els.wheel.width, cx = W / 2, cy = W / 2, r = W / 2 - 10;
  ctx.clearRect(0, 0, W, W);
  const n = tasks.length;
  if (n === 0) return;
  const seg = (2 * Math.PI) / n;

  for (let i = 0; i < n; i++) {
    const start = rotation + i * seg;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, start, start + seg);
    ctx.closePath();
    ctx.fillStyle = WHEEL_COLORS[i % WHEEL_COLORS.length];
    ctx.fill();
    ctx.strokeStyle = '#1a1410';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Skill icon near the rim + task name to its left
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(start + seg / 2);
    const icon = ICON_IMGS[tasks[i].skill];
    if (icon && icon.complete && icon.naturalWidth) {
      ctx.drawImage(icon, r - 32, -10, 20, 20);
    }
    ctx.textAlign = 'right';
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 13px Georgia';
    ctx.shadowColor = 'rgba(0,0,0,0.7)';
    ctx.shadowBlur = 3;
    let label = tasks[i].name;
    if (label.length > 24) label = label.slice(0, 22) + '…';
    ctx.fillText(label, r - 38, 5);
    ctx.restore();
  }

  // Hub
  ctx.beginPath();
  ctx.arc(cx, cy, 34, 0, 2 * Math.PI);
  ctx.fillStyle = '#f5c542';
  ctx.fill();
  ctx.strokeStyle = '#7a5f1e';
  ctx.lineWidth = 4;
  ctx.stroke();
  ctx.fillStyle = '#241a08';
  ctx.font = '22px Georgia';
  ctx.textAlign = 'center';
  ctx.fillText('⚔️', cx, cy + 8);

  // Outer rim
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, 2 * Math.PI);
  ctx.strokeStyle = '#f5c542';
  ctx.lineWidth = 6;
  ctx.stroke();
}

function drawIdleWheel() {
  wheelTasks = pickWheelTasks();
  drawWheel(wheelTasks, -Math.PI / 2);
}

function spin() {
  if (spinning) return;
  wheelTasks = pickWheelTasks();
  if (wheelTasks.length === 0) return;
  spinning = true;
  els.spinBtn.disabled = true;
  els.resultPanel.classList.add('hidden');
  clearStatus(els.discordStatus);

  const n = wheelTasks.length;
  const seg = (2 * Math.PI) / n;
  const winner = Math.floor(Math.random() * n);
  // Pointer sits at the top (-90°); rotate so the winning segment's center lands on it.
  const pointerAngle = -Math.PI / 2;
  const targetRotation = pointerAngle - (winner * seg + seg / 2);
  const fullTurns = 5 + Math.floor(Math.random() * 3); // 5–7 turns
  const startRotation = -Math.PI / 2;
  const totalDelta = fullTurns * 2 * Math.PI + (((targetRotation - startRotation) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  const duration = 5500;
  const t0 = performance.now();

  function frame(now) {
    const t = Math.min(1, (now - t0) / duration);
    const eased = 1 - Math.pow(1 - t, 4); // easeOutQuart
    drawWheel(wheelTasks, startRotation + totalDelta * eased);
    if (t < 1) {
      requestAnimationFrame(frame);
    } else {
      spinning = false;
      els.spinBtn.disabled = false;
      onSpinEnd(wheelTasks[winner]);
    }
  }
  requestAnimationFrame(frame);
}

// ---------- Result ----------

function onSpinEnd(task) {
  currentTask = task;
  localStorage.setItem('afk_daily', JSON.stringify({ date: todayKey(), nick: playerName, task }));
  renderResult(task, false);
}

function renderResult(task, restored) {
  const meta = SKILL_META[task.skill];
  const reqStr = Object.entries(task.reqs)
    .map(([s, l]) => `${SKILL_META[s].name} ${l}`)
    .join(', ');
  const url = taskUrl(task);
  const nameHtml = url
    ? `<a href="${url}" target="_blank" rel="noopener">${task.name}</a> 🔗`
    : task.name;
  els.resultCard.innerHTML = `
    <div class="task-name">${iconImg(task.skill)} ${nameHtml}</div>
    <div class="task-skill">Skill: <b>${meta.name}</b> (yours: ${playerLevels ? (playerLevels[task.skill] || '?') : '?'})</div>
    <div class="task-meta">
      <div>⏱️ AFK time: ~${task.afk} per click</div>
      <div>📋 Requirements: ${reqStr}</div>
      ${task.notes ? `<div>💡 ${task.notes}</div>` : ''}
      ${restored ? '<div><i>(today\'s previously rolled task)</i></div>' : ''}
    </div>`;
  updateDoneBtn();
  els.resultPanel.classList.remove('hidden');
  if (!restored) els.resultPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function updateDoneBtn() {
  if (doneToday()) {
    els.doneBtn.disabled = true;
    els.doneBtn.textContent = '✅ Done today!';
  } else {
    els.doneBtn.disabled = false;
    els.doneBtn.textContent = '✅ Mark as done';
  }
}

function markDone() {
  if (!currentTask || doneToday()) return;
  recordEvent('done', currentTask);
  updateDoneBtn();
}

function skipAndReroll() {
  if (spinning) return;
  // A skip only counts if there's a task rolled today that hasn't been completed
  if (currentTask && !doneToday()) {
    recordEvent('skipped', currentTask);
  }
  els.resultPanel.classList.add('hidden');
  spin();
}

function checkExistingDaily() {
  try {
    const saved = JSON.parse(localStorage.getItem('afk_daily') || 'null');
    if (saved && saved.date === todayKey() && saved.nick === playerName && saved.task) {
      currentTask = saved.task;
      renderResult(saved.task, true);
    }
  } catch (_) { /* ignore */ }
}

// ---------- Discord ----------

async function sendToDiscord() {
  if (!currentTask) return;
  // The channel webhook lives on the server — the API builds the embed and posts it.
  const reqStr = Object.entries(currentTask.reqs).map(([s, l]) => `${SKILL_META[s].name} ${l}`).join(', ');
  els.discordBtn.disabled = true;
  try {
    await apiPost('/api/announce', {
      nick: playerName,
      task: {
        name: currentTask.name,
        skill: currentTask.skill,
        afk: currentTask.afk,
        reqs: reqStr,
        notes: currentTask.notes || '',
        url: taskUrl(currentTask) || '',
      },
    });
    setStatus(els.discordStatus, '✅ Sent to the Discord channel!', 'success');
  } catch (e) {
    console.error(e);
    setStatus(els.discordStatus, String(e).includes('429')
      ? 'Slow down — you can post again in half a minute.'
      : 'Sending failed — try again in a moment.', 'error');
  }
  els.discordBtn.disabled = false;
}

// ---------- Task suggestions & voting ----------

async function loadApprovedTasks() {
  try {
    const r = await apiGet('/api/tasks/approved');
    approvedTasks = r.tasks;
    if (playerLevels) updateEligible();
  } catch (_) { /* pool just stays at the built-in tasks */ }
}

async function loadSuggestions() {
  try {
    const r = await apiGet(`/api/suggestions${playerName ? `?nick=${encodeURIComponent(playerName)}` : ''}`);
    if (!r.suggestions.length) {
      els.suggestionsList.innerHTML = '<span class="hint">No open suggestions — be the first to suggest one!</span>';
      return;
    }
    els.suggestionsList.innerHTML = r.suggestions.map((s) => {
      const reqStr = Object.entries(s.reqs).map(([k, v]) => `${SKILL_META[k].name} ${v}`).join(', ');
      const nameHtml = s.url ? `<a href="${s.url}" target="_blank" rel="noopener">${s.name}</a>` : s.name;
      return `
        <div class="suggestion-card" data-id="${s.id}">
          <div class="sug-title">${iconImg(s.skill)} ${nameHtml}</div>
          <div class="sug-meta">
            <div>Suggested by <b>${s.by}</b>${s.f2p ? ' · F2P' : ''}${s.afk ? ` · ~${s.afk} AFK` : ''}</div>
            <div>📋 ${reqStr}</div>
            ${s.notes ? `<div>💡 ${s.notes}</div>` : ''}
          </div>
          <div class="sug-votes">
            <button class="vote-btn ${s.myVote === 1 ? 'my-vote' : ''}" data-vote="1">👍 ${s.up}/2</button>
            <button class="vote-btn ${s.myVote === -1 ? 'my-vote' : ''}" data-vote="-1">👎 ${s.down}/2</button>
          </div>
        </div>`;
    }).join('');
  } catch (_) {
    els.suggestionsList.innerHTML = '<span class="hint">Could not load suggestions right now.</span>';
  }
}

async function castVote(sid, vote) {
  if (!playerName) {
    setStatus(els.voteStatus, 'Fetch your levels first — votes are cast with your username.', 'error');
    return;
  }
  clearStatus(els.voteStatus);
  try {
    const r = await apiPost(`/api/suggestions/${sid}/vote`, { nick: playerName, vote });
    if (r.status === 'approved') {
      setStatus(els.voteStatus, `✅ "${r.name}" was approved and added to the task pool!`, 'success');
      loadApprovedTasks();
    } else if (r.status === 'rejected') {
      setStatus(els.voteStatus, `❌ "${r.name}" was rejected by vote.`, 'info');
    }
    loadSuggestions();
  } catch (e) {
    setStatus(els.voteStatus, String(e).includes('409') ? 'Voting on this one is already closed.' : 'Vote failed — try again.', 'error');
    loadSuggestions();
  }
}

function initSuggestForm() {
  els.sugSkill.innerHTML = Object.entries(SKILL_META)
    .map(([k, m]) => `<option value="${k}">${m.name}</option>`).join('');
  els.sugReqs.innerHTML = Object.entries(SKILL_META).map(([k, m]) => `
    <label class="sug-req-cell">${iconImg(k)}<span>${m.name}</span>
      <input type="number" min="1" max="99" data-skill="${k}" placeholder="–">
    </label>`).join('');
}

async function submitSuggestion(ev) {
  ev.preventDefault();
  if (!playerName) {
    setStatus(els.suggestStatus, 'Fetch your levels first — suggestions are made with your username.', 'error');
    return;
  }
  const reqs = {};
  for (const inp of els.sugReqs.querySelectorAll('input[data-skill]')) {
    const v = parseInt(inp.value, 10);
    if (v >= 1 && v <= 99) reqs[inp.dataset.skill] = v;
  }
  if (!els.sugName.value.trim()) {
    setStatus(els.suggestStatus, 'Give the task a name.', 'error');
    return;
  }
  if (!Object.keys(reqs).length) {
    setStatus(els.suggestStatus, 'Fill in at least one skill requirement.', 'error');
    return;
  }
  els.sugSubmit.disabled = true;
  try {
    await apiPost('/api/suggestions', {
      nick: playerName,
      name: els.sugName.value.trim(),
      skill: els.sugSkill.value,
      afk: els.sugAfk.value.trim(),
      notes: els.sugNotes.value.trim(),
      url: els.sugUrl.value.trim(),
      f2p: els.sugF2p.checked,
      reqs,
    });
    els.suggestForm.reset();
    els.suggestForm.classList.add('hidden');
    clearStatus(els.suggestStatus);
    setStatus(els.voteStatus, '🗳️ Suggestion submitted — it was announced on Discord and is now open for voting!', 'success');
    loadSuggestions();
  } catch (e) {
    const msg = String(e).includes('409') ? 'A suggestion with this name already exists.'
      : String(e).includes('429') ? 'Slow down — wait a minute between suggestions.'
      : 'Submitting failed — check the fields (wiki link must point to oldschool.runescape.wiki).';
    setStatus(els.suggestStatus, msg, 'error');
  }
  els.sugSubmit.disabled = false;
}

// ---------- Init ----------

els.fetchBtn.addEventListener('click', fetchLevels);
els.nick.addEventListener('keydown', (e) => { if (e.key === 'Enter') fetchLevels(); });
els.spinBtn.addEventListener('click', spin);
els.rerollBtn.addEventListener('click', skipAndReroll);
els.doneBtn.addEventListener('click', markDone);
els.discordBtn.addEventListener('click', sendToDiscord);
els.f2pOnly.addEventListener('change', updateEligible);
els.suggestToggle.addEventListener('click', () => els.suggestForm.classList.toggle('hidden'));
els.suggestForm.addEventListener('submit', submitSuggestion);
els.suggestionsList.addEventListener('click', (e) => {
  const btn = e.target.closest('.vote-btn');
  if (!btn) return;
  castVote(parseInt(btn.closest('.suggestion-card').dataset.id, 10), parseInt(btn.dataset.vote, 10));
});

const savedNick = localStorage.getItem('afk_nick');
if (savedNick) els.nick.value = savedNick;
localStorage.removeItem('afk_webhook'); // webhook moved to the server

initSuggestForm();
renderLeaderboard(); // shared board + suggestions are visible even before fetching levels
loadSuggestions();
loadApprovedTasks();
