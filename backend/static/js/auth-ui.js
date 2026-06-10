function renderUserbar() {
  const bar = $('userbar');
  if (!bar) return;
  if (currentUser) {
    const admin = currentUser.is_admin;
    bar.innerHTML = `
      <div class="user-chip">
        <button class="user-chip-btn" id="userChipBtn">
          ${admin ? `<span class="admin-dot" title="${escapeHtml(t('admin_dot_title'))}"></span>` : ''}
          <span>${escapeHtml(currentUser.username)}</span>
          <span class="points-pill" title="${escapeHtml(t('points_label'))}" style="margin-left:6px;padding:1px 8px;border-radius:10px;background:#fde68a;color:#78350f;font-size:11px;font-weight:600">★ ${currentUser.points != null ? currentUser.points : 0}</span>
          <span style="color:var(--muted);font-size:11px;margin-left:4px">▼</span>
        </button>
        <div id="userMenu" class="menu">
          <button data-act="account">${escapeHtml(t('menu_account'))}</button>
          <button data-act="points">${escapeHtml(t('menu_points'))}</button>
          <button data-act="recharge">${escapeHtml(t('menu_recharge'))}</button>
          ${admin ? `<button data-act="admin">${escapeHtml(t('menu_admin'))}</button>` : ''}
          <button data-act="logout">${escapeHtml(t('btn_logout'))}</button>
        </div>
      </div>`;
    $('userChipBtn').onclick = (e) => { e.stopPropagation(); $('userMenu').classList.toggle('open'); };
    document.addEventListener('click', () => { const m = $('userMenu'); if (m) m.classList.remove('open'); }, { once: true });
    bar.querySelectorAll('.menu button').forEach(b => {
      b.onclick = (e) => {
        e.stopPropagation();
        $('userMenu').classList.remove('open');
        const act = b.dataset.act;
        if (act === 'logout') doLogout();
        else {
          openModal(act);
          if (act === 'points') refreshPoints();
          else if (act === 'recharge') { openRecharge(); return; }
        }
      };
    });
  } else {
    bar.innerHTML = `
      <button id="btnShowLogin" class="ghost anon-btn">${escapeHtml(t('btn_login'))}</button>
      <button id="btnShowRegister" class="anon-btn">${escapeHtml(t('btn_register'))}</button>`;
    $('btnShowLogin').onclick = () => openModal('login');
    $('btnShowRegister').onclick = () => openModal('register');
  }
  // Lobby gating: show hint + disable create/join buttons when anonymous
  const loggedIn = !!currentUser;
  const hint = document.getElementById('lobbyLoginHint');
  if (hint) hint.style.display = loggedIn ? 'none' : '';
  for (const id of ['btnCreate', 'btnJoinExisting']) {
    const b = document.getElementById(id);
    if (b) {
      b.disabled = !loggedIn;
      b.title = loggedIn ? '' : t('hint_login_required');
      b.style.opacity = loggedIn ? '' : '0.55';
      b.style.cursor = loggedIn ? '' : 'not-allowed';
    }
  }
}

async function loadMe() {
  try {
    const r = await api('GET', '/api/auth/me');
    currentUser = r.user;
  } catch { currentUser = null; }
  renderUserbar();
}

async function doLogin() {
  $('loginErr').textContent = '';
  const login = $('loginLogin').value.trim();
  const password = $('loginPassword').value;
  if (!login || !password) { $('loginErr').textContent = t('err_fill_login'); return; }
  try {
    const r = await api('POST', '/api/auth/login', { login, password });
    currentUser = r.user;
    closeModals();
    renderUserbar();
    log(t('log_loggedin') + currentUser.username, 'me');
  } catch (e) { $('loginErr').textContent = e.message; }
}

