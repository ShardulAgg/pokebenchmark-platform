"""Per-run play session state."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlaySession:
    run_id: str
    emulator: Any  # GBAEmulator — typed loosely to avoid a hard import cycle
    adapter: Any = None  # GameAdapter; None disables state broadcasts
    held_keys: int = 0
    speed: int = 1  # emulator frames advanced per broadcast tick (VBA-style fast-forward)
    clients: set = field(default_factory=set)
    loop_task: "asyncio.Task | None" = None
    frame_counter: int = 0
    last_client_disconnect_at: float | None = None
    recorder: Any = None            # VideoRecorder writing to recording_path
    recording_path: str | None = None
