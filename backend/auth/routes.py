"""Auth + admin HTTP routes."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import db
from .deps import (
    SESSION_COOKIE,
    CurrentUser,
    optional_current_user,
    require_admin,
    require_user,
)
from .security import (
    check_email,
    check_password_strength,
    check_username,
    hash_password,
    new_api_key,
    new_session_id,
    verify_password,
)


SESSION_TTL_SECONDS = 14 * 24 * 3600  # 14 days


router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


class RegisterReq(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginReq(BaseModel):
    login: str
    password: str


class ChangePasswordReq(BaseModel):
    old_password: str
    new_password: str


class CreateKeyReq(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class KeygenReq(BaseModel):
    login: str
    password: str
    name: str = "agent"


class BanReq(BaseModel):
    reason: str = ""
class UpdateProfileReq(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None



def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _set_session_cookie(response: Response, sid: str, request: Request) -> None:
    secure = request.url.scheme == "https"
    response.set_cookie(
        SESSION_COOKIE, sid,
        max_age=SESSION_TTL_SECONDS,
        httponly=True, samesite="lax",
        secure=secure, path="/",
    )


def _user_summary(row: sqlite3.Row) -> dict:
    keys = row.keys()
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "email": row["email"],
        "is_admin": bool(row["is_admin"]),
        "is_banned": bool(row["is_banned"]),
        "banned_reason": row["banned_reason"] if "banned_reason" in keys else None,
        "display_name": (row["display_name"] if "display_name" in keys else None) or "",
        "bio": (row["bio"] if "bio" in keys else None) or "",
        "created_at": int(row["created_at"]),
        "last_login_at": int(row["last_login_at"]) if row["last_login_at"] else None,
    }


@router.post("/register")
def register(req: RegisterReq, request: Request, response: Response) -> dict:
    err = check_username(req.username)
    if err:
        raise HTTPException(status_code=400, detail=err)
    err = check_password_strength(req.password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    email = req.email.strip().lower() if req.email else None
    if email:
        err = check_email(email)
        if err:
            raise HTTPException(status_code=400, detail=err)
    if db.find_user_by_username(req.username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    if email and db.find_user_by_email(email):
        raise HTTPException(status_code=409, detail="邮箱已被注册")
    uid = db.create_user(
        username=req.username, email=email,
        password_hash=hash_password(req.password), is_admin=False,
    )
    sid = new_session_id()
    db.create_session(sid=sid, user_id=uid, ttl_seconds=SESSION_TTL_SECONDS,
                      ip=_client_ip(request), ua=request.headers.get("user-agent"))
    db.touch_user_login(uid)
    _set_session_cookie(response, sid, request)
    u = db.find_user_by_id(uid)
    # Issue a bootstrap API key so AI agents can authenticate without managing cookies.
    full, prefix, h = new_api_key()
    db.create_api_key(user_id=uid, name="bootstrap", key_prefix=prefix, key_hash=h)
    return {
        "ok": True,
        "user": _user_summary(u),
        "api_key": {
            "name": "bootstrap",
            "key_prefix": prefix,
            "key": full,
            "warning": "请妥善保存，此 key 仅在创建时显示一次。",
        },
    }


@router.post("/login")
def login(req: LoginReq, request: Request, response: Response) -> dict:
    u = db.find_user_by_login(req.login.strip())
    if u is None or not verify_password(req.password, u["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if int(u["is_banned"]):
        raise HTTPException(status_code=403, detail=f"账号已被封禁: {u['banned_reason'] or '无理由'}")
    sid = new_session_id()
    db.create_session(sid=sid, user_id=int(u["id"]), ttl_seconds=SESSION_TTL_SECONDS,
                      ip=_client_ip(request), ua=request.headers.get("user-agent"))
    db.touch_user_login(int(u["id"]))
    _set_session_cookie(response, sid, request)
    return {"ok": True, "user": _user_summary(u)}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        db.delete_session(sid)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: Optional[CurrentUser] = Depends(optional_current_user)) -> dict:
    if user is None:
        return {"user": None}
    u = db.find_user_by_id(user.id)
    return {"user": _user_summary(u), "via": user.via}


@router.patch("/profile")
def update_profile(req: UpdateProfileReq, user: CurrentUser = Depends(require_user)) -> dict:
    dn = (req.display_name or "").strip()
    if len(dn) > 32:
        raise HTTPException(status_code=400, detail="显示名最长 32 字符")
    bio = (req.bio or "").strip()
    if len(bio) > 500:
        raise HTTPException(status_code=400, detail="简介最长 500 字符")
    db.update_profile(user.id, dn or None, bio or None)
    u = db.find_user_by_id(user.id)
    return {"ok": True, "user": _user_summary(u)}


@router.post("/change-password")
def change_password(
    req: ChangePasswordReq,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_user),
) -> dict:
    u = db.find_user_by_id(user.id)
    if u is None or not verify_password(req.old_password, u["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码错误")
    err = check_password_strength(req.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    db.change_password(user.id, hash_password(req.new_password), drop_sessions=True)
    sid = new_session_id()
    db.create_session(sid=sid, user_id=user.id, ttl_seconds=SESSION_TTL_SECONDS,
                      ip=_client_ip(request), ua=request.headers.get("user-agent"))
    _set_session_cookie(response, sid, request)
    return {"ok": True}


@router.get("/api-keys")
def list_keys(user: CurrentUser = Depends(require_user)) -> dict:
    rows = db.list_api_keys(user.id)
    return {"keys": [
        {"id": int(r["id"]), "name": r["name"], "key_prefix": r["key_prefix"],
         "created_at": int(r["created_at"]),
         "last_used_at": int(r["last_used_at"]) if r["last_used_at"] else None,
         "revoked_at": int(r["revoked_at"]) if r["revoked_at"] else None}
        for r in rows
    ]}


@router.post("/api-keys")
def create_key(req: CreateKeyReq, user: CurrentUser = Depends(require_user)) -> dict:
    if user.via == "apikey":
        raise HTTPException(status_code=403, detail="API key 不能再签发 API key")
    full, prefix, h = new_api_key()
    kid = db.create_api_key(user_id=user.id, name=req.name.strip(), key_prefix=prefix, key_hash=h)
    return {"id": kid, "name": req.name.strip(), "key_prefix": prefix, "key": full,
            "warning": "请妥善保存，此 key 仅在创建时显示一次。"}


@router.post("/keygen")
def keygen(req: KeygenReq) -> dict:
    """Stateless endpoint for AI agents: exchange username+password for a new API key.

    Returns the full key only here. Subsequent calls should use
    `Authorization: Bearer <key>`. No cookie/session is set.
    """
    u = db.find_user_by_login(req.login.strip())
    if u is None or not verify_password(req.password, u["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if int(u["is_banned"]):
        raise HTTPException(status_code=403, detail="账号已被封禁")
    name = req.name.strip() or "agent"
    if len(name) > 64:
        name = name[:64]
    full, prefix, h = new_api_key()
    kid = db.create_api_key(user_id=int(u["id"]), name=name, key_prefix=prefix, key_hash=h)
    return {
        "id": kid,
        "name": name,
        "key_prefix": prefix,
        "key": full,
        "user": _user_summary(u),
        "warning": "请妥善保存，此 key 仅在创建时显示一次。",
    }


@router.delete("/api-keys/{key_id}")
def delete_key(key_id: int, user: CurrentUser = Depends(require_user)) -> dict:
    if not db.revoke_api_key(user.id, key_id):
        raise HTTPException(status_code=404, detail="key 不存在或已撤销")
    return {"ok": True}


@admin_router.get("/users")
def admin_list_users(_admin: CurrentUser = Depends(require_admin)) -> dict:
    return {"users": [_user_summary(r) for r in db.list_users()]}


@admin_router.post("/users/{uid}/ban")
def admin_ban(uid: int, req: BanReq, _admin: CurrentUser = Depends(require_admin)) -> dict:
    u = db.find_user_by_id(uid)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if int(u["is_admin"]):
        raise HTTPException(status_code=400, detail="不能封禁管理员")
    db.set_user_banned(uid, True, req.reason.strip() or "(no reason)")
    return {"ok": True}


@admin_router.post("/users/{uid}/unban")
def admin_unban(uid: int, _admin: CurrentUser = Depends(require_admin)) -> dict:
    db.set_user_banned(uid, False, None)
    return {"ok": True}


@admin_router.post("/users/{uid}/make-admin")
def admin_grant(uid: int, _admin: CurrentUser = Depends(require_admin)) -> dict:
    db.set_user_admin(uid, True)
    return {"ok": True}


@admin_router.post("/users/{uid}/remove-admin")
def admin_revoke(uid: int, admin: CurrentUser = Depends(require_admin)) -> dict:
    if uid == admin.id:
        raise HTTPException(status_code=400, detail="不能取消自己的管理员")
    db.set_user_admin(uid, False)
    return {"ok": True}


@admin_router.post("/users/{uid}/logout-all")
def admin_logout_all(uid: int, _admin: CurrentUser = Depends(require_admin)) -> dict:
    db.delete_user_sessions(uid)
    return {"ok": True}
