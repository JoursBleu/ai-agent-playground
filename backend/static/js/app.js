function _requireLogin() {
  if (currentUser) return true;
  log(t("hint_login_required"), "err");
  openModal("login");
  return false;
}

async function _joinGameId(gid) {
  let j;
  try {
    j = await api("POST", `/api/games/${gid}/join`, {});
  } catch (e) {
    if (e && e.status === 404) {
      try { alert(t("alert_room_gone")); } catch (_) {}
      log(t("log_room_gone"), "err");
      try { if (location.pathname !== "/") history.pushState({}, "", "/"); } catch (_) {}
      loadRooms();
      return;
    }
    throw e;
  }
  gameId = gid;
  token = j.token;
  mySeat = j.seat;
  $("gameId").value = gid;
  $("btnRefresh").disabled = false;
  enterRoom(gid, false);
  log(`${t("log_joined")}${gid}: seat=${j.seat} player=${j.player_id}`, "me");
  log(`${t("log_token")}${j.token}  game_id: ${gid}`, "me");
  startPolling();
}

$("btnCreate").onclick = async () => {
  if (!_requireLogin()) return;
  const name = $("roomName").value.trim();
  if (!name) { log(t("log_room_name_req"), "err"); $("roomName").focus(); return; }
  const description = $("roomDesc").value.trim();
  const rule_mode = $("ruleMode").value;
  try {
    const game_type = currentGameType || "doudizhu";
    const r = await api("POST", "/api/games", { name, description, rule_mode, game_type });
    log(`${t("log_create_room")}${r.name} (${r.game_id})  game_type=${r.game_type || game_type}  rule_mode=${r.rule_mode}`, "me");
    await _joinGameId(r.game_id);
  } catch (e) {
    log(t("log_create_fail") + e.message, "err");
  }
};

$("btnJoinExisting").onclick = async () => {
  if (!_requireLogin()) return;
  const gid = $("gameId").value.trim();
  if (!gid) { log(t("log_room_id_req"), "err"); $("gameId").focus(); return; }
  try { await _joinGameId(gid); }
  catch (e) { log(t("log_join_fail") + e.message, "err"); }
};

$("btnRefresh").onclick = () => refresh();

let currentGameType = 'doudizhu';
function setActiveGame(gt) {
  if (gt !== 'doudizhu' && gt !== 'zhajinhua' && gt !== 'texas_holdem') return;
  currentGameType = gt;
  document.querySelectorAll('#gamePicker .game-pick-item').forEach(el => {
    el.classList.toggle('active', el.dataset.game === gt);
  });
  // update create-button hint
  const btn = $("btnCreate");
  if (btn) {
    let k = 'lobby_btn_create_ddz';
    if (gt === 'zhajinhua') k = 'lobby_btn_create_zjh';
    else if (gt === 'texas_holdem') k = 'lobby_btn_create_texas';
    btn.textContent = t(k) || t('lobby_btn_create');
  }
  loadRooms();
}
(function bindGamePicker(){
  document.querySelectorAll('#gamePicker .game-pick-item').forEach(el => {
    el.onclick = () => setActiveGame(el.dataset.game);
  });
})();
// keep button label in sync with active game once i18n is ready
setTimeout(() => { try { setActiveGame(currentGameType); } catch(_) {} }, 0);

