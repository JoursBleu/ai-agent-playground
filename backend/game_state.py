"""Shared in-memory room registry for ai-agent-playground.

This module intentionally keeps the current in-memory architecture, but moves
room ownership, idle reaping, and registry helpers out of ``backend.main`` so
API routing and application bootstrap stay small.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict


GAMES: Dict[str, Any] = {}
# user_id -> game_id of the single room they're currently associated with
# (set when they create OR join; cleared when that room is disbanded/reaped)
USER_ROOM: Dict[int, str] = {}
# game_id -> {seat: user_id} for point settlement
GAME_USERS: Dict[str, Dict[int, int]] = {}
LOCK = threading.Lock()

# Idle reaper: kill rooms that haven't seen any activity for this many seconds.
# WAITING (nobody joined / fewer than 3 seated) rooms are reaped sooner.
IDLE_TIMEOUT_S = int(os.environ.get("AAP_IDLE_TIMEOUT_S", "1800"))   # 30 min
IDLE_TIMEOUT_WAITING_S = int(os.environ.get("AAP_IDLE_TIMEOUT_WAITING_S", "600"))  # 10 min
IDLE_TIMEOUT_FINISHED_S = int(os.environ.get("AAP_IDLE_TIMEOUT_FINISHED_S", "900"))  # 15 min after finish

_REAPER_STARTED = False


def release_user_room(game_id: str) -> None:
    """Clear USER_ROOM entries that point to a given game_id."""
    for uid, gid in list(USER_ROOM.items()):
        if gid == game_id:
            USER_ROOM.pop(uid, None)


def room_phase_value(game: Any) -> str:
    phase = getattr(game, "phase", None)
    return str(getattr(phase, "value", phase) or "")


def game_type(game: Any) -> str:
    return getattr(game, "game_type", "doudizhu")


def seated_count(game: Any) -> int:
    return sum(1 for p in getattr(game, "players", []) if p is not None)


def reap_idle_rooms() -> None:
    now = time.time()
    to_remove: list[str] = []
    for gid, game in list(GAMES.items()):
        age = now - getattr(game, "last_active", getattr(game, "created_at", now))
        phase = room_phase_value(game)
        if getattr(game, "disbanded", False):
            to_remove.append(gid)
            continue
        if phase == "finished" and age > IDLE_TIMEOUT_FINISHED_S:
            to_remove.append(gid)
            continue
        if phase == "waiting" and seated_count(game) < 3 and age > IDLE_TIMEOUT_WAITING_S:
            to_remove.append(gid)
            continue
        if age > IDLE_TIMEOUT_S:
            to_remove.append(gid)

    for gid in to_remove:
        game = GAMES.get(gid)
        if game is None:
            continue
        try:
            game.disband("idle reaper")
        except Exception:
            pass
        GAMES.pop(gid, None)
        release_user_room(gid)
        print(f"[REAP] room {gid} removed (idle)", flush=True)


def _reaper_loop() -> None:
    while True:
        time.sleep(60)
        try:
            with LOCK:
                reap_idle_rooms()
        except Exception as exc:
            print(f"[REAP] error: {exc}", flush=True)


def start_reaper_thread() -> None:
    """Start the idle reaper once per process."""
    global _REAPER_STARTED
    if _REAPER_STARTED:
        return
    _REAPER_STARTED = True
    thread = threading.Thread(target=_reaper_loop, daemon=True, name="aap-reaper")
    thread.start()
