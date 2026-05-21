"""Chat + Blog ('AI Social') routes."""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import db as auth_db
from ..auth.deps import CurrentUser, optional_current_user, require_user


router = APIRouter(prefix="/api/social", tags=["social"])


# ---------- helpers --------------------------------------------------------

_CHAT_MAX_LEN = 2000
_BLOG_TITLE_MAX = 200
_BLOG_CONTENT_MAX = 50000
_COMMENT_MAX = 4000


def _user_brief(uid: int) -> dict:
    u = auth_db.find_user_by_id(uid)
    if u is None:
        return {"id": uid, "username": "(deleted)", "display_name": None, "is_admin": 0}
    return {
        "id": int(u["id"]),
        "username": u["username"],
        "display_name": u["display_name"] if "display_name" in u.keys() else None,
        "is_admin": int(u["is_admin"]),
    }


# ---------- chat -----------------------------------------------------------


class ChatPostReq(BaseModel):
    content: str = Field(min_length=1, max_length=_CHAT_MAX_LEN)


@router.get("/chat/messages")
def chat_list(
    since_id: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _u: Optional[CurrentUser] = Depends(optional_current_user),
) -> dict:
    with auth_db.connect() as c:
        rows = list(c.execute(
            "SELECT id, user_id, content, created_at FROM chat_messages "
            "WHERE deleted_at IS NULL AND id > ? "
            "ORDER BY id DESC LIMIT ?",
            (since_id, limit),
        ))
    rows.reverse()  # oldest first for natural display
    msgs = []
    user_cache: dict[int, dict] = {}
    for r in rows:
        uid = int(r["user_id"])
        if uid not in user_cache:
            user_cache[uid] = _user_brief(uid)
        msgs.append({
            "id": int(r["id"]),
            "content": r["content"],
            "created_at": int(r["created_at"]),
            "user": user_cache[uid],
        })
    return {"messages": msgs}


@router.post("/chat/messages")
def chat_post(req: ChatPostReq, user: CurrentUser = Depends(require_user)) -> dict:
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    u = auth_db.find_user_by_id(user.id)
    if u is None:
        raise HTTPException(status_code=401, detail="账号不存在")
    if int(u["is_banned"]):
        raise HTTPException(status_code=403, detail="账号已被封禁，不能发言")
    now = int(time.time())
    with auth_db.connect() as c:
        # simple per-user rate-limit: max 5 msgs / 10s
        cnt = c.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE user_id=? AND created_at>?",
            (user.id, now - 10),
        ).fetchone()[0]
        if cnt >= 5:
            raise HTTPException(status_code=429, detail="发言过于频繁，请稍后再试")
        cur = c.execute(
            "INSERT INTO chat_messages (user_id, content, created_at) VALUES (?, ?, ?)",
            (user.id, content, now),
        )
        mid = int(cur.lastrowid)
    return {
        "ok": True,
        "message": {
            "id": mid,
            "content": content,
            "created_at": now,
            "user": _user_brief(user.id),
        },
    }


@router.delete("/chat/messages/{mid}")
def chat_delete(mid: int, user: CurrentUser = Depends(require_user)) -> dict:
    with auth_db.connect() as c:
        row = c.execute("SELECT user_id FROM chat_messages WHERE id=? AND deleted_at IS NULL", (mid,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="消息不存在")
        u = auth_db.find_user_by_id(user.id)
        if row["user_id"] != user.id and not (u and int(u["is_admin"])):
            raise HTTPException(status_code=403, detail="无权删除该消息")
        c.execute("UPDATE chat_messages SET deleted_at=? WHERE id=?", (int(time.time()), mid))
    return {"ok": True}


# ---------- blog -----------------------------------------------------------


class BlogPostReq(BaseModel):
    title: str = Field(min_length=1, max_length=_BLOG_TITLE_MAX)
    content: str = Field(min_length=1, max_length=_BLOG_CONTENT_MAX)


class BlogUpdateReq(BaseModel):
    title: Optional[str] = Field(default=None, max_length=_BLOG_TITLE_MAX)
    content: Optional[str] = Field(default=None, max_length=_BLOG_CONTENT_MAX)


class CommentReq(BaseModel):
    content: str = Field(min_length=1, max_length=_COMMENT_MAX)


def _post_row_to_dict(r, comment_count: int = 0) -> dict:
    return {
        "id": int(r["id"]),
        "user": _user_brief(int(r["user_id"])),
        "title": r["title"],
        "content": r["content"],
        "created_at": int(r["created_at"]),
        "updated_at": int(r["updated_at"]),
        "comment_count": comment_count,
    }


@router.get("/blog/posts")
def blog_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _u: Optional[CurrentUser] = Depends(optional_current_user),
) -> dict:
    offset = (page - 1) * page_size
    with auth_db.connect() as c:
        total = c.execute("SELECT COUNT(*) FROM blog_posts WHERE deleted_at IS NULL").fetchone()[0]
        rows = list(c.execute(
            "SELECT * FROM blog_posts WHERE deleted_at IS NULL "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ))
        # comment counts
        counts: dict[int, int] = {}
        if rows:
            pids = [int(r["id"]) for r in rows]
            ph = ",".join("?" * len(pids))
            for r in c.execute(
                f"SELECT post_id, COUNT(*) AS c FROM blog_comments "
                f"WHERE deleted_at IS NULL AND post_id IN ({ph}) GROUP BY post_id",
                pids,
            ):
                counts[int(r["post_id"])] = int(r["c"])
    # truncate content for the list view
    posts = []
    for r in rows:
        d = _post_row_to_dict(r, comment_count=counts.get(int(r["id"]), 0))
        if len(d["content"]) > 280:
            d["content"] = d["content"][:280] + "…"
        posts.append(d)
    return {"posts": posts, "total": int(total), "page": page, "page_size": page_size}


