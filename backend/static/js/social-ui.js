// ========== AI Social: Chat ==========
let _aiChatPoll = null;
let _aiChatLastId = 0;

function _aiChatFormatTime(ts) {
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getMonth()+1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function _renderAiChatMessages(msgs, append) {
  const box = document.getElementById('aiChatList');
  if (!box) return;
  const atBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 40;
  if (!append) box.innerHTML = '';
  if (!msgs.length && !append) {
    box.innerHTML = '<div class="muted" style="text-align:center;padding:20px">' + escapeHtml(t('chat_no_messages')) + '</div>';
    return;
  }
  const isAdmin = currentUser && currentUser.is_admin;
  const myId = currentUser ? currentUser.id : -1;
  const frag = document.createDocumentFragment();
  for (const m of msgs) {
    if (m.id <= _aiChatLastId && append) continue;
    _aiChatLastId = Math.max(_aiChatLastId, m.id);
    const isMine = m.user.id === myId;
    const row = document.createElement('div');
    row.style.cssText = 'margin-bottom:10px;padding:8px 10px;background:' + (isMine ? '#eef2ff' : '#fff') + ';border:1px solid #e5e7eb;border-radius:8px';
    const canDelete = (isMine || isAdmin) && currentUser;
    row.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#6b7280;margin-bottom:4px">' +
        '<span><b style="color:#111">' + escapeHtml(m.user.display_name || m.user.username) + '</b>' +
        (m.user.is_admin ? '<span class="admin-dot" style="margin-left:4px"></span>' : '') +
        ' · ' + _aiChatFormatTime(m.created_at) + '</span>' +
        (canDelete ? '<button class="ghost" style="padding:2px 8px;font-size:11px" onclick="_aiChatDelete(' + m.id + ')">×</button>' : '') +
      '</div>' +
      '<div style="white-space:pre-wrap;word-break:break-word">' + escapeHtml(m.content) + '</div>';
    frag.appendChild(row);
  }
  box.appendChild(frag);
  if (atBottom || !append) box.scrollTop = box.scrollHeight;
}

async function _aiChatRefresh() {
  try {
    const r = await api('GET', '/api/social/chat/messages?since_id=' + _aiChatLastId + '&limit=100');
    if (_aiChatLastId === 0) {
      _renderAiChatMessages(r.messages, false);
    } else if (r.messages.length) {
      _renderAiChatMessages(r.messages, true);
    }
  } catch (e) { /* swallow */ }
}

async function _aiChatDelete(id) {
  if (!confirm(t('confirm_delete') || '删除？')) return;
  try {
    await api('DELETE', '/api/social/chat/messages/' + id);
    // refetch from scratch
    _aiChatLastId = 0;
    _aiChatRefresh();
  } catch (e) { alert(e.message); }
}

async function _aiChatSend() {
  if (!_requireLogin()) return;
  const inp = document.getElementById('aiChatInput');
  const text = inp.value.trim();
  if (!text) return;
  const btn = document.getElementById('btnAiChatSend');
  if (btn) btn.disabled = true;
  try {
    await api('POST', '/api/social/chat/messages', { content: text });
    inp.value = '';
    await _aiChatRefresh();
  } catch (e) { alert(e.message); }
  finally { if (btn) btn.disabled = false; inp.focus(); }
}

function openAiChat() {
  _aiChatLastId = 0;
  openModal('aiChat');
  // wire compose state
  const hint = document.getElementById('aiChatLoginHint');
  const row = document.getElementById('aiChatComposeRow');
  if (currentUser) { hint.style.display = 'none'; row.style.display = 'flex'; }
  else { hint.style.display = 'block'; row.style.display = 'none'; }
  _aiChatRefresh();
  if (_aiChatPoll) clearInterval(_aiChatPoll);
  _aiChatPoll = setInterval(_aiChatRefresh, 3000);
}

function closeAiChat() {
  if (_aiChatPoll) { clearInterval(_aiChatPoll); _aiChatPoll = null; }
}

// stop polling when any modal closes
const _origCloseModals = closeModals;
closeModals = function() { closeAiChat(); _origCloseModals(); };

document.addEventListener('click', (e) => {
  if (e.target && e.target.id === 'btnAiChatSend') _aiChatSend();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && document.activeElement && document.activeElement.id === 'aiChatInput') {
    e.preventDefault();
    _aiChatSend();
  }
});


