from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from pokebenchmark_platform.orchestrator.routes.runs import router as runs_router
from pokebenchmark_platform.orchestrator.play.session import PlaySession


def build_app():
    app = FastAPI()
    app.state.manual_sessions = {}
    app.state.play_sessions = {}
    app.state.db = MagicMock()

    # Seed a fake manual session for "r-1"
    emu = MagicMock()
    emu.framebuffer_image.return_value = Image.new("RGB", (240, 160))
    adapter = MagicMock()
    app.state.manual_sessions["r-1"] = {"emulator": emu, "adapter": adapter}

    app.include_router(runs_router, prefix="/api/runs")
    return app


def test_press_returns_409_when_play_session_active():
    app = build_app()
    app.state.play_sessions["r-1"] = PlaySession(run_id="r-1", emulator=MagicMock())

    with TestClient(app) as c:
        r = c.post("/api/runs/r-1/press", json={"button": "A", "frames": 2})
        assert r.status_code == 409
        assert r.json()["detail"] == "play session active"


def test_press_returns_200_without_play_session():
    app = build_app()
    with TestClient(app) as c:
        r = c.post("/api/runs/r-1/press", json={"button": "A", "frames": 2})
        assert r.status_code == 200


def test_wait_returns_409_when_play_session_active():
    app = build_app()
    app.state.play_sessions["r-1"] = PlaySession(run_id="r-1", emulator=MagicMock())
    with TestClient(app) as c:
        r = c.post("/api/runs/r-1/wait", json={"frames": 60})
        assert r.status_code == 409
