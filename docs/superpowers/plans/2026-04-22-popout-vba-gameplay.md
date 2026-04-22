# Popout VBA-like Gameplay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated popup window that plays a manual run at ~60 FPS with hold-to-move keyboard input, fully separate from the existing fixed-tap `ManualControls` flow.

**Architecture:** A new `play/` module in the orchestrator runs one asyncio task per manual run that advances the emulator at 60 Hz, reads a thread-safe held-keys bitmask updated over WebSocket, and fans JPEG-encoded frames out to all connected viewers. The frontend opens an OS-level popup via `window.open` that mounts a full-bleed canvas and captures `keydown`/`keyup` events.

**Tech Stack:** FastAPI + Starlette WebSockets + Pillow (backend), React 18 + TypeScript + plain `<canvas>` + `createImageBitmap` (frontend).

**Repos:**
- `pokebenchmark-emulator` — add thin accessor methods to `GBAEmulator`
- `pokebenchmark-platform` — the play module, routes, conflict check
- `pokebenchmark-dashboard` — API client, PlayCanvas, Play page, entry button

**Spec:** `docs/superpowers/specs/2026-04-22-popout-vba-gameplay-design.md` (in pokebenchmark-platform).

---

## Task 1: Add held-key / frame-advance accessors to `GBAEmulator`

**Repo:** `pokebenchmark-emulator`

**Files:**
- Modify: `pokebenchmark_emulator/gba.py`
- Test: `tests/test_emulator.py` (append new test class)

**Why:** The play loop must set a held-key bitmask, advance exactly one frame, and read the framebuffer without advancing. The current `press_button` is tap-only and `screenshot` couples a frame advance with image capture. Three thin accessors remove the need to reach into `emulator.gba.core` from the platform layer.

- [ ] **Step 1.1: Write failing tests**

Append to `/home/convo2/projects/pokebenchmark-emulator/tests/test_emulator.py`:

```python
class TestHeldKeyAccessors:
    def test_set_keys_passes_bitmask_through(self):
        emu = make_emulator()
        emu.set_keys(0b0101010101)
        emu.gba.core.set_keys.assert_called_once_with(0b0101010101)

    def test_set_keys_accepts_zero(self):
        emu = make_emulator()
        emu.set_keys(0)
        emu.gba.core.set_keys.assert_called_once_with(0)

    def test_run_frame_advances_one_frame(self):
        emu = make_emulator()
        emu.run_frame()
        emu.gba.core.run_frame.assert_called_once_with()

    def test_framebuffer_image_returns_pil_without_advancing(self):
        emu = make_emulator()
        img = emu.framebuffer_image()
        emu.gba.core.run_frame.assert_not_called()
        assert img.size == (240, 160)
        assert img.mode == "RGB"
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /home/convo2/projects/pokebenchmark-emulator
pytest tests/test_emulator.py::TestHeldKeyAccessors -v
```

Expected: 4 FAILED with `AttributeError: 'GBAEmulator' object has no attribute 'set_keys'` (or similar for the other methods).

- [ ] **Step 1.3: Implement the three accessors**

Add to `/home/convo2/projects/pokebenchmark-emulator/pokebenchmark_emulator/gba.py` — insert before the final `def reset(self)` method:

```python
    def set_keys(self, keys: int) -> None:
        """Set the held-key bitmask (mGBA GBA_KEY_* bits). Persists across frames."""
        self.gba.core.set_keys(keys)

    def run_frame(self) -> None:
        """Advance exactly one frame using currently held keys."""
        self.gba.core.run_frame()

    def framebuffer_image(self):
        """Return the current framebuffer as a PIL RGB image without advancing."""
        return self._framebuffer.to_pil().convert("RGB")
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
pytest tests/test_emulator.py::TestHeldKeyAccessors -v
```

Expected: 4 PASSED.

- [ ] **Step 1.5: Run the full emulator test suite to catch regressions**

```bash
pytest tests/ -v
```

Expected: all tests PASS (no regressions in existing adapter/emulator tests).

- [ ] **Step 1.6: Commit**

```bash
cd /home/convo2/projects/pokebenchmark-emulator
git add pokebenchmark_emulator/gba.py tests/test_emulator.py
git commit -m "feat: add set_keys/run_frame/framebuffer_image accessors

Thin wrappers over core.set_keys/run_frame and the framebuffer so callers
don't reach into .gba.core. Required for the play module's 60 Hz loop."
```

- [ ] **Step 1.7: Push**

```bash
git push origin main
```

---

