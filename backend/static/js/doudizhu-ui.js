function render() {
  if (!state) return;
  const gt = state.game_type;
  const isZjh = gt === 'zhajinhua';
  const isTexas = gt === 'texas_holdem';
  if ($("zjhBoard")) $("zjhBoard").style.display = isZjh ? "" : "none";
  if ($("texasBoard")) $("texasBoard").style.display = isTexas ? "" : "none";
  $("board").style.display = (isZjh || isTexas) ? "none" : "";
  if (isZjh) { renderZjh(); return; }
  if (isTexas) { renderTexas(); return; }
  // seats -> render into left rail
  const seatsBox = $("seatsRail");
  if (seatsBox) {
    seatsBox.innerHTML = "";
    for (let i = 0; i < 3; i++) {
      const p = (state.seats || state.players)[i];
      const d = document.createElement("div");
      d.className = "seat" + (i === mySeat ? " me" : "");
      const badges = [];
      if (i === mySeat) badges.push(`<span class="badge you">${escapeHtml(t('badge_you'))}</span>`);
      if (p.is_landlord) badges.push(`<span class="badge ll">${escapeHtml(t('badge_landlord'))}</span>`);
      if (i === (state.table && state.table.current_turn !== undefined ? state.table.current_turn : state.current_turn) && state.phase === "playing") badges.push(`<span class="badge you">${escapeHtml(t('badge_playing'))}</span>`);
      if (i === (state.table && state.table.bid_turn !== undefined ? state.table.bid_turn : state.bid_turn) && state.phase === "bidding") badges.push(`<span class="badge you">${escapeHtml(t('badge_bidding'))}</span>`);
      const bioHtml = (p.joined && p.bio) ? `<div class="bio">${escapeHtml(p.bio)}</div>` : "";
      d.innerHTML = `
        <div class="name">${escapeHtml(t('seat_label'))}${i}: ${p.name || `<em class="muted">${escapeHtml(t('seat_empty'))}</em>`}</div>
        <div style="font-size:12px;color:var(--muted);margin-top:2px">${escapeHtml(t('hand_count_label'))}${p.hand_count}</div>
        <div style="margin-top:4px">${badges.join(" ")}</div>
        ${bioHtml}
      `;
      // omniscient spectator: render the other seats' hands as tiny card tiles
      if (p.hand && i !== mySeat) {
        const sh = document.createElement("div");
        sh.className = "spec-hand";
        for (const c of p.hand) sh.appendChild(renderCard(c, false));
        d.appendChild(sh);
      }
      seatsBox.appendChild(d);
    }
  }
  renderDdzTableSeats();

  // table — show current trick: every play / pass since the last completed trick
  // (a trick is considered completed once we see two consecutive passes at its tail;
  // the next play then starts a fresh trick)
  const tableEl = $("table");
  tableEl.innerHTML = "";
  const hist = Array.isArray(((state.table && state.table.history) || state.history)) ? ((state.table && state.table.history) || state.history) : [];
  const currentTrick = [];
  for (const h of hist) {
    const isPass = !h.cards || h.cards.length === 0;
    if (!isPass) {
      // if the previous trick already ended in 2 passes, reset
      const n = currentTrick.length;
      if (n >= 2
          && (!currentTrick[n-1].cards || currentTrick[n-1].cards.length === 0)
          && (!currentTrick[n-2].cards || currentTrick[n-2].cards.length === 0)) {
        currentTrick.length = 0;
      }
      currentTrick.push(h);
    } else if (currentTrick.length > 0) {
      currentTrick.push(h);
    }
  }
  if (currentTrick.length === 0) {
    tableEl.innerHTML = `<div class="empty">${escapeHtml(t('trick_empty'))}</div>`;
  } else {
    for (let idx = 0; idx < currentTrick.length; idx++) {
      const h = currentTrick[idx];
      const isPass = !h.cards || h.cards.length === 0;
      const row = document.createElement('div');
      row.className = 'trick-row' + (idx === currentTrick.length - 1 ? ' latest' : '');
      const who = document.createElement('div');
      who.className = 'who';
      const pl = (state.seats || state.players) && (state.seats || state.players)[h.seat];
      const nm = (pl && pl.name) ? pl.name : `${t('seat_label')}${h.seat}`;
      who.appendChild(document.createTextNode(nm));
      if (pl && pl.is_landlord) {
        const ll = document.createElement('span');
        ll.className = 'll';
        ll.textContent = `[${t('trick_landlord_mark')}]`;
        who.appendChild(ll);
      }
      row.appendChild(who);
      const cardsBox = document.createElement('div');
      cardsBox.className = 'cards';
      if (isPass) {
        const tag = document.createElement('span');
        tag.className = 'pass-tag';
        tag.textContent = t('trick_pass_label');
        cardsBox.appendChild(tag);
      } else {
        for (const c of h.cards) cardsBox.appendChild(renderCard(c, false));
      }
      row.appendChild(cardsBox);
      tableEl.appendChild(row);
    }
  }
  // bottom
  const b = $("bottom");
  b.innerHTML = "";
  if (((state.table && state.table.bottom_cards) || state.bottom_cards) && ((state.table && state.table.bottom_cards) || state.bottom_cards).length) {
    for (const c of ((state.table && state.table.bottom_cards) || state.bottom_cards)) b.appendChild(renderCard(c, false));
  } else {
    b.innerHTML = `<span class="muted">${escapeHtml(t('bottom_hidden'))}</span>`;
  }
  // hand
  const h = $("myHand");
  h.innerHTML = "";
  const myHand = (state.you && state.you.hand) || [];
  const myCodes = new Set(myHand);
  for (const c of Array.from(selected)) if (!myCodes.has(c)) selected.delete(c);
  for (const c of myHand) h.appendChild(renderCard(c, true));
  if (!state.you) {
    h.innerHTML = `<span class="muted">${escapeHtml(t('spec_no_hand'))}</span>`;
  }
  updateDdzSelectionInfo();
  // owner-only buttons
  const isOwner = state.you && state.owner_seat === state.you.seat;
  $("btnDisband").style.display = isOwner ? "" : "none";
  $("btnDisband").textContent = t('board_disband');
  // restart only when round finished (and not disbanded)
  const canRestart = isOwner && state.phase === "finished" && !state.disbanded;
  $("btnRestart").style.display = canRestart ? "" : "none";
  // disbanded state
  if (state.disbanded) {
    $("turnClock").className = "clock idle";
    $("turnClock").textContent = t('disbanded');
  }
  // bid/play areas
  const myTurn = !!(state.you && state.you.is_your_turn);
  const tc = state.turn_clock || {};
  const canAct = !!tc.can_act;
  $("bidArea").style.display = state.phase === "bidding" && myTurn ? "" : "none";
  $("playArea").style.display = state.phase === "playing" && myTurn ? "" : "none";
  const actionById = new Map(((state && state.actions) || []).map(a => [a && a.id, a]));
  const bidAction = actionById.get('bid') || null;
  document.querySelectorAll("#bidArea button[data-bid]").forEach(b => {
    const value = Number(b.dataset.bid);
    const enabled = !!(bidAction && bidAction.enabled && Number(bidAction.params && bidAction.params.bid) === value);
    const reason = bidAction && !enabled ? (bidAction.disabled_reason || 'not callable') : '';
    b.disabled = !enabled;
    b.dataset.actionId = 'bid';
    b.dataset.actionEnabled = enabled ? 'true' : 'false';
    b.title = reason;
  });
  ['play_cards', 'pass', 'play_hint'].forEach(id => {
    const a = actionById.get(id);
    const btn = id === 'play_cards' ? $('btnPlay') : (id === 'pass' ? $('btnPass') : $('btnHint'));
    if (!btn) return;
    const enabled = !!(a && a.enabled);
    btn.disabled = !enabled;
    btn.dataset.actionId = id;
    btn.dataset.actionEnabled = enabled ? 'true' : 'false';
    btn.title = enabled ? '' : ((a && a.disabled_reason) || 'not callable');
  });
  // Anchor clock to server-reported elapsed; tickClock advances locally from here.
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

  let bigParts = [];
  if (state.phase === "playing") {
    const cs = (state.table && state.table.current_turn !== undefined ? state.table.current_turn : state.current_turn);
    const cp = state.players[cs];
    const cname = (cp && cp.name) ? cp.name : "";
    bigParts.push(`<span style="font-size:20px;font-weight:800;color:#b45309;background:#fef3c7;padding:6px 14px;border-radius:6px;border:2px solid #f59e0b">${escapeHtml(t('cur_play_prefix'))}${cs}${cname ? " · " + escapeHtml(cname) : ""}</span>`);
  } else if (state.phase === "bidding") {
    const cs = (state.table && state.table.bid_turn !== undefined ? state.table.bid_turn : state.bid_turn);
    const cp = state.players[cs];
    const cname = (cp && cp.name) ? cp.name : "";
    bigParts.push(`<span style="font-size:20px;font-weight:800;color:#6d28d9;background:#ede9fe;padding:6px 14px;border-radius:6px;border:2px solid #8b5cf6">${escapeHtml(t('cur_bid_prefix'))}${cs}${cname ? " · " + escapeHtml(cname) : ""}</span>`);
  } else if (state.phase === "finished") {
    const w = (state.table && state.table.winner_seat !== undefined ? state.table.winner_seat : state.winner_seat);
    const winner = state.players[w];
    bigParts.push(`<span style="font-size:20px;font-weight:800;color:#15803d;background:#dcfce7;padding:6px 14px;border-radius:6px;border:2px solid #22c55e">${escapeHtml(t('winner_prefix'))}${w} · ${escapeHtml(winner.name || "")} ${winner.is_landlord ? '('+escapeHtml(t('landlord'))+')' : '('+escapeHtml(t('farmer'))+')'}</span>`);
  }
  $("boardStatus").innerHTML = bigParts.join("");
  $("turnInfo").textContent = (state.you && state.you.is_your_turn) ? t('my_turn') : "";

  // chat
  renderChat(state.chat || []);
}

