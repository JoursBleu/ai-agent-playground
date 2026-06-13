function renderTexas() {
  if (!state) return;
  const me = state.you || {};
  const isOwner = !!me.is_owner;
  const myTurn = !!me.is_your_turn;
  const tc = gameClock();
  const table = gameTable();
  const seats = gameSeats();
  const canAct = !!tc.can_act;
  const isPlaying = state.phase === 'playing';
  const isFinished = state.phase === 'finished';

  // Header
  const room = state.room || {};
  $("texasBoardRoomTag").textContent = (state.name || room.name) ? `[${state.name || room.name}]` : '';
  $("texasRound").textContent = gameRoundNo() != null ? gameRoundNo() : '—';
  $("texasPot").textContent = gamePot() != null ? gamePot() : 0;
  $("texasCurBet").textContent = gameCurrentBet() != null ? gameCurrentBet() : 0;
  if ($("texasPotCenter")) $("texasPotCenter").textContent = gamePot() != null ? gamePot() : 0;
  if ($("texasCurBetCenter")) $("texasCurBetCenter").textContent = gameCurrentBet() != null ? gameCurrentBet() : 0;
  $("texasBlinds").textContent = `${table.small_blind ?? state.small_blind}/${table.big_blind ?? state.big_blind}`;
  $("texasDealer").textContent = (table.dealer_seat ?? state.dealer_seat) >= 0 ? ('seat ' + (table.dealer_seat ?? state.dealer_seat)) : '—';
  const street = gameStreet() || 'preflop';
  const streetKey = `texas_street_${street}`;
  $("texasStreet").textContent = t(streetKey) || (street || '—');

  // Community cards
  const com = $("texasCommunity");
  com.innerHTML = "";
  const cc = gameCommunity();
  for (let i = 0; i < 5; i++) {
    const card = document.createElement("span");
    card.className = "card";
    if (cc[i]) card.textContent = formatCard(cc[i]); else { card.textContent = '?'; card.classList.add('back'); }
    com.appendChild(card);
  }

  // Seats panel
  const seatsBox = $("texasSeats");
  seatsBox.innerHTML = "";
  const nSeats = Math.max(seats.length || 0, state.n_seats || 0, 2);
  seatsBox.innerHTML = "";
  for (let i = 0; i < nSeats; i++) {
    const p = seats[i] || { seat:i, joined:false };
    const div = document.createElement("div");
    const angle = (-90 + (360 * i / nSeats)) * Math.PI / 180;
    const x = 50 + 42 * Math.cos(angle);
    const y = 50 + 40 * Math.sin(angle);
    div.style.left = `${x}%`;
    div.style.top = `${y}%`;
    let cls = "texas-player-seat";
    if (i === gameCurrentTurn()) cls += " active";
    if (i === me.seat) cls += " me";
    if (!p.joined) cls += " empty";
    div.className = cls;
    const tags = [];
    if (i === (table.dealer_seat ?? state.dealer_seat)) tags.push('<span class="badge">D</span>');
    if (i === me.seat) tags.push(`<span class="badge you">${escapeHtml(t('badge_you'))}</span>`);
    if (p.folded) tags.push(`<span class="muted">[${t('texas_status_folded')}]</span>`);
    else if (p.all_in) tags.push(`<span class="muted" style="color:var(--bad)">[${t('texas_status_allin')}]</span>`);
    else if (i === gameCurrentTurn() && isPlaying) tags.push(`<span class="muted" style="color:var(--good)">[${t('texas_status_acting')}]</span>`);
    const name = p.joined ? (p.name || ('seat ' + i)) : `(empty seat ${i})`;
    const chips = p.joined ? p.chips : 0;
    const bet = p.joined ? p.bet_in_round : 0;
    const hand = (i === me.seat && me.hand) ? me.hand : (p.hand || []);
    const cardHtml = hand.length
      ? hand.map(c => `<span class="texas-mini-card">${escapeHtml(formatCard(c))}</span>`).join('')
      : (p.joined ? '<span class="texas-mini-card back">?</span><span class="texas-mini-card back">?</span>' : '');
    div.innerHTML = `
      <div class="texas-seat-name"><strong>#${i}</strong> ${escapeHtml(name)}</div>
      <div class="texas-seat-meta"><span>chips <strong>${chips}</strong></span><span>bet <strong>${bet}</strong></span></div>
      <div class="texas-seat-badges">${tags.join(' ')}</div>
      <div class="texas-seat-cards">${cardHtml}</div>
    `;
    seatsBox.appendChild(div);
  }

  // History
  const hist = $("texasHistory");
  hist.innerHTML = "";
  gameHistory().slice(-30).forEach(h => {
    const div = document.createElement("div");
    let line = `seat ${h.seat}: ${h.action}`;
    if (h.amount) line += ` (${h.amount})`;
    if (h.note) line += ` — ${escapeHtml(h.note)}`;
    div.textContent = line;
    hist.appendChild(div);
  });
  if (!hist.children.length) hist.innerHTML = '<span class="muted">—</span>';

  // My hand
  const handBox = $("texasHand");
  handBox.innerHTML = "";
  (me.hand || []).forEach(c => {
    const card = document.createElement("span");
    card.className = "card";
    card.textContent = formatCard(c);
    handBox.appendChild(card);
  });
  if (!(me.hand || []).length) handBox.innerHTML = '<span class="muted">—</span>';

  renderTexasActionMirror(state.actions || []);

  renderTexasActionBar({ me, myTurn, canAct, isPlaying, tc });

  // Owner controls
  $("btnTexasDisband").style.display = isOwner ? "" : "none";
  const seated = seats.filter(p => p && p.joined).length;
  const canRestart = isOwner && isFinished && seated >= 2 && !state.disbanded;
  $("btnTexasRestart").style.display = canRestart ? "" : "none";

  // Mirror turn clock
  const sm = $("turnClock"), tm = $("texasTurnClock");
  if (sm && tm) { tm.className = sm.className; tm.textContent = sm.textContent; }

  // Status line
  let status = "";
  if (state.disbanded) status = state.disbanded_reason || 'disbanded';
  else if (isFinished && ((table.showdown || state.last_showdown) || []).length) {
    const parts = (table.showdown || state.last_showdown || []).map(r => {
      const who = `seat ${r.seat}`;
      const cat = r.rank ? r.rank.category_name : (r.reason || '');
      return `${who}: +${r.won}${cat ? ' ('+cat+')' : ''}`;
    });
    status = parts.join('  ·  ');
  }
  $("texasBoardStatus").textContent = status;
}