async function loadRooms() {
  const box = $("roomsList");
  try {
    const r = await api("GET", "/api/games");
    const allGames = r.games || [];
    const games = allGames.filter(g => (g.game_type || 'doudizhu') === currentGameType);
    if (!games.length) {
      box.innerHTML = `<span class="muted">${escapeHtml(t('rooms_empty'))}</span>`;
      return;
    }
    const rows = games.map(g => {
      const seats = (g.players || []).map(p => p || `<em class="muted">${escapeHtml(t('rooms_seat_empty'))}</em>`).join(' · ');
      const open = (g.players || []).some(p => !p);
      const phaseColor = g.phase === 'waiting' ? '#059669' : (g.phase === 'bidding' ? '#d97706' : '#6b7280');
      const joinBtn = open
        ? `<button class="ghost" data-join="${g.game_id}" style="padding:2px 10px;font-size:12px">${escapeHtml(t('rooms_join'))}</button>`
        : `<button class="ghost" data-join="${g.game_id}" style="padding:2px 10px;font-size:12px" disabled>${escapeHtml(t('rooms_full'))}</button>`;
      const watchBtn = `<button class="ghost" data-watch="${g.game_id}" style="padding:2px 10px;font-size:12px;margin-left:4px">${escapeHtml(t('rooms_watch'))}</button>`;
      const btn = joinBtn + watchBtn;
      const roomName = escapeHtml(g.name || g.game_id);
      const roomDesc = g.description ? `<div class="muted" style="font-size:12px;margin-top:2px">${escapeHtml(g.description)}</div>` : "";
      return `<div class="row" style="justify-content:space-between;border-bottom:1px solid var(--border);padding:8px 0">
        <div style="min-width:0;flex:1">
          <div style="font-size:14px;font-weight:600">${roomName}
            <code style="font-size:11px;color:var(--muted);font-weight:400;margin-left:6px">${g.game_id}</code>
            <span class="gt-tag gt-${escapeHtml(g.game_type||'doudizhu')}" style="font-size:11px;margin-left:6px">${escapeHtml(g.game_type === 'zhajinhua' ? t('lobby_gt_zjh') : (g.game_type === 'texas_holdem' ? t('lobby_gt_texas') : t('lobby_gt_ddz')))}</span>
            <span style="color:${phaseColor};font-size:12px;margin-left:6px">${g.phase}</span>
            <span class="muted" style="font-size:12px;margin-left:6px">${g.rule_mode}</span>
          </div>
          ${roomDesc}
          <div style="font-size:13px;margin-top:4px">${seats}</div>
        </div>
        <div>${btn}</div>
      </div>`;
    }).join('');
    box.innerHTML = rows;
    box.querySelectorAll('[data-join]:not([disabled])').forEach(b => {
      b.onclick = () => { $("gameId").value = b.dataset.join; $("btnJoinExisting").click(); };
    });
    box.querySelectorAll('[data-watch]').forEach(b => {
      b.onclick = () => watchGame(b.dataset.watch);
    });
  } catch (e) {
    box.innerHTML = `<span class="err">${escapeHtml(t('rooms_load_fail'))}${escapeHtml(e.message)}</span>`;
  }
}

