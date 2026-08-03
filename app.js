// OSRS AFK-ruletti — staattinen sivu, ei backendiä.
// Levelit: Wise Old Man API (CORS ok), fallback virallinen hiscores CORS-proxyn läpi.

const $ = (id) => document.getElementById(id);

const els = {
  nick: $('nick'), fetchBtn: $('fetch-btn'), f2pOnly: $('f2p-only'),
  settingsToggle: $('settings-toggle'), settingsBox: $('settings-box'), webhook: $('webhook'),
  fetchStatus: $('fetch-status'), skillsPanel: $('skills-panel'), skillsTitle: $('skills-title'),
  skillsGrid: $('skills-grid'), eligibleCount: $('eligible-count'),
  wheelSection: $('wheel-section'), wheel: $('wheel'), spinBtn: $('spin-btn'),
  resultPanel: $('result-panel'), resultCard: $('result-card'),
  discordBtn: $('discord-btn'), rerollBtn: $('reroll-btn'), discordStatus: $('discord-status'),
};

let playerLevels = null;   // { attack: 60, ... }
let playerName = '';
let wheelTasks = [];       // pyörässä olevat tehtävät
let currentTask = null;
let spinning = false;

// ---------- Apufunktiot ----------

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

// ---------- Levelien haku ----------

const WOM_SKILL_MAP = { runecrafting: 'runecraft' }; // WOM käyttää eri nimeä

async function fetchFromWOM(nick) {
  const enc = encodeURIComponent(nick);
  let res = await fetch(`https://api.wiseoldman.net/v2/players/${enc}`);
  if (res.status === 404) {
    // Ei vielä seurannassa — pyydä WOMia hakemaan pelaaja hiscoreista
    res = await fetch(`https://api.wiseoldman.net/v2/players/${enc}`, { method: 'POST' });
  }
  if (!res.ok) throw new Error(`WOM ${res.status}`);
  const data = await res.json();
  const skills = data.latestSnapshot && data.latestSnapshot.data && data.latestSnapshot.data.skills;
  if (!skills) throw new Error('WOM: ei snapshotia');
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
  if (!data.skills) throw new Error('Hiscores: ei skillejä');
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
}

// ---------- UI ----------

function renderSkills() {
  els.skillsTitle.textContent = `${playerName} — levels`;
  els.skillsGrid.innerHTML = '';
  for (const [key, meta] of Object.entries(SKILL_META)) {
    if (!(key in playerLevels)) continue;
    const cell = document.createElement('div');
    cell.className = 'skill-cell';
    cell.innerHTML = `<span>${meta.emoji}</span><span>${meta.name}</span><span class="lvl">${playerLevels[key]}</span>`;
    els.skillsGrid.appendChild(cell);
  }
  els.skillsPanel.classList.remove('hidden');
  els.wheelSection.classList.remove('hidden');
}

function eligibleTasks() {
  if (!playerLevels) return [];
  const f2p = els.f2pOnly.checked;
  return TASKS.filter((t) => {
    if (f2p && !t.f2p) return false;
    return Object.entries(t.reqs).every(([skill, lvl]) => (playerLevels[skill] || 1) >= lvl);
  });
}

function updateEligible() {
  const n = eligibleTasks().length;
  els.eligibleCount.textContent = `${TASKS.length} tasks in the pool — available to you: ${n}`;
  els.spinBtn.disabled = n === 0;
  if (playerLevels) drawIdleWheel();
}

// ---------- Ruletti ----------

const WHEEL_COLORS = ['#8e44ad', '#c0392b', '#27ae60', '#2980b9', '#d35400', '#16a085', '#7f6000', '#5b2c6f', '#a04000', '#1e8449', '#884ea0', '#b03a2e', '#1f618d', '#9c640c'];
const MAX_SEGMENTS = 14;