async function doRegister() {
  $('regErr').textContent = '';
  const username = $('regUsername').value.trim();
  const email = $('regEmail').value.trim();
  const code = $('regCode').value.trim();
  const password = $('regPassword').value;
  const password2 = $('regPassword2').value;
  if (!username || !password) { $('regErr').textContent = t('err_fill_login'); return; }
  if (!email) { $('regErr').textContent = t('err_email_required'); return; }
  if (!code) { $('regErr').textContent = t('err_code_required'); return; }
  if (password !== password2) { $('regErr').textContent = t('err_password_mismatch'); return; }
  try {
    const r = await api('POST', '/api/auth/register', { username, password, email, code });
    currentUser = r.user;
    closeModals();
    renderUserbar();
    log(t('log_register_ok') + currentUser.username, 'me');
  } catch (e) { $('regErr').textContent = e.message; }
}

// ---- email verification code helpers ----
const _codeCooldown = {};   // { btnId: epoch_ms_unlock }
function _startCooldown(btnId, seconds) {
  const btn = $(btnId);
  if (!btn) return;
  btn.dataset.label = btn.dataset.label || btn.textContent;
  _codeCooldown[btnId] = Date.now() + seconds * 1000;
  btn.disabled = true;
  const tick = () => {
    const remain = Math.max(0, Math.ceil((_codeCooldown[btnId] - Date.now()) / 1000));
    if (remain <= 0) {
      btn.disabled = false;
      btn.textContent = t('btn_send_code');
      return;
    }
    btn.textContent = t('btn_resend_in').replace('{s}', remain);
    setTimeout(tick, 500);
  };
  tick();
}

async function doRecoverUsername() {
  const errEl = $('recoverErr'); const okEl = $('recoverOk');
  errEl.textContent = ''; okEl.style.display = 'none';
  const email = $('recoverEmail').value.trim();
  if (!email) { errEl.textContent = t('err_email_required'); return; }
  const btn = $('btnRecoverSubmit');
  if (btn) { btn.disabled = true; btn.dataset.label = btn.dataset.label || btn.textContent; btn.textContent = t('sending'); }
  try {
    const r = await api('POST', '/api/auth/account-lookup', { email });
    okEl.style.display = 'block';
    _startCooldown('btnRecoverSubmit', r.resend_after || 60);
  } catch (e) {
    errEl.textContent = e.message;
    if (btn) { btn.disabled = false; btn.textContent = t('btn_send'); }
  }
}

async function _sendForgotCode() {
  const errEl = $('forgotErr'); errEl.textContent = '';
  const username = $('forgotUsername').value.trim();
  if (!username) { errEl.textContent = t('err_username_required') || '请填写用户名'; return; }
  const btn = $('btnSendForgotCode');
  if (btn) { btn.disabled = true; btn.dataset.label = btn.dataset.label || btn.textContent; btn.textContent = t('sending'); }
  try {
    const r = await api('POST', '/api/auth/forgot-password', { username });
    log(t('log_code_sent') + username, 'me');
    _startCooldown('btnSendForgotCode', r.resend_after || 60);
  } catch (e) {
    errEl.textContent = e.message;
    if (btn) { btn.disabled = false; btn.textContent = t('btn_send_code'); }
  }
}

async function _sendCode(emailFieldId, purpose, btnId, errFieldId) {
  const email = $(emailFieldId).value.trim();
  const errEl = errFieldId ? $(errFieldId) : null;
  if (errEl) errEl.textContent = '';
  if (!email) { if (errEl) errEl.textContent = t('err_email_required'); return; }
  const btn = $(btnId);
  if (btn) { btn.disabled = true; btn.dataset.label = btn.dataset.label || btn.textContent; btn.textContent = t('sending'); }
  try {
    const r = await api('POST', '/api/auth/send-code', { email, purpose });
    log(t('log_code_sent') + email, 'me');
    _startCooldown(btnId, r.resend_after || 60);
  } catch (e) {
    if (errEl) errEl.textContent = e.message;
    if (btn) { btn.disabled = false; btn.textContent = t('btn_send_code'); }
  }
}

async function doForgotPassword() {
  $('forgotErr').textContent = '';
  const username = $('forgotUsername').value.trim();
  const code = $('forgotCode').value.trim();
  const password = $('forgotPassword').value;
  const password2 = $('forgotPassword2').value;
  if (!username) { $('forgotErr').textContent = t('err_username_required') || '请填写用户名'; return; }
  if (!code) { $('forgotErr').textContent = t('err_code_required'); return; }
  if (!password) { $('forgotErr').textContent = t('err_fill_login'); return; }
  if (password !== password2) { $('forgotErr').textContent = t('err_password_mismatch'); return; }
  try {
    await api('POST', '/api/auth/reset-password', { username, code, new_password: password });
    currentUser = null;
    closeModals();
    renderUserbar();
    log(t('log_reset_ok'), 'me');
    openModal('login');
    $('loginLogin').value = username;
  } catch (e) { $('forgotErr').textContent = e.message; }
}