## Task 2: Platform — `play/keymap.py`

**Repo:** `pokebenchmark-platform`

**Files:**
- Create: `pokebenchmark_platform/orchestrator/play/__init__.py`
- Create: `pokebenchmark_platform/orchestrator/play/keymap.py`
- Create: `tests/test_play_keymap.py`

- [ ] **Step 2.1: Write failing tests**

Create `/home/convo2/projects/pokebenchmark-platform/tests/test_play_keymap.py`:

```python
import pytest
from pokebenchmark_platform.orchestrator.play.keymap import GBA_KEYS, bit


def test_key_bits_match_mgba_enum():
    # mGBA GBA_KEY_* enum: A=0, B=1, Select=2, Start=3, Right=4, Left=5, Up=6, Down=7, R=8, L=9
    assert GBA_KEYS == {
        "A": 0, "B": 1, "Select": 2, "Start": 3,
        "Right": 4, "Left": 5, "Up": 6, "Down": 7,
        "R": 8, "L": 9,
    }


def test_bit_for_each_key():
    assert bit("A") == 1
    assert bit("B") == 2
    assert bit("Right") == 1 << 4
    assert bit("L") == 1 << 9


def test_bit_unknown_key_raises():
    with pytest.raises(KeyError):
        bit("Turbo")
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
cd /home/convo2/projects/pokebenchmark-platform
pytest tests/test_play_keymap.py -v
```

Expected: `ModuleNotFoundError: No module named 'pokebenchmark_platform.orchestrator.play'`.

- [ ] **Step 2.3: Create the `play` package**

Create `/home/convo2/projects/pokebenchmark-platform/pokebenchmark_platform/orchestrator/play/__init__.py` (empty file).

Create `/home/convo2/projects/pokebenchmark-platform/pokebenchmark_platform/orchestrator/play/keymap.py`:

```python
"""GBA key names and bitmask helpers for the play module."""

GBA_KEYS: dict[str, int] = {
    "A": 0,
    "B": 1,
    "Select": 2,
    "Start": 3,
    "Right": 4,
    "Left": 5,
    "Up": 6,
    "Down": 7,
    "R": 8,
    "L": 9,
}


def bit(name: str) -> int:
    """Return the single-bit mask for the given GBA key name."""
    return 1 << GBA_KEYS[name]
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
pytest tests/test_play_keymap.py -v
```

Expected: 3 PASSED.

- [ ] **Step 2.5: Commit**

```bash
git add pokebenchmark_platform/orchestrator/play/__init__.py \
        pokebenchmark_platform/orchestrator/play/keymap.py \
        tests/test_play_keymap.py
git commit -m "feat(play): GBA keymap + bit helper"
```

---

## Task 3: Platform — `play/encoding.py`

**Files:**
- Create: `pokebenchmark_platform/orchestrator/play/encoding.py`
- Create: `tests/test_play_encoding.py`

- [ ] **Step 3.1: Write failing tests**

Create `/home/convo2/projects/pokebenchmark-platform/tests/test_play_encoding.py`:

```python
import io
from PIL import Image
from pokebenchmark_platform.orchestrator.play.encoding import encode_jpeg


def test_encode_jpeg_returns_bytes():
    img = Image.new("RGB", (240, 160), color=(10, 20, 30))
    data = encode_jpeg(img)
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_encode_jpeg_is_valid_jpeg():
    img = Image.new("RGB", (240, 160), color=(10, 20, 30))
    data = encode_jpeg(img)
    # JPEG magic bytes
    assert data[:2] == b"\xff\xd8"
    # Round-trip: decode and verify dimensions + approximate color
    decoded = Image.open(io.BytesIO(data))
    assert decoded.size == (240, 160)
    assert decoded.mode == "RGB"
    # Pixel close to original (JPEG is lossy)
    r, g, b = decoded.getpixel((100, 100))
    assert abs(r - 10) < 15 and abs(g - 20) < 15 and abs(b - 30) < 15


def test_encode_jpeg_accepts_rgba_input():
    img = Image.new("RGBA", (240, 160), color=(0, 0, 0, 255))
    data = encode_jpeg(img)
    assert data[:2] == b"\xff\xd8"
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
pytest tests/test_play_encoding.py -v
```

Expected: `ModuleNotFoundError: ... .play.encoding`.

- [ ] **Step 3.3: Implement the encoder**

Create `/home/convo2/projects/pokebenchmark-platform/pokebenchmark_platform/orchestrator/play/encoding.py`:

```python
"""JPEG encoding for play-mode frame streaming."""
import io
from PIL import Image

JPEG_QUALITY = 75


def encode_jpeg(img: Image.Image) -> bytes:
    """Encode a PIL image as JPEG bytes. Accepts RGB or RGBA input."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
pytest tests/test_play_encoding.py -v
```

Expected: 3 PASSED.

- [ ] **Step 3.5: Commit**

```bash
git add pokebenchmark_platform/orchestrator/play/encoding.py \
        tests/test_play_encoding.py
git commit -m "feat(play): JPEG frame encoder"
```

---

## Task 4: Platform — `play/session.py`

**Files:**
- Create: `pokebenchmark_platform/orchestrator/play/session.py`
- Create: `tests/test_play_session.py`

- [ ] **Step 4.1: Write failing tests**

Create `/home/convo2/projects/pokebenchmark-platform/tests/test_play_session.py`:

```python
from unittest.mock import MagicMock
from pokebenchmark_platform.orchestrator.play.session import PlaySession
from pokebenchmark_platform.orchestrator.play.keymap import bit


def test_defaults():
    s = PlaySession(run_id="run-1", emulator=MagicMock())
    assert s.run_id == "run-1"
    assert s.held_keys == 0
    assert s.clients == set()
    assert s.loop_task is None
    assert s.frame_counter == 0
    assert s.last_client_disconnect_at is None


def test_held_keys_mutation_bitmask_math():
    s = PlaySession(run_id="run-1", emulator=MagicMock())
    s.held_keys |= bit("Right")
    s.held_keys |= bit("A")
    assert s.held_keys == bit("Right") | bit("A")
    s.held_keys &= ~bit("Right")
    assert s.held_keys == bit("A")
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
pytest tests/test_play_session.py -v
```

Expected: `ModuleNotFoundError: ... .play.session`.

- [ ] **Step 4.3: Implement the dataclass**

Create `/home/convo2/projects/pokebenchmark-platform/pokebenchmark_platform/orchestrator/play/session.py`:

```python
"""Per-run play session state."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlaySession:
    run_id: str
    emulator: Any  # GBAEmulator — typed loosely to avoid a hard import cycle
    held_keys: int = 0
    clients: set = field(default_factory=set)
    loop_task: "asyncio.Task | None" = None
    frame_counter: int = 0
    last_client_disconnect_at: float | None = None
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
pytest tests/test_play_session.py -v
```

Expected: 2 PASSED.

- [ ] **Step 4.5: Commit**

```bash
git add pokebenchmark_platform/orchestrator/play/session.py \
        tests/test_play_session.py
git commit -m "feat(play): PlaySession dataclass"
```

---

## Task 5: Platform — `play/loop.py`

**Files:**
- Create: `pokebenchmark_platform/orchestrator/play/loop.py`
- Create: `tests/test_play_loop.py`

- [ ] **Step 5.1: Write failing tests**

Create `/home/convo2/projects/pokebenchmark-platform/tests/test_play_loop.py`:

```python
import asyncio
from unittest.mock import MagicMock, AsyncMock
import pytest
from PIL import Image

from pokebenchmark_platform.orchestrator.play.session import PlaySession
from pokebenchmark_platform.orchestrator.play.loop import run_play_loop
from pokebenchmark_platform.orchestrator.play.keymap import bit


def make_emulator():
    emu = MagicMock()
    emu.framebuffer_image.return_value = Image.new("RGB", (240, 160), color=(0, 0, 0))
    return emu


@pytest.mark.asyncio
async def test_loop_sets_keys_and_advances_frames():
    emu = make_emulator()
    session = PlaySession(run_id="r", emulator=emu)
    session.held_keys = bit("Right") | bit("A")

    ws = AsyncMock()
    ws.send_bytes = AsyncMock()
    session.clients.add(ws)

    # Run for a short budget then cancel
    task = asyncio.create_task(run_play_loop(session))
    await asyncio.sleep(0.08)  # ~5 frames at 60Hz
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # set_keys called with held bitmask
    emu.set_keys.assert_called()
    assert emu.set_keys.call_args_list[0].args[0] == bit("Right") | bit("A")
    # run_frame advanced at least once
    assert emu.run_frame.call_count >= 1
    # Frame counter advanced
    assert session.frame_counter >= 1
    # Broadcast happened
    assert ws.send_bytes.await_count >= 1


@pytest.mark.asyncio
async def test_loop_idle_timeout_exits(monkeypatch):
    emu = make_emulator()
    session = PlaySession(run_id="r", emulator=emu)
    # No clients, simulate idle started a long time ago
    session.last_client_disconnect_at = 0.0

    # Monkey-patch perf_counter to report a time past the idle threshold
    import pokebenchmark_platform.orchestrator.play.loop as loop_mod
    monkeypatch.setattr(loop_mod, "perf_counter", lambda: 100.0)

    await asyncio.wait_for(run_play_loop(session), timeout=1.0)
    # Completed naturally (did not need to be cancelled)


@pytest.mark.asyncio
async def test_loop_handles_dead_client_disconnect():
    emu = make_emulator()
    session = PlaySession(run_id="r", emulator=emu)

    ws_alive = AsyncMock()
    ws_dead = AsyncMock()
    ws_dead.send_bytes.side_effect = RuntimeError("disconnected")
    session.clients.add(ws_alive)
    session.clients.add(ws_dead)

    task = asyncio.create_task(run_play_loop(session))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Dead client was removed; alive client still in set
    assert ws_alive in session.clients
    assert ws_dead not in session.clients
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
pytest tests/test_play_loop.py -v
```

