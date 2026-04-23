"""Recordings: list files per run + serve mp4 with Range support."""
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

RECORDINGS_ROOT = Path("data/recordings")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.mp4$")


router = APIRouter()


@router.get("/{run_id}/recordings")
async def list_run_recordings(run_id: str):
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(400, "invalid run_id")
    run_dir = RECORDINGS_ROOT / run_id
    if not run_dir.is_dir():
        return {"recordings": []}
    entries = []
    for p in sorted(run_dir.glob("*.mp4")):
        st = p.stat()
        entries.append({
            "run_id": run_id,
            "filename": p.name,
            "url": f"/api/recordings/{run_id}/{p.name}",
            "size_bytes": st.st_size,
            "mtime": st.st_mtime,
        })
    return {"recordings": entries}


files_router = APIRouter()


@files_router.get("/{run_id}/{filename}")
async def get_recording(run_id: str, filename: str):
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(400, "invalid run_id")
    if not FILENAME_RE.match(filename):
        raise HTTPException(400, "invalid filename")
    path = RECORDINGS_ROOT / run_id / filename
    if not path.is_file():
        raise HTTPException(404, "recording not found")
    return FileResponse(path, media_type="video/mp4")