async function doLogout() {
  try { await api('POST', '/api/auth/logout'); } catch {}
  currentUser = null;
  renderUserbar();
  log(t('log_loggedout'));
}

async function refreshAccount() {
  if (!currentUser) { openModal('login'); return; }
  $('acctInfo').textContent = `${currentUser.username}${currentUser.email ? '  ·  ' + currentUser.email : ''}${currentUser.is_admin ? '  ·  ' + t('admin_dot_title') : ''}`;
  $('profDisplayName').value = currentUser.display_name || '';
  $('profBio').value = currentUser.bio || '';
  $('profErr').textContent = '';
  $('profErr').style.color = '';
  $('cpErr').textContent = '';
  $('cpOld').value = ''; $('cpNew').value = '';
  $('newKeyName').value = ''; $('newKeyOut').innerHTML = '';
  try {
    const r = await api('GET', '/api/auth/api-keys');
    renderKeys(r.keys);
  } catch (e) { $('keyList').innerHTML = '<div class="err">' + escapeHtml(e.message) + '</div>'; }
}

async function doSaveProfile() {
  $('profErr').textContent = '';
  $('profErr').style.color = '';
  const display_name = $('profDisplayName').value.trim();
  const bio = $('profBio').value.trim();
  try {
    const r = await api('PATCH', '/api/auth/profile', { display_name, bio });
    currentUser = r.user;
    $('profErr').style.color = 'var(--good)';
    $('profErr').textContent = t('profile_saved');
    setTimeout(() => { $('profErr').textContent = ''; $('profErr').style.color = ''; }, 1500);
  } catch (e) { $('profErr').textContent = e.message; }
}

function renderKeys(keys) {
  if (!keys.length) { $('keyList').innerHTML = `<div style="color:var(--muted);font-size:12px">${escapeHtml(t('apikey_empty'))}</div>`; return; }
  $('keyList').innerHTML = keys.map(k => {
    const revoked = !!k.revoked_at;
    const created = new Date(k.created_at * 1000).toLocaleString();
    const last = k.last_used_at ? new Date(k.last_used_at * 1000).toLocaleString() : t('apikey_never_used');
    return `<div class="key-row" style="${revoked ? 'opacity:0.5' : ''}">
      <div>
        <div><b>${escapeHtml(k.name)}</b> <span style="color:var(--muted);font-family:ui-monospace,monospace">${escapeHtml(k.key_prefix)}…</span>${revoked ? ` <span style="color:var(--bad);font-size:11px">${escapeHtml(t('apikey_revoked'))}</span>` : ''}</div>
        <div class="meta">${escapeHtml(t('apikey_created_at'))} ${created} · ${escapeHtml(t('apikey_last_used_at'))} ${last}</div>
      </div>
      ${revoked ? '' : `<button class="revoke" data-revoke="${k.id}">${escapeHtml(t('apikey_revoke'))}</button>`}
    </div>`;
  }).join('');
  $('keyList').querySelectorAll('[data-revoke]').forEach(b => {
    b.onclick = async () => {
      if (!confirm(t('apikey_confirm_revoke'))) return;
      try { await api('DELETE', '/api/auth/api-keys/' + b.dataset.revoke); await refreshAccount(); } catch (e) { alert(e.message); }
    };
  });
}

async function doCreateKey() {
  const name = $('newKeyName').value.trim();
  if (!name) { alert(t('apikey_name_required')); return; }
  try {
    const r = await api('POST', '/api/auth/api-keys', { name });
    $('newKeyOut').innerHTML = `<div class="key-new"><div style="margin-bottom:4px;color:#92400e;font-weight:600">⚠ ${escapeHtml(r.warning)}</div><div>${escapeHtml(r.key)}</div></div>`;
    $('newKeyName').value = '';
    const list = await api('GET', '/api/auth/api-keys');
    renderKeys(list.keys);
  } catch (e) { alert(e.message); }
}

