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
    email           TEXT,
    password_hash   TEXT NOT NULL,
    is_admin        INTEGER NOT NULL DEFAULT 0,
    is_banned       INTEGER NOT NULL DEFAULT 0,
    banned_reason   TEXT,
    display_name    TEXT,
    bio             TEXT,
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

CREATE TABLE IF NOT EXISTS email_verifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL,
    purpose     TEXT NOT NULL,
    code_hash   TEXT NOT NULL,
    expires_at  INTEGER NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    used_at     INTEGER,
    created_at  INTEGER NOT NULL,
    user_id     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_email_verif_lookup ON email_verifications(email, purpose, used_at);
CREATE INDEX IF NOT EXISTS idx_email_verif_created ON email_verifications(created_at);

CREATE TABLE IF NOT EXISTS points_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    delta       INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    game_id     TEXT,
    round_no    INTEGER,
    created_at  INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_points_ledger_user ON points_ledger(user_id, created_at);

CREATE TABLE IF NOT EXISTS deposit_orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no            TEXT UNIQUE NOT NULL,
    user_id             INTEGER NOT NULL,
    amount_usd          INTEGER NOT NULL,
    points              INTEGER NOT NULL,
    expected_amount_units INTEGER NOT NULL,
    expected_amount_usdt TEXT NOT NULL,
    network             TEXT NOT NULL,
    recv_address        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    tx_hash             TEXT,
    from_address        TEXT,
    paid_amount_usdt    TEXT,
    created_at          INTEGER NOT NULL,
    paid_at             INTEGER,
    expires_at          INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_deposit_user ON deposit_orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_deposit_pending ON deposit_orders(network, status, expected_amount_units);
CREATE INDEX IF NOT EXISTS idx_deposit_expires ON deposit_orders(status, expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_txhash ON deposit_orders(tx_hash) WHERE tx_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS kv_store (
    k          TEXT PRIMARY KEY,
    v          TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


def init_db(db_path: Path) -> None:
    global _DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH = db_path
    with connect() as conn:
        conn.executescript(SCHEMA)
        # idempotent migration: add columns that may be missing on old DBs
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        for col, ddl in (("display_name", "TEXT"), ("bio", "TEXT"),
                        ("points", "INTEGER NOT NULL DEFAULT 1000")):
            if col not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        # add email_verifications.user_id if missing
        ev_existing = {r["name"] for r in conn.execute("PRAGMA table_info(email_verifications)")}
        if "user_id" not in ev_existing:
            conn.execute("ALTER TABLE email_verifications ADD COLUMN user_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_verif_user ON email_verifications(user_id, purpose, used_at)")
        # idempotent migration: drop UNIQUE constraint on users.email (allow duplicate emails)
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if row and row["sql"]:
            tail = row["sql"].split("email", 1)[1] if "email" in row["sql"] else ""
            head = tail.split(",", 1)[0] if tail else ""
            if "UNIQUE" in head.upper():
                cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)")]
                col_list = ", ".join(cols)
                conn.execute("PRAGMA foreign_keys = OFF")
                try:
                    conn.execute("ALTER TABLE users RENAME TO users_old_emailunique")
                    conn.executescript(SCHEMA)
                    new_existing = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
                    for col, ddl in (("display_name", "TEXT"), ("bio", "TEXT"),
                                    ("points", "INTEGER NOT NULL DEFAULT 1000")):
                        if col not in new_existing:
                            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
                    conn.execute(f"INSERT INTO users ({col_list}) SELECT {col_list} FROM users_old_emailunique")
                    conn.execute("DROP TABLE users_old_emailunique")
                finally:
                    conn.execute("PRAGMA foreign_keys = ON")
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


def list_users_by_email(email: str) -> List[sqlite3.Row]:
    """Return all (active or banned) users sharing this email, ordered by id."""
    with connect() as c:
        return list(c.execute(
            "SELECT id, username, email, is_admin, is_banned, created_at, last_login_at "
            "FROM users WHERE email = ? ORDER BY id",
            (email,),
        ))


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

def update_profile(uid: int, display_name: Optional[str], bio: Optional[str]) -> None:
    with connect() as c:
        c.execute(
            "UPDATE users SET display_name = ?, bio = ? WHERE id = ?",
            (display_name, bio, uid),
        )

# ----- email verifications -----------------------------------------------

def latest_verification(email: str, purpose: str) -> Optional[sqlite3.Row]:
    """Return the most recent (any state) verification row for email+purpose."""
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM email_verifications WHERE email=? AND purpose=? "
            "ORDER BY id DESC LIMIT 1",
            (email, purpose),
        ).fetchone()


