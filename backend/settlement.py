"""Point settlement helpers for completed game rounds."""

from __future__ import annotations

from typing import Any

from .auth import db as auth_db
from .game_state import GAME_USERS, game_type


def maybe_settle(game_id: str, game: Any) -> None:
    """Apply points settlement when a hand/round has just finished.

    Idempotent via ``game._points_settled_round``. Safe to call on every
    state-poll or after any action.
    """
    if game is None or getattr(game, "disbanded", False):
        return
    phase = getattr(game, "phase", None)
    phase_val = getattr(phase, "value", phase)
    if phase_val != "finished":
        return

    round_no = int(getattr(game, "round_no", 1) or 1)
    if getattr(game, "_points_settled_round", 0) >= round_no:
        return

    try:
        deltas = game.compute_settlement()
    except Exception as exc:
        print(f"[points] compute_settlement failed for {game_id}: {exc}", flush=True)
        game._points_settled_round = round_no
        return

    if not deltas:
        game._points_settled_round = round_no
        return

    seat_to_user = GAME_USERS.get(game_id, {})
    gtype = game_type(game)
    for seat, delta in deltas.items():
        uid = seat_to_user.get(int(seat))
        if uid is None or not isinstance(delta, int) or delta == 0:
            continue
        try:
            auth_db.apply_points(
                uid,
                int(delta),
                reason=f"{gtype}:round_end",
                game_id=game_id,
                round_no=round_no,
            )
        except Exception as exc:
            print(f"[points] apply_points failed uid={uid} delta={delta}: {exc}", flush=True)

    game._points_settled_round = round_no