async function doChangePassword() {
  $('cpErr').textContent = '';
  const old_password = $('cpOld').value;
  const new_password = $('cpNew').value;
  if (!old_password || !new_password) { $('cpErr').textContent = t('err_fill_all'); return; }
  try {
    await api('POST', '/api/auth/change-password', { old_password, new_password });
    $('cpErr').style.color = 'var(--good)';
    $('cpErr').textContent = t('change_pw_ok');
    setTimeout(() => { $('cpErr').style.color = ''; $('cpErr').textContent = ''; }, 2500);
    $('cpOld').value = ''; $('cpNew').value = '';
  } catch (e) { $('cpErr').textContent = e.message; }
}

async function refreshAdmin() {
  if (!currentUser || !currentUser.is_admin) { closeModals(); return; }
  try {
    const r = await api('GET', '/api/admin/users');
    const rows = r.users.map(u => `
      <div class="user-row" data-uid="${u.id}">
        <div style="color:var(--muted);font-family:ui-monospace,monospace">#${u.id}</div>
        <div>
          <div><b>${escapeHtml(u.username)}</b>${u.email ? ' <span style="color:var(--muted);font-size:12px">'+escapeHtml(u.email)+'</span>' : ''}</div>
          <div class="badges">
            ${u.is_admin ? '<span class="badge admin">admin</span>' : ''}
            ${u.is_banned ? '<span class="badge banned">banned'+(u.banned_reason?': '+escapeHtml(u.banned_reason):'')+'</span>' : ''}
            <span style="color:var(--muted)">${escapeHtml(t('admin_created_label'))} ${new Date(u.created_at*1000).toLocaleDateString()}</span>
          </div>
        </div>
        <div class="acts">
          ${u.is_banned ? `<button data-act="unban">${escapeHtml(t('admin_unban'))}</button>` : (u.is_admin ? '' : `<button class="ghost" data-act="ban">${escapeHtml(t('admin_ban'))}</button>`)}
          ${u.is_admin ? (u.id===currentUser.id?'' : `<button class="ghost" data-act="demote">${escapeHtml(t('admin_demote'))}</button>`) : `<button class="ghost" data-act="promote">${escapeHtml(t('admin_promote'))}</button>`}
          <button class="ghost" data-act="logout-all">${escapeHtml(t('admin_logout_all'))}</button>
        </div>
      </div>`).join('');
    $('adminBody').innerHTML = rows || `<div style="color:var(--muted)">${escapeHtml(t('admin_empty'))}</div>`;
    $('adminBody').querySelectorAll('.user-row').forEach(row => {
      const uid = row.dataset.uid;
      row.querySelectorAll('[data-act]').forEach(b => {
        b.onclick = async () => {
          const act = b.dataset.act;
          try {
            if (act === 'ban') {
              const reason = prompt(t('admin_ban_reason')) || '';
              await api('POST', `/api/admin/users/${uid}/ban`, { reason });
            } else if (act === 'unban') await api('POST', `/api/admin/users/${uid}/unban`, {});
            else if (act === 'promote') await api('POST', `/api/admin/users/${uid}/make-admin`, {});
            else if (act === 'demote') await api('POST', `/api/admin/users/${uid}/remove-admin`, {});
            else if (act === 'logout-all') await api('POST', `/api/admin/users/${uid}/logout-all`, {});
            await refreshAdmin();
          } catch (e) { alert(e.message); }
        };
      });
    });
  } catch (e) { $('adminBody').innerHTML = '<div class="err">'+escapeHtml(e.message)+'</div>'; }
}

