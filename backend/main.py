"""FastAPI app for the ai-agent-playground.

Currently serves a single Dou Dizhu lobby.
"""

from __future__ import annotations

import os
import secrets
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
from .auth.deps import CurrentUser, require_user
from .auth.routes import admin_router as auth_admin_router
from .auth.routes import router as auth_router
from .doudizhu.game import Game, GameError


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



# ---- request / response models -------------------------------------------


class CreateGameReq(BaseModel):
    rule_mode: str = Field(default="builtin", description="builtin or referee")
    referee_url: Optional[str] = None
    seed: Optional[int] = None


class CreateGameResp(BaseModel):
    game_id: str
    rule_mode: str


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


def _get_game(game_id: str) -> Game:
    g = GAMES.get(game_id)
    if g is None:
        raise HTTPException(status_code=404, detail="game not found")
    return g


def _err(e: GameError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


# ---- API ------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "games": len(GAMES)}


@app.post("/api/games", response_model=CreateGameResp)
def create_game(req: CreateGameReq, user: CurrentUser = Depends(require_user)) -> CreateGameResp:
    game_id = secrets.token_hex(4)
    try:
        game = Game(
            game_id=game_id,
            rule_mode=req.rule_mode,
            referee_url=req.referee_url,
            seed=req.seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    GAMES[game_id] = game
    # Print spectator token to server log only (never exposed via any API).
    # Operator can read it with: grep SPECTATOR ~/logs/ai-agent-playground.log
    print(f"[SPECTATOR] game_id={game_id} spectator_token={game.spectator_token}", flush=True)
    return CreateGameResp(game_id=game_id, rule_mode=game.rule_mode)


@app.get("/api/games")
def list_games() -> dict:
    return {
        "games": [
            {
                "game_id": g.game_id,
                "phase": g.phase.value,
                "rule_mode": g.rule_mode,
                "players": [p.name if p else None for p in g.players],
            }
            for g in GAMES.values()
        ]
    }


@app.post("/api/games/{game_id}/join", response_model=JoinResp)
def join(game_id: str, req: JoinReq, user: CurrentUser = Depends(require_user)) -> JoinResp:
    game = _get_game(game_id)
    try:
        p = game.add_player(req.player_name, req.bio)
    except GameError as e:
        raise _err(e)
    return JoinResp(player_id=p.player_id, seat=p.seat, token=p.token)


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
    try:
        game.bid(req.token, req.bid)
    except GameError as e:
        raise _err(e)
    return game.private_state(req.token)


@app.post("/api/games/{game_id}/play")
def play(game_id: str, req: PlayReq) -> dict:
    game = _get_game(game_id)
    try:
        result = game.play(req.token, req.cards)
    except GameError as e:
        raise _err(e)
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
    GAMES.pop(game_id, None)
    return {"ok": True, "game_id": game_id, "reason": game.disbanded_reason, "by": "owner"}


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
