"""Background process helpers for ai-agent-playground."""

from __future__ import annotations

import threading
import time

from .auth import db as auth_db
from .game_state import start_reaper_thread
from .payments.bsc import SCANNER as BSC_SCANNER

_DEPOSIT_EXPIRY_STARTED = False
_BSC_STARTED = False


def _deposit_expiry_loop() -> None:
    # one-shot sweep at startup so stale rows from a previous run clean up immediately
    try:
        n = auth_db.expire_pending_deposits()
        if n:
            print(f"[deposit-expiry] startup swept {n} stale pending orders", flush=True)
    except Exception as exc:
        print(f"[deposit-expiry] startup error: {exc}", flush=True)

    while True:
        time.sleep(300)  # every 5 minutes
        try:
            n = auth_db.expire_pending_deposits()
            if n:
                print(f"[deposit-expiry] swept {n} expired pending orders", flush=True)
        except Exception as exc:
            print(f"[deposit-expiry] error: {exc}", flush=True)


def start_deposit_expiry_thread() -> None:
    global _DEPOSIT_EXPIRY_STARTED
    if _DEPOSIT_EXPIRY_STARTED:
        return
    _DEPOSIT_EXPIRY_STARTED = True
    thread = threading.Thread(
        target=_deposit_expiry_loop,
        daemon=True,
        name="aap-deposit-expiry",
    )
    thread.start()


def start_background_workers() -> None:
    """Start all process-local background workers once."""
    global _BSC_STARTED
    start_reaper_thread()
    start_deposit_expiry_thread()
    if not _BSC_STARTED:
        _BSC_STARTED = True
        BSC_SCANNER.start()