// Bind submit buttons + Enter key.
window.addEventListener('DOMContentLoaded', () => {
  applyI18n();
  $('btnLangToggle')?.addEventListener('click', () => setLang(CURRENT_LANG === 'zh' ? 'en' : 'zh'));
  $('btnSaveProfile')?.addEventListener('click', doSaveProfile);
  $('btnShowLogin')?.addEventListener('click', () => openModal('login'));
  $('btnShowRegister')?.addEventListener('click', () => openModal('register'));
  document.addEventListener('click', (e) => {
    if (e.target && e.target.id === 'hintLogin')    { e.preventDefault(); openModal('login'); }
    if (e.target && e.target.id === 'hintRegister') { e.preventDefault(); openModal('register'); }
  });
  document.addEventListener('click', (e) => {
    if (e.target.id === 'btnLoginSubmit') doLogin();
    if (e.target.id === 'btnRegisterSubmit') doRegister();
    if (e.target.id === 'btnForgotSubmit') doForgotPassword();
    if (e.target.id === 'btnRecoverSubmit') doRecoverUsername();
    if (e.target.id === 'btnSendRegCode') _sendCode('regEmail', 'register', 'btnSendRegCode', 'regErr');
    if (e.target.id === 'btnSendForgotCode') _sendForgotCode();
    if (e.target.id === 'btnChangePw') doChangePassword();
    if (e.target.id === 'btnCreateKey') doCreateKey();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const open = document.querySelector('.modal-bg.open');
    if (!open) return;
    const mod = open.dataset.mod;
    if (mod === 'login') doLogin();
    else if (mod === 'register') doRegister();
    else if (mod === 'forgot') doForgotPassword();
    else if (mod === 'recoverUsername') doRecoverUsername();
  });
  loadMe();
});

// ---- recharge / points ---------------------------------------------------
async function openRecharge() {
  if (!currentUser) { openModal('login'); return; }
  _stopRechargePolling();
  $('rechargeOrder').style.display = 'none';
  $('rechargeForm').style.display = '';
  $('rechargeDisabled').style.display = 'none';
  try {
    if (!_rcConfig) _rcConfig = await api('GET', '/api/auth/deposit/config');
  } catch (e) { log('[recharge] ' + e.message, 'err'); return; }
  if (!_rcConfig.enabled) {
    $('rechargeForm').style.display = 'none';
    $('rechargeDisabled').style.display = '';
  } else {
    $('rechargeNetworkInfo').textContent =
      `${_rcConfig.network} · chain_id=${_rcConfig.chain_id} · USDT=${(_rcConfig.usdt_address||'').slice(0,10)}…`;
  }
  refreshRechargeOrders();
}

document.addEventListener('click', (e) => {
  const t = e.target;
  if (t && t.dataset && t.dataset.rcq) {
    const v = parseInt(t.dataset.rcq, 10);
    const inp = document.getElementById('rechargeAmount');
    if (inp) inp.value = v;
  }
});

document.addEventListener('click', (e) => {
  if (e.target && e.target.id === 'rechargeCreateBtn') createRechargeOrder();
  else if (e.target && e.target.id === 'rcBackBtn') {
    _stopRechargePolling();
    $('rechargeOrder').style.display = 'none';
    $('rechargeForm').style.display = '';
    refreshRechargeOrders();
  } else if (e.target && e.target.id === 'rcCopyAmount') {
    if (_rcCurrentOrder) _copyText(_rcCurrentOrder.expected_amount_usdt, e.target);
  } else if (e.target && e.target.id === 'rcCopyAddr') {
    if (_rcCurrentOrder) _copyText(_rcCurrentOrder.recv_address, e.target);
  }
});

function _copyText(text, btn) {
  try {
    navigator.clipboard.writeText(text);
    const old = btn.textContent;
    btn.textContent = t('recharge_copied');
    setTimeout(() => { btn.textContent = old; }, 1200);
  } catch (_) {}
}

