function renderZjh() {
  if (!state) return;
  const me = state.you || null;
  // seats rail
  const seatsBox = $("seatsRail");
  if (seatsBox) {
    seatsBox.innerHTML = "";
    for (let i = 0; i < 3; i++) {
      const p = state.players[i] || {};
      const d = document.createElement("div");
      d.className = "seat" + (i === mySeat ? " me" : "");
      const badges = [];
      if (i === mySeat) badges.push(`<span class="badge you">${escapeHtml(t('badge_you'))}</span>`);
      if (i === state.owner_seat) badges.push(`<span class="badge" style="background:#a78bfa;color:#fff">${escapeHtml(t('badge_owner'))}</span>`);
      if (i === state.dealer_seat) badges.push(`<span class="badge" style="background:#f59e0b;color:#fff">${escapeHtml(t('zjh_badge_dealer'))}</span>`);
      if (i === state.current_turn && state.phase === "playing") badges.push(`<span class="badge you">${escapeHtml(t('badge_playing'))}</span>`);
      if (state.phase === "finished" && i === state.winner_seat) badges.push(`<span class="badge" style="background:#22c55e;color:#fff">${escapeHtml(t('zjh_badge_winner'))}</span>`);
      if (p.folded) badges.push(`<span class="badge" style="background:#9ca3af;color:#fff">${escapeHtml(t('zjh_badge_fold'))}</span>`);
      else if (p.seen) badges.push(`<span class="badge" style="background:#06b6d4;color:#fff">${escapeHtml(t('zjh_badge_seen'))}</span>`);
      else if (p.joined && state.phase === "playing") badges.push(`<span class="badge" style="background:#64748b;color:#fff">${escapeHtml(t('zjh_badge_blind'))}</span>`);
      const bioHtml = (p.joined && p.bio) ? `<div class="bio">${escapeHtml(p.bio)}</div>` : "";
      d.innerHTML = `
        <div class="name">${escapeHtml(t('seat_label'))}${i}: ${p.name ? escapeHtml(p.name) : `<em class="muted">${escapeHtml(t('seat_empty'))}</em>`}</div>
        <div class="seat-zjh-info">${escapeHtml(t('zjh_chips_label'))}<span class="seat-zjh-chips">${p.chips != null ? p.chips : '-'}</span> · ${escapeHtml(t('zjh_bet_label'))}<strong>${p.bet_in_round != null ? p.bet_in_round : 0}</strong></div>
        <div style="margin-top:4px">${badges.join(' ')}</div>
        ${bioHtml}
      `;
      if (p.hand && p.hand.length && i !== mySeat) {
        const sh = document.createElement("div"); sh.className = "spec-hand";
        for (const c of p.hand) sh.appendChild(renderCard(c, false));
        d.appendChild(sh);
      }
      seatsBox.appendChild(d);
    }
  }
  // meta
  $("zjhRound").textContent = state.round_no != null ? state.round_no : '—';
  $("zjhPot").textContent = state.pot != null ? state.pot : 0;
  $("zjhStake").textContent = state.stake != null ? state.stake : 1;
  $("zjhMaxStake").textContent = state.max_stake != null ? state.max_stake : 20;
  if (state.dealer_seat != null && state.dealer_seat >= 0) {
    const dp = state.players[state.dealer_seat] || {};
    $("zjhDealer").textContent = `${state.dealer_seat}${dp.name ? ' · ' + dp.name : ''}`;
  } else {
    $("zjhDealer").textContent = '—';
  }
  // history (current round only)
  const histBox = $("zjhHistory");
  histBox.innerHTML = "";
  const hist = Array.isArray(state.history) ? state.history : [];
  let startIdx = 0;
  for (let i = hist.length - 1; i >= 0; i--) {
    if (hist[i].action === 'win') { startIdx = i + 1; break; }
  }
  const cur = hist.slice(startIdx);
  if (!cur.length) {
    histBox.innerHTML = `<div class="empty">${escapeHtml(t('zjh_history_empty'))}</div>`;
  } else {
    for (let i = 0; i < cur.length; i++) {
      const h = cur[i];
      const row = document.createElement('div');
      row.className = 'zjh-history-row' + (i === cur.length - 1 ? ' latest' : '');
      const pl = state.players[h.seat] || {};
      const nm = pl.name || `${t('seat_label')}${h.seat}`;
      let desc = ''; let cls = 'act-' + h.action;
      if (h.action === 'look') desc = t('zjh_log_look');
      else if (h.action === 'call') desc = `${t('zjh_log_call')} ${h.amount}`;
      else if (h.action === 'raise') desc = `${t('zjh_log_raise')} ${h.amount}` + (h.note ? ` (${h.note})` : '');
      else if (h.action === 'fold') desc = t('zjh_log_fold');
      else if (h.action === 'timeout_fold') desc = t('zjh_log_timeout_fold');
      else if (h.action === 'compare') {
        const tp = state.players[h.target_seat] || {};
        const tn = tp.name || `${t('seat_label')}${h.target_seat}`;
        desc = `${t('zjh_log_compare')} ${tn}` + (h.note ? ` (${h.note})` : '');
      } else if (h.action === 'win') desc = `${t('zjh_log_win')} +${h.amount}`;
      else desc = h.action;
      row.innerHTML = `<span class="who">${escapeHtml(nm)}</span> <span class="${cls}">${escapeHtml(desc)}</span>`;
      histBox.appendChild(row);
    }
  }
  // my hand
  const handBox = $("zjhHand");
  handBox.innerHTML = "";
  if (me) {
    const myHand = me.hand || [];
    if (myHand.length && me.seen) {
      for (const c of myHand) handBox.appendChild(renderCard(c, false));
    } else if (state.phase === "playing" && !me.folded) {
      for (let i = 0; i < 3; i++) {
        const back = document.createElement('div');
        back.className = 'zjh-card-back';
        handBox.appendChild(back);
      }
    } else {
      handBox.innerHTML = `<span class="muted">${escapeHtml(t('zjh_no_hand'))}</span>`;
    }
  } else {
    handBox.innerHTML = `<span class="muted">${escapeHtml(t('spec_no_hand'))}</span>`;
  }
  // owner buttons
  const isOwner = !!(me && state.owner_seat === me.seat);
  $("btnZjhDisband").style.display = isOwner ? "" : "none";
  const canRestart = isOwner && state.phase === "finished" && !state.disbanded;
  $("btnZjhRestart").style.display = canRestart ? "" : "none";
  // action area
  const playing = state.phase === "playing";
  const myFolded = me && me.folded;
  const showActions = !!(me && playing && !myFolded);
  $("zjhActionArea").style.display = showActions ? "" : "none";
  if (showActions) {
    const myTurn = !!me.is_your_turn;
    const tc = state.turn_clock || {};
    const canAct = !!tc.can_act;
    $("btnZjhLook").disabled = !!me.seen;
    $("btnZjhCall").disabled = !myTurn || !canAct;
    $("btnZjhCall").textContent = `${t('zjh_btn_call')} (${me.call_cost != null ? me.call_cost : '?'})`;
    $("btnZjhRaise").disabled = !myTurn || !canAct;
    const ri = $("zjhRaiseInput");
    ri.disabled = !myTurn || !canAct;
    ri.min = (state.stake || 0) + 1;
    ri.max = state.max_stake;
    if (!ri.value || parseInt(ri.value, 10) <= state.stake) {
      ri.value = Math.min((state.stake || 0) + 1, state.max_stake);
    }
    $("btnZjhFold").disabled = !myTurn || !canAct;
    $("btnZjhCompare").disabled = !myTurn || !canAct || !me.seen;
    const sel = $("zjhCompareTarget");
    const prev = sel.value;
    sel.innerHTML = "";
    let any = false;
    for (let i = 0; i < 3; i++) {
      const p = state.players[i] || {};
      if (!p.joined || i === me.seat || p.folded) continue;
      const opt = document.createElement('option');
      opt.value = i;
      opt.textContent = `${t('seat_label')}${i}${p.name ? ': ' + p.name : ''}`;
      sel.appendChild(opt);
      any = true;
    }
    if (any && prev) sel.value = prev;
    if (!any) {
      const opt = document.createElement('option');
      opt.value = ""; opt.textContent = '—';
      sel.appendChild(opt);
    }
    $("zjhTurnInfo").textContent = myTurn ? t('my_turn') : "";
  }
  // big status
  let bigParts = [];
  if (playing) {
    const cs = state.current_turn;
    const cp = state.players[cs] || {};
    bigParts.push(`<span style="font-size:20px;font-weight:800;color:#b45309;background:#fef3c7;padding:6px 14px;border-radius:6px;border:2px solid #f59e0b">${escapeHtml(t('cur_play_prefix'))}${cs}${cp.name ? ' · ' + escapeHtml(cp.name) : ''}</span>`);
  } else if (state.phase === "finished") {
    const w = state.winner_seat;
    if (w >= 0) {
      const winner = state.players[w] || {};
      bigParts.push(`<span style="font-size:20px;font-weight:800;color:#15803d;background:#dcfce7;padding:6px 14px;border-radius:6px;border:2px solid #22c55e">${escapeHtml(t('winner_prefix'))}${w}${winner.name ? ' · ' + escapeHtml(winner.name) : ''}</span>`);
    }
  } else if (state.phase === "waiting") {
    bigParts.push(`<span class="muted">${escapeHtml(t('zjh_waiting'))}</span>`);
  }
  if (state.disbanded) {
    bigParts.push(`<span style="margin-left:8px;color:#dc2626">${escapeHtml(t('disbanded'))}</span>`);
  }
  $("zjhBoardStatus").innerHTML = bigParts.join("");
  // clocks
  const tc = state.turn_clock || {};
  if (tc.turn_started_at) {
    let serverElapsed;
    if (typeof tc.thinking_remaining === "number" && tc.thinking_remaining > 0) {
      serverElapsed = tc.think_seconds - tc.thinking_remaining;
    } else if (typeof tc.action_remaining === "number" && tc.action_remaining > 0) {
      serverElapsed = tc.total_seconds - tc.action_remaining;
    } else {
      serverElapsed = tc.total_seconds;
    }
    clockAnchorServerElapsed = Math.max(0, serverElapsed);
    clockAnchorLocalMs = performance.now();
  }
  tickClock();
  const sm = $("turnClock"), zm = $("zjhTurnClock");
  if (sm && zm) { zm.className = sm.className; zm.textContent = sm.textContent; }
  // chat
  renderChat(state.chat || []);
}