Expected: `ModuleNotFoundError: ... .play.loop`.

- [ ] **Step 5.3: Implement the loop**

Create `/home/convo2/projects/pokebenchmark-platform/pokebenchmark_platform/orchestrator/play/loop.py`:

```python
"""60 Hz frame loop + broadcast for play sessions."""
import asyncio
import logging
from time import perf_counter

from pokebenchmark_platform.orchestrator.play.encoding import encode_jpeg
from pokebenchmark_platform.orchestrator.play.session import PlaySession

log = logging.getLogger(__name__)

TARGET_FRAME_S = 1 / 60
IDLE_TIMEOUT_S = 30.0


async def run_play_loop(session: PlaySession) -> None:
    """Run the play loop for a session until cancelled or idle timeout."""
    try:
        while True:
            t0 = perf_counter()

            session.emulator.set_keys(session.held_keys)
            session.emulator.run_frame()
            session.frame_counter += 1

            img = session.emulator.framebuffer_image()
            jpeg = encode_jpeg(img)
            await _broadcast(session, jpeg)

            # idle auto-stop
            if (not session.clients
                    and session.last_client_disconnect_at is not None
                    and perf_counter() - session.last_client_disconnect_at > IDLE_TIMEOUT_S):
                log.info("play: idle timeout for run %s", session.run_id)
                return

            dt = perf_counter() - t0
            if dt < TARGET_FRAME_S:
                await asyncio.sleep(TARGET_FRAME_S - dt)
            else:
                # Yield once so other coroutines (WS receive, cancellation) can run
                await asyncio.sleep(0)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("play: loop crashed for run %s", session.run_id)
        raise


async def _broadcast(session: PlaySession, data: bytes) -> None:
    """Send bytes to all clients, dropping any that fail."""
    dead = []
    for ws in list(session.clients):
        try:
            await ws.send_bytes(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        session.clients.discard(ws)
    if dead and not session.clients and session.last_client_disconnect_at is None:
        session.last_client_disconnect_at = perf_counter()
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
pytest tests/test_play_loop.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5.5: Commit**

```bash
git add pokebenchmark_platform/orchestrator/play/loop.py \
        tests/test_play_loop.py
git commit -m "feat(play): 60Hz frame loop with broadcast + idle auto-stop"
```

---

## Task 6: Platform — `routes/play.py` (HTTP + WS)

**Files:**
- Create: `pokebenchmark_platform/orchestrator/routes/play.py`
- Create: `tests/test_play_routes.py`

- [ ] **Step 6.1: Write failing tests**

Create `/home/convo2/projects/pokebenchmark-platform/tests/test_play_routes.py`:

```python
import asyncio
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from pokebenchmark_platform.orchestrator.routes.play import router as play_router


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


def test_start_twice_returns_409():
    app = build_app_with_manual()
    with TestClient(app) as c:
        c.post("/api/play/r-1/start")
        r = c.post("/api/play/r-1/start")
        assert r.status_code == 409
        # Clean up
        session = app.state.play_sessions["r-1"]
        if session.loop_task is not None:
            session.loop_task.cancel()


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
            with c.websocket_connect("/api/play/r-1/ws"):
                pass