def create_verification(email: str, purpose: str, code_hash: str,
                        ttl_seconds: int, user_id: Optional[int] = None) -> int:
    now = int(time.time())
    with connect() as conn:
        # invalidate previous unused codes. when user_id is given, scope by user_id+purpose;
        # otherwise scope by email+purpose (register flow has no user yet).
        if user_id is not None:
            conn.execute(
                "UPDATE email_verifications SET used_at=? "
                "WHERE user_id=? AND purpose=? AND used_at IS NULL",
                (now, user_id, purpose),
            )
        else:
            conn.execute(
                "UPDATE email_verifications SET used_at=? "
                "WHERE email=? AND purpose=? AND user_id IS NULL AND used_at IS NULL",
                (now, email, purpose),
            )
        cur = conn.execute(
            "INSERT INTO email_verifications "
            "(email, purpose, code_hash, expires_at, attempts, used_at, created_at, user_id) "
            "VALUES (?, ?, ?, ?, 0, NULL, ?, ?)",
            (email, purpose, code_hash, now + ttl_seconds, now, user_id),
        )
        return cur.lastrowid


def latest_verification_by_user(user_id: int, purpose: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM email_verifications WHERE user_id=? AND purpose=? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, purpose),
        ).fetchone()


def find_active_verification_by_user(user_id: int, purpose: str) -> Optional[sqlite3.Row]:
    now = int(time.time())
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM email_verifications WHERE user_id=? AND purpose=? "
            "AND used_at IS NULL AND expires_at > ? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, purpose, now),
        ).fetchone()


def find_active_verification(email: str, purpose: str) -> Optional[sqlite3.Row]:
    now = int(time.time())
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM email_verifications WHERE email=? AND purpose=? "
            "AND used_at IS NULL AND expires_at > ? "
            "ORDER BY id DESC LIMIT 1",
            (email, purpose, now),
        ).fetchone()


def bump_verification_attempts(vid: int) -> int:
    with connect() as conn:
        conn.execute("UPDATE email_verifications SET attempts = attempts + 1 WHERE id=?", (vid,))
        r = conn.execute("SELECT attempts FROM email_verifications WHERE id=?", (vid,)).fetchone()
        return int(r["attempts"]) if r else 0


def consume_verification(vid: int) -> None:
    now = int(time.time())
    with connect() as conn:
        conn.execute("UPDATE email_verifications SET used_at=? WHERE id=?", (now, vid))


def purge_old_verifications(older_than_seconds: int = 7 * 24 * 3600) -> None:
    cutoff = int(time.time()) - older_than_seconds
    with connect() as conn:
        conn.execute("DELETE FROM email_verifications WHERE created_at < ?", (cutoff,))


# -------- points / ledger --------

def get_points(uid: int) -> int:
    with connect() as c:
        row = c.execute("SELECT points FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None:
            return 0
        return int(row["points"] or 0)


def apply_points(uid: int, delta: int, reason: str,
                 game_id: Optional[str] = None,
                 round_no: Optional[int] = None) -> int:
    """Apply a points delta atomically and record in ledger. Returns new balance."""
    if not isinstance(delta, int):
        raise TypeError("delta must be int")
    now = int(time.time())
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT points FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None:
            c.execute("ROLLBACK")
            raise ValueError(f"user {uid} not found")
        new_balance = int(row["points"] or 0) + delta
        c.execute("UPDATE users SET points = ? WHERE id = ?", (new_balance, uid))
        c.execute(
            "INSERT INTO points_ledger (user_id, delta, balance_after, reason, game_id, round_no, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, delta, new_balance, reason, game_id, round_no, now),
        )
        c.execute("COMMIT")
        return new_balance


def list_ledger(uid: int, limit: int = 50) -> List[sqlite3.Row]:
    with connect() as c:
        return c.execute(
            "SELECT id, delta, balance_after, reason, game_id, round_no, created_at "
            "FROM points_ledger WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (uid, int(limit)),
        ).fetchall()


def leaderboard(limit: int = 20) -> List[sqlite3.Row]:
    with connect() as c:
        return c.execute(
            "SELECT id, username, display_name, points FROM users "
            "WHERE is_banned = 0 ORDER BY points DESC, id ASC LIMIT ?",
            (int(limit),),
        ).fetchall()

# -------- kv store --------

def get_kv(k: str) -> Optional[str]:
    with connect() as c:
        r = c.execute("SELECT v FROM kv_store WHERE k = ?", (k,)).fetchone()
        return r["v"] if r else None


def set_kv(k: str, v: str) -> None:
    now = int(time.time())
    with connect() as c:
        c.execute(
            "INSERT INTO kv_store (k, v, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = excluded.updated_at",
            (k, v, now),
        )


# -------- deposits --------

import secrets as _secrets


def _new_order_no() -> str:
    # 16 hex chars
    return "dep_" + _secrets.token_hex(8)


def create_deposit_order(
    user_id: int,
    amount_usd: int,
    points: int,
    network: str,
    recv_address: str,
    ttl_seconds: int,
) -> sqlite3.Row:
    """Create a pending deposit order with a unique 4-decimal USDT amount.

    The expected USDT amount = amount_usd + random_offset/10000 (in [0.0001..0.9999]).
    Uniqueness is enforced within (network, status='pending', expires_at>now).
    """
    if amount_usd < 1:
        raise ValueError("amount_usd must be >= 1")
    now = int(time.time())
    base_units = int(amount_usd) * 10000  # 1 USDT = 10000 units
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        # purge expired pending orders so their units become free
        c.execute(
            "UPDATE deposit_orders SET status='expired' WHERE status='pending' AND expires_at <= ?",
            (now,),
        )
        # pick a unique offset; try random first, then sweep
        existing = {int(r["expected_amount_units"]) for r in c.execute(
            "SELECT expected_amount_units FROM deposit_orders "
            "WHERE network=? AND status='pending' AND expires_at > ? "
            "AND expected_amount_units BETWEEN ? AND ?",
            (network, now, base_units + 1, base_units + 9999),
        )}
        offset = None
        for _ in range(40):
            cand = _secrets.randbelow(9999) + 1  # 1..9999
            if (base_units + cand) not in existing:
                offset = cand
                break
        if offset is None:
            for cand in range(1, 10000):
                if (base_units + cand) not in existing:
                    offset = cand
                    break
        if offset is None:
            c.execute("ROLLBACK")
            raise RuntimeError("no free deposit slot in this USD bucket; please try a different amount")
        units = base_units + offset
        amount_usdt_str = f"{units / 10000:.4f}"
        order_no = _new_order_no()
        c.execute(
            "INSERT INTO deposit_orders "
            "(order_no, user_id, amount_usd, points, expected_amount_units, expected_amount_usdt, "
            " network, recv_address, status, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (order_no, user_id, int(amount_usd), int(points), units, amount_usdt_str,
             network, recv_address, now, now + int(ttl_seconds)),
        )
        row_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("COMMIT")
        return c.execute("SELECT * FROM deposit_orders WHERE id = ?", (row_id,)).fetchone()


