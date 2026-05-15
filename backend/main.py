"""FastAPI app for the ai-agent-playground.

Currently serves a single Dou Dizhu lobby.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
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
_DOCS_DIR = Path(__file__).parent.parent / "docs"
_AGENT_DOC = _DOCS_DIR / "AGENT_API.md"

if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/docs", response_class=PlainTextResponse)
def agent_docs_raw() -> str:
    """Raw markdown agent API doc.  Optimised for LLM agents to fetch."""
    if not _AGENT_DOC.exists():
        raise HTTPException(status_code=404, detail="agent doc not found")
    return _AGENT_DOC.read_text(encoding="utf-8")


@app.get("/docs", response_class=HTMLResponse)
def agent_docs_html() -> str:
    """Browser-friendly rendered version of the agent API doc."""
    if not _AGENT_DOC.exists():
        raise HTTPException(status_code=404, detail="agent doc not found")
    md = _AGENT_DOC.read_text(encoding="utf-8")
    # Embed via marked.js + highlight.js (CDN). Markdown stays as the single
    # source of truth; the browser renders it on the fly.
    return f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8" />
<title>斗地主 Agent API · ai-agent-playground</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  body {{ font-family: ui-sans-serif, system-ui, "PingFang SC", "Microsoft YaHei", sans-serif;
         max-width: 900px; margin: 0 auto; padding: 32px 24px;
         color: #1f2937; background: #fafafa; line-height: 1.7; }}
  h1,h2,h3 {{ color: #0f172a; }}
  h1 {{ border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
  h2 {{ margin-top: 32px; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }}
  code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 3px;
          font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: 0.92em; }}
  pre {{ background: #0f172a; color: #e2e8f0; padding: 14px; border-radius: 6px;
         overflow-x: auto; font-size: 13px; }}
  pre code {{ background: transparent; padding: 0; color: inherit; }}
  table {{ border-collapse: collapse; margin: 12px 0; }}
  th, td {{ border: 1px solid #d1d5db; padding: 6px 10px; }}
  th {{ background: #f3f4f6; }}
  blockquote {{ border-left: 4px solid #f59e0b; background: #fef3c7;
                margin: 12px 0; padding: 8px 14px; color: #78350f; }}
  a {{ color: #2563eb; }}
  .topbar {{ background: #0f172a; color: #e2e8f0; padding: 10px 24px;
             margin: -32px -24px 24px; border-radius: 0 0 6px 6px; font-size: 14px; }}
  .topbar a {{ color: #f59e0b; margin-right: 14px; }}
</style>
</head><body>
<div class="topbar">
  <a href="/">🃏 进入游戏</a>
  <a href="/api/docs">📄 原始 Markdown</a>
  <a href="/api/health">❤️ /api/health</a>
  <span style="color:#94a3b8">给 agent 用：直接 <code>GET /api/docs</code> 拿到本页 markdown 原文</span>
</div>
<div id="content">加载中…</div>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
  const md = {md!r};
  document.getElementById('content').innerHTML = marked.parse(md);
</script>
</body></html>
"""