async function createRechargeOrder() {
  if (!currentUser) return;
  const amt = parseInt(($('rechargeAmount').value || '0'), 10);
  if (!amt || amt < 1) { log('amount must be >= 1', 'err'); return; }
  const btn = $('rechargeCreateBtn');
  btn.disabled = true;
  try {
    const r = await api('POST', '/api/auth/deposit/create', { amount_usd: amt });
    _showRechargeOrder(r.order);
  } catch (e) {
    log('[recharge] ' + e.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

function _showRechargeOrder(order) {
  if (!order) return;
  _rcCurrentOrder = order;
  $('rechargeForm').style.display = 'none';
  $('rechargeOrder').style.display = '';
  $('rcAmountBig').textContent = order.expected_amount_usdt;
  $('rcAddress').textContent = order.recv_address;
  $('rcNetwork').textContent = `${order.network} (chain_id=${order.chain_id})`;
  $('rcPoints').textContent = order.points;
  _renderQr($('rcQrBox'), order.pay_uri || order.recv_address);
  _updateRechargeStatus(order);
  _startRechargePolling(order.order_no);
}

function _updateRechargeStatus(order) {
  const line = $('rechargeStatusLine');
  let label = t('recharge_status_pending');
  let color = '#666';
  if (order.status === 'paid') { label = '✓ ' + t('recharge_status_paid'); color = 'var(--good)'; }
  else if (order.status === 'expired') { label = t('recharge_status_expired'); color = 'var(--bad)'; }
  else if (order.status === 'failed') { label = t('recharge_status_failed'); color = 'var(--bad)'; }
  line.innerHTML = `<span style="color:${color};font-weight:600">${escapeHtml(label)}</span> · <code style="font-size:11px">${escapeHtml(order.order_no)}</code>`;
}

function _startRechargePolling(orderNo) {
  _stopRechargePolling();
  const tick = async () => {
    if (!_rcCurrentOrder || _rcCurrentOrder.order_no !== orderNo) return;
    try {
      const r = await api('GET', '/api/auth/deposit/' + encodeURIComponent(orderNo));
      _rcCurrentOrder = r.order;
      _updateRechargeStatus(r.order);
      if (r.order.status === 'paid') {
        _stopRechargePolling();
        log('[recharge] +' + r.order.points + ' 积分 → ' + r.current_balance, 'me');
        await _refreshMeQuiet();
        refreshRechargeOrders();
      } else if (r.order.status === 'expired') {
        _stopRechargePolling();
      }
    } catch (_) {}
  };
  _rcPollTimer = setInterval(tick, 5000);
  const tickCD = () => {
    if (!_rcCurrentOrder) return;
    const left = (_rcCurrentOrder.expires_at || 0) - Math.floor(Date.now()/1000);
    const el = $('rcCountdown');
    if (left <= 0) { el.textContent = '0s'; return; }
    const m = Math.floor(left / 60), sc = left % 60;
    el.textContent = `${m}m ${sc}s`;
  };
  tickCD();
  _rcCountdownTimer = setInterval(tickCD, 1000);
}

function _stopRechargePolling() {
  if (_rcPollTimer) { clearInterval(_rcPollTimer); _rcPollTimer = null; }
  if (_rcCountdownTimer) { clearInterval(_rcCountdownTimer); _rcCountdownTimer = null; }
}

async function refreshRechargeOrders() {
  try {
    const r = await api('GET', '/api/auth/deposit/orders?limit=20');
    const box = $('rechargeOrdersBox');
    box.innerHTML = '';
    if (!r.items || !r.items.length) {
      box.innerHTML = `<div class="muted">${escapeHtml(t('recharge_no_orders'))}</div>`;
      return;
    }
    for (const it of r.items) {
      const row = document.createElement('div');
      row.className = 'row';
      row.style.cssText = 'gap:8px;padding:3px 0;border-bottom:1px solid var(--border)';
      const ts = new Date((it.created_at||0)*1000).toLocaleString();
      let st = t('recharge_status_pending'), col = '#666';
      if (it.status === 'paid') { st = '✓ ' + t('recharge_status_paid'); col = 'var(--good)'; }
      else if (it.status === 'expired') { st = t('recharge_status_expired'); col = 'var(--bad)'; }
      row.innerHTML =
        `<div style="flex:0 0 130px;color:var(--muted)">${escapeHtml(ts)}</div>` +
        `<div style="flex:0 0 80px">${it.amount_usd} USDT</div>` +
        `<div style="flex:0 0 60px">+${it.points}</div>` +
        `<div style="flex:1;color:${col}">${escapeHtml(st)}</div>` +
        `<div style="flex:0 0 80px"><a href="#" data-rcorder="${escapeHtml(it.order_no)}" style="font-size:11px">↗</a></div>`;
      box.appendChild(row);
    }
    box.querySelectorAll('[data-rcorder]').forEach(a => {
      a.onclick = async (e) => {
        e.preventDefault();
        try {
          const rr = await api('GET', '/api/auth/deposit/' + encodeURIComponent(a.dataset.rcorder));
          _showRechargeOrder(rr.order);
        } catch (er) { log(er.message, 'err'); }
      };
    });
  } catch (e) { /* silent */ }
}

// Minimal QR-code renderer using Google chart API as fallback if local lib absent.
function _renderQr(container, text) {
  container.innerHTML = '';
  if (!text) return;
  const img = document.createElement('img');
  img.alt = 'QR';
  img.width = 180; img.height = 180;
  // Use api.qrserver.com (no-tracking, free, https). If offline this just shows broken-image.
  img.src = 'https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=' + encodeURIComponent(text);
  img.referrerPolicy = 'no-referrer';
  container.appendChild(img);
}

async function refreshPoints() {
  if (!currentUser) return;
  try {
    const r = await api('GET', '/api/auth/points/ledger?limit=100');
    $('pointsBalance').textContent = r.balance != null ? r.balance : 0;
    const box = $('pointsLedgerBox');
    box.innerHTML = "";
    if (!r.items || !r.items.length) {
      box.innerHTML = `<div class="muted">${escapeHtml(t('points_no_records'))}</div>`;
    } else {
      const head = document.createElement('div');
      head.className = 'row';
      head.style.cssText = 'gap:8px;padding:4px 0;border-bottom:1px solid var(--border);font-weight:600;font-size:12px;color:var(--muted)';
      head.innerHTML = `<div style="flex:0 0 140px">${escapeHtml(t('points_col_time'))}</div><div style="flex:0 0 70px">${escapeHtml(t('points_col_delta'))}</div><div style="flex:0 0 80px">${escapeHtml(t('points_col_balance'))}</div><div style="flex:1">${escapeHtml(t('points_col_reason'))}</div><div style="flex:0 0 90px">${escapeHtml(t('points_col_round'))}</div>`;
      box.appendChild(head);
      for (const it of r.items) {
        const row = document.createElement('div');
        row.className = 'row';
        row.style.cssText = 'gap:8px;padding:4px 0;border-bottom:1px solid var(--border);font-size:13px';
        const d = new Date((it.created_at || 0) * 1000);
        const tstr = d.toLocaleString();
        const sign = it.delta > 0 ? '+' : '';
        const color = it.delta > 0 ? 'var(--good)' : (it.delta < 0 ? 'var(--bad)' : 'inherit');
        row.innerHTML = `<div style="flex:0 0 140px;color:var(--muted)">${escapeHtml(tstr)}</div><div style="flex:0 0 70px;color:${color};font-weight:600">${sign}${it.delta}</div><div style="flex:0 0 80px">${it.balance_after}</div><div style="flex:1">${escapeHtml(it.reason || '')}${it.game_id ? ` <span class="muted">[${escapeHtml(it.game_id)}]</span>` : ''}</div><div style="flex:0 0 90px;color:var(--muted)">${it.round_no != null ? '#' + it.round_no : '—'}</div>`;
        box.appendChild(row);
      }
    }
  } catch (e) { log('[points] ' + e.message, 'err'); }
  try {
    const r = await api('GET', '/api/auth/points/leaderboard?limit=20');
    const box = $('pointsLeaderboardBox');
    box.innerHTML = "";
    (r.items || []).forEach((it, i) => {
      const row = document.createElement('div');
      row.className = 'row';
      row.style.cssText = 'gap:8px;padding:3px 0;font-size:13px';
      const name = it.display_name || it.username;
      row.innerHTML = `<div style="flex:0 0 30px;color:var(--muted)">#${i+1}</div><div style="flex:1">${escapeHtml(name)} <span class="muted" style="font-size:11px">@${escapeHtml(it.username)}</span></div><div style="flex:0 0 80px;font-weight:600">★ ${it.points}</div>`;
      box.appendChild(row);
    });
  } catch (_) {}
}

// Track game phase transitions to refresh /me (and points pill) on round end.
