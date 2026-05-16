"""Password hashing, API key generation, and validation helpers."""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Optional, Tuple

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


_CAT_PATTERNS = (
    re.compile(r"[A-Z]"),
    re.compile(r"[a-z]"),
    re.compile(r"[0-9]"),
    re.compile(r"[^A-Za-z0-9]"),
)


def check_password_strength(password: str) -> Optional[str]:
    if len(password) < 8:
        return "密码至少 8 位"
    if len(password) > 128:
        return "密码不能超过 128 位"
    cats = sum(1 for pat in _CAT_PATTERNS if pat.search(password))
    if cats < 3:
        return "密码需包含大写、小写、数字、特殊字符中的至少 3 类"
    return None


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{1,30}$")


def check_username(username: str) -> Optional[str]:
    if not username:
        return "用户名必填"
    if not _USERNAME_RE.match(username):
        return "用户名 2-31 位，仅可含字母/数字/下划线/点/横杠，且不可以点或横杠开头"
    return None


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check_email(email: str) -> Optional[str]:
    if not _EMAIL_RE.match(email or ""):
        return "邮箱格式不正确"
    return None


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


API_KEY_PREFIX = "aap_"


def new_api_key() -> Tuple[str, str, str]:
    body = secrets.token_urlsafe(32)
    full = API_KEY_PREFIX + body
    prefix = full[: len(API_KEY_PREFIX) + 6]
    h = hashlib.sha256(full.encode("utf-8")).hexdigest()
    return full, prefix, h


def hash_api_key(full: str) -> str:
    return hashlib.sha256(full.encode("utf-8")).hexdigest()