$("btnLeaveRoom").onclick = async () => {
  if (gameId && token) {
    const isOwner = !!(state && state.you && state.owner_seat === state.you.seat);
    const msg = isOwner ? t("confirm_leave_owner") : t("confirm_leave_seat");
    if (!confirm(msg.replace("{gid}", gameId))) return;
    try {
      const r = await api("POST", `/api/games/${gameId}/leave`, { token });
      log(r && r.disbanded ? t("log_disbanded") : t("log_left_seat"), "me");
    } catch (e) {
      if (e && e.status === 404) {
        // room already gone — fall through to leaveRoom()
      } else {
        log(t("log_leave_fail") + e.message, "err");
        return;
      }
    }
  }
  leaveRoom();
};
$("btnDisband").onclick = async () => {
  if (!gameId || !token) return;
  if (!confirm(t("confirm_disband").replace("{gid}", gameId))) return;
  try {
    await api("POST", `/api/games/${gameId}/disband`, { token });
    log(t("log_disbanded"), "me");
    leaveRoom();
  } catch (e) {
    log(t("log_disband_fail") + e.message, "err");
  }
};
$("btnRestart").onclick = async () => {
  if (!gameId || !token) return;
  if (!confirm(t("confirm_restart"))) return;
  try {
    await api("POST", `/api/games/${gameId}/restart`, { token });
    log(t("log_restarted"), "me");
  } catch (e) {
    log(t("log_restart_fail") + e.message, "err");
  }
};
$("btnRefreshRooms").onclick = loadRooms;
(function initFromUrl(){
  const m = location.pathname.match(/^\/r\/([^\/?#]+)$/);
  if (!m) return;
  const gid = decodeURIComponent(m[1]);
  const el = document.getElementById("gameId");
  if (el) el.value = gid;
  const params = new URLSearchParams(location.search);
  const spec = params.get("spectator");
  if (spec) spectatorToken = spec;
  // implicit auto-enter as spectator (with or without omniscient token)
  gameId = gid;
  token = null;
  mySeat = -1;
  selected.clear();
  enterRoom(gid, true);
  startPolling();
})();
loadRooms();
// auto-refresh rooms list while user is sitting in the lobby
setInterval(() => {
  if (!gameId && $("lobby").style.display !== "none") loadRooms();
}, 3000);

function updateClocks(phase, think, act) {
  const small = $("turnClock");
  const big = $("turnClockBig");
  const hint = $("turnClockHint");
  const tc = (state && state.turn_clock) || {};
  const thinkTotal = Math.round(tc.think_seconds || 0);
  const actTotal = Math.round(tc.action_seconds || 0);
  let cls = "clock idle", txt = "—", hintTxt = t('clock_not_started');
  if (phase === "bidding" || phase === "playing") {
    if (think > 0) {
      cls = "clock thinking";
      txt = `⏳ ${Math.ceil(think)}/${thinkTotal}s`;
      hintTxt = t('clock_thinking');
    } else if (act > 0) {
      cls = "clock action";
      txt = `▶ ${Math.ceil(act)}/${actTotal}s`;
      hintTxt = t('clock_action');
    } else {
      cls = "clock idle"; txt = t('clock_timeout_label'); hintTxt = t('clock_timeout_hint');
    }
  } else if (phase === "finished") {
    hintTxt = t('clock_finished');
  } else if (phase === "waiting") {
    hintTxt = t('clock_waiting');
  }
  if (small) { small.className = cls; small.textContent = txt; }
  if (big)   { big.className   = cls; big.textContent   = txt; }
  if (hint)  { hint.textContent = hintTxt; }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  if (clockTimer) clearInterval(clockTimer);
  refresh();
  pollTimer = setInterval(refresh, 1500);
  clockTimer = setInterval(tickClock, 250);
}

// Clock anchor: avoids server/browser clock skew by recording server-elapsed at the
// moment we received the last state, then advancing locally using performance.now().
let clockAnchorServerElapsed = 0;
let clockAnchorLocalMs = 0;

function tickClock() {
  if (!state || !state.turn_clock || !state.turn_clock.turn_started_at) return;
  const tc = state.turn_clock;
  const localDelta = (performance.now() - clockAnchorLocalMs) / 1000;
  const elapsed = Math.max(0, clockAnchorServerElapsed + localDelta);
  const think = Math.max(0, tc.think_seconds - elapsed);
  const act = Math.max(0, tc.total_seconds - elapsed);
  updateClocks(state.phase, think, act);
  // also gate buttons during local tick
  const myTurn = !!(state.you && state.you.is_your_turn);
  const canAct = think <= 0 && act > 0;
  document.querySelectorAll("#bidArea button, #playArea button").forEach(b => { b.disabled = myTurn && !canAct; });
}


function compactUiStateForPreview(ui) {
  if (!ui) return null;
  const table = ui.table || {};
  const you = ui.you || null;
  return {
    game_id: ui.game_id,
    game_type: ui.game_type,
    phase: ui.phase,
    clock: ui.clock ? {
      can_act: ui.clock.can_act,
      thinking_remaining: ui.clock.thinking_remaining,
      action_remaining: ui.clock.action_remaining,
    } : null,
    you: you ? {
      seat: you.seat,
      is_your_turn: you.is_your_turn,
      hand_count: Array.isArray(you.hand) ? you.hand.length : undefined,
      call_amount: you.call_amount,
      can_check: you.can_check,
    } : null,
    table: {
      current_turn: table.current_turn,
      current_bid: table.current_bid,
      street: table.street,
      pot: table.pot,
      current_bet: table.current_bet,
      last_play_category: table.last_play_category,
      history_count: Array.isArray(table.history) ? table.history.length : 0,
    },
  };
}

function renderAgentApiPanel(ui) {
  const panel = $('agentApiPanel');
  if (!panel) return;
  if (!ui) {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = '';
  const gameType = $('apiGameType');
  const phase = $('apiPhase');
  if (gameType) gameType.textContent = ui.game_type || '—';
  if (phase) phase.textContent = ui.phase || '—';
  const preview = $('apiUiPreview');
  if (preview) preview.textContent = JSON.stringify(compactUiStateForPreview(ui), null, 2);
  const actionsBox = $('apiActions');
  if (!actionsBox) return;
  const actions = Array.isArray(ui.actions) ? ui.actions : [];
  if (!actions.length) {
    actionsBox.innerHTML = '<span class="muted">No callable actions</span>';
    return;
  }
  actionsBox.innerHTML = actions.map(a => {
    const enabled = !!a.enabled;
    const reasonText = a.disabled_reason || '';
    const title = reasonText ? ` title="${escapeHtml(reasonText)}"` : '';
    const params = a.params && Object.keys(a.params).length ? `<code>${escapeHtml(JSON.stringify(a.params))}</code>` : '';
    return `<div class="api-action ${enabled ? 'enabled' : 'disabled'}" data-action-id="${escapeHtml(a.id || '')}" data-action-enabled="${enabled ? 'true' : 'false'}" data-disabled-reason="${escapeHtml(reasonText)}"${title}>
      <div><strong>${escapeHtml(a.id || '')}</strong> <span>${escapeHtml(a.label || '')}</span></div>
      ${params}
    </div>`;
  }).join('');
}

async function fetchUiState() {
  if (!gameId) return null;
  let url = `/api/games/${gameId}/ui-state`;
  if (token) url += `?token=${encodeURIComponent(token)}`;
  else if (spectatorToken) url += `?spectator=${encodeURIComponent(spectatorToken)}`;
  return await api('GET', url);
}


var _rcPollTimer = null;
var _rcCountdownTimer = null;
var _rcCurrentOrder = null;
var _rcConfig = null;

let _aap_lastGamePhase = null;
async function _refreshMeQuiet() {
  try {
    const r = await api('GET', '/api/auth/me');
    if (r && r.user) {
      const prev = currentUser ? currentUser.points : null;
      currentUser = r.user;
      renderUserbar();
      if (prev != null && currentUser.points != null && currentUser.points !== prev) {
        const d = currentUser.points - prev;
        log(`[points] ${d > 0 ? '+' : ''}${d} → ${currentUser.points}`, d > 0 ? 'me' : 'err');
      }
    }
  } catch (_) {}
}


async function refresh() {
  if (!gameId) return;
  try {
    const ui = await fetchUiState();
    state = normalizeUiStateForLegacyRender(ui);
    renderAgentApiPanel(ui);
    if (state && state.phase !== _aap_lastGamePhase) {
      if (state.phase === 'finished') _refreshMeQuiet();
      _aap_lastGamePhase = state.phase;
    }
    if (!token && (!state.chat || !state.chat.length)) {
      // Compatibility fallback for legacy public_state without embedded chat.
      try {
        const ch = await api("GET", `/api/games/${gameId}/chat?since=0&limit=50`);
        state.chat = ch.messages || [];
      } catch (_) {}
    }
    render();
  } catch (e) {
    if (e && e.status === 404) {
      log(t("log_room_gone"), "err");
      try { alert(t("alert_room_gone")); } catch (_) {}
      leaveRoom();
      return;
    }
    log(t("log_refresh_fail") + e.message, "err");
  }
}

function watchGame(gid) {
  gameId = gid;
  token = null;
  mySeat = -1;
  selected.clear();
  $("gameId").value = gid;
  $("btnRefresh").disabled = false;
  enterRoom(gid, true);
  log(t("log_watch") + gid, "me");
  startPolling();
}

function enterRoom(gid, spectator) {
  $("lobby").style.display = "none";
  $("board").style.display = "";
  if ($("zjhBoard")) $("zjhBoard").style.display = "none";
  $("chatPanel").style.display = "";
  $("logPanel").style.display = "";
  $("boardRoomTag").textContent = (spectator ? t("spec_prefix") : "") + gid;
  if ($("zjhBoardRoomTag")) $("zjhBoardRoomTag").textContent = (spectator ? t("spec_prefix") : "") + gid;
  document.body.classList.add("in-room");
  try {
    const target = "/r/" + encodeURIComponent(gid);
    if (location.pathname !== target) history.pushState({gid}, "", target);
  } catch (e) {}
}

function leaveRoom() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (clockTimer) { clearInterval(clockTimer); clockTimer = null; }
  gameId = null;
  token = null;
  spectatorToken = null;
  mySeat = -1;
  state = null;
  selected.clear();
  $("board").style.display = "none";
  if ($("zjhBoard")) $("zjhBoard").style.display = "none";
  $("chatPanel").style.display = "none";
  $("logPanel").style.display = "none";
  $("lobby").style.display = "";
  $("btnRefresh").disabled = true;
  document.body.classList.remove("in-room");
  renderAgentApiPanel(null);
  const sb = $("seatsRail");
  if (sb) sb.innerHTML = `<div class="muted" style="font-size:12px">${escapeHtml(t('side_not_in_room'))}</div>`;
  updateClocks("waiting", 0, 0);
  try { if (location.pathname !== "/") history.pushState({}, "", "/"); } catch (e) {}
  loadRooms();
}

function cardLabel(code) {
  // Returns {rank, suit, red, joker}
  if (code === "RJ") return { rank: t('joker_small'), suit: "", red: true, joker: true };
  if (code === "BJ") return { rank: t('joker_big'),   suit: "", red: false, joker: true };
  const rank = code[0], suit = code[1];
  const suitChar = { S: "\u2660", H: "\u2665", D: "\u2666", C: "\u2663" }[suit] || "";
  const red = suit === "H" || suit === "D";
  const r = rank === "T" ? "10" : rank;
  return { rank: r, suit: suitChar, red, joker: false };
}

function renderCard(code, selectable) {
  const { rank, suit, red, joker } = cardLabel(code);
  const el = document.createElement("div");
  el.className = "card" + (red ? " red" : "") + (joker ? " joker" : "") + (selected.has(code) ? " selected" : "");
  if (joker) {
    // Big/Small joker: just a centered label
    el.innerHTML = `<div class="pip">${rank}</div>`;
  } else {
    el.innerHTML =
      `<div class="corner tl"><div class="r">${rank}</div><div class="s">${suit}</div></div>` +
      `<div class="pip">${suit}</div>` +
      `<div class="corner br"><div class="r">${rank}</div><div class="s">${suit}</div></div>`;
  }
  if (selectable) {
    el.setAttribute("data-selectable", "1");
    el.onclick = () => {
      if (selected.has(code)) selected.delete(code);
      else selected.add(code);
      if (typeof updateDdzSelectionInfo === 'function') updateDdzSelectionInfo();
      render();
    };
  }
  return el;
}

function renderChat(msgs) {
  const box = $("chat");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 20;
  box.innerHTML = "";
  for (const m of msgs) {
    const d = document.createElement("div");
    d.className = "msg" + (m.seat === mySeat ? " me" : "");
    const ts = new Date(m.timestamp * 1000).toLocaleTimeString();
    const who = (m.name || (t('seat_label') + m.seat));
    d.innerHTML = `<span class="ts">${ts}</span><span class="who">${escapeHtml(who)}:</span><span>${escapeHtml(m.text)}</span>`;
    box.appendChild(d);
    if (m.timestamp > lastChatTs) lastChatTs = m.timestamp;
  }
  if (atBottom) box.scrollTop = box.scrollHeight;
}

async function gameAction(action, payload) {
  if (!gameId || !token) throw new Error('missing gameId/token');
  const body = Object.assign({ token, action }, payload || {});
  return await api("POST", `/api/games/${gameId}/action`, body);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function sendChat() {
  const inp = $("chatInput");
  const text = inp.value.trim();
  if (!text || !gameId || !token) return;
  try {
    await api("POST", `/api/games/${gameId}/chat`, { token, text });
    inp.value = "";
    refresh();
  } catch (e) {
    log(t("log_chat_fail") + e.message, "err");
  }
}

document.querySelectorAll("#bidArea button").forEach((btn) => {
  btn.onclick = async () => {
    try {
      await gameAction("bid", { bid: +btn.dataset.bid });
      log(t("log_bid") + btn.dataset.bid, "me");
      refresh();
    } catch (e) {
      log(t("log_bid_fail") + e.message, "err");
    }
  };
});

$("btnPlay").onclick = async () => {
  if (!selected.size) { log(t("log_select_cards"), "err"); return; }
  const cards = Array.from(selected);
  try {
    const r = await gameAction("play_cards", { cards });
    log(t('log_play_prefix') + cards.join(",") + (r.result && r.result.pattern ? " [" + r.result.pattern.category + "]" : ""), "me");
    selected.clear();
    refresh();
  } catch (e) {
    log(t("log_play_fail") + e.message, "err");
  }
};

if ($("btnClearSelection")) $("btnClearSelection").onclick = () => {
  selected.clear();
  if (typeof updateDdzSelectionInfo === 'function') updateDdzSelectionInfo();
  render();
};

if ($("btnHint")) $("btnHint").onclick = () => {
  const hint = typeof findDdzHint === 'function' ? findDdzHint() : null;
  if (!hint || !hint.cards || !hint.cards.length) {
    log('no legal hint found', 'err');
    return;
  }
  if (hint.enabled === false) {
    log(`hint unavailable: ${hint.disabled_reason || 'not your action window'}`, 'err');
    return;
  }
  selected.clear();
  hint.cards.forEach(c => selected.add(c));
  const pattern = hint.pattern && hint.pattern.category ? ` [${hint.pattern.category}]` : '';
  const source = hint.source ? `${hint.source}: ` : '';
  log(`hint: ${source}${hint.reason || hint.cards.join(',')}${pattern}`, 'me');
  if (typeof updateDdzSelectionInfo === 'function') updateDdzSelectionInfo();
  render();
};

$("btnPass").onclick = async () => {
  try {
    await gameAction("pass");
    log(t("log_pass"), "me");
    selected.clear();
    refresh();
  } catch (e) {
    log(t("log_pass_fail") + e.message, "err");
  }
};

$("btnSendChat").onclick = sendChat;
$("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); sendChat(); }
});

// Toggle chat input usability based on token (spectator vs player)
function _refreshChatInputState() {
  const inp = $("chatInput"), btn = $("btnSendChat");
  if (!inp || !btn) return;
  if (token) {
    inp.disabled = false; btn.disabled = false;
    inp.placeholder = t('chat_ph');
  } else {
    inp.disabled = true; btn.disabled = true;
    inp.placeholder = t('chat_ph_spec');
  }
}
const _origRender = render;
render = function() { _origRender(); _refreshChatInputState(); };
