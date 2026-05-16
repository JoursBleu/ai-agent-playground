"""On-startup admin bootstrap helper."""

from __future__ import annotations

import os
import secrets
import string
import sys
from pathlib import Path

from . import db
from .security import hash_password


def _generate_password(length: int = 20) -> str:
    upper = string.ascii_uppercase
    lower = string.ascii_lowercase
    digit = string.digits
    punct = "!@#$%^&*()-_=+[]{}"
    pools = [upper, lower, digit, punct]
    chars = [secrets.choice(p) for p in pools]
    all_chars = "".join(pools)
    chars += [secrets.choice(all_chars) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def bootstrap_admin(data_dir: Path) -> None:
    rows = [r for r in db.list_users(limit=10000) if int(r["is_admin"])]
    if rows:
        return

    username = (os.environ.get("AAP_ADMIN_USERNAME") or "admin").strip()
    email = (os.environ.get("AAP_ADMIN_EMAIL") or "kangletian@hotmail.com").strip() or None
    password = (os.environ.get("AAP_ADMIN_PASSWORD") or "").strip()
    generated = False
    if not password:
        password = _generate_password()
        generated = True

    existing = db.find_user_by_username(username) or (db.find_user_by_email(email) if email else None)
    if existing is not None:
        db.set_user_admin(int(existing["id"]), True)
        print(f"[bootstrap] promoted existing user '{existing['username']}' to admin", file=sys.stderr, flush=True)
        return

    db.create_user(username=username, email=email, password_hash=hash_password(password), is_admin=True)
    print(f"[bootstrap] created admin user '{username}' (email={email or 'none'})", file=sys.stderr, flush=True)
    if generated:
        out = data_dir / "admin_password.txt"
        try:
            out.write_text(f"username: {username}\nemail: {email or ''}\npassword: {password}\n", encoding="utf-8")
            os.chmod(out, 0o600)
            print(f"[bootstrap] admin password written to {out} (chmod 600)", file=sys.stderr, flush=True)
        except OSError as e:
            print(f"[bootstrap] WARNING: could not write admin password file: {e}", file=sys.stderr, flush=True)
        print(f"[bootstrap] ===== ADMIN PASSWORD: {password} =====", file=sys.stderr, flush=True)
