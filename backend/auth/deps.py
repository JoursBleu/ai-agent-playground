"""FastAPI dependencies: resolve current user from cookie or API key."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Request

from . import db
from .security import hash_api_key


SESSION_COOKIE = "aap_sid"


class CurrentUser:
    __slots__ = ("id", "username", "email", "is_admin", "is_banned", "via")

    def __init__(self, row, via: str) -> None:
        self.id: int = int(row["id"])
        self.username: str = row["username"]
        self.email: Optional[str] = row["email"]
        self.is_admin: bool = bool(row["is_admin"])
        self.is_banned: bool = bool(row["is_banned"])
        self.via: str = via

    def to_public(self) -> dict:
        return {"id": self.id, "username": self.username, "email": self.email, "is_admin": self.is_admin}


def _user_from_apikey(authorization: Optional[str]) -> Optional[CurrentUser]:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token:
        return None
    row = db.find_api_key_by_hash(hash_api_key(token))
    if row is None:
        return None
    if int(row["is_banned"]):
        return None
    db.touch_api_key(int(row["id"]))
    u = db.find_user_by_id(int(row["user_id"]))
    if u is None:
        return None
    return CurrentUser(u, via="apikey")


def _user_from_cookie(sid: Optional[str]) -> Optional[CurrentUser]:
    if not sid:
        return None
    sess = db.find_session(sid)
    if sess is None:
        return None
    u = db.find_user_by_id(int(sess["user_id"]))
    if u is None or int(u["is_banned"]):
        return None
    return CurrentUser(u, via="cookie")


def optional_current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Optional[CurrentUser]:
    user = _user_from_apikey(authorization)
    if user is not None:
        return user
    return _user_from_cookie(request.cookies.get(SESSION_COOKIE))


def require_user(user: Optional[CurrentUser] = Depends(optional_current_user)) -> CurrentUser:
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