// ========== AI Social: Blog ==========
let _blogPage = 1;
const _blogPageSize = 10;
let _blogCurrentPostId = null;

function _blogFormatTime(ts) {
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}/${pad(d.getMonth()+1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function _showBlogView(which) {
  document.getElementById('blogListView').style.display    = which === 'list'    ? 'block' : 'none';
  document.getElementById('blogDetailView').style.display  = which === 'detail'  ? 'block' : 'none';
  document.getElementById('blogComposeView').style.display = which === 'compose' ? 'block' : 'none';
  const back = document.getElementById('btnBlogBack');
  back.style.display = which === 'list' ? 'none' : 'inline-block';
}

async function openAiBlog() {
  openModal('aiBlog');
  _blogPage = 1;
  await _blogLoadList();
}

async function _blogLoadList() {
  _showBlogView('list');
  document.getElementById('blogHeaderTitle').innerHTML = '📝 <span data-i18n="ai_social_blog">' + escapeHtml(t('ai_social_blog')) + '</span>';
  const box = document.getElementById('blogList');
  box.innerHTML = '<div class="muted" style="text-align:center;padding:20px">' + escapeHtml(t('loading')) + '</div>';
  try {
    const r = await api('GET', '/api/social/blog/posts?page=' + _blogPage + '&page_size=' + _blogPageSize);
    document.getElementById('blogTotalLabel').textContent = (t('blog_total') || '共 {n} 篇').replace('{n}', r.total);
    if (!r.posts.length) {
      box.innerHTML = '<div class="muted" style="text-align:center;padding:30px">' + escapeHtml(t('blog_empty')) + '</div>';
    } else {
      box.innerHTML = r.posts.map(_renderBlogCard).join('');
    }
    _renderBlogPager(r.total);
  } catch (e) {
    box.innerHTML = '<p class="err">' + escapeHtml(e.message) + '</p>';
  }
}

function _renderBlogCard(p) {
  return '<div class="panel" style="padding:12px 14px;margin-bottom:10px;cursor:pointer;border:1px solid #e5e7eb;border-radius:8px" onclick="_blogOpenDetail(' + p.id + ')">' +
    '<div style="font-weight:600;font-size:16px;margin-bottom:4px">' + escapeHtml(p.title) + '</div>' +
    '<div style="color:#6b7280;font-size:12px;margin-bottom:6px">' +
      '<b>' + escapeHtml(p.user.display_name || p.user.username) + '</b>' +
      (p.user.is_admin ? '<span class="admin-dot" style="margin-left:4px"></span>' : '') +
      ' · ' + _blogFormatTime(p.created_at) +
      ' · <span title="' + escapeHtml(t('comments') || '评论') + '">💬 ' + p.comment_count + '</span>' +
    '</div>' +
    '<div style="color:#374151;font-size:13px;white-space:pre-wrap;word-break:break-word">' + escapeHtml(p.content) + '</div>' +
  '</div>';
}

function _renderBlogPager(total) {
  const pager = document.getElementById('blogPager');
  const maxPage = Math.max(1, Math.ceil(total / _blogPageSize));
  if (maxPage <= 1) { pager.innerHTML = ''; return; }
  let html = '';
  html += '<button class="ghost" ' + (_blogPage <= 1 ? 'disabled' : '') + ' onclick="_blogGoto(' + (_blogPage - 1) + ')">‹</button>';
  html += '<span style="padding:4px 8px">' + _blogPage + ' / ' + maxPage + '</span>';
  html += '<button class="ghost" ' + (_blogPage >= maxPage ? 'disabled' : '') + ' onclick="_blogGoto(' + (_blogPage + 1) + ')">›</button>';
  pager.innerHTML = html;
}

function _blogGoto(p) { _blogPage = p; _blogLoadList(); }

async function _blogOpenDetail(pid) {
  _blogCurrentPostId = pid;
  _showBlogView('detail');
  const v = document.getElementById('blogDetailView');
  v.innerHTML = '<div class="muted" style="text-align:center;padding:30px">' + escapeHtml(t('loading')) + '</div>';
  try {
    const r = await api('GET', '/api/social/blog/posts/' + pid);
    const p = r.post;
    document.getElementById('blogHeaderTitle').textContent = p.title;
    const isOwner = currentUser && currentUser.id === p.user.id;
    const isAdmin = currentUser && currentUser.is_admin;
    let html = '';
    html += '<div style="margin-bottom:12px">';
    html += '<h2 style="margin:0 0 6px 0;font-size:22px">' + escapeHtml(p.title) + '</h2>';
    html += '<div style="color:#6b7280;font-size:12px">' +
      '<b>' + escapeHtml(p.user.display_name || p.user.username) + '</b>' +
      (p.user.is_admin ? '<span class="admin-dot" style="margin-left:4px"></span>' : '') +
      ' · ' + _blogFormatTime(p.created_at) +
      (p.updated_at !== p.created_at ? ' · <span title="updated">✎ ' + _blogFormatTime(p.updated_at) + '</span>' : '') +
    '</div>';
    if (isOwner || isAdmin) {
      html += '<div style="margin-top:8px;display:flex;gap:6px">';
      if (isOwner) html += '<button class="ghost" style="padding:3px 10px;font-size:12px" onclick="_blogEdit(' + p.id + ')" data-i18n="btn_edit">编辑</button>';
      html += '<button class="ghost" style="padding:3px 10px;font-size:12px;color:#dc2626" onclick="_blogDelete(' + p.id + ')" data-i18n="btn_delete">删除</button>';
      html += '</div>';
    }
    html += '</div>';
    html += '<div style="white-space:pre-wrap;word-break:break-word;line-height:1.7;padding:12px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:18px">' + escapeHtml(p.content) + '</div>';
    // comments
    html += '<h3 style="font-size:14px;margin:14px 0 8px 0">💬 ' + escapeHtml(t('comments') || '评论') + ' (' + r.comments.length + ')</h3>';
    html += '<div id="blogCommentList">';
    if (!r.comments.length) {
      html += '<p class="muted" style="font-size:13px">' + escapeHtml(t('blog_no_comments') || '还没有评论') + '</p>';
    } else {
      for (const cm of r.comments) {
        const canDel = currentUser && (currentUser.id === cm.user.id || currentUser.is_admin);
        html += '<div style="border-left:3px solid #e5e7eb;padding:6px 10px;margin-bottom:8px">' +
          '<div style="font-size:12px;color:#6b7280;display:flex;justify-content:space-between">' +
            '<span><b>' + escapeHtml(cm.user.display_name || cm.user.username) + '</b>' +
            (cm.user.is_admin ? '<span class="admin-dot" style="margin-left:4px"></span>' : '') +
            ' · ' + _blogFormatTime(cm.created_at) + '</span>' +
            (canDel ? '<button class="ghost" style="padding:1px 6px;font-size:11px" onclick="_blogCommentDelete(' + cm.id + ')">×</button>' : '') +
          '</div>' +
          '<div style="white-space:pre-wrap;word-break:break-word;font-size:13px;margin-top:2px">' + escapeHtml(cm.content) + '</div>' +
        '</div>';
      }
    }
    html += '</div>';
    // new comment
    if (currentUser) {
      html += '<div style="margin-top:14px;display:flex;gap:6px;align-items:flex-end">' +
        '<textarea id="blogCommentInput" rows="2" maxlength="4000" placeholder="' + escapeHtml(t('blog_comment_placeholder') || '友好留言…') + '" style="flex:1;resize:vertical;padding:6px;border:1px solid #d1d5db;border-radius:6px;font-family:inherit"></textarea>' +
        '<button onclick="_blogSubmitComment()" data-i18n="btn_send">发送</button>' +
      '</div>';
    } else {
      html += '<p class="muted" style="font-size:13px;margin-top:12px">' + escapeHtml(t('blog_login_to_comment') || '登录后才能评论') + '</p>';
    }
    v.innerHTML = html;
  } catch (e) {
    v.innerHTML = '<p class="err">' + escapeHtml(e.message) + '</p>';
  }
}

async function _blogSubmitComment() {
  if (!_requireLogin()) return;
  const inp = document.getElementById('blogCommentInput');
  const text = inp.value.trim();
  if (!text || !_blogCurrentPostId) return;
  try {
    await api('POST', '/api/social/blog/posts/' + _blogCurrentPostId + '/comments', { content: text });
    inp.value = '';
    _blogOpenDetail(_blogCurrentPostId);
  } catch (e) { alert(e.message); }
}

async function _blogCommentDelete(cid) {
  if (!confirm(t('confirm_delete') || '删除？')) return;
  try {
    await api('DELETE', '/api/social/blog/comments/' + cid);
    _blogOpenDetail(_blogCurrentPostId);
  } catch (e) { alert(e.message); }
}

async function _blogDelete(pid) {
  if (!confirm(t('confirm_delete_post') || '删除这篇文章？')) return;
  try {
    await api('DELETE', '/api/social/blog/posts/' + pid);
    _blogLoadList();
  } catch (e) { alert(e.message); }
}

let _blogEditingId = null;

function _blogOpenCompose() {
  if (!_requireLogin()) return;
  _blogEditingId = null;
  _showBlogView('compose');
  document.getElementById('blogHeaderTitle').textContent = t('btn_new_post') || '写新文章';
  document.getElementById('blogTitle').value = '';
  document.getElementById('blogContent').value = '';
  document.getElementById('blogComposeErr').textContent = '';
}

async function _blogEdit(pid) {
  if (!_requireLogin()) return;
  try {
    const r = await api('GET', '/api/social/blog/posts/' + pid);
    _blogEditingId = pid;
    _showBlogView('compose');
    document.getElementById('blogHeaderTitle').textContent = t('btn_edit') || '编辑';
    document.getElementById('blogTitle').value = r.post.title;
    document.getElementById('blogContent').value = r.post.content;
    document.getElementById('blogComposeErr').textContent = '';
  } catch (e) { alert(e.message); }
}

async function _blogSubmitCompose() {
  const errEl = document.getElementById('blogComposeErr'); errEl.textContent = '';
  const title = document.getElementById('blogTitle').value.trim();
  const content = document.getElementById('blogContent').value.trim();
  if (!title) { errEl.textContent = t('blog_title_required') || '请填写标题'; return; }
  if (!content) { errEl.textContent = t('blog_content_required') || '请填写正文'; return; }
  const btn = document.getElementById('btnBlogComposeSubmit');
  if (btn) btn.disabled = true;
  try {
    if (_blogEditingId) {
      await api('PUT', '/api/social/blog/posts/' + _blogEditingId, { title, content });
      await _blogOpenDetail(_blogEditingId);
    } else {
      const r = await api('POST', '/api/social/blog/posts', { title, content });
      await _blogOpenDetail(r.id);
    }
  } catch (e) { errEl.textContent = e.message; }
  finally { if (btn) btn.disabled = false; }
}

function _blogBack() {
  if (document.getElementById('blogComposeView').style.display !== 'none') {
    if (_blogEditingId) { _blogOpenDetail(_blogEditingId); }
    else { _blogLoadList(); }
  } else {
    _blogLoadList();
  }
}

document.addEventListener('click', (e) => {
  if (e.target && e.target.id === 'btnBlogBack') _blogBack();
  if (e.target && e.target.id === 'btnBlogNew') _blogOpenCompose();
  if (e.target && e.target.id === 'btnBlogComposeCancel') _blogBack();
  if (e.target && e.target.id === 'btnBlogComposeSubmit') _blogSubmitCompose();
});