function renderDdzTableSeats() {
  const seats = gameSeats();
  const meSeat = state.you ? state.you.seat : mySeat;
  const current = state.phase === "bidding" ? gameBidTurn() : gameCurrentTurn();
  const positions = ["Left", "Top", "Right"];
  for (let i = 0; i < 3; i++) {
    const box = $(`ddzSeat${positions[i]}`);
    if (!box) continue;
    const p = seats[i] || { seat:i, joined:false };
    let cls = `ddz-player ddz-player-${positions[i].toLowerCase()}`;
    if (i === current && (state.phase === "playing" || state.phase === "bidding")) cls += " active";
    if (i === meSeat) cls += " me";
    box.className = cls;
    const badges = [];
    if (i === meSeat) badges.push(`<span class="badge you">${escapeHtml(t('badge_you'))}</span>`);
    if (p.is_landlord) badges.push(`<span class="badge ll">${escapeHtml(t('badge_landlord'))}</span>`);
    if (i === current && state.phase === "playing") badges.push(`<span class="badge you">${escapeHtml(t('badge_playing'))}</span>`);
    if (i === current && state.phase === "bidding") badges.push(`<span class="badge you">${escapeHtml(t('badge_bidding'))}</span>`);
    const name = p.joined ? (p.name || `${t('seat_label')}${i}`) : t('seat_empty');
    const handCount = p.hand_count != null ? p.hand_count : ((p.hand || []).length || 0);
    box.innerHTML = `
      <div class="ddz-player-name"><strong>#${i}</strong> ${escapeHtml(name)}</div>
      <div class="ddz-player-meta"><span>${escapeHtml(t('hand_count_label'))}${handCount}</span><span>${p.is_landlord ? escapeHtml(t('landlord')) : escapeHtml(t('farmer'))}</span></div>
      <div class="ddz-player-badges">${badges.join(' ')}</div>
    `;
  }
}

