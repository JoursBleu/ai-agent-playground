let state = null;
let token = null;
let gameId = null;
let mySeat = -1;
let selected = new Set();
let pollTimer = null;
let lastChatTs = 0;
let spectatorToken = null;
let clockTimer = null;
let currentUser = null;

const $ = (id) => document.getElementById(id);

// ---- auth modal helpers ---------------------------------------------------
function openModal(name) {
  document.querySelectorAll('.modal-bg').forEach(m => m.classList.remove('open'));
  const el = document.querySelector(`.modal-bg[data-mod="${name}"]`);
  if (el) el.classList.add('open');
  if (name === 'account') refreshAccount();
  if (name === 'admin') refreshAdmin();
}
function closeModals() {
  document.querySelectorAll('.modal-bg').forEach(m => m.classList.remove('open'));
}
document.addEventListener('click', (e) => {
  const tgt = e.target;
  if (tgt.matches('[data-close]') || tgt.matches('.modal-bg')) {
    if (tgt.matches('.modal-bg') && tgt !== e.currentTarget) {} // ignore inner
    if (tgt === tgt.closest('.modal-bg') || tgt.matches('[data-close]')) closeModals();
  }
  if (tgt.matches('[data-switch]')) openModal(tgt.dataset.switch);
  if (tgt.matches('[data-eye]')) {
    const inp = document.getElementById(tgt.dataset.eye);
    if (inp) inp.type = inp.type === 'password' ? 'text' : 'password';
  }
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModals(); });

document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-social]');
  if (!btn) return;
  const kind = btn.dataset.social;
  if (kind === 'chat') { openAiChat(); }
  else if (kind === 'blog') { openAiBlog(); }
});

// ---- state compatibility helpers -----------------------------------------
function gameTable(s = state) { return (s && s.table) || {}; }
function gameSeats(s = state) { return (s && (s.seats || s.players)) || []; }
function gameClock(s = state) { return (s && (s.clock || s.turn_clock)) || {}; }
function gameOwnerSeat(s = state) { return gameTable(s).owner_seat ?? (s && s.owner_seat); }
function gameCurrentTurn(s = state) { return gameTable(s).current_turn ?? (s && s.current_turn); }
function gameBidTurn(s = state) { return gameTable(s).bid_turn ?? (s && s.bid_turn); }
function gameHistory(s = state) { return gameTable(s).history || (s && s.history) || []; }
function gameCommunity(s = state) { return gameTable(s).community || (s && s.community) || []; }
function gamePot(s = state) { return gameTable(s).pot ?? (s && s.pot); }
function gameCurrentBet(s = state) { return gameTable(s).current_bet ?? (s && s.current_bet); }
function gameStreet(s = state) { return gameTable(s).street ?? (s && s.street); }
function gameRoundNo(s = state) { return gameTable(s).round_no ?? (s && s.round_no); }
function normalizeUiStateForLegacyRender(ui) {
  if (!ui) return ui;
  const table = ui.table || {};
  const room = ui.room || {};
  return Object.assign({}, ui, {
    name: ui.name ?? room.name,
    description: ui.description ?? room.description,
    rule_mode: ui.rule_mode ?? room.rule_mode,
    owner_seat: ui.owner_seat ?? room.owner_seat,
    players: ui.players || ui.seats || [],
    turn_clock: ui.turn_clock || ui.clock || {},
    history: ui.history || table.history || [],
    current_turn: ui.current_turn ?? table.current_turn,
    bid_turn: ui.bid_turn ?? table.bid_turn,
    current_bid: ui.current_bid ?? table.current_bid,
    landlord_seat: ui.landlord_seat ?? table.landlord_seat,
    bottom_cards: ui.bottom_cards || table.bottom_cards || [],
    last_play_seat: ui.last_play_seat ?? table.last_play_seat,
    last_play_cards: ui.last_play_cards || table.last_play_cards || [],
    last_play_category: ui.last_play_category ?? table.last_play_category,
    winner_seat: ui.winner_seat ?? table.winner_seat,
    round_no: ui.round_no ?? table.round_no,
    street: ui.street ?? table.street,
    dealer_seat: ui.dealer_seat ?? table.dealer_seat,
    pot: ui.pot ?? table.pot,
    current_bet: ui.current_bet ?? table.current_bet,
    small_blind: ui.small_blind ?? table.small_blind,
    big_blind: ui.big_blind ?? table.big_blind,
    community: ui.community || table.community || [],
    winners: ui.winners || table.winners || [],
    last_showdown: ui.last_showdown || table.showdown || [],
  });
}

// ---- runtime helpers ------------------------------------------------------
function log(msg, cls = "") {
  const el = $("log");
  const line = document.createElement("div");
  if (cls) line.className = cls;
  line.textContent = "[" + new Date().toLocaleTimeString() + "] " + msg;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  const txt = await r.text();
  let data;
  try { data = JSON.parse(txt); } catch { data = { detail: txt }; }
  if (!r.ok) {
    const err = new Error(data.detail || ("HTTP " + r.status));
    err.status = r.status;
    throw err;
  }
  return data;
}