function texasActionById(actions, id) {
  return (Array.isArray(actions) ? actions : []).find(a => a && a.id === id) || null;
}

function setTexasButton(id, action) {
  const btn = $(id);
  if (!btn) return;
  const enabled = !!(action && action.enabled);
  btn.disabled = !enabled;
  btn.title = action && !enabled ? (action.disabled_reason || '') : '';
  btn.dataset.actionId = action && action.id ? action.id : '';
  btn.dataset.actionEnabled = enabled ? 'true' : 'false';
  btn.dataset.disabledReason = action && !enabled ? (action.disabled_reason || '') : '';
}

function renderTexasActionBar(ctx) {
  const me = ctx.me || {};
  const actions = state.actions || [];
  const act = $("texasActionArea");
  if (!act) return;
  act.style.display = ctx.isPlaying && me.seat != null && !me.folded && !me.all_in ? "block" : "none";
  if (act.style.display === "none") return;

  const foldA = texasActionById(actions, "fold");
  const checkA = texasActionById(actions, "check");
  const callA = texasActionById(actions, "call");
  const raiseA = texasActionById(actions, "raise");
  const allInA = texasActionById(actions, "all_in");
  setTexasButton("btnTexasFold", foldA);
  setTexasButton("btnTexasCheck", checkA);
  setTexasButton("btnTexasCall", callA);
  setTexasButton("btnTexasRaise", raiseA);
  setTexasButton("btnTexasAllin", allInA);

  const callAmt = me.call_amount || (callA && callA.params && callA.params.amount) || 0;
  const callButton = $("btnTexasCall");
  if (callButton) {
    callButton.textContent = `${t('texas_btn_call')} (${callAmt})`;
    callButton.dataset.actionParamAmount = String(callAmt || 0);
  }
  const minRaise = raiseA && raiseA.params ? raiseA.params.min : me.min_raise_to;
  const maxRaise = raiseA && raiseA.params ? raiseA.params.max : me.max_raise_to;
  if ($("texasCallInfo")) {
    $("texasCallInfo").textContent = `call ${callAmt || 0} · raise ${minRaise || '—'}-${maxRaise || '—'}`;
    $("texasCallInfo").dataset.actionParamCallAmount = String(callAmt || 0);
    $("texasCallInfo").dataset.actionParamRaiseMin = String(minRaise || '');
    $("texasCallInfo").dataset.actionParamRaiseMax = String(maxRaise || '');
  }

  const range = $("texasRaiseInput");
  const number = $("texasRaiseNumber");
  const min = Number(minRaise || 1);
  const max = Number(maxRaise || min);
  const disabledRaise = !(raiseA && raiseA.enabled) || max < min;
  [range, number].forEach(inp => {
    if (!inp) return;
    inp.min = min;
    inp.max = max;
    inp.disabled = disabledRaise;
    inp.dataset.actionId = 'raise';
    inp.dataset.actionParamMin = String(min);
    inp.dataset.actionParamMax = String(max);
    const cur = parseInt(inp.value, 10);
    if (!Number.isFinite(cur) || cur < min || cur > max) inp.value = min;
  });
  if (range && number && String(range.value) !== String(number.value)) number.value = range.value;

  const info = $("texasTurnInfo");
  if (info) {
    if (ctx.myTurn && !ctx.canAct) info.textContent = `${t('zjh_thinking_phase') || 'thinking'} ${Math.ceil(ctx.tc.thinking_remaining || 0)}s`;
    else if (ctx.myTurn) info.textContent = `${t('zjh_action_remaining') || 'action'} ${Math.ceil(ctx.tc.action_remaining || 0)}s`;
    else info.textContent = "waiting for other player";
  }
}

