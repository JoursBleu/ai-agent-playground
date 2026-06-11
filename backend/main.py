"""FastAPI app bootstrap for ai-agent-playground."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .auth import db as auth_db
from .auth.bootstrap import bootstrap_admin
from .auth.routes import admin_router as auth_admin_router
from .auth.routes import router as auth_router
from .background import start_background_workers
from .game_routes import router as game_router
from .social import social_router


_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.environ.get("AAP_DATA_DIR", str(_DEFAULT_DATA_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
auth_db.init_db(DATA_DIR / "users.db")
bootstrap_admin(DATA_DIR)


app = FastAPI(title="ai-agent-playground", version="0.2.0")
app.include_router(auth_router)
app.include_router(auth_admin_router)
app.include_router(social_router)
app.include_router(game_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

start_background_workers()


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


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt() -> str:
    return "\n".join([
        "User-agent: *",
        "Allow: /",
        "Sitemap: https://agent-playground.space/sitemap.xml",
        "",
    ])


@app.get("/sitemap.xml", response_class=PlainTextResponse)
def sitemap_xml() -> str:
    return """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
  <url>
    <loc>https://agent-playground.space/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://agent-playground.space/docs-agent</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://agent-playground.space/api/health</loc>
    <changefreq>daily</changefreq>
    <priority>0.3</priority>
  </url>
  <url>
    <loc>https://agent-playground.space/api/capabilities</loc>
    <changefreq>daily</changefreq>
    <priority>0.6</priority>
  </url>
</urlset>
"""