function pickWheelTasks() {
  const pool = [...eligibleTasks()];
  // Fisher-Yates ja poimitaan max MAX_SEGMENTS
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

    // Teksti
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(start + seg / 2);
    ctx.textAlign = 'right';
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 13px Georgia';
    ctx.shadowColor = 'rgba(0,0,0,0.7)';
    ctx.shadowBlur = 3;
    const meta = SKILL_META[tasks[i].skill];
    let label = `${meta.emoji} ${tasks[i].name}`;
    if (label.length > 26) label = label.slice(0, 24) + '…';
    ctx.fillText(label, r - 14, 5);
    ctx.restore();
  }

  // Keskiö
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

  // Ulkoreunus
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
  // Osoitin on ylhäällä (-90°). Pyöritetään niin että voittajasegmentin keskikohta osuu osoittimeen.
  const pointerAngle = -Math.PI / 2;
  const targetRotation = pointerAngle - (winner * seg + seg / 2);
  const fullTurns = 5 + Math.floor(Math.random() * 3); // 5–7 kierrosta
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

// ---------- Tulos ----------

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
  els.resultCard.innerHTML = `
    <div class="task-name">${meta.emoji} ${task.name}</div>
    <div class="task-skill">Skill: <b>${meta.name}</b> (yours: ${playerLevels ? (playerLevels[task.skill] || '?') : '?'})</div>
    <div class="task-meta">
      <div>⏱️ AFK time: ~${task.afk} per click</div>
      <div>📋 Requirements: ${reqStr}</div>
      ${task.notes ? `<div>💡 ${task.notes}</div>` : ''}
      ${restored ? '<div><i>(today\'s previously rolled task)</i></div>' : ''}
    </div>`;
  els.resultPanel.classList.remove('hidden');
  if (!restored) els.resultPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
  const url = els.webhook.value.trim();
  if (!url) {
    els.settingsBox.classList.remove('hidden');
    setStatus(els.discordStatus, 'Enter your Discord webhook URL in the settings (⚙️) first.', 'error');
    return;
  }
  if (!currentTask) return;
  localStorage.setItem('afk_webhook', url);

  const meta = SKILL_META[currentTask.skill];
  const reqStr = Object.entries(currentTask.reqs).map(([s, l]) => `${SKILL_META[s].name} ${l}`).join(', ');
  const payload = {
    username: 'AFK Roulette',
    embeds: [{
      title: `🎡 Today's AFK task: ${meta.emoji} ${currentTask.name}`,
      color: 0xf5c542,
      fields: [
        { name: 'Player', value: playerName, inline: true },
        { name: 'Skill', value: meta.name, inline: true },
        { name: 'AFK time', value: `~${currentTask.afk}`, inline: true },
        { name: 'Requirements', value: reqStr, inline: false },
        ...(currentTask.notes ? [{ name: 'Note', value: currentTask.notes, inline: false }] : []),
      ],
      footer: { text: 'OSRS AFK Roulette' },
      timestamp: new Date().toISOString(),
    }],
  };

  els.discordBtn.disabled = true;
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Discord ${res.status}`);
    setStatus(els.discordStatus, '✅ Sent to the Discord channel!', 'success');
  } catch (e) {
    console.error(e);
    setStatus(els.discordStatus, 'Sending failed — check the webhook URL.', 'error');
  }
  els.discordBtn.disabled = false;
}

// ---------- Init ----------

els.fetchBtn.addEventListener('click', fetchLevels);
els.nick.addEventListener('keydown', (e) => { if (e.key === 'Enter') fetchLevels(); });
els.spinBtn.addEventListener('click', spin);
els.rerollBtn.addEventListener('click', () => { els.resultPanel.classList.add('hidden'); spin(); });
els.discordBtn.addEventListener('click', sendToDiscord);
els.f2pOnly.addEventListener('change', updateEligible);
els.settingsToggle.addEventListener('click', () => els.settingsBox.classList.toggle('hidden'));

const savedNick = localStorage.getItem('afk_nick');
if (savedNick) els.nick.value = savedNick;
const savedHook = localStorage.getItem('afk_webhook');
if (savedHook) els.webhook.value = savedHook;
