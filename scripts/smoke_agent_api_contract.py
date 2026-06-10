#!/usr/bin/env python3
"""Smoke-test the agent-readable game API contract without running FastAPI.

This imports lightweight helpers from backend.game_routes with FastAPI stubbed
when the local dev environment has no dependencies installed. It validates that
state/action descriptors and generic action dispatch stay coherent for agents.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_fastapi_stubs() -> None:
    if "fastapi" in sys.modules:
        return
    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int = 500, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
            return lambda fn: fn

        def delete(self, *args, **kwargs):
            return lambda fn: fn

        def patch(self, *args, **kwargs):
            return lambda fn: fn

    def Depends(dep=None):
        return dep

    def Header(default=None, **_kwargs):
        return default

    class Request:
        pass

    fastapi.APIRouter = APIRouter
    fastapi.Depends = Depends
    fastapi.Header = Header
    fastapi.HTTPException = HTTPException
    fastapi.Request = Request
    sys.modules["fastapi"] = fastapi


def _install_pydantic_stubs() -> None:
    if "pydantic" in sys.modules:
        return
    pydantic = types.ModuleType("pydantic")

    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def dict(self):
            return dict(self.__dict__)

    def Field(default=..., **_kwargs):
        return default

    pydantic.BaseModel = BaseModel
    pydantic.Field = Field
    sys.modules["pydantic"] = pydantic


def _install_auth_stubs() -> None:
    deps = types.ModuleType("backend.auth.deps")

    class CurrentUser:
        id = 0
        username = "smoke"
        is_admin = True

    def require_user():
        return CurrentUser()

    def require_admin():
        return CurrentUser()

    deps.CurrentUser = CurrentUser
    deps.require_user = require_user
    deps.require_admin = require_admin
    sys.modules["backend.auth.deps"] = deps

    db = types.ModuleType("backend.auth.db")
    db.find_user_by_id = lambda _user_id: {"id": 0, "username": "smoke", "display_name": "smoke", "bio": "bot"}
    sys.modules["backend.auth.db"] = db


_install_fastapi_stubs()
_install_pydantic_stubs()
_install_auth_stubs()

from backend.doudizhu.game import Game as DoudizhuGame, Phase as DoudizhuPhase  # noqa: E402
from backend.doudizhu.hints import find_legal_hint  # noqa: E402
from backend.texas_holdem.game import TexasGame  # noqa: E402
from backend.game_routes import (  # noqa: E402
    GameActionReq,
    action_descriptors,
    apply_generic_action,
    game_type,
    generic_action,
    get_action_schema,
    get_events,
    health,
    ui_state,
)
from backend.game_state import GAMES  # noqa: E402


def _join_all_doudizhu(game: DoudizhuGame):
    return [game.add_player(f"ddz-{i}", "bot").token for i in range(3)]


def _join_texas(game: TexasGame, n: int = 3):
    return [game.add_player(f"texas-{i}", "bot").token for i in range(n)]


def test_health_contract() -> None:
    h = health()
    assert h["ok"] is True
    assert isinstance(h["games"], int)
    assert h["version"]["commit"]
    assert h["version"]["source"] in {"env", "git", "unknown"}


def test_doudizhu_hint_helper() -> None:
    lead = find_legal_hint(["5S", "3S", "4H"], must_lead=True)
    assert lead and lead["cards"] == ["3S"]
    assert lead["pattern"]["category"] == "single"

    pair_response = find_legal_hint(
        ["4S", "4H", "5S", "RJ", "BJ"],
        last_play_codes=["3S", "3H"],
        must_lead=False,
    )
    assert pair_response and set(pair_response["cards"]) == {"4S", "4H"}
    assert pair_response["pattern"]["category"] == "pair"

    straight_response = find_legal_hint(
        ["4S", "5H", "6D", "7C", "8S", "9H"],
        last_play_codes=["3S", "4H", "5D", "6C", "7S"],
        must_lead=False,
    )
    assert straight_response and straight_response["pattern"]["category"] == "straight"
    assert len(straight_response["cards"]) == 5

    bomb_response = find_legal_hint(
        ["4S", "4H", "4D", "4C", "7S"],
        last_play_codes=["AS", "AH"],
        must_lead=False,
    )
    assert bomb_response and bomb_response["pattern"]["category"] == "bomb"

    rocket_response = find_legal_hint(
        ["RJ", "BJ"],
        last_play_codes=["AS", "AH"],
        must_lead=False,
    )
    assert rocket_response and rocket_response["pattern"]["category"] == "rocket"


def test_doudizhu_contract() -> None:
    game = DoudizhuGame("ddz-smoke", name="ddz smoke", seed=7)
    tokens = _join_all_doudizhu(game)
    state = game.private_state(tokens[0])
    view = ui_state(game, state, tokens[0])
    assert view["schema_version"]
    assert view["game_type"] == "doudizhu"
    assert "actions" in view and isinstance(view["actions"], list)
    assert "event_log" in view and isinstance(view["event_log"], list)
    assert "table" in view and "seats" in view and "clock" in view
    assert game_type(game) == "doudizhu"
    GAMES[game.game_id] = game
    events = get_events(game.game_id, token=tokens[0])
    assert events["schema_version"] == view["schema_version"]
    assert events["events"] == view["event_log"]
    schema = get_action_schema(game.game_id)
    assert schema["schema_version"] == view["schema_version"]
    schema_ids = {a["id"] for a in schema["actions"]}
    assert "play_hint" in schema_ids
    assert "play_smallest_single" not in schema_ids

    bidder = game.bid_turn
    game.turn_started_at -= game.THINK_SECONDS + 1
    req = GameActionReq(token=tokens[bidder], action="bid", bid=1)
    result = apply_generic_action(game.game_id, game, req)
    assert result["action"] == "bid"

    bidder_state = game.private_state(tokens[game.bid_turn])
    actions = action_descriptors(game, bidder_state, tokens[game.bid_turn])
    assert "bid" in {a["id"] for a in actions}

    # Force a simple playing position and verify the agent-readable hint action.
    game.phase = DoudizhuPhase.PLAYING
    game.current_turn = 0
    game.turn_started_at -= game.THINK_SECONDS + 1
    game.last_play_seat = -1
    game.last_pattern = None
    play_state = game.private_state(tokens[0])
    play_actions = action_descriptors(game, play_state, tokens[0])
    hint = next((a for a in play_actions if a["id"] == "play_hint"), None)
    assert hint and hint["enabled"] and hint["params"].get("cards")
    assert hint["params"].get("pattern", {}).get("category")
    before_count = len(game.players[0].hand)
    hint_response = generic_action(
        game.game_id, GameActionReq(token=tokens[0], action="play_hint")
    )
    assert hint_response["ok"] is True
    assert hint_response["result"]["action"] == "play"
    assert hint_response["ui_state"]["game_type"] == "doudizhu"
    assert "actions" in hint_response["ui_state"]
    assert hint_response["ui_state"]["event_log"]
    assert len(game.players[0].hand) < before_count


def test_texas_contract() -> None:
    game = TexasGame(game_id="texas-smoke", name="texas smoke", seed=11, n_seats=3)
    tokens = _join_texas(game, 3)
    state = game.private_state(tokens[0])
    view = ui_state(game, state, tokens[0])
    assert view["schema_version"]
    assert view["game_type"] == "texas_holdem"
    assert "table" in view and "actions" in view and "seats" in view
    assert "event_log" in view and isinstance(view["event_log"], list)
    assert game_type(game) == "texas_holdem"
    GAMES[game.game_id] = game
    events = get_events(game.game_id, token=tokens[0])
    assert events["schema_version"] == view["schema_version"]
    assert events["events"] == view["event_log"]
    schema = get_action_schema(game.game_id)
    assert schema["schema_version"] == view["schema_version"]
    raise_schema = next(a for a in schema["actions"] if a["id"] == "raise")
    assert {"amount", "min", "max"}.issubset(set(raise_schema["params"].keys()))

    current = game.current_turn
    current_token = tokens[current]
    state = game.private_state(current_token)
    actions = action_descriptors(game, state, current_token)
    ids = {a["id"] for a in actions}
    assert {"fold", "check", "call", "raise", "all_in"}.issubset(ids)

    # Force timer guard open for smoke dispatch.
    game.turn_started_at -= game.THINK_SECONDS + 1
    if state["you"].get("max_raise_to", 0) >= state["you"].get("min_raise_to", 1):
        raise_to = int(state["you"]["min_raise_to"])
        response = generic_action(
            game.game_id, GameActionReq(token=current_token, action="raise", amount=raise_to)
        )
        assert response["ok"] is True
        assert response["result"]["action"] == "raise"
        assert response["ui_state"]["game_type"] == "texas_holdem"
        assert "actions" in response["ui_state"]
        assert response["ui_state"]["event_log"]
    elif state["you"]["can_check"]:
        response = generic_action(
            game.game_id, GameActionReq(token=current_token, action="check")
        )
        assert response["ok"] is True
        assert response["result"]["action"] == "check"
        assert response["ui_state"]["game_type"] == "texas_holdem"
        assert response["ui_state"]["event_log"]
    else:
        response = generic_action(
            game.game_id, GameActionReq(token=current_token, action="call")
        )
        assert response["ok"] is True
        assert response["result"]["action"] in {"call", "check"}
        assert response["ui_state"]["game_type"] == "texas_holdem"
        assert response["ui_state"]["event_log"]


if __name__ == "__main__":
    test_health_contract()
    test_doudizhu_hint_helper()
    test_doudizhu_contract()
    test_texas_contract()
    print("agent API contract smoke: ok")
