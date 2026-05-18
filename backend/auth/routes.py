"""Auth + admin HTTP routes."""

from __future__ import annotations

import hashlib
import logging
import random
import sqlite3
import threading
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import db, email_sender
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
    email: str
    code: str


class LoginReq(BaseModel):
    login: str
    password: str


class ChangePasswordReq(BaseModel):
    old_password: str
    new_password: str


class SendCodeReq(BaseModel):
    email: str
    purpose: Literal["register", "reset"]


class ForgotPasswordReq(BaseModel):
    email: str


class ResetPasswordReq(BaseModel):
    email: str
    code: str
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
        "points": int(row["points"]) if ("points" in keys and row["points"] is not None) else 1000,
    }


@router.post("/register")
def register(req: RegisterReq, request: Request, response: Response) -> dict:
    err = check_username(req.username)
    if err:
        raise HTTPException(status_code=400, detail=err)
    err = check_password_strength(req.password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    email = (req.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="请填写邮箱")
    err = check_email(email)
    if err:
        raise HTTPException(status_code=400, detail=err)
    code = (req.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="请填写邮箱验证码")
    if db.find_user_by_username(req.username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    if db.find_user_by_email(email):
        raise HTTPException(status_code=409, detail="邮箱已被注册")
    _consume_email_code(email, "register", code)
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




# ----- email verification helpers ----------------------------------------

_CODE_TTL_SECONDS = 10 * 60       # 10 minutes
_CODE_RESEND_SECONDS = 60         # min interval between resends
_CODE_MAX_ATTEMPTS = 5

log = logging.getLogger(__name__)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def _send_email_async(to_addr: str, subject: str, text_body: str, html_body: str) -> None:
    def _run():
        try:
            email_sender.send_mail(to_addr, subject, text_body, html_body)
            log.info("sent verification email to %s", to_addr)
        except Exception as exc:
            log.exception("failed to send verification email to %s: %s", to_addr, exc)
    threading.Thread(target=_run, daemon=True).start()


def _issue_email_code(email: str, purpose: str) -> None:
    """Generate code, persist hashed copy, dispatch email asynchronously."""
    code = f"{random.randint(0, 999999):06d}"
    db.create_verification(email, purpose, _hash_code(code), _CODE_TTL_SECONDS)
    if not email_sender.smtp_configured():
        log.warning("SMTP not configured; code for %s (%s) = %s", email, purpose, code)
        return
    subject, text, html = email_sender.render_code_mail(purpose, code)
    _send_email_async(email, subject, text, html)


def _consume_email_code(email: str, purpose: str, code: str) -> None:
    row = db.find_active_verification(email, purpose)
    if row is None:
        raise HTTPException(status_code=400, detail="验证码不存在或已失效，请重新获取")
    attempts = db.bump_verification_attempts(int(row["id"]))
    if attempts > _CODE_MAX_ATTEMPTS:
        db.consume_verification(int(row["id"]))
        raise HTTPException(status_code=400, detail="验证码尝试次数过多，请重新获取")
    if _hash_code(code) != row["code_hash"]:
        raise HTTPException(status_code=400, detail="验证码错误")
    db.consume_verification(int(row["id"]))


@router.post("/send-code")
def send_code(req: SendCodeReq) -> dict:
    email = (req.email or "").strip().lower()
    err = check_email(email)
    if err:
        raise HTTPException(status_code=400, detail=err)
    purpose = req.purpose
    if purpose == "register":
        if db.find_user_by_email(email):
            raise HTTPException(status_code=409, detail="邮箱已被注册")
    elif purpose == "reset":
        # do not leak account existence; pretend success
        if db.find_user_by_email(email) is None:
            return {"ok": True, "resend_after": _CODE_RESEND_SECONDS}
    last = db.latest_verification(email, purpose)
    if last is not None:
        age = int(time.time()) - int(last["created_at"])
        if age < _CODE_RESEND_SECONDS:
            wait = _CODE_RESEND_SECONDS - age
            raise HTTPException(status_code=429, detail=f"请求过于频繁，请 {wait} 秒后重试")
    _issue_email_code(email, purpose)
    return {"ok": True, "resend_after": _CODE_RESEND_SECONDS}


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordReq) -> dict:
    """Alias for send-code(purpose=reset). Always returns ok to avoid leaking."""
    email = (req.email or "").strip().lower()
    err = check_email(email)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if db.find_user_by_email(email) is not None:
        last = db.latest_verification(email, "reset")
        if last is None or (int(time.time()) - int(last["created_at"])) >= _CODE_RESEND_SECONDS:
            _issue_email_code(email, "reset")
    return {"ok": True, "resend_after": _CODE_RESEND_SECONDS}


@router.post("/reset-password")
def reset_password(req: ResetPasswordReq, request: Request, response: Response) -> dict:
    email = (req.email or "").strip().lower()
    err = check_email(email)
    if err:
        raise HTTPException(status_code=400, detail=err)
    err = check_password_strength(req.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    u = db.find_user_by_email(email)
    if u is None:
        # consume the attempt anyway to slow probing
        _consume_email_code(email, "reset", req.code)
        raise HTTPException(status_code=400, detail="账号不存在")
    _consume_email_code(email, "reset", req.code)
    db.change_password(int(u["id"]), hash_password(req.new_password), drop_sessions=True)
    # also clear any current session cookie
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


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





@router.get("/points/ledger")
def points_ledger(limit: int = 50, user: CurrentUser = Depends(require_user)) -> dict:
    rows = db.list_ledger(user.id, limit=max(1, min(int(limit), 200)))
    return {
        "balance": db.get_points(user.id),
        "items": [
            {
                "id": int(r["id"]),
                "delta": int(r["delta"]),
                "balance_after": int(r["balance_after"]),
                "reason": r["reason"],
                "game_id": r["game_id"],
                "round_no": int(r["round_no"]) if r["round_no"] is not None else None,
                "created_at": int(r["created_at"]),
            }
            for r in rows
        ],
    }


@router.get("/points/leaderboard")
def points_leaderboard(limit: int = 20) -> dict:
    rows = db.leaderboard(limit=max(1, min(int(limit), 100)))
    return {
        "items": [
            {
                "id": int(r["id"]),
                "username": r["username"],
                "display_name": (r["display_name"] or ""),
                "points": int(r["points"] or 0),
            }
            for r in rows
        ],
    }


# -------- USDT-BEP20 deposit (recharge to points) --------

DEPOSIT_TTL_SECONDS = 30 * 60          # 30 min
DEPOSIT_MIN_USD = 1
POINTS_PER_USD = 1000


class DepositCreateReq(BaseModel):
    amount_usd: int = Field(..., ge=1, le=100000)


def _deposit_row_to_dict(row, scanner) -> dict:
    if row is None:
        return {}
    keys = row.keys()
    chain_id = scanner.chain_id
    usdt = scanner.usdt_address
    recv = row["recv_address"]
    amt_str = row["expected_amount_usdt"]
    units = int(row["expected_amount_units"])
    # EIP-681 payment URI for ERC20 transfer (works in MetaMask & most BSC wallets)
    wei = units * (10 ** 14)             # 18 - 4 = 14
    pay_uri = f"ethereum:{usdt}@{chain_id}/transfer?address={recv}&uint256={wei}"
    return {
        "order_no": row["order_no"],
        "status": row["status"],
        "amount_usd": int(row["amount_usd"]),
        "points": int(row["points"]),
        "expected_amount_usdt": amt_str,
        "network": row["network"],
        "chain_id": chain_id,
        "recv_address": recv,
        "usdt_contract": usdt,
        "tx_hash": row["tx_hash"] if "tx_hash" in keys else None,
        "paid_amount_usdt": row["paid_amount_usdt"] if "paid_amount_usdt" in keys else None,
        "created_at": int(row["created_at"]),
        "paid_at": int(row["paid_at"]) if row["paid_at"] else None,
        "expires_at": int(row["expires_at"]),
        "pay_uri": pay_uri,
    }


@router.get("/deposit/config")
def deposit_config() -> dict:
    """Public: tells the frontend whether USDT recharge is available."""
    from ..payments.bsc import SCANNER
    cfg = SCANNER.public_config()
    cfg["min_amount_usd"] = DEPOSIT_MIN_USD
    cfg["points_per_usd"] = POINTS_PER_USD
    cfg["ttl_seconds"] = DEPOSIT_TTL_SECONDS
    return cfg


@router.post("/deposit/create")
def deposit_create(req: DepositCreateReq,
                   user: CurrentUser = Depends(require_user)) -> dict:
    from ..payments.bsc import SCANNER
    if not SCANNER.enabled:
        raise HTTPException(status_code=503, detail="USDT 充值未启用")
    amount = int(req.amount_usd)
    if amount < DEPOSIT_MIN_USD:
        raise HTTPException(status_code=400, detail=f"最小充值金额为 {DEPOSIT_MIN_USD} USDT")
    # Optional: cap pending orders per user to prevent spamming the bucket.
    pending = [r for r in db.list_user_deposits(user.id, limit=20)
               if r["status"] == "pending" and int(r["expires_at"]) > int(time.time())]
    if len(pending) >= 5:
        raise HTTPException(status_code=429, detail="未支付订单过多，请先完成或等待过期")
    try:
        row = db.create_deposit_order(
            user_id=user.id,
            amount_usd=amount,
            points=amount * POINTS_PER_USD,
            network=SCANNER.network,
            recv_address=SCANNER.recv_address,
            ttl_seconds=DEPOSIT_TTL_SECONDS,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "order": _deposit_row_to_dict(row, SCANNER)}


@router.get("/deposit/orders")
def deposit_list(limit: int = 20,
                 user: CurrentUser = Depends(require_user)) -> dict:
    from ..payments.bsc import SCANNER
    limit = max(1, min(int(limit), 100))
    rows = db.list_user_deposits(user.id, limit=limit)
    # Auto-mark expired pending rows in the view (DB cleanup runs in scanner loop).
    out = []
    now = int(time.time())
    for r in rows:
        d = dict(r)
        if d["status"] == "pending" and int(d["expires_at"]) <= now:
            d["status"] = "expired"
        # Convert back to row-like dict via the helper.
        out.append({
            "order_no": d["order_no"],
            "status": d["status"],
            "amount_usd": int(d["amount_usd"]),
            "points": int(d["points"]),
            "expected_amount_usdt": d["expected_amount_usdt"],
            "network": d["network"],
            "tx_hash": d.get("tx_hash"),
            "created_at": int(d["created_at"]),
            "paid_at": int(d["paid_at"]) if d.get("paid_at") else None,
            "expires_at": int(d["expires_at"]),
        })
    return {"items": out}


@router.get("/deposit/{order_no}")
def deposit_status(order_no: str,
                   user: CurrentUser = Depends(require_user)) -> dict:
    from ..payments.bsc import SCANNER
    row = db.get_deposit_order(order_no)
    if row is None or int(row["user_id"]) != user.id:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {"order": _deposit_row_to_dict(row, SCANNER),
            "current_balance": db.get_points(user.id)}


@router.patch("/profile")
def update_profile(req: UpdateProfileReq, user: CurrentUser = Depends(require_user)) -> dict:
    dn = (req.display_name or "").strip()
    if len(dn) > 32:
        raise HTTPException(status_code=400, detail="显示名最长 32 字符")
    if any(c in dn for c in "<>&\"'`\n\r\t"):
        raise HTTPException(status_code=400, detail="显示名不能包含特殊字符或换行")
    bio = (req.bio or "").strip()
    if len(bio) > 500:
        raise HTTPException(status_code=400, detail="简介最长 500 字符")
    # strip HTML-ish chars from bio (keep newlines)
    if any(c in bio for c in "<>"):
        raise HTTPException(status_code=400, detail="简介不能包含 < 或 > 字符")
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