def test_ws_keydown_sets_bit_and_keyup_clears():
    """Pre-seed a session without a live loop task, then test WS key handling."""
    app = build_app_with_manual()
    emu = app.state.manual_sessions["r-1"]["emulator"]
    session = PlaySession(run_id="r-1", emulator=emu)
    app.state.play_sessions["r-1"] = session

    with TestClient(app) as c:
        with c.websocket_connect("/api/play/r-1/ws") as ws:
            ws.send_json({"t": "down", "k": "Right"})
            # Round-trip by sending a 2nd msg; server processes in order
            ws.send_json({"t": "reset_keys"})
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
        with c.websocket_connect("/api/play/r-1/ws") as ws:
            ws.send_json({"t": "reset_keys"})
        assert session.held_keys == 0


def test_ws_ignores_unknown_key():
    app = build_app_with_manual()
    emu = app.state.manual_sessions["r-1"]["emulator"]
    session = PlaySession(run_id="r-1", emulator=emu)
    app.state.play_sessions["r-1"] = session

    with TestClient(app) as c:
        with c.websocket_connect("/api/play/r-1/ws") as ws:
            ws.send_json({"t": "down", "k": "Turbo"})
        assert session.held_keys == 0
```

Note: the WS tests that check state pre-seed `PlaySession` directly into
`app.state.play_sessions` without calling `/start`, so no live loop task
competes with the test for the event loop. The start/stop round-trip is
exercised separately by `test_start_creates_session_and_returns_200` and
`test_stop_cancels_loop_and_removes_session`.

- [ ] **Step 6.2: Run tests to verify they fail**

```bash
pytest tests/test_play_routes.py -v
```

Expected: `ModuleNotFoundError: ... .routes.play`.

- [ ] **Step 6.3: Implement the routes**

Create `/home/convo2/projects/pokebenchmark-platform/pokebenchmark_platform/orchestrator/routes/play.py`:

```python
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
```

- [ ] **Step 6.4: Run tests to verify they pass**

```bash
pytest tests/test_play_routes.py -v
```

Expected: 9 PASSED.

- [ ] **Step 6.5: Commit**

```bash
git add pokebenchmark_platform/orchestrator/routes/play.py \
        tests/test_play_routes.py
git commit -m "feat(play): HTTP routes + WebSocket handler"
```

---

## Task 7: Platform — wire `play` router into `app.py`

**Files:**
- Modify: `pokebenchmark_platform/orchestrator/app.py`

- [ ] **Step 7.1: Read the current app.py**

```bash
cat pokebenchmark_platform/orchestrator/app.py
```

Confirm the `include_router` block lives around lines 43–47 and looks like:

```python
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
app.include_router(games.router, prefix="/api/games", tags=["games"])
app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
app.include_router(ws.router, prefix="/ws", tags=["websocket"])
```

Also confirm the import block imports `runs, catalog, games, skills, ws` from `pokebenchmark_platform.orchestrator.routes`.

- [ ] **Step 7.2: Add import for `play` router**

In `/home/convo2/projects/pokebenchmark-platform/pokebenchmark_platform/orchestrator/app.py`, find the line that imports `runs, catalog, games, skills, ws` from `.routes` and add `play` to that import:

```python
from pokebenchmark_platform.orchestrator.routes import (
    runs, catalog, games, skills, ws, play,
)
```

(If the file uses a different import style, add `from pokebenchmark_platform.orchestrator.routes import play` alongside the others.)

- [ ] **Step 7.3: Register the `play` router**

Add this line immediately after the existing `ws.router` include:

```python
app.include_router(play.router, prefix="/api/play", tags=["play"])
```

- [ ] **Step 7.4: Initialize `play_sessions` state at startup**

Find the lifespan / startup block in `app.py`. Add this line alongside any other `app.state.*` initialization (e.g., where `manual_sessions` or the db is initialized):

```python
app.state.play_sessions = {}
```

If no lifespan handler exists but state is initialized in `create_app`, add it there directly after any existing state init.

- [ ] **Step 7.5: Smoke test — boot and probe**

```bash
pytest tests/ -v
```

Expected: all tests still PASS, including the play tests from Tasks 2–6.

Also run:

```bash
python -c "from pokebenchmark_platform.orchestrator.app import create_app; app = create_app(); routes = [r.path for r in app.routes]; print([r for r in routes if 'play' in r])"
```

Expected output includes: `/api/play/{run_id}/start`, `/api/play/{run_id}/stop`, `/api/play/{run_id}/ws`.

- [ ] **Step 7.6: Commit**

```bash
git add pokebenchmark_platform/orchestrator/app.py
git commit -m "feat(play): mount play router + init play_sessions state"
```

---

## Task 8: Platform — 409 conflict in `routes/runs.py` when play is active

**Files:**
- Modify: `pokebenchmark_platform/orchestrator/routes/runs.py`
- Create: `tests/test_play_conflict.py`

- [ ] **Step 8.1: Write failing tests**

Create `/home/convo2/projects/pokebenchmark-platform/tests/test_play_conflict.py`:

```python
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
    # Add a play session for the same run
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
```

- [ ] **Step 8.2: Run tests to verify they fail**

```bash
pytest tests/test_play_conflict.py -v
```

Expected: tests for 409 FAIL (returns 200). Tests for 200 pass.

- [ ] **Step 8.3: Add the conflict guard**

Open `/home/convo2/projects/pokebenchmark-platform/pokebenchmark_platform/orchestrator/routes/runs.py`.

Add this helper near the existing `_manual_sessions` helper (around line 30):

```python
def _play_sessions(request) -> dict:
    if not hasattr(request.app.state, "play_sessions"):
        request.app.state.play_sessions = {}
    return request.app.state.play_sessions


