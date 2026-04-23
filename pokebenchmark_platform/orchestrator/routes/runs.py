"""Routes for managing benchmark runs (both AI-driven and manual)."""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from pokebenchmark_emulator.adapters.emerald import EmeraldAdapter
from pokebenchmark_emulator.adapters.firered import FireRedAdapter
from pokebenchmark_platform.catalog.models import RunEntry, SaveStateEntry
from pokebenchmark_emulator.gba import GBAEmulator
from pokebenchmark_platform.orchestrator.container_manager import ContainerManager
from pokebenchmark_platform.recording.run_recorder import RunRecorder

router = APIRouter()


def _get_container_manager(request: Request) -> ContainerManager:
    if request.app.state.container_manager is None:
        request.app.state.container_manager = ContainerManager(
            image_name=request.app.state.container_image
        )
    return request.app.state.container_manager


def _manual_sessions(request: Request) -> dict:
    if not hasattr(request.app.state, "manual_sessions"):
        request.app.state.manual_sessions = {}
    return request.app.state.manual_sessions


def _require_manual_session(request: Request, run_id: str) -> dict:
    sess = _manual_sessions(request).get(run_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"No manual session for run {run_id}")
    return sess


def _play_sessions(request: Request) -> dict:
    if not hasattr(request.app.state, "play_sessions"):
        request.app.state.play_sessions = {}
    return request.app.state.play_sessions


def _raise_if_play_active(request: Request, run_id: str) -> None:
    if run_id in _play_sessions(request):
        raise HTTPException(status_code=409, detail="play session active")


def _adapter_for(game: str):
    if game == "emerald":
        return EmeraldAdapter()
    if game == "firered":
        return FireRedAdapter()
    raise HTTPException(status_code=400, detail=f"Unsupported game: {game}")


class CreateRunRequest(BaseModel):
    game: str
    model_provider: str
    model_name: Optional[str] = None
    input_mode: Optional[str] = None
    skill_files: list[str] = []
    save_state_id: Optional[str] = None
    rom_path: str
    api_key: Optional[str] = None
    orchestrator_url: Optional[str] = None
    extra_env: Optional[dict[str, str]] = None
    steps: Optional[int] = None


class PressRequest(BaseModel):
    button: str
    frames: int = 2


class WaitRequest(BaseModel):
    frames: int


class SaveRunStateRequest(BaseModel):
    label: str
    curated: bool = True


class LoadStateRequest(BaseModel):
    state_id: str


@router.post("/")
async def create_run(body: CreateRunRequest, request: Request) -> dict:
    db = request.app.state.db
    run_id = str(uuid.uuid4())

    if body.model_provider == "manual":
        if not os.path.isfile(body.rom_path):
            raise HTTPException(status_code=400, detail=f"ROM not found: {body.rom_path}")
        emulator = GBAEmulator(rom_path=body.rom_path)
        adapter = _adapter_for(body.game)

        if body.save_state_id:
            entry = await db.get_save_state(body.save_state_id)
            if entry is None:
                raise HTTPException(status_code=404, detail="Save state not found")
            emulator.load_state_from_file(entry.file_path)

        recorder = RunRecorder(emulator, run_id)
        recorder.start()
        _manual_sessions(request)[run_id] = {
            "emulator": emulator,
            "adapter": adapter,
            "game": body.game,
            "rom_path": body.rom_path,
            "recorder": recorder,
        }

        entry = RunEntry(
            id=run_id,
            game=body.game,
            model_provider="manual",
            model_name="human",
            input_mode="manual",
            skill_files=body.skill_files,
            save_state_id=body.save_state_id,
            status="running",
            started_at=datetime.now(timezone.utc),
            container_id=None,
        )
        await db.add_run(entry)
        return {"run_id": run_id, "container_id": None, "status": "running", "type": "manual"}

    # Agent-driven run
    if not body.model_name:
        raise HTTPException(status_code=400, detail="model_name required for agent runs")
    if not body.input_mode:
        raise HTTPException(status_code=400, detail="input_mode required for agent runs")

    cm = _get_container_manager(request)
    container_id = cm.launch_session(
        run_id=run_id,
        game=body.game,
        rom_path=body.rom_path,
        model_provider=body.model_provider,
        model_name=body.model_name,
        api_key=body.api_key,
        input_mode=body.input_mode,
        save_state_path=None,
        orchestrator_url=body.orchestrator_url,
        extra_env=body.extra_env,
    )

    entry = RunEntry(
        id=run_id,
        game=body.game,
        model_provider=body.model_provider,
        model_name=body.model_name,
        input_mode=body.input_mode,
        skill_files=body.skill_files,
        save_state_id=body.save_state_id,
        status="running",
        started_at=datetime.now(timezone.utc),
        container_id=container_id,
    )
    await db.add_run(entry)

    return {"run_id": run_id, "container_id": container_id, "status": "running", "type": "agent"}