async function _zjhAction(action, extra) {
  if (!gameId || !token) { log(t('log_need_login') || 'need login', 'err'); return; }
  const body = Object.assign({ token, action }, extra || {});
  try {
    const r = await api("POST", `/api/games/${gameId}/zjh/action`, body);
    if (r && r.result) log(`[zjh] ${action} → ${JSON.stringify(r.result)}`, 'me');
    else log(`[zjh] ${action} ok`, 'me');
    refresh();
  } catch (e) {
    log(`[zjh] ${action} fail: ${e.message}`, 'err');
  }
}

(function bindZjh(){
  const bind = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  bind("btnZjhLook", () => _zjhAction("look"));
  bind("btnZjhCall", () => _zjhAction("call"));
  bind("btnZjhRaise", () => {
    const v = parseInt(($("zjhRaiseInput") || {}).value, 10);
    if (!Number.isFinite(v) || v <= 0) { log(t('zjh_invalid_raise'), 'err'); return; }
    _zjhAction("raise", { amount: v });
  });
  bind("btnZjhFold", () => { if (confirm(t('zjh_confirm_fold'))) _zjhAction("fold"); });
  bind("btnZjhCompare", () => {
    const sel = $("zjhCompareTarget");
    if (!sel || !sel.value) return;
    const target = parseInt(sel.value, 10);
    if (!confirm(t('zjh_confirm_compare'))) return;
    _zjhAction("compare", { target_seat: target });
  });
  bind("btnZjhLeaveRoom", () => $("btnLeaveRoom").click());
  bind("btnZjhDisband", () => $("btnDisband").click());
  bind("btnZjhRestart", () => $("btnRestart").click());
})();
