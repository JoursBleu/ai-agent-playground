"""FastAPI app for the ai-agent-playground.

Currently serves a single Dou Dizhu lobby.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .doudizhu.game import Game, GameError


app = FastAPI(title="ai-agent-playground", version="0.1.0")
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
def create_game(req: CreateGameReq) -> CreateGameResp:
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
def join(game_id: str, req: JoinReq) -> JoinResp:
    game = _get_game(game_id)
    try:
        p = game.add_player(req.player_name)
    except GameError as e:
        raise _err(e)
    return JoinResp(player_id=p.player_id, seat=p.seat, token=p.token)


@app.get("/api/games/{game_id}/state")
def get_state(game_id: str, token: Optional[str] = None) -> dict:
    game = _get_game(game_id)
    if token:
        try:
            return game.private_state(token)
        except GameError as e:
            raise _err(e)
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


# ---- static frontend ------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")