@router.get("/blog/posts/{pid}")
def blog_detail(pid: int, _u: Optional[CurrentUser] = Depends(optional_current_user)) -> dict:
    with auth_db.connect() as c:
        r = c.execute("SELECT * FROM blog_posts WHERE id=? AND deleted_at IS NULL", (pid,)).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="文章不存在")
        comments = list(c.execute(
            "SELECT * FROM blog_comments WHERE post_id=? AND deleted_at IS NULL ORDER BY id ASC",
            (pid,),
        ))
    return {
        "post": _post_row_to_dict(r, comment_count=len(comments)),
        "comments": [
            {
                "id": int(cm["id"]),
                "user": _user_brief(int(cm["user_id"])),
                "content": cm["content"],
                "created_at": int(cm["created_at"]),
            }
            for cm in comments
        ],
    }


@router.post("/blog/posts")
def blog_create(req: BlogPostReq, user: CurrentUser = Depends(require_user)) -> dict:
    u = auth_db.find_user_by_id(user.id)
    if u is None or int(u["is_banned"]):
        raise HTTPException(status_code=403, detail="账号不可用")
    title = req.title.strip()
    content = req.content.strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="标题或正文不能为空")
    now = int(time.time())
    with auth_db.connect() as c:
        # rate-limit: max 5 posts / hour
        cnt = c.execute(
            "SELECT COUNT(*) FROM blog_posts WHERE user_id=? AND created_at>?",
            (user.id, now - 3600),
        ).fetchone()[0]
        if cnt >= 5:
            raise HTTPException(status_code=429, detail="发文过于频繁，每小时最多 5 篇")
        cur = c.execute(
            "INSERT INTO blog_posts (user_id, title, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user.id, title, content, now, now),
        )
        pid = int(cur.lastrowid)
    return {"ok": True, "id": pid}


@router.put("/blog/posts/{pid}")
def blog_update(pid: int, req: BlogUpdateReq, user: CurrentUser = Depends(require_user)) -> dict:
    with auth_db.connect() as c:
        r = c.execute("SELECT user_id, title, content FROM blog_posts WHERE id=? AND deleted_at IS NULL", (pid,)).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="文章不存在")
        if int(r["user_id"]) != user.id:
            raise HTTPException(status_code=403, detail="只能编辑自己的文章")
        new_title = (req.title or r["title"]).strip()
        new_content = (req.content or r["content"]).strip()
        if not new_title or not new_content:
            raise HTTPException(status_code=400, detail="标题或正文不能为空")
        c.execute(
            "UPDATE blog_posts SET title=?, content=?, updated_at=? WHERE id=?",
            (new_title, new_content, int(time.time()), pid),
        )
    return {"ok": True}


@router.delete("/blog/posts/{pid}")
def blog_delete(pid: int, user: CurrentUser = Depends(require_user)) -> dict:
    with auth_db.connect() as c:
        r = c.execute("SELECT user_id FROM blog_posts WHERE id=? AND deleted_at IS NULL", (pid,)).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="文章不存在")
        u = auth_db.find_user_by_id(user.id)
        if int(r["user_id"]) != user.id and not (u and int(u["is_admin"])):
            raise HTTPException(status_code=403, detail="无权删除该文章")
        c.execute("UPDATE blog_posts SET deleted_at=? WHERE id=?", (int(time.time()), pid))
    return {"ok": True}


@router.post("/blog/posts/{pid}/comments")
def comment_create(pid: int, req: CommentReq, user: CurrentUser = Depends(require_user)) -> dict:
    u = auth_db.find_user_by_id(user.id)
    if u is None or int(u["is_banned"]):
        raise HTTPException(status_code=403, detail="账号不可用")
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="评论不能为空")
    now = int(time.time())
    with auth_db.connect() as c:
        # confirm post exists
        r = c.execute("SELECT id FROM blog_posts WHERE id=? AND deleted_at IS NULL", (pid,)).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="文章不存在")
        # rate-limit: 10 comments / minute per user
        cnt = c.execute(
            "SELECT COUNT(*) FROM blog_comments WHERE user_id=? AND created_at>?",
            (user.id, now - 60),
        ).fetchone()[0]
        if cnt >= 10:
            raise HTTPException(status_code=429, detail="评论过于频繁")
        cur = c.execute(
            "INSERT INTO blog_comments (post_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (pid, user.id, content, now),
        )
        cid = int(cur.lastrowid)
    return {
        "ok": True,
        "comment": {
            "id": cid,
            "user": _user_brief(user.id),
            "content": content,
            "created_at": now,
        },
    }


@router.delete("/blog/comments/{cid}")
def comment_delete(cid: int, user: CurrentUser = Depends(require_user)) -> dict:
    with auth_db.connect() as c:
        r = c.execute("SELECT user_id FROM blog_comments WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="评论不存在")
        u = auth_db.find_user_by_id(user.id)
        if int(r["user_id"]) != user.id and not (u and int(u["is_admin"])):
            raise HTTPException(status_code=403, detail="无权删除该评论")
        c.execute("UPDATE blog_comments SET deleted_at=? WHERE id=?", (int(time.time()), cid))
    return {"ok": True}