def _raise_if_play_active(request, run_id: str) -> None:
    if run_id in _play_sessions(request):
        raise HTTPException(status_code=409, detail="play session active")
```

Then in the `press` endpoint handler (the one at line ~200 that calls `sess["emulator"].press_button(...)`), add this as the first line inside the handler, before `sess = ...` is resolved:

```python
_raise_if_play_active(request, run_id)
```

Do the same in the `wait` endpoint handler (around line 210).

- [ ] **Step 8.4: Run tests to verify they pass**

```bash
pytest tests/test_play_conflict.py -v
```

Expected: 3 PASSED.

- [ ] **Step 8.5: Run the full test suite to catch regressions**

```bash
pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 8.6: Commit**

```bash
git add pokebenchmark_platform/orchestrator/routes/runs.py \
        tests/test_play_conflict.py
git commit -m "feat(runs): 409 when play session active on press/wait"
```

- [ ] **Step 8.7: Push platform**

```bash
git push origin main
```

---

## Task 9: Dashboard — `src/api/play.ts`

**Repo:** `pokebenchmark-dashboard`

**Files:**
- Create: `/home/convo2/projects/pokebenchmark-dashboard/src/api/play.ts`

The dashboard has no test framework. Verification is `npm run build` (TypeScript type-check) plus manual QA later.

- [ ] **Step 9.1: Create the API client**

Create `/home/convo2/projects/pokebenchmark-dashboard/src/api/play.ts`:

```typescript
export type GbaKey =
  | 'A' | 'B' | 'Select' | 'Start'
  | 'Right' | 'Left' | 'Up' | 'Down'
  | 'R' | 'L'

export const KEY_MAP: Record<string, GbaKey> = {
  ArrowUp: 'Up',
  ArrowDown: 'Down',
  ArrowLeft: 'Left',
  ArrowRight: 'Right',
  z: 'B',
  x: 'A',
  a: 'L',
  s: 'R',
  Enter: 'Start',
  Shift: 'Select',
}

export async function startPlay(runId: string): Promise<void> {
  const res = await fetch(`/api/play/${runId}/start`, { method: 'POST' })
  if (!res.ok) throw new Error(`startPlay ${res.status}: ${await res.text()}`)
}

export async function stopPlay(runId: string): Promise<{ frames: number }> {
  const res = await fetch(`/api/play/${runId}/stop`, { method: 'POST' })
  if (!res.ok) throw new Error(`stopPlay ${res.status}: ${await res.text()}`)
  return res.json()
}

export interface PlayConnection {
  readonly ws: WebSocket
  close(): void
  sendKeyDown(k: GbaKey): void
  sendKeyUp(k: GbaKey): void
  sendResetKeys(): void
}

export function openPlayConnection(
  runId: string,
  onFrame: (bitmap: ImageBitmap) => void,
  onClose: () => void,
): PlayConnection {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/api/play/${runId}/ws`)
  ws.binaryType = 'blob'

  ws.addEventListener('message', async (e) => {
    if (e.data instanceof Blob) {
      try {
        const bmp = await createImageBitmap(e.data)
        onFrame(bmp)
      } catch {
        /* ignore decode errors on occasional corrupt frames */
      }
    }
  })

  ws.addEventListener('close', onClose)
  ws.addEventListener('error', onClose)

  const send = (obj: object) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj))
  }

  return {
    ws,
    close: () => ws.close(),
    sendKeyDown: (k) => send({ t: 'down', k }),
    sendKeyUp: (k) => send({ t: 'up', k }),
    sendResetKeys: () => send({ t: 'reset_keys' }),
  }
}
```

- [ ] **Step 9.2: Type-check**

```bash
cd /home/convo2/projects/pokebenchmark-dashboard
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 9.3: Commit**

