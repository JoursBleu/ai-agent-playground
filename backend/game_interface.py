"""Shared game-interface metadata for agent-readable room APIs.

The route layer still owns HTTP details, but this module centralizes stable
per-game action schemas and endpoint templates so UI builders and verifiers have
one source of truth while the engines are incrementally refactored.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from .doudizhu.game import GameError
from .doudizhu.hints import find_legal_hint
from .texas_holdem.game import TexasError


@dataclass(frozen=True)
class GameInterface:
    """Stable machine-facing contract for a game type."""

    game_type: str
    actions: tuple[dict[str, Any], ...]
    legal_actions: Callable[[dict[str, Any], str | None], list[dict[str, Any]]]
    apply_action_fn: Callable[[Any, Any], dict[str, Any]]

    def action_schema(self) -> list[dict[str, Any]]:
        """Return a JSON-safe action schema copy."""
        return deepcopy(list(self.actions))

    def action_descriptors(self, state: dict[str, Any], token: str | None) -> list[dict[str, Any]]:
        """Return current visible action handles for one viewer."""
        return self.legal_actions(state, token)

    def apply_action(self, game: Any, req: Any) -> dict[str, Any]:
        """Apply a normalized mutation request to the underlying engine."""
        return self.apply_action_fn(game, req)

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


def _base_action(action_id: str, label: str, *, enabled: bool, reason: str = "", **params: Any) -> dict[str, Any]:
    return {
        "id": action_id,
        "label": label,
        "enabled": bool(enabled),
        "disabled_reason": "" if enabled else reason,
        "params": params,
    }


def doudizhu_legal_actions(state: dict[str, Any], token: str | None) -> list[dict[str, Any]]:
    phase = state.get("phase")
    you = state.get("you") or {}
    clock = state.get("turn_clock") or {}
    is_turn = bool(you.get("is_your_turn"))
    can_act = bool(clock.get("can_act"))
    wait_reason = "not your turn" if not is_turn else "thinking/timeout window"
    actions: list[dict[str, Any]] = []

    if phase == "bidding":
        current_bid = int(state.get("current_bid") or 0)
        for value in (0, 1, 2, 3):
            enabled = bool(token and is_turn and can_act and (value == 0 or value > current_bid))
            reason = "bid must be 0 or greater than current bid" if value and value <= current_bid else wait_reason
            actions.append(_base_action("bid", f"bid {value}", enabled=enabled, reason=reason, bid=value))
        return actions

    if phase == "playing":
        must_lead = state.get("last_play_seat", -1) in (-1, you.get("seat"))
        hand = list(you.get("hand") or [])
        actions.append(_base_action(
            "play_cards",
            "play selected cards",
            enabled=bool(token and is_turn and can_act and hand),
            reason=wait_reason,
            schema={"cards": "string[]"},
        ))
        actions.append(_base_action(
            "pass",
            "pass",
            enabled=bool(token and is_turn and can_act and not must_lead),
            reason="leader must play cards" if must_lead else wait_reason,
            cards=[],
        ))
        hint = None
        if hand:
            try:
                hint = find_legal_hint(
                    hand,
                    last_play_codes=state.get("last_play_cards") or [],
                    must_lead=must_lead,
                )
            except Exception:
                hint = None
        if hint:
            actions.append(_base_action(
                "play_hint",
                "play suggested legal cards",
                enabled=bool(token and is_turn and can_act),
                reason=wait_reason,
                cards=hint["cards"],
                pattern=hint["pattern"],
                hint_reason=hint.get("reason", ""),
            ))
        return actions

    return actions


def doudizhu_apply_action(game: Any, req: Any) -> dict[str, Any]:
    action = (req.action or "").strip().lower().replace("-", "_")
    if action == "bid":
        if req.bid is None:
            raise GameError("bid is required for bid action")
        game.bid(req.token, int(req.bid))
        return {"action": "bid", "bid": int(req.bid)}
    if action in ("play", "play_cards"):
        return game.play(req.token, req.cards)
    if action == "pass":
        return game.play(req.token, [])
    if action == "play_hint":
        state = game.private_state(req.token)
        you = state.get("you") or {}
        must_lead = state.get("last_play_seat", -1) in (-1, you.get("seat"))
        hint = find_legal_hint(
            you.get("hand") or [],
            last_play_codes=state.get("last_play_cards") or [],
            must_lead=must_lead,
        )
        if not hint:
            raise GameError("no legal hint available")
        return game.play(req.token, hint["cards"])
    raise GameError(f"unknown doudizhu action {action!r}")





def texas_holdem_legal_actions(state: dict[str, Any], token: str | None) -> list[dict[str, Any]]:
    you = state.get("you") or {}
    clock = state.get("turn_clock") or {}
    is_turn = bool(you.get("is_your_turn"))
    can_act = bool(clock.get("can_act"))
    base_enabled = bool(token and state.get("phase") == "playing" and is_turn and can_act)
    reason = "not your action window"
    call_amount = int(you.get("call_amount") or 0)
    min_raise_to = int(you.get("min_raise_to") or 0)
    max_raise_to = int(you.get("max_raise_to") or 0)
    can_check = bool(you.get("can_check"))
    can_raise = base_enabled and max_raise_to >= min_raise_to and min_raise_to > 0
    return [
        _base_action("fold", "fold", enabled=base_enabled, reason=reason),
        _base_action("check", "check", enabled=base_enabled and can_check, reason="must call before checking" if not can_check else reason),
        _base_action("call", "call", enabled=base_enabled and call_amount > 0, reason="nothing to call" if call_amount <= 0 else reason, amount=call_amount),
        _base_action("raise", "raise", enabled=can_raise, reason="not enough chips to raise" if base_enabled else reason, min=min_raise_to, max=max_raise_to, min_amount=min_raise_to, max_amount=max_raise_to),
        _base_action("all_in", "all-in", enabled=base_enabled and max_raise_to > 0, reason=reason, amount=max_raise_to),
    ]


def texas_holdem_apply_action(game: Any, req: Any) -> dict[str, Any]:
    action = (req.action or "").strip().lower().replace("-", "_")
    if action == "fold":
        return game.fold(req.token)
    if action == "check":
        return game.check(req.token)
    if action == "call":
        return game.call(req.token)
    if action == "raise":
        if req.amount is None:
            raise TexasError("amount is required for raise")
        return game.raise_to(req.token, int(req.amount))
    if action in ("allin", "all_in"):
        return game.all_in(req.token)
    raise TexasError(f"unknown texas_holdem action {action!r}")


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
    legal_actions=doudizhu_legal_actions,
    apply_action_fn=doudizhu_apply_action,
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
    legal_actions=texas_holdem_legal_actions,
    apply_action_fn=texas_holdem_apply_action,
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


def base_ui_state(
    *,
    schema_version: str,
    game_type: str,
    state: dict[str, Any],
    event_log: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return common machine-readable UI state fields shared by all games."""
    return {
        "schema_version": schema_version,
        "game_id": state.get("game_id"),
        "game_type": game_type,
        "phase": state.get("phase"),
        "room": {
            "name": state.get("name"),
            "description": state.get("description"),
            "rule_mode": state.get("rule_mode"),
            "owner_seat": state.get("owner_seat"),
        },
        "clock": state.get("turn_clock") or {},
        "seats": state.get("players") or [],
        "you": state.get("you"),
        "chat": state.get("chat") or [],
        "event_log": event_log,
        "actions": actions,
    }



def table_view_for(game_type: str, state: dict[str, Any], event_log: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the game-specific table section of /ui-state."""
    if game_type == "texas_holdem":
        return {
            "street": state.get("street"),
            "round_no": state.get("round_no"),
            "dealer_seat": state.get("dealer_seat"),
            "current_turn": state.get("current_turn"),
            "community": state.get("community") or [],
            "pot": state.get("pot"),
            "current_bet": state.get("current_bet"),
            "small_blind": state.get("small_blind"),
            "big_blind": state.get("big_blind"),
            "winners": state.get("winners") or [],
            "showdown": state.get("last_showdown") or [],
            "history": state.get("history") or [],
            "event_log": event_log,
        }
    return {
        "bid_turn": state.get("bid_turn"),
        "current_bid": state.get("current_bid"),
        "landlord_seat": state.get("landlord_seat"),
        "current_turn": state.get("current_turn"),
        "bottom_cards": state.get("bottom_cards") or [],
        "last_play_seat": state.get("last_play_seat"),
        "last_play_cards": state.get("last_play_cards") or [],
        "last_play_category": state.get("last_play_category"),
        "history": state.get("history") or [],
        "event_log": event_log,
        "winner_seat": state.get("winner_seat"),
    }


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
