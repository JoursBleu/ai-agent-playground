"""Shared game-interface metadata for agent-readable room APIs.

The route layer still owns HTTP details, but this module centralizes stable
per-game action schemas and endpoint templates so UI builders and verifiers have
one source of truth while the engines are incrementally refactored.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GameInterface:
    """Stable machine-facing contract for a game type."""

    game_type: str
    actions: tuple[dict[str, Any], ...]

    def action_schema(self) -> list[dict[str, Any]]:
        """Return a JSON-safe action schema copy."""
        return deepcopy(list(self.actions))


DOUDIZHU_INTERFACE = GameInterface(
    game_type="doudizhu",
    actions=(
        {"id": "bid", "params": {"bid": "integer 0..3"}},
        {"id": "play_cards", "params": {"cards": "string[] card codes"}},
        {"id": "pass", "params": {}},
        {
            "id": "play_hint",
            "params": {"cards": "string[] suggested by /actions", "pattern": "object", "hint_reason": "string"},
            "execute_as": {"action": "play_cards", "cards": "<params.cards>"},
        },
    ),
)

TEXAS_HOLDEM_INTERFACE = GameInterface(
    game_type="texas_holdem",
    actions=(
        {"id": "fold", "params": {}},
        {"id": "check", "params": {}},
        {"id": "call", "params": {}},
        {
            "id": "raise",
            "params": {
                "amount": "integer target bet_in_round",
                "min": "integer from /actions",
                "max": "integer from /actions",
            },
        },
        {"id": "all_in", "params": {}},
    ),
)

INTERFACES: dict[str, GameInterface] = {
    DOUDIZHU_INTERFACE.game_type: DOUDIZHU_INTERFACE,
    TEXAS_HOLDEM_INTERFACE.game_type: TEXAS_HOLDEM_INTERFACE,
}


def get_game_interface(game_type: str) -> GameInterface:
    try:
        return INTERFACES[game_type]
    except KeyError as exc:
        raise ValueError(f"unknown game_type {game_type!r}") from exc


def interface_names() -> list[str]:
    return sorted(INTERFACES)