```bash
git add src/api/play.ts
git commit -m "feat(play): WS + REST client for play sessions"
```

---

## Task 10: Dashboard — `src/components/PlayCanvas.tsx`

**Files:**
- Create: `src/components/PlayCanvas.tsx`

- [ ] **Step 10.1: Create the component**

Create `/home/convo2/projects/pokebenchmark-dashboard/src/components/PlayCanvas.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import { KEY_MAP, openPlayConnection, type PlayConnection } from '../api/play'

interface Props {
  runId: string
  onClosed: () => void
}

export default function PlayCanvas({ runId, onClosed }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const connRef = useRef<PlayConnection | null>(null)
  const heldRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const conn = openPlayConnection(
      runId,
      (bmp) => {
        ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height)
        bmp.close()
      },
      () => onClosed(),
    )
    connRef.current = conn

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.repeat) return
      const k = KEY_MAP[e.key]
      if (!k) return
      e.preventDefault()
      if (heldRef.current.has(k)) return
      heldRef.current.add(k)
      conn.sendKeyDown(k)
    }
    const onKeyUp = (e: KeyboardEvent) => {
      const k = KEY_MAP[e.key]
      if (!k) return
      e.preventDefault()
      heldRef.current.delete(k)
      conn.sendKeyUp(k)
    }
    const onBlur = () => {
      heldRef.current.clear()
      conn.sendResetKeys()
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', onBlur)

    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', onBlur)
      conn.close()
    }
  }, [runId, onClosed])

  return (
    <canvas
      ref={canvasRef}
      width={240}
      height={160}
      style={{
        width: '100%',
        height: '100%',
        imageRendering: 'pixelated',
        background: '#000',
        display: 'block',
      }}
    />
  )
}
```

- [ ] **Step 10.2: Type-check**

```bash
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 10.3: Commit**

```bash
git add src/components/PlayCanvas.tsx
git commit -m "feat(play): PlayCanvas component with keydown/keyup capture"
```

---

## Task 11: Dashboard — `/play/:runId` route + `Play.tsx` page

**Files:**
- Create: `src/pages/Play.tsx`
- Modify: `src/App.tsx`

- [ ] **Step 11.1: Create the page**

Create `/home/convo2/projects/pokebenchmark-dashboard/src/pages/Play.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import PlayCanvas from '../components/PlayCanvas'
import { startPlay, stopPlay } from '../api/play'

