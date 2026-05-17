"""FastAPI app for the ai-agent-playground.

Currently serves a single Dou Dizhu lobby.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fastapi import Depends

from .auth import db as auth_db
from .auth.bootstrap import bootstrap_admin
from .auth.deps import CurrentUser, require_admin, require_user
from .auth.routes import admin_router as auth_admin_router
from .auth.routes import router as auth_router
from .doudizhu.game import Game, GameError
from .zhajinhua.game import ZjhGame, ZjhError


_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.environ.get("AAP_DATA_DIR", str(_DEFAULT_DATA_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
auth_db.init_db(DATA_DIR / "users.db")
bootstrap_admin(DATA_DIR)


app = FastAPI(title="ai-agent-playground", version="0.2.0")
app.include_router(auth_router)
app.include_router(auth_admin_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


GAMES: Dict[str, Game] = {}
# user_id -> game_id of the single room they're currently associated with
# (set when they create OR join; cleared when that room is disbanded/reaped)
USER_ROOM: Dict[int, str] = {}
_LOCK = threading.Lock()

# Idle reaper: kill rooms that haven't seen any activity for this many seconds.
# WAITING (nobody joined / fewer than 3 seated) rooms are reaped sooner.
IDLE_TIMEOUT_S = int(os.environ.get("AAP_IDLE_TIMEOUT_S", "1800"))   # 30 min
IDLE_TIMEOUT_WAITING_S = int(os.environ.get("AAP_IDLE_TIMEOUT_WAITING_S", "600"))  # 10 min
IDLE_TIMEOUT_FINISHED_S = int(os.environ.get("AAP_IDLE_TIMEOUT_FINISHED_S", "900"))  # 15 min after finish


def _release_user_room(game_id: str) -> None:
    """Clear USER_ROOM entries that point to a given game_id."""
    for uid, gid in list(USER_ROOM.items()):
        if gid == game_id:
            USER_ROOM.pop(uid, None)


def _reap_idle_rooms() -> None:
    now = time.time()
    to_remove: list[str] = []
    for gid, g in list(GAMES.items()):
        age = now - getattr(g, "last_active", g.created_at)
        seated = sum(1 for p in g.players if p is not None)
        if g.disbanded:
            to_remove.append(gid)
            continue
        if g.phase.value == "finished" and age > IDLE_TIMEOUT_FINISHED_S:
            to_remove.append(gid)
            continue
        if g.phase.value == "waiting" and seated < 3 and age > IDLE_TIMEOUT_WAITING_S:
            to_remove.append(gid)
            continue
        if age > IDLE_TIMEOUT_S:
            to_remove.append(gid)
    for gid in to_remove:
        g = GAMES.get(gid)
        if g is None:
            continue
        try:
            g.disband("idle reaper")
        except Exception:
            pass
        GAMES.pop(gid, None)
        _release_user_room(gid)
        print(f"[REAP] room {gid} removed (idle)", flush=True)


def _reaper_loop() -> None:
    while True:
        time.sleep(60)
        try:
            with _LOCK:
                _reap_idle_rooms()
        except Exception as e:
            print(f"[REAP] error: {e}", flush=True)


_reaper_thread = threading.Thread(target=_reaper_loop, daemon=True, name="aap-reaper")
_reaper_thread.start()



# ---- request / response models -------------------------------------------


class CreateGameReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=40, description="room display name (required)")
    description: str = Field(default="", max_length=200, description="optional room description")
    rule_mode: str = Field(default="builtin", description="builtin or referee")
    referee_url: Optional[str] = None
    seed: Optional[int] = None
    game_type: str = Field(default="doudizhu", description="doudizhu | zhajinhua")


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


# ---- helpers --------------------------------------------------------------


def _get_game(game_id: str):
    g = GAMES.get(game_id)
    if g is None:
        raise HTTPException(status_code=404, detail="game not found")
    return g


def _game_type(g) -> str:
    return getattr(g, "game_type", "doudizhu")


def _require_type(g, want: str):
    gt = _game_type(g)
    if gt != want:
        raise HTTPException(status_code=400, detail=f"endpoint only valid for game_type={want} (this room is {gt})")


def _err(e) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


# ---- API ------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "games": len(GAMES)}


@app.post("/api/games", response_model=CreateGameResp)
def create_game(req: CreateGameReq, user: CurrentUser = Depends(require_user)) -> CreateGameResp:
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="房间名不能为空")
    desc = (req.description or "").strip()
    # only builtin referee is enabled for now
    rule_mode = (req.rule_mode or "builtin").strip() or "builtin"
    if rule_mode != "builtin":
        raise HTTPException(status_code=400, detail="referee 规则模式暂未开放")
    game_type = (req.game_type or "doudizhu").strip().lower()
    if game_type not in ("doudizhu", "zhajinhua"):
        raise HTTPException(status_code=400, detail=f"unknown game_type {game_type!r} (expected doudizhu | zhajinhua)")
    game_id = secrets.token_hex(4)
    try:
        if game_type == "zhajinhua":
            game = ZjhGame(
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    with _LOCK:
        existing = USER_ROOM.get(user.id)
        if existing and existing in GAMES:
            raise HTTPException(
                status_code=409,
                detail=f"你已在房间 {existing} 中，请先离开（解散或等待结束）",
            )
        GAMES[game_id] = game
        USER_ROOM[user.id] = game_id
    # Print spectator token to server log only (never exposed via any API).
    # Operator can read it with: grep SPECTATOR ~/logs/ai-agent-playground.log
    print(f"[SPECTATOR] game_id={game_id} game_type={game_type} spectator_token={game.spectator_token}", flush=True)
    return CreateGameResp(game_id=game_id, name=game.name, rule_mode=game.rule_mode, game_type=game_type)


@app.get("/api/games")
def list_games() -> dict:
    now = time.time()
    items = []
    for g in GAMES.values():
        if g.disbanded:
            continue
        if g.phase.value == "finished":
            continue
        age = now - getattr(g, "last_active", g.created_at)
        # hide rooms that have been silent for over 5 min from the public lobby
        if age > 300:
            continue
        items.append({
            "game_id": g.game_id,
            "name": g.name,
            "description": g.description,
            "phase": g.phase.value,
            "rule_mode": g.rule_mode,
            "game_type": _game_type(g),
            "players": [p.name if p else None for p in g.players],
        })
    return {"games": items}


@app.post("/api/games/{game_id}/join", response_model=JoinResp)
def join(game_id: str, req: JoinReq, user: CurrentUser = Depends(require_user)) -> JoinResp:
    game = _get_game(game_id)
    with _LOCK:
        existing = USER_ROOM.get(user.id)
        if existing and existing != game_id and existing in GAMES:
            raise HTTPException(
                status_code=409,
                detail=f"你已在房间 {existing} 中，请先离开",
            )
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
        pl = game.add_player(name, bio)
    except GameError as e:
        raise _err(e)
    with _LOCK:
        USER_ROOM[user.id] = game_id
    return JoinResp(player_id=pl.player_id, seat=pl.seat, token=pl.token)


@app.get("/api/games/{game_id}/state")
def get_state(
    game_id: str,
    token: Optional[str] = None,
    spectator: Optional[str] = None,
) -> dict:
    game = _get_game(game_id)
    if token:
        try:
            return game.private_state(token)
        except GameError as e:
            raise _err(e)
    if spectator and game.is_spectator_token(spectator):
        return game.omniscient_state()
    return game.public_state()


@app.post("/api/games/{game_id}/bid")
def bid(game_id: str, req: BidReq) -> dict:
    game = _get_game(game_id)
    _require_type(game, "doudizhu")
    try:
        game.bid(req.token, req.bid)
    except GameError as e:
        raise _err(e)
    return game.private_state(req.token)


@app.post("/api/games/{game_id}/play")
def play(game_id: str, req: PlayReq) -> dict:
    game = _get_game(game_id)
    _require_type(game, "doudizhu")
    try:
        result = game.play(req.token, req.cards)
    except GameError as e:
        raise _err(e)
    state = game.private_state(req.token)
    state["result"] = result
    return state


# ---- zhajinhua-specific endpoint ------------------------------------------


class ZjhActionReq(BaseModel):
    token: str
    action: str                          # look | call | raise | fold | compare
    amount: int = 0                      # for raise: new stake
    target_seat: int = -1                # for compare: target seat index


@app.post("/api/games/{game_id}/zjh/action")
def zjh_action(game_id: str, req: ZjhActionReq) -> dict:
    game = _get_game(game_id)
    _require_type(game, "zhajinhua")
    a = (req.action or "").strip().lower()
    try:
        if a == "look":
            result = game.look(req.token)
        elif a == "call":
            result = game.call(req.token)
        elif a == "raise":
            result = game.raise_bet(req.token, int(req.amount))
        elif a == "fold":
            result = game.fold(req.token)
        elif a == "compare":
            result = game.compare(req.token, int(req.target_seat))
        else:
            raise HTTPException(status_code=400, detail=f"unknown action {a!r} (expected look|call|raise|fold|compare)")
    except ZjhError as e:
        raise HTTPException(status_code=400, detail=str(e))
    state = game.private_state(req.token)
    state["result"] = result
    return state


@app.post("/api/games/{game_id}/chat")
def chat(game_id: str, req: ChatReq) -> dict:
    game = _get_game(game_id)
    try:
        msg = game.post_chat(req.token, req.text)
    except GameError as e:
        raise _err(e)
    return {
        "seat": msg.seat,
        "name": msg.name,
        "text": msg.text,
        "timestamp": msg.timestamp,
    }


@app.get("/api/games/{game_id}/chat")
def chat_history(game_id: str, since: float = 0.0, limit: int = 50) -> dict:
    game = _get_game(game_id)
    msgs = game.chat_since(since_ts=since, limit=limit)
    return {
        "messages": [
            {"seat": m.seat, "name": m.name, "text": m.text, "timestamp": m.timestamp}
            for m in msgs
        ]
    }


@app.post("/api/games/{game_id}/disband")
def disband(game_id: str, req: DisbandReq) -> dict:
    game = _get_game(game_id)
    if not game.is_owner(req.token):
        raise HTTPException(status_code=403, detail="forbidden: only the room owner may disband")
    reason = (req.reason or "").strip() or "owner disbanded"
    game.disband(reason)
    with _LOCK:
        GAMES.pop(game_id, None)
        _release_user_room(game_id)
    return {"ok": True, "game_id": game_id, "reason": game.disbanded_reason, "by": "owner"}


class LeaveReq(BaseModel):
    token: str


@app.post("/api/games/{game_id}/leave")
def leave_seat(game_id: str, req: LeaveReq, user: CurrentUser = Depends(require_user)) -> dict:
    game = _get_game(game_id)
    try:
        result = game.leave_seat(req.token)
    except GameError as e:
        raise _err(e)
    with _LOCK:
        if result.get("disbanded"):
            GAMES.pop(game_id, None)
            _release_user_room(game_id)
        else:
            if USER_ROOM.get(user.id) == game_id:
                USER_ROOM.pop(user.id, None)
    return {"ok": True, "game_id": game_id, **result}


class RestartReq(BaseModel):
    token: str


@app.post("/api/games/{game_id}/restart")
def restart(game_id: str, req: RestartReq) -> dict:
    game = _get_game(game_id)
    if not game.is_owner(req.token):
        raise HTTPException(status_code=403, detail="forbidden: only the room owner may restart")
    try:
        game.restart()
    except GameError as e:
        raise _err(e)
    return {"ok": True, "game_id": game_id, "phase": game.phase.value}


# ---- admin -----------------------------------------------------------------


@app.get("/api/admin/games")
def admin_list_games(_admin: CurrentUser = Depends(require_admin)) -> dict:
    """Admin: list every in-memory room (including disbanded/finished)."""
    now = time.time()
    items = []
    for g in GAMES.values():
        age = now - getattr(g, "last_active", g.created_at)
        items.append({
            "game_id": g.game_id,
            "name": g.name,
            "description": g.description,
            "phase": g.phase.value,
            "rule_mode": g.rule_mode,
            "players": [p.name if p else None for p in g.players],
            "owner_seat": g.owner_seat,
            "owner_name": (g.players[g.owner_seat].name
                           if 0 <= g.owner_seat < 3 and g.players[g.owner_seat] else None),
            "disbanded": g.disbanded,
            "disbanded_reason": g.disbanded_reason,
            "created_at": g.created_at,
            "last_active": getattr(g, "last_active", g.created_at),
            "idle_seconds": round(age, 1),
        })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return {"games": items, "total": len(items)}


@app.delete("/api/admin/games/{game_id}")
def admin_delete_game(game_id: str, _admin: CurrentUser = Depends(require_admin)) -> dict:
    """Admin: force-disband and remove a room regardless of phase/owner."""
    with _LOCK:
        g = GAMES.get(game_id)
        if g is None:
            raise HTTPException(status_code=404, detail="game not found")
        try:
            g.disband("admin removed")
        except Exception:
            pass
        GAMES.pop(game_id, None)
        _release_user_room(game_id)
    print(f"[ADMIN] room {game_id} force-removed", flush=True)
    return {"ok": True, "game_id": game_id, "removed": True}


# ---- static frontend ------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"
_DOCS_DIR = Path(__file__).parent.parent / "docs"
_AGENT_DOC = _DOCS_DIR / "AGENT_API.md"

if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/r/{game_id}")
    def room_page(game_id: str) -> FileResponse:
        # SPA route: same index.html, frontend reads game id from URL.
        return FileResponse(_STATIC_DIR / "index.html")


@app.get("/docs-agent", response_class=PlainTextResponse)
def agent_docs_raw() -> str:
    """Raw markdown agent API doc.  Optimised for LLM agents to fetch."""
    if not _AGENT_DOC.exists():
        raise HTTPException(status_code=404, detail="agent doc not found")
    return _AGENT_DOC.read_text(encoding="utf-8")