function renderTexasActionMirror(actions) {
  const box = $("texasActionMirror");
  if (!box) return;
  const list = Array.isArray(actions) ? actions : [];
  if (!list.length) {
    box.innerHTML = '<span class="muted">—</span>';
    return;
  }
  box.innerHTML = list.map(a => {
    const enabled = !!a.enabled;
    const params = a.params && Object.keys(a.params).length ? JSON.stringify(a.params) : '';
    const reason = enabled ? '' : (a.disabled_reason || 'disabled');
    return `<div class="texas-action-chip ${enabled ? 'enabled' : 'disabled'}" data-action-id="${escapeHtml(a.id || '')}" data-action-enabled="${enabled ? 'true' : 'false'}" data-disabled-reason="${escapeHtml(reason)}">
      <span><strong>${escapeHtml(a.id || '')}</strong> ${escapeHtml(a.label || '')}</span>
      <span class="muted">${escapeHtml(params || reason)}</span>
    </div>`;
  }).join('');
}

async function _texasAction(action, extra) {
  if (!gameId || !token) { log(t('log_need_login') || 'need login', 'err'); return; }
  const body = Object.assign({ token, action }, extra || {});
  try {
    const r = await gameAction(action === "allin" ? "all_in" : action, extra || {});
    if (r && r.result) log(`[texas] ${action} → ${JSON.stringify(r.result)}`, 'me');
    else log(`[texas] ${action} ok`, 'me');
    refresh();
  } catch (e) {
    log(`[texas] ${action} fail: ${e.message}`, 'err');
  }
}

(function bindTexas(){
  const bind = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  bind("btnTexasFold", () => { if (confirm(t('texas_confirm_fold'))) _texasAction("fold"); });
  bind("btnTexasCheck", () => _texasAction("check"));
  bind("btnTexasCall", () => _texasAction("call"));
  bind("btnTexasRaise", () => {
    const v = parseInt(( $("texasRaiseNumber") || $("texasRaiseInput") || {} ).value, 10);
    if (!Number.isFinite(v) || v <= 0) { log(t('texas_invalid_raise'), 'err'); return; }
    _texasAction("raise", { amount: v });
  });
  const syncRaise = (from, to) => {
    const a = document.getElementById(from), b = document.getElementById(to);
    if (!a || !b) return;
    a.addEventListener('input', () => { b.value = a.value; });
  };
  syncRaise("texasRaiseInput", "texasRaiseNumber");
  syncRaise("texasRaiseNumber", "texasRaiseInput");
  bind("btnTexasAllin", () => _texasAction("all_in"));
  bind("btnTexasLeaveRoom", () => $("btnLeaveRoom").click());
  bind("btnTexasDisband", () => $("btnDisband").click());
  bind("btnTexasRestart", () => $("btnRestart").click());
})();