export default function Play() {
  const { runId = '' } = useParams<{ runId: string }>()
  const [started, setStarted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    startPlay(runId)
      .then(() => { if (!cancelled) setStarted(true) })
      .catch((e) => { if (!cancelled) setError(String(e)) })

    const onUnload = () => { stopPlay(runId).catch(() => {}) }
    window.addEventListener('beforeunload', onUnload)

    return () => {
      cancelled = true
      window.removeEventListener('beforeunload', onUnload)
      stopPlay(runId).catch(() => {})
    }
  }, [runId])

  return (
    <div style={{
      position: 'fixed', inset: 0, background: '#000',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {error ? (
        <div style={{ color: '#f88', padding: 24, fontFamily: 'monospace' }}>
          Failed to start: {error}
        </div>
      ) : !started ? (
        <div style={{ color: '#888', fontFamily: 'monospace' }}>Starting…</div>
      ) : (
        <div style={{
          width: 'min(100vw, calc(100vh * 1.5))',
          aspectRatio: '3 / 2',
        }}>
          <PlayCanvas runId={runId} onClosed={() => setError('connection closed')} />
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 11.2: Register the route outside of `<Layout />`**

Open `/home/convo2/projects/pokebenchmark-dashboard/src/App.tsx`.

Replace the contents of the file with:

```tsx
import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import RunCatalog from './pages/RunCatalog'
import RunDetail from './pages/RunDetail'
import SaveStateCatalog from './pages/SaveStateCatalog'
import Comparison from './pages/Comparison'
import Games from './pages/Games'
import GameDetail from './pages/GameDetail'
import Skills from './pages/Skills'
import Play from './pages/Play'

export default function App() {
  return (
    <Routes>
      {/* Chrome-less popout route — must sit OUTSIDE the Layout wrapper */}
      <Route path="/play/:runId" element={<Play />} />
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/games" element={<Games />} />
        <Route path="/games/:gameId" element={<GameDetail />} />
        <Route path="/games/:gameId/skills" element={<Skills />} />
        <Route path="/skills" element={<Skills />} />
        <Route path="/runs" element={<RunCatalog />} />
        <Route path="/runs/:runId" element={<RunDetail />} />
        <Route path="/save-states" element={<SaveStateCatalog />} />
        <Route path="/compare" element={<Comparison />} />
      </Route>
    </Routes>
  )
}
```

- [ ] **Step 11.3: Type-check**

```bash
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 11.4: Commit**

```bash
git add src/pages/Play.tsx src/App.tsx
git commit -m "feat(play): /play/:runId route with chrome-less Play page"
```

---

## Task 12: Dashboard — "Play in Window" button in `RunDetail`

**Files:**
- Modify: `src/pages/RunDetail.tsx`

- [ ] **Step 12.1: Locate the ManualControls render site**

```bash
cd /home/convo2/projects/pokebenchmark-dashboard
grep -n "ManualControls\|run.id" src/pages/RunDetail.tsx
```

You will see this structure around lines 92–97:

```tsx
{run.model_provider === 'manual' ? (
  (run.status === 'running' || run.status === 'pending') ? (
    <ManualControls runId={run.id} game={run.game} />
  ) : (
    <div>This manual run is {run.status}. Controls are disabled.</div>
  )
) : ( /* ... non-manual branch ... */ )}
```

The field is `run.id` (not `run.run_id`).

- [ ] **Step 12.2: Wrap ManualControls in a fragment with the Play button**

In `/home/convo2/projects/pokebenchmark-dashboard/src/pages/RunDetail.tsx`, replace the line

```tsx
<ManualControls runId={run.id} game={run.game} />
```

with

```tsx
<>
  <button
    type="button"
    onClick={() => {
      window.open(
        `/play/${run.id}`,
        `play_${run.id}`,
        'popup=yes,width=720,height=480,resizable=yes'
      )
    }}
    style={{
      padding: '6px 12px',
      marginBottom: 12,
      fontFamily: 'monospace',
      cursor: 'pointer',
    }}
  >
    ▶ Play in Window
  </button>
  <ManualControls runId={run.id} game={run.game} />
</>
```

- [ ] **Step 12.3: Type-check**

```bash
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 12.4: Full build**

```bash
npm run build
```

Expected: build completes, outputs to `dist/`, no TypeScript errors.

- [ ] **Step 12.5: Commit and push dashboard**

```bash
git add src/pages/RunDetail.tsx
git commit -m "feat(play): 'Play in Window' entry button in RunDetail"
git push origin main
```

---

## Task 13: End-to-end manual QA

Backend + dashboard must already be deployed/running via `docker compose up` for this task.

- [ ] **Step 13.1: Start a manual run**

Open the dashboard in a browser. Go to `/games/firered`. Start a **new manual run** (`model_provider=manual`) with any save state (or fresh).

- [ ] **Step 13.2: Open the popup**

From the run detail page, click **"▶ Play in Window"**. A ~720×480 popup window opens at `/play/:runId` with a black background and a fullscreen-scaled canvas.

- [ ] **Step 13.3: Verify hold-to-move**

Hold `ArrowRight`. The character walks continuously. Release — walking stops on the frame release is processed.

Repeat for ArrowLeft/Up/Down, `z` (B), `x` (A), `Enter` (Start), `Shift` (Select).

- [ ] **Step 13.4: Verify frame rate**

Open the popup's devtools Network panel → WS tab → confirm binary frames arriving at ~60/sec.

- [ ] **Step 13.5: Verify blur clears keys**

Hold `ArrowRight`. Click outside the popup (focus lost). Character stops.

- [ ] **Step 13.6: Verify tap endpoint is blocked**

While the popup is open, from the main dashboard, try the existing ManualControls "Press" button. Confirm it errors with `409 play session active`.

- [ ] **Step 13.7: Verify close stops the session**

Close the popup window. Within 30 seconds, confirm backend logs show `play: idle timeout for run <run_id>` and `app.state.play_sessions` is empty (check via orchestrator logs or `docker exec` into the container and `python -c "..."`).

- [ ] **Step 13.8: Verify `/press` works again after session ends**

After the idle timeout fires, confirm the dashboard ManualControls "Press" button succeeds (200, not 409).

---

## Done

All 12 implementation tasks + manual QA complete. Feature shipped.

No changes to the agent loop, recording pipeline, catalog DB, or existing `ManualControls` component.