def get_deposit_order(order_no: str) -> Optional[sqlite3.Row]:
    with connect() as c:
        return c.execute("SELECT * FROM deposit_orders WHERE order_no = ?", (order_no,)).fetchone()


def list_user_deposits(user_id: int, limit: int = 50) -> List[sqlite3.Row]:
    with connect() as c:
        return list(c.execute(
            "SELECT * FROM deposit_orders WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, int(limit)),
        ))


def try_credit_deposit(tx_hash: str, amount_usdt: float, from_address: str,
                       network: str) -> Optional[dict]:
    """Atomically match an incoming USDT transfer to a pending order, mark paid
    and credit the user with points.

    Returns {order_no, user_id, points, amount_usd} on success, None if no match.
    Idempotent on tx_hash via unique index.
    """
    units = int(round(amount_usdt * 10000))
    now = int(time.time())
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        # Idempotency: if tx_hash already credited, no-op.
        seen = c.execute(
            "SELECT order_no FROM deposit_orders WHERE tx_hash = ? LIMIT 1",
            (tx_hash,),
        ).fetchone()
        if seen is not None:
            c.execute("ROLLBACK")
            return None
        # Match the oldest pending order with the exact units on this network.
        row = c.execute(
            "SELECT * FROM deposit_orders "
            "WHERE network = ? AND status = 'pending' AND expected_amount_units = ? "
            "  AND expires_at > ? "
            "ORDER BY created_at ASC LIMIT 1",
            (network, units, now),
        ).fetchone()
        if row is None:
            c.execute("ROLLBACK")
            return None
        order_no = row["order_no"]
        uid = int(row["user_id"])
        points = int(row["points"])
        amount_usd = int(row["amount_usd"])
        amount_usdt_str = f"{amount_usdt:.6f}"
        c.execute(
            "UPDATE deposit_orders SET status='paid', tx_hash=?, from_address=?, "
            " paid_amount_usdt=?, paid_at=? WHERE id=?",
            (tx_hash, (from_address or "").lower(), amount_usdt_str, now, int(row["id"])),
        )
        # Credit points + ledger in the same transaction.
        u = c.execute("SELECT points FROM users WHERE id = ?", (uid,)).fetchone()
        if u is None:
            c.execute("ROLLBACK")
            return None
        new_balance = int(u["points"] or 0) + points
        c.execute("UPDATE users SET points = ? WHERE id = ?", (new_balance, uid))
        c.execute(
            "INSERT INTO points_ledger (user_id, delta, balance_after, reason, game_id, round_no, created_at) "
            "VALUES (?, ?, ?, ?, NULL, NULL, ?)",
            (uid, points, new_balance, f"deposit:usdt-bep20:{network}:{order_no}", now),
        )
        c.execute("COMMIT")
        return {
            "order_no": order_no,
            "user_id": uid,
            "points": points,
            "amount_usd": amount_usd,
            "new_balance": new_balance,
        }


def expire_pending_deposits() -> int:
    now = int(time.time())
    with connect() as c:
        cur = c.execute(
            "UPDATE deposit_orders SET status='expired' "
            "WHERE status='pending' AND expires_at <= ?",
            (now,),
        )
        return int(cur.rowcount or 0)