function updateDdzSelectionInfo() {
  const info = $("ddzSelectionInfo");
  if (!info) return;
  const n = selected.size;
  const pattern = identifyDdzCards(Array.from(selected));
  info.textContent = n ? `${n} selected${pattern ? ' · ' + pattern.category : ''}` : '—';
}

const DDZ_VALUE = { "3":3, "4":4, "5":5, "6":6, "7":7, "8":8, "9":9, "T":10, "J":11, "Q":12, "K":13, "A":14, "2":15, "SJ":16, "BJ":17 };
function ddzRank(code) { return code === "SJ" || code === "BJ" ? code : String(code || '')[0]; }
function ddzValue(codeOrRank) { return DDZ_VALUE[codeOrRank] || DDZ_VALUE[ddzRank(codeOrRank)] || 0; }
function ddzGroups(cards) {
  const m = new Map();
  cards.forEach(c => { const r = ddzRank(c); if (!m.has(r)) m.set(r, []); m.get(r).push(c); });
  return Array.from(m.entries()).map(([rank, cards]) => ({ rank, value:ddzValue(rank), cards })).sort((a,b) => a.value - b.value);
}
function isDdzStraight(groups, needLen, stepCount) {
  if (groups.length < needLen || groups.some(g => g.cards.length !== stepCount || g.value >= 15)) return false;
  for (let i = 1; i < groups.length; i++) if (groups[i].value !== groups[i-1].value + 1) return false;
  return true;
}
function identifyDdzCards(cards) {
  cards = Array.from(cards || []);
  const n = cards.length;
  if (!n) return null;
  const groups = ddzGroups(cards);
  const counts = groups.map(g => g.cards.length).sort((a,b) => b-a);
  if (n === 1) return { category:'single', main:ddzValue(cards[0]), len:1 };
  if (n === 2 && groups.length === 2 && groups.some(g => g.rank === 'SJ') && groups.some(g => g.rank === 'BJ')) return { category:'rocket', main:17, len:2 };
  if (n === 2 && groups.length === 1) return { category:'pair', main:groups[0].value, len:2 };
  if (n === 3 && groups.length === 1) return { category:'trio', main:groups[0].value, len:3 };
  if (n === 4 && groups.length === 1) return { category:'bomb', main:groups[0].value, len:4 };
  if (n === 4 && counts[0] === 3) return { category:'trio_single', main:groups.find(g => g.cards.length === 3).value, len:4 };
  if (n === 5 && counts[0] === 3 && counts[1] === 2) return { category:'trio_pair', main:groups.find(g => g.cards.length === 3).value, len:5 };
  if (n >= 5 && isDdzStraight(groups, 5, 1)) return { category:'straight', main:groups[groups.length - 1].value, len:n };
  if (n >= 6 && n % 2 === 0 && isDdzStraight(groups, 3, 2)) return { category:'pair_straight', main:groups[groups.length - 1].value, len:n };
  const triples = groups.filter(g => g.cards.length === 3).sort((a,b) => a.value - b.value);
  if (triples.length >= 2 && triples.every(g => g.value < 15)) {
    let consec = true;
    for (let i = 1; i < triples.length; i++) if (triples[i].value !== triples[i-1].value + 1) consec = false;
    if (consec && (n === triples.length * 3 || n === triples.length * 4 || n === triples.length * 5)) {
      return { category:'airplane', main:triples[triples.length - 1].value, len:n, triples:triples.length };
    }
  }
  return null;
}
function ddzBeats(prev, curr) {
  if (!curr) return false;
  if (!prev) return true;
  if (curr.category === 'rocket') return prev.category !== 'rocket';
  if (curr.category === 'bomb' && prev.category !== 'bomb' && prev.category !== 'rocket') return true;
  if (curr.category !== prev.category || curr.len !== prev.len) return false;
  return curr.main > prev.main;
}
function ddzBackendHint() {
  const action = ((state && state.actions) || []).find(a => a && a.id === 'play_hint' && a.params && Array.isArray(a.params.cards));
  if (!action) return null;
  return {
    cards: action.params.cards,
    pattern: action.params.pattern || null,
    reason: action.params.hint_reason || action.label || 'backend hint',
    source: 'backend',
    enabled: !!action.enabled,
    disabled_reason: action.disabled_reason || '',
  };
}

