"""HTTP routes for game rooms.

The public API paths intentionally remain unchanged.  This module only moves
route handlers out of ``backend.main`` so app bootstrap, room state, settlement,
and game APIs are easier to maintain independently.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import db as auth_db
from .auth.deps import CurrentUser, require_admin, require_user
from .doudizhu.game import Game, GameError
from .doudizhu.hints import find_legal_hint
from .game_state import GAME_USERS, GAMES, LOCK, USER_ROOM, game_type, release_user_room
from .settlement import maybe_settle
from .texas_holdem.game import TexasError, TexasGame

router = APIRouter()
AGENT_API_SCHEMA_VERSION = "2026-06-10.1"


@lru_cache(maxsize=1)
def app_version() -> dict:
    env_commit = os.getenv("AAP_GIT_COMMIT") or os.getenv("GIT_COMMIT")
    if env_commit:
        return {"commit": env_commit[:12], "source": "env"}
    try:
        root = Path(__file__).resolve().parents[1]
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
        ).strip()
        if commit:
            return {"commit": commit, "source": "git"}
    except Exception:
        pass
    return {"commit": "unknown", "source": "unknown"}


# ---- request / response models -------------------------------------------


class CreateGameReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=40, description="room display name (required)")
    description: str = Field(default="", max_length=200, description="optional room description")
    rule_mode: str = Field(default="builtin", description="builtin or referee")
    referee_url: Optional[str] = None
    seed: Optional[int] = None
    game_type: str = Field(default="doudizhu", description="doudizhu | texas_holdem")


class CreateGameResp(BaseModel):
    game_id: str
    name: str
    rule_mode: str
    game_type: str


class JoinReq(BaseModel):
    player_name: str = ""
    bio: str = ""


class JoinResp(BaseModel):
    player_id: str
    seat: int
    token: str


class BidReq(BaseModel):
    token: str
    bid: int


class PlayReq(BaseModel):
    token: str
    cards: List[str] = []


class ChatReq(BaseModel):
    token: str
    text: str


class DisbandReq(BaseModel):
    token: str                          # owner's player token
    reason: str = ""


class TexasActionReq(BaseModel):
    token: str
    action: str                          # fold | check | call | raise | allin
    amount: int = 0                      # for raise: bet_in_round target


class LeaveReq(BaseModel):
    token: str


class RestartReq(BaseModel):
    token: str


class GameActionReq(BaseModel):
    """Generic machine-callable game action.

    This is the agent handle: every UI button should have an equivalent action
    here, while legacy game-specific endpoints remain for compatibility.
    """
    token: str
    action: str
    cards: List[str] = []
    bid: Optional[int] = None
    amount: Optional[int] = None
    text: str = ""


# ---- helpers --------------------------------------------------------------


def get_game_or_404(game_id: str):
    game = GAMES.get(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    return game


def require_game_type(game, want: str) -> None:
    actual = game_type(game)
    if actual != want:
        raise HTTPException(
            status_code=400,
            detail=f"endpoint only valid for game_type={want} (this room is {actual})",
        )


def game_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def public_room_item(game) -> dict:
    return {
        "game_id": game.game_id,
        "name": game.name,
        "description": game.description,
        "phase": game.phase.value,
        "rule_mode": game.rule_mode,
        "game_type": game_type(game),
        "players": [p.name if p else None for p in game.players],
    }


# ---- machine-readable UI/action helpers ----------------------------------


def _state_for_reader(game, token: Optional[str], spectator: Optional[str]) -> dict:
    """Return the same state a UI/agent reader is allowed to see."""
    if token:
        try:
            return game.private_state(token)
        except (GameError, TexasError) as exc:
            raise game_error(exc)
    if spectator and game.is_spectator_token(spectator):
        return game.omniscient_state()
    return game.public_state()


def _base_action(action_id: str, label: str, *, enabled: bool, reason: str = "", **params: Any) -> dict:
    return {
        "id": action_id,
        "label": label,
        "enabled": bool(enabled),
        "disabled_reason": "" if enabled else reason,
        "params": params,
    }


def _doudizhu_actions(state: dict, token: Optional[str]) -> list[dict]:
    phase = state.get("phase")
    you = state.get("you") or {}
    clock = state.get("turn_clock") or {}
    is_turn = bool(you.get("is_your_turn"))
    can_act = bool(clock.get("can_act"))
    wait_reason = "not your turn" if not is_turn else "thinking/timeout window"
    actions: list[dict] = []

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


def _texas_actions(state: dict, token: Optional[str]) -> list[dict]:
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


def action_descriptors(game, state: dict, token: Optional[str]) -> list[dict]:
    gt = game_type(game)
    if gt == "texas_holdem":
        return _texas_actions(state, token)
    return _doudizhu_actions(state, token)


def _event_log(gt: str, state: dict) -> list[dict]:
    events: list[dict] = []
    for idx, h in enumerate(state.get("history") or []):
        item = dict(h)
        item.setdefault("index", idx)
        item.setdefault("game_type", gt)
        if gt == "texas_holdem":
            item.setdefault("type", item.get("action") or "action")
        else:
            item.setdefault("type", "pass" if not item.get("cards") else "play")
            item.setdefault("action", item["type"])
        events.append(item)
    return events


def ui_state(game, state: dict, token: Optional[str]) -> dict:
    """Machine-readable view model: every important visual region is structured."""
    gt = game_type(game)
    event_log = _event_log(gt, state)
    common = {
        "schema_version": AGENT_API_SCHEMA_VERSION,
        "game_id": state.get("game_id"),
        "game_type": gt,
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
        "actions": action_descriptors(game, state, token),
    }
    if gt == "texas_holdem":
        common["table"] = {
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
    else:
        common["table"] = {
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
    return common


def apply_generic_action(game_id: str, game, req: GameActionReq) -> dict:
    """Dispatch a machine-callable action to the underlying engine."""
    gt = game_type(game)
    action = (req.action or "").strip().lower().replace("-", "_")
    if gt == "texas_holdem":
        try:
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
        except TexasError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        raise HTTPException(status_code=400, detail=f"unknown texas_holdem action {action!r}")

    try:
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
    except GameError as exc:
        raise game_error(exc)
    raise HTTPException(status_code=400, detail=f"unknown doudizhu action {action!r}")


# ---- API ------------------------------------------------------------------


@router.get("/api/health")
def health() -> dict:
    return {"ok": True, "games": len(GAMES), "version": app_version()}


@router.post("/api/games", response_model=CreateGameResp)
def create_game(req: CreateGameReq, user: CurrentUser = Depends(require_user)) -> CreateGameResp:
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="房间名不能为空")

    desc = (req.description or "").strip()
    rule_mode = (req.rule_mode or "builtin").strip() or "builtin"
    if rule_mode != "builtin":
        raise HTTPException(status_code=400, detail="referee 规则模式暂未开放")

    requested_type = (req.game_type or "doudizhu").strip().lower()
    if requested_type not in ("doudizhu", "texas_holdem"):
        raise HTTPException(
            status_code=400,
            detail=f"unknown game_type {requested_type!r} (expected doudizhu | texas_holdem)",
        )

    game_id = secrets.token_hex(4)
    try:
        if requested_type == "texas_holdem":
            game = TexasGame(
                game_id=game_id,
                name=name,
                description=desc,
                rule_mode=rule_mode,
                referee_url=None,
                seed=req.seed,
            )
        else:
            game = Game(
                game_id=game_id,
                name=name,
                description=desc,
                rule_mode=rule_mode,
                referee_url=None,
                seed=req.seed,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with LOCK:
        existing = USER_ROOM.get(user.id)
        if existing and existing in GAMES:
            raise HTTPException(
                status_code=409,
                detail=f"你已在房间 {existing} 中，请先离开（解散或等待结束）",
            )
        GAMES[game_id] = game
        USER_ROOM[user.id] = game_id
        GAME_USERS[game_id] = {}

    # Print spectator token to server log only (never exposed via any API).
    # Operator can read it with: grep SPECTATOR ~/logs/ai-agent-playground.log
    print(
        f"[SPECTATOR] game_id={game_id} game_type={requested_type} spectator_token={game.spectator_token}",
        flush=True,
    )
    return CreateGameResp(
        game_id=game_id,
        name=game.name,
        rule_mode=game.rule_mode,
        game_type=requested_type,
    )


@router.get("/api/games")
def list_games() -> dict:
    now = time.time()
    items = []
    for game in GAMES.values():
        if game.disbanded or game.phase.value == "finished":
            continue
        age = now - getattr(game, "last_active", game.created_at)
        # hide rooms that have been silent for over 5 min from the public lobby
        if age > 300:
            continue
        items.append(public_room_item(game))
    return {"games": items}


@router.post("/api/games/{game_id}/join", response_model=JoinResp)
def join(game_id: str, req: JoinReq, user: CurrentUser = Depends(require_user)) -> JoinResp:
    game = get_game_or_404(game_id)
    with LOCK:
        existing = USER_ROOM.get(user.id)
        if existing and existing != game_id and existing in GAMES:
            raise HTTPException(status_code=409, detail=f"你已在房间 {existing} 中，请先离开")

    # Player display name and bio now come from the user's profile, not the request.
    profile = auth_db.find_user_by_id(user.id)
    if profile is None:
        raise HTTPException(status_code=401, detail="profile not found")
    prof_keys = profile.keys()
    profile_name = (profile["display_name"] if "display_name" in prof_keys else None) or ""
    profile_bio = (profile["bio"] if "bio" in prof_keys else None) or ""
    name = profile_name.strip() or profile["username"]
    bio = profile_bio.strip()

    try:
        player = game.add_player(name, bio)
    except GameError as exc:
        raise game_error(exc)

    with LOCK:
        USER_ROOM[user.id] = game_id
        GAME_USERS.setdefault(game_id, {})[player.seat] = user.id
    return JoinResp(player_id=player.player_id, seat=player.seat, token=player.token)


@router.get("/api/games/{game_id}/state")
def get_state(game_id: str, token: Optional[str] = None, spectator: Optional[str] = None) -> dict:
    game = get_game_or_404(game_id)
    maybe_settle(game_id, game)
    if token:
        try:
            return game.private_state(token)
        except GameError as exc:
            raise game_error(exc)
    if spectator and game.is_spectator_token(spectator):
        return game.omniscient_state()
    return game.public_state()


@router.get("/api/games/{game_id}/ui-state")
def get_ui_state(game_id: str, token: Optional[str] = None, spectator: Optional[str] = None) -> dict:
    """Agent-readable view model for the current room.

    This is the API equivalent of the web UI: table regions, visible cards,
    seats, clock, chat, and currently callable actions are all structured.
    """
    game = get_game_or_404(game_id)
    maybe_settle(game_id, game)
    state = _state_for_reader(game, token, spectator)
    return ui_state(game, state, token)


@router.get("/api/games/{game_id}/actions")
def get_actions(game_id: str, token: Optional[str] = None) -> dict:
    """List machine-callable actions available to this token right now."""
    game = get_game_or_404(game_id)
    maybe_settle(game_id, game)
    state = _state_for_reader(game, token, None)
    return {
        "game_id": game_id,
        "game_type": game_type(game),
        "phase": state.get("phase"),
        "actions": action_descriptors(game, state, token),
    }


@router.get("/api/games/{game_id}/events")
def get_events(game_id: str, token: Optional[str] = None, spectator: Optional[str] = None) -> dict:
    """Stable read-only event stream for replay/debug/agent memory.

    This mirrors `ui_state.event_log` but gives agents and tooling a smaller
    endpoint when they only need the chronological event graph.
    """
    game = get_game_or_404(game_id)
    maybe_settle(game_id, game)
    state = _state_for_reader(game, token, spectator)
    return {
        "schema_version": AGENT_API_SCHEMA_VERSION,
        "game_id": game_id,
        "game_type": game_type(game),
        "phase": state.get("phase"),
        "events": _event_log(game_type(game), state),
    }


@router.get("/api/games/{game_id}/action-schema")
def get_action_schema(game_id: str) -> dict:
    """Static action schema for UI builders and agents.

    `/actions` answers what is currently enabled.  This endpoint answers the
    stable operation contract for the room's game type.
    """
    game = get_game_or_404(game_id)
    gt = game_type(game)
    common = {
        "schema_version": AGENT_API_SCHEMA_VERSION,
        "game_id": game_id,
        "game_type": gt,
        "execute_endpoint": f"/api/games/{game_id}/action",
        "state_endpoint": f"/api/games/{game_id}/ui-state",
        "actions_endpoint": f"/api/games/{game_id}/actions",
        "events_endpoint": f"/api/games/{game_id}/events",
    }
    if gt == "texas_holdem":
        common["actions"] = [
            {"id": "fold", "params": {}},
            {"id": "check", "params": {}},
            {"id": "call", "params": {}},
            {"id": "raise", "params": {"amount": "integer target bet_in_round", "min": "integer from /actions", "max": "integer from /actions"}},
            {"id": "all_in", "params": {}},
        ]
    else:
        common["actions"] = [
            {"id": "bid", "params": {"bid": "integer 0..3"}},
            {"id": "play_cards", "params": {"cards": "string[] card codes"}},
            {"id": "pass", "params": {}},
            {"id": "play_hint", "params": {"cards": "string[] suggested by /actions", "pattern": "object", "hint_reason": "string"}, "execute_as": {"action": "play_cards", "cards": "<params.cards>"}},
        ]
    return common


@router.post("/api/games/{game_id}/action")
def generic_action(game_id: str, req: GameActionReq) -> dict:
    """Generic agent handle for game operations.

    Legacy endpoints remain available, but new agents can use this one endpoint
    across games.
    """
    game = get_game_or_404(game_id)
    result = apply_generic_action(game_id, game, req)
    maybe_settle(game_id, game)
    state = _state_for_reader(game, req.token, None)
    return {
        "ok": True,
        "game_id": game_id,
        "game_type": game_type(game),
        "result": result,
        "ui_state": ui_state(game, state, req.token),
    }


@router.post("/api/games/{game_id}/bid")
def bid(game_id: str, req: BidReq) -> dict:
    game = get_game_or_404(game_id)
    require_game_type(game, "doudizhu")
    try:
        game.bid(req.token, req.bid)
    except GameError as exc:
        raise game_error(exc)
    return game.private_state(req.token)


@router.post("/api/games/{game_id}/play")
def play(game_id: str, req: PlayReq) -> dict:
    game = get_game_or_404(game_id)
    require_game_type(game, "doudizhu")
    try:
        result = game.play(req.token, req.cards)
    except GameError as exc:
        raise game_error(exc)
    maybe_settle(game_id, game)
    state = game.private_state(req.token)
    state["result"] = result
    return state


@router.post("/api/games/{game_id}/texas/action")
def texas_action(game_id: str, req: TexasActionReq) -> dict:
    game = get_game_or_404(game_id)
    require_game_type(game, "texas_holdem")
    action = (req.action or "").strip().lower()
    try:
        if action == "fold":
            result = game.fold(req.token)
        elif action == "check":
            result = game.check(req.token)
        elif action == "call":
            result = game.call(req.token)
        elif action == "raise":
            result = game.raise_to(req.token, int(req.amount))
        elif action in ("allin", "all_in", "all-in"):
            result = game.all_in(req.token)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"unknown action {action!r} (expected fold|check|call|raise|allin)",
            )
    except TexasError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    maybe_settle(game_id, game)
    state = game.private_state(req.token)
    state["result"] = result
    return state


@router.post("/api/games/{game_id}/chat")
def chat(game_id: str, req: ChatReq) -> dict:
    game = get_game_or_404(game_id)
    try:
        msg = game.post_chat(req.token, req.text)
    except GameError as exc:
        raise game_error(exc)
    return {"seat": msg.seat, "name": msg.name, "text": msg.text, "timestamp": msg.timestamp}


@router.get("/api/games/{game_id}/chat")
def chat_history(game_id: str, since: float = 0.0, limit: int = 50) -> dict:
    game = get_game_or_404(game_id)
    msgs = game.chat_since(since_ts=since, limit=limit)
    return {
        "messages": [
            {"seat": m.seat, "name": m.name, "text": m.text, "timestamp": m.timestamp}
            for m in msgs
        ]
    }


@router.post("/api/games/{game_id}/disband")
def disband(game_id: str, req: DisbandReq) -> dict:
    game = get_game_or_404(game_id)
    if not game.is_owner(req.token):
        raise HTTPException(status_code=403, detail="forbidden: only the room owner may disband")
    reason = (req.reason or "").strip() or "owner disbanded"
    game.disband(reason)
    with LOCK:
        GAMES.pop(game_id, None)
        release_user_room(game_id)
    return {"ok": True, "game_id": game_id, "reason": game.disbanded_reason, "by": "owner"}


@router.post("/api/games/{game_id}/leave")
def leave_seat(game_id: str, req: LeaveReq, user: CurrentUser = Depends(require_user)) -> dict:
    game = get_game_or_404(game_id)
    try:
        result = game.leave_seat(req.token)
    except GameError as exc:
        raise game_error(exc)
    with LOCK:
        if result.get("disbanded"):
            GAMES.pop(game_id, None)
            release_user_room(game_id)
        else:
            if USER_ROOM.get(user.id) == game_id:
                USER_ROOM.pop(user.id, None)
    return {"ok": True, "game_id": game_id, **result}


@router.post("/api/games/{game_id}/restart")
def restart(game_id: str, req: RestartReq) -> dict:
    game = get_game_or_404(game_id)
    if not game.is_owner(req.token):
        raise HTTPException(status_code=403, detail="forbidden: only the room owner may restart")
    try:
        game.restart()
    except GameError as exc:
        raise game_error(exc)
    return {"ok": True, "game_id": game_id, "phase": game.phase.value}


# ---- admin -----------------------------------------------------------------


@router.get("/api/admin/games")
def admin_list_games(_admin: CurrentUser = Depends(require_admin)) -> dict:
    """Admin: list every in-memory room (including disbanded/finished)."""
    now = time.time()
    items = []
    for game in GAMES.values():
        age = now - getattr(game, "last_active", game.created_at)
        owner = None
        if 0 <= game.owner_seat < len(game.players) and game.players[game.owner_seat]:
            owner = game.players[game.owner_seat].name
        items.append({
            "game_id": game.game_id,
            "name": game.name,
            "description": game.description,
            "phase": game.phase.value,
            "rule_mode": game.rule_mode,
            "game_type": game_type(game),
            "players": [p.name if p else None for p in game.players],
            "owner_seat": game.owner_seat,
            "owner_name": owner,
            "disbanded": game.disbanded,
            "disbanded_reason": game.disbanded_reason,
            "created_at": game.created_at,
            "last_active": getattr(game, "last_active", game.created_at),
            "idle_seconds": round(age, 1),
        })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return {"games": items, "total": len(items)}


@router.delete("/api/admin/games/{game_id}")
def admin_delete_game(game_id: str, _admin: CurrentUser = Depends(require_admin)) -> dict:
    """Admin: force-disband and remove a room regardless of phase/owner."""
    with LOCK:
        game = GAMES.get(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        try:
            game.disband("admin removed")
        except Exception:
            pass
        GAMES.pop(game_id, None)
        release_user_room(game_id)
    print(f"[ADMIN] room {game_id} force-removed", flush=True)
    return {"ok": True, "game_id": game_id, "removed": True}
