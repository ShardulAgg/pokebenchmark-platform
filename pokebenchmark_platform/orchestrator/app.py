"""FastAPI orchestrator application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pokebenchmark_platform.catalog.db import CatalogDB
from pokebenchmark_platform.orchestrator.container_manager import ContainerManager
from pokebenchmark_platform.orchestrator.routes import catalog, games, play, runs, skills, ws


def create_app(
    db_path: str = "catalog.db",
    container_image: str = "pokebenchmark:latest",
) -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        db = CatalogDB(db_path)
        await db.init()
        app.state.db = db
        app.state.container_image = container_image
        app.state.container_manager = None  # Lazy-initialized on first use
        app.state.play_sessions = {}
        yield
        # Shutdown
        await db.close()

    app = FastAPI(title="PokeBenchmark Orchestrator", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
    app.include_router(games.router, prefix="/api/games", tags=["games"])
    app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
    app.include_router(ws.router, prefix="/ws", tags=["websocket"])
    app.include_router(play.router, prefix="/api/play", tags=["play"])

    @app.get("/api/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok"}

    return app


# Default application instance
app = create_app()