function findDdzHint() {
  const backend = ddzBackendHint();
  if (backend && backend.cards && backend.cards.length) return backend;
  const hand = ((state && state.you && state.you.hand) || []).slice().sort((a,b) => ddzValue(a) - ddzValue(b));
  if (!hand.length) return null;
  const table = gameTable();
  const mustLead = (table.last_play_seat ?? state.last_play_seat ?? -1) === -1 || (state.you && (table.last_play_seat ?? state.last_play_seat) === state.you.seat);
  const prevCards = mustLead ? [] : ((table.last_play_cards || state.last_play_cards || []).slice());
  const prev = identifyDdzCards(prevCards);
  const groups = ddzGroups(hand);
  const candidates = [];
  const add = (cards, reason) => { const p = identifyDdzCards(cards); if (p && (mustLead || ddzBeats(prev, p))) candidates.push({ cards, pattern:p, reason }); };
  groups.forEach(g => add([g.cards[0]], 'smallest legal single'));
  groups.filter(g => g.cards.length >= 2).forEach(g => add(g.cards.slice(0,2), 'smallest legal pair'));
  groups.filter(g => g.cards.length >= 3).forEach(g => add(g.cards.slice(0,3), 'smallest legal triple'));
  groups.filter(g => g.cards.length === 4).forEach(g => add(g.cards.slice(0,4), 'bomb'));
  const sj = hand.find(c => c === 'SJ'), bj = hand.find(c => c === 'BJ');
  if (sj && bj) add([sj, bj], 'rocket');
  candidates.sort((a,b) => {
    const bombA = a.pattern.category === 'bomb' || a.pattern.category === 'rocket';
    const bombB = b.pattern.category === 'bomb' || b.pattern.category === 'rocket';
    if (bombA !== bombB && prev && prev.category !== 'bomb' && prev.category !== 'rocket') return bombA ? 1 : -1;
    if (a.cards.length !== b.cards.length) return a.cards.length - b.cards.length;
    return a.pattern.main - b.pattern.main;
  });
  const hint = candidates[0] || null;
  if (hint) hint.source = 'local';
  return hint;
}
