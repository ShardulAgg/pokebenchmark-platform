"""HTTP + WebSocket routes for popout VBA-like play sessions."""
import asyncio
import logging
from time import perf_counter

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from pokebenchmark_platform.orchestrator.play.keymap import GBA_KEYS, bit
from pokebenchmark_platform.orchestrator.play.loop import run_play_loop
from pokebenchmark_platform.orchestrator.play.session import PlaySession

log = logging.getLogger(__name__)
router = APIRouter()


def _play_sessions(request_or_ws) -> dict:
    app = request_or_ws.app
    if not hasattr(app.state, "play_sessions"):
        app.state.play_sessions = {}
    return app.state.play_sessions


def _manual_sessions(request_or_ws) -> dict:
    app = request_or_ws.app
    if not hasattr(app.state, "manual_sessions"):
        app.state.manual_sessions = {}
    return app.state.manual_sessions


@router.post("/{run_id}/start")
async def start_play(run_id: str, request: Request):
    manual = _manual_sessions(request).get(run_id)
    if manual is None:
        raise HTTPException(status_code=404, detail="no active manual session for this run")

    sessions = _play_sessions(request)
    if run_id in sessions:
        raise HTTPException(status_code=409, detail="play session already active")

    session = PlaySession(run_id=run_id, emulator=manual["emulator"])
    session.loop_task = asyncio.create_task(run_play_loop(session))
    sessions[run_id] = session
    return {"run_id": run_id}


@router.post("/{run_id}/stop")
async def stop_play(run_id: str, request: Request):
    sessions = _play_sessions(request)
    session = sessions.pop(run_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail="no play session")

    if session.loop_task is not None:
        session.loop_task.cancel()
        try:
            await session.loop_task
        except (asyncio.CancelledError, Exception):
            pass

    for ws in list(session.clients):
        try:
            await ws.close()
        except Exception:
            pass
    session.clients.clear()

    return {"frames": session.frame_counter}


@router.websocket("/{run_id}/ws")
async def play_ws(websocket: WebSocket, run_id: str):
    sessions = _play_sessions(websocket)
    session = sessions.get(run_id)
    if session is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    session.clients.add(websocket)
    session.last_client_disconnect_at = None

    try:
        while True:
            msg = await websocket.receive_json()
            t = msg.get("t")
            if t == "down":
                k = msg.get("k")
                if k in GBA_KEYS:
                    session.held_keys |= bit(k)
            elif t == "up":
                k = msg.get("k")
                if k in GBA_KEYS:
                    session.held_keys &= ~bit(k)
            elif t == "reset_keys":
                session.held_keys = 0
            else:
                log.debug("play: unknown ws msg type %r", t)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("play: ws handler error for run %s", run_id)
    finally:
        session.clients.discard(websocket)
        if not session.clients:
            session.last_client_disconnect_at = perf_counter()
