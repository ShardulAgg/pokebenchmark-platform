"""FastAPI orchestrator application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pokebenchmark_platform.catalog.db import CatalogDB

log = logging.getLogger(__name__)
from pokebenchmark_platform.orchestrator.container_manager import ContainerManager
from pokebenchmark_platform.orchestrator.routes import catalog, games, play, recordings, runs, skills, ws


def create_app(
    db_path: str = "data/catalog.db",
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

        # Reconcile: any manual run left in 'running'/'pending' from a prior
        # boot is a phantom now — its in-memory emulator and RunRecorder are
        # gone. Mark them stopped so the UI doesn't show them as live.
        now = datetime.now(timezone.utc)
        stale_count = 0
        for status in ("running", "pending"):
            for run in await db.list_runs(status=status):
                if run.model_provider == "manual":
                    await db.update_run(run.id, status="stopped", finished_at=now)
                    stale_count += 1
        if stale_count:
            log.info("startup: reconciled %d stale manual run(s) to stopped", stale_count)

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
    app.include_router(play.ws_router, prefix="/ws/play", tags=["play-ws"])
    app.include_router(recordings.router, prefix="/api/runs", tags=["recordings"])
    app.include_router(recordings.files_router, prefix="/api/recordings", tags=["recordings"])

    @app.get("/api/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok"}

    return app


# Default application instance
app = create_app()
