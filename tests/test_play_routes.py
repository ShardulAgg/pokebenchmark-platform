import asyncio
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from pokebenchmark_platform.orchestrator.routes.play import router as play_router, ws_router as play_ws_router
from pokebenchmark_platform.orchestrator.play.session import PlaySession


def build_app_with_manual(run_id: str | None = "r-1"):
    """Build a minimal FastAPI app with the play router mounted and a
    fake manual session containing a mocked emulator."""
    app = FastAPI()
    app.state.manual_sessions = {}
    app.state.play_sessions = {}

    if run_id is not None:
        emu = MagicMock()
        emu.framebuffer_image.return_value = Image.new("RGB", (240, 160))
        app.state.manual_sessions[run_id] = {"emulator": emu}

    app.include_router(play_router, prefix="/api/play")
    app.include_router(play_ws_router, prefix="/ws/play")
    return app


def test_start_returns_404_when_no_manual_session():
    app = build_app_with_manual(run_id=None)
    with TestClient(app) as c:
        r = c.post("/api/play/missing/start")
        assert r.status_code == 404


def test_start_creates_session_and_returns_200():
    app = build_app_with_manual()
    with TestClient(app) as c:
        r = c.post("/api/play/r-1/start")
        assert r.status_code == 200
        assert "r-1" in app.state.play_sessions
        # Clean up (cancel the loop task) before teardown
        session = app.state.play_sessions["r-1"]
        if session.loop_task is not None:
            session.loop_task.cancel()


def test_start_twice_is_idempotent():
    """Duplicate start returns 200 and reuses the existing session — defangs
    React StrictMode double-mount in dev. WS is the source of truth for who
    can observe the session."""
    app = build_app_with_manual()
    with TestClient(app) as c:
        r1 = c.post("/api/play/r-1/start")
        assert r1.status_code == 200
        session_before = app.state.play_sessions["r-1"]

        r2 = c.post("/api/play/r-1/start")
        assert r2.status_code == 200
        assert r2.json().get("reused") is True
        assert app.state.play_sessions["r-1"] is session_before  # same object

        # Clean up
        if session_before.loop_task is not None:
            session_before.loop_task.cancel()


def test_stop_returns_404_when_no_session():
    app = build_app_with_manual()
    with TestClient(app) as c:
        r = c.post("/api/play/r-1/stop")
        assert r.status_code == 404


def test_stop_cancels_loop_and_removes_session():
    app = build_app_with_manual()
    with TestClient(app) as c:
        c.post("/api/play/r-1/start")
        r = c.post("/api/play/r-1/stop")
        assert r.status_code == 200
        body = r.json()
        assert "frames" in body
        assert "r-1" not in app.state.play_sessions


def test_ws_rejects_when_no_session():
    from starlette.websockets import WebSocketDisconnect
    app = build_app_with_manual()
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/play/r-1"):
                pass


def test_ws_keydown_sets_bit_and_keyup_clears():
    """Pre-seed a session without a live loop task, then test WS key handling."""
    app = build_app_with_manual()
    emu = app.state.manual_sessions["r-1"]["emulator"]
    session = PlaySession(run_id="r-1", emulator=emu)
    app.state.play_sessions["r-1"] = session

    with TestClient(app) as c:
        with c.websocket_connect("/ws/play/r-1") as ws:
            # reset_keys first so Right is pressed after the reset
            ws.send_json({"t": "reset_keys"})
            # Round-trip by sending a 2nd msg; server processes in order
            ws.send_json({"t": "down", "k": "Right"})
            ws.send_json({"t": "down", "k": "A"})
            ws.send_json({"t": "up", "k": "A"})
            # Close cleanly; server finally-block drains above before disconnect
        # Post-close: held_keys should reflect only the "Right" down (never released)
        assert session.held_keys & (1 << 4) != 0  # Right still held
        assert session.held_keys & (1 << 0) == 0  # A was released


def test_ws_accepts_reset_keys():
    app = build_app_with_manual()
    emu = app.state.manual_sessions["r-1"]["emulator"]
    session = PlaySession(run_id="r-1", emulator=emu)
    session.held_keys = (1 << 4) | (1 << 0)
    app.state.play_sessions["r-1"] = session

    with TestClient(app) as c:
        with c.websocket_connect("/ws/play/r-1") as ws:
            ws.send_json({"t": "reset_keys"})
        assert session.held_keys == 0


def test_ws_ignores_unknown_key():
    app = build_app_with_manual()
    emu = app.state.manual_sessions["r-1"]["emulator"]
    session = PlaySession(run_id="r-1", emulator=emu)
    app.state.play_sessions["r-1"] = session

    with TestClient(app) as c:
        with c.websocket_connect("/ws/play/r-1") as ws:
            ws.send_json({"t": "down", "k": "Turbo"})
        assert session.held_keys == 0


def test_start_evicts_session_when_loop_crashes():
    """If run_play_loop raises, the session should be removed so a re-start works."""
    import asyncio as _asyncio
    app = build_app_with_manual()
    # Make the emulator crash on set_keys, which run_play_loop calls every iteration
    emu = app.state.manual_sessions["r-1"]["emulator"]
    emu.set_keys.side_effect = RuntimeError("emulator exploded")

    with TestClient(app) as c:
        r = c.post("/api/play/r-1/start")
        assert r.status_code == 200

        # Give the loop a chance to crash and the done_callback to run
        import time
        for _ in range(20):
            if "r-1" not in app.state.play_sessions:
                break
            time.sleep(0.05)

        # After the crash, the session should be gone
        assert "r-1" not in app.state.play_sessions

        # And we should be able to start again
        emu.set_keys.side_effect = None  # let the next loop run cleanly
        r2 = c.post("/api/play/r-1/start")
        assert r2.status_code == 200

        # Cleanup
        session = app.state.play_sessions.get("r-1")
        if session is not None and session.loop_task is not None:
            session.loop_task.cancel()
