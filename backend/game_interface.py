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

    def action_schema_response(self, *, schema_version: str, game_id: str) -> dict[str, Any]:
        """Return the full /action-schema response for one room."""
        return {
            "schema_version": schema_version,
            "game_id": game_id,
            "game_type": self.game_type,
            "execute_endpoint": f"/api/games/{game_id}/action",
            "state_endpoint": f"/api/games/{game_id}/ui-state",
            "actions_endpoint": f"/api/games/{game_id}/actions",
            "events_endpoint": f"/api/games/{game_id}/events",
            "actions": self.action_schema(),
        }


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


def event_log_for(game_type: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a normalized event log for an engine state snapshot."""
    events: list[dict[str, Any]] = []
    for idx, history_item in enumerate(state.get("history") or []):
        item = dict(history_item)
        item.setdefault("index", idx)
        item.setdefault("game_type", game_type)
        if game_type == "texas_holdem":
            item.setdefault("type", item.get("action") or "action")
        else:
            item.setdefault("type", "pass" if not item.get("cards") else "play")
            item.setdefault("action", item["type"])
        events.append(item)
    return events