@router.get("/")
async def list_runs(
    request: Request,
    game: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    db = request.app.state.db
    runs = await db.list_runs(game=game, status=status)
    return [r.to_dict() for r in runs]


@router.get("/{run_id}")
async def get_run(run_id: str, request: Request) -> dict:
    db = request.app.state.db
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()


@router.post("/{run_id}/stop")
async def stop_run(run_id: str, request: Request) -> dict:
    db = request.app.state.db
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    sessions = _manual_sessions(request)
    if run_id in sessions:
        sess = sessions[run_id]
        recorder = sess.get("recorder")
        if recorder is not None:
            await recorder.stop()
        sess["emulator"].reset()
        del sessions[run_id]
    elif run.container_id:
        cm = _get_container_manager(request)
        cm.stop_session(run.container_id)

    await db.update_run(run_id, status="stopped", finished_at=datetime.now(timezone.utc))
    return {"run_id": run_id, "status": "stopped"}


# --- Manual control endpoints (only valid for manual runs) ---

@router.post("/{run_id}/press")
async def press_button(run_id: str, body: PressRequest, request: Request) -> dict:
    _raise_if_play_active(request, run_id)
    sess = _require_manual_session(request, run_id)
    sess["emulator"].press_button(body.button, frames=body.frames)
    return {"pressed": body.button, "frames": body.frames}


@router.post("/{run_id}/wait")
async def wait_frames(run_id: str, body: WaitRequest, request: Request) -> dict:
    _raise_if_play_active(request, run_id)
    sess = _require_manual_session(request, run_id)
    sess["emulator"].wait(body.frames)
    return {"waited": body.frames}


@router.get("/{run_id}/frame")
async def get_frame(run_id: str, request: Request) -> Response:
    sess = _require_manual_session(request, run_id)
    img = sess["emulator"].screenshot()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/{run_id}/state")
async def get_state(run_id: str, request: Request) -> dict:
    sess = _require_manual_session(request, run_id)
    gs = sess["adapter"].read_state(sess["emulator"])
    return {
        "text": gs.to_text(),
        "x": gs.x,
        "y": gs.y,
        "location": gs.location,
        "badges": gs.badges,
        "money": gs.money,
        "party": gs.party,
    }


@router.post("/{run_id}/save-state")
async def save_run_state(run_id: str, body: SaveRunStateRequest, request: Request) -> dict:
    sess = _require_manual_session(request, run_id)
    db = request.app.state.db

    state_id = f"ss_{uuid.uuid4().hex[:12]}"
    saves_dir = os.environ.get("SAVES_DIR", "./saves")
    os.makedirs(saves_dir, exist_ok=True)
    file_path = os.path.join(saves_dir, f"{state_id}.state")
    sess["emulator"].save_state_to_file(file_path)

    gs = sess["adapter"].read_state(sess["emulator"])

    entry = SaveStateEntry(
        id=state_id,
        file_path=file_path,
        game=sess["game"],
        curated=body.curated,
        timestamp=datetime.now(timezone.utc),
        label=body.label,
        run_id=run_id,
        badges=len(gs.badges) if gs.badges is not None else 0,
        location=gs.location,
        party_levels=",".join(str(p.get("level", 0)) for p in (gs.party or [])),
    )
    await db.add_save_state(entry)
    return entry.to_dict()


@router.post("/{run_id}/load-state")
async def load_run_state(run_id: str, body: LoadStateRequest, request: Request) -> dict:
    sess = _require_manual_session(request, run_id)
    db = request.app.state.db

    entry = await db.get_save_state(body.state_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Save state not found")
    if entry.game != sess["game"]:
        raise HTTPException(status_code=400, detail=f"Save state is for {entry.game}, session is {sess['game']}")

    sess["emulator"].load_state_from_file(entry.file_path)
    return {"loaded": body.state_id, "label": entry.label}
