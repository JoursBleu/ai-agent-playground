"""SQLite database for users / sessions / API keys."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import List, Optional


_DB_PATH: Optional[Path] = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    email           TEXT UNIQUE,
    password_hash   TEXT NOT NULL,
    is_admin        INTEGER NOT NULL DEFAULT 0,
    is_banned       INTEGER NOT NULL DEFAULT 0,
    banned_reason   TEXT,
    created_at      INTEGER NOT NULL,
    last_login_at   INTEGER
);

CREATE TABLE IF NOT EXISTS sessions (
    sid         TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL,
    ip          TEXT,
    ua          TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    name            TEXT NOT NULL,
    key_prefix      TEXT NOT NULL,
    key_hash        TEXT UNIQUE NOT NULL,
    created_at      INTEGER NOT NULL,
    last_used_at    INTEGER,
    revoked_at      INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_apikeys_user ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_apikeys_hash ON api_keys(key_hash);
"""


def init_db(db_path: Path) -> None:
    global _DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH = db_path
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def connect() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("auth db not initialised")
    conn = sqlite3.connect(_DB_PATH, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def create_user(username: str, email: Optional[str], password_hash: str, is_admin: bool = False) -> int:
    now = int(time.time())
    with connect() as c:
        cur = c.execute(
            "INSERT INTO users (username, email, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, email, password_hash, 1 if is_admin else 0, now),
        )
        return int(cur.lastrowid)


def find_user_by_login(login: str) -> Optional[sqlite3.Row]:
    with connect() as c:
        return c.execute("SELECT * FROM users WHERE username = ? OR email = ?", (login, login)).fetchone()


def find_user_by_id(uid: int) -> Optional[sqlite3.Row]:
    with connect() as c:
        return c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def find_user_by_username(username: str) -> Optional[sqlite3.Row]:
    with connect() as c:
        return c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def find_user_by_email(email: str) -> Optional[sqlite3.Row]:
    with connect() as c:
        return c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def list_users(limit: int = 500) -> List[sqlite3.Row]:
    with connect() as c:
        return list(c.execute(
            "SELECT id, username, email, is_admin, is_banned, banned_reason, created_at, last_login_at FROM users ORDER BY id DESC LIMIT ?",
            (limit,),
        ))


def set_user_banned(uid: int, banned: bool, reason: Optional[str]) -> None:
    with connect() as c:
        c.execute("UPDATE users SET is_banned = ?, banned_reason = ? WHERE id = ?",
                  (1 if banned else 0, reason if banned else None, uid))
        if banned:
            c.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))


def set_user_admin(uid: int, is_admin: bool) -> None:
    with connect() as c:
        c.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, uid))


def touch_user_login(uid: int) -> None:
    with connect() as c:
        c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (int(time.time()), uid))


def change_password(uid: int, new_hash: str, drop_sessions: bool = True) -> None:
    with connect() as c:
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, uid))
        if drop_sessions:
            c.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))


def create_session(sid: str, user_id: int, ttl_seconds: int, ip: Optional[str], ua: Optional[str]) -> None:
    now = int(time.time())
    with connect() as c:
        c.execute("INSERT INTO sessions (sid, user_id, created_at, expires_at, ip, ua) VALUES (?, ?, ?, ?, ?, ?)",
                  (sid, user_id, now, now + ttl_seconds, ip, ua))


def find_session(sid: str) -> Optional[sqlite3.Row]:
    now = int(time.time())
    with connect() as c:
        return c.execute("SELECT * FROM sessions WHERE sid = ? AND expires_at > ?", (sid, now)).fetchone()


def delete_session(sid: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM sessions WHERE sid = ?", (sid,))


def delete_user_sessions(user_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def create_api_key(user_id: int, name: str, key_prefix: str, key_hash: str) -> int:
    now = int(time.time())
    with connect() as c:
        cur = c.execute(
            "INSERT INTO api_keys (user_id, name, key_prefix, key_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, key_prefix, key_hash, now),
        )
        return int(cur.lastrowid)


def list_api_keys(user_id: int) -> List[sqlite3.Row]:
    with connect() as c:
        return list(c.execute(
            "SELECT id, name, key_prefix, created_at, last_used_at, revoked_at FROM api_keys WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ))


def find_api_key_by_hash(key_hash: str) -> Optional[sqlite3.Row]:
    with connect() as c:
        return c.execute(
            "SELECT k.*, u.username, u.is_admin, u.is_banned FROM api_keys k JOIN users u ON u.id = k.user_id WHERE k.key_hash = ? AND k.revoked_at IS NULL",
            (key_hash,),
        ).fetchone()


def revoke_api_key(user_id: int, key_id: int) -> bool:
    now = int(time.time())
    with connect() as c:
        cur = c.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
            (now, key_id, user_id),
        )
        return (cur.rowcount or 0) > 0


def touch_api_key(key_id: int) -> None:
    with connect() as c:
        c.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (int(time.time()), key_id))
