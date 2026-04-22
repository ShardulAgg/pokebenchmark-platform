# Popout VBA-like Manual Gameplay

Date: 2026-04-22
Repos touched: `pokebenchmark-platform`, `pokebenchmark-dashboard`

## Goal

Let a human play a manual run with the responsiveness of a native emulator
(Visual Boy Advance, mGBA-qt): ~60 FPS continuous rendering, hold-to-move
directional input, keyboard-first, in a dedicated OS-level popup window.

Additive: the existing fixed-tap `ManualControls` flow stays exactly as it is.

## Non-goals

- Audio streaming (GBA sound output)
- Multiplayer or shared input between viewers
- Recording integration (existing `VideoRecorder` is untouched while a play
  session runs)
- Native desktop emulator (ruled out; requires host-side mGBA install and
  doesn't work remotely)

## Architecture

```
┌─ Popup Window (/play/:runId) ─────────────┐
│  PlayCanvas:                              │
│   - keydown/keyup → WS                    │
│   - binary WS frames → canvas.drawImage   │
└───────────────┬───────────────────────────┘
                │ WS /ws/play/{run_id}
                ▼
┌─ Orchestrator ────────────────────────────┐
│  routes/play.py  (start/stop/WS)          │
│  play/session.py (PlaySession)            │
│  play/loop.py    (60Hz frame loop task)   │
│           │                               │
│           ▼                               │
│   GBAEmulator (shared instance per run)   │
└───────────────────────────────────────────┘
```

One `PlaySession` per `run_id`, stored on `app.state.play_sessions`.

One `asyncio.Task` per session drives the emulator at ~60 Hz and fans rendered
frames out to every WebSocket client connected to that session (supports
multiple viewers of the same game).

## Backend

### New module layout

```
pokebenchmark_platform/orchestrator/
    play/
        __init__.py
        session.py      # PlaySession dataclass
        loop.py         # frame loop + broadcast
        encoding.py     # JPEG encode helper
        keymap.py       # GBA button name → bitmask
    routes/
        play.py         # HTTP + WS routes
```

No existing files are modified except:
- `app.py` — add `app.state.play_sessions = {}` and register `routes/play.py` with prefix `/api/play`; WebSocket route registered via its own `APIRouter` at prefix `/ws` alongside existing ws router
- `routes/runs.py` — `POST /{run_id}/press` and `POST /{run_id}/wait` return `409 {"error":"play session active"}` when `run_id` has an active play session (looked up in `app.state.play_sessions`)

The play session reuses the `GBAEmulator` instance owned by the manual
session at `app.state.manual_sessions[run_id]["emulator"]`; it does not
create its own. This matches the existing single-instance-per-run model.

### `play/session.py`

```python
@dataclass
class PlaySession:
    run_id: str
    emulator: GBAEmulator          # reused from the manual run
    held_keys: int = 0             # GBA button bitmask (mGBA key codes)
    clients: set[WebSocket] = field(default_factory=set)
    loop_task: asyncio.Task | None = None
    frame_counter: int = 0
    last_client_disconnect_at: float | None = None  # for idle auto-stop
```

### `play/loop.py`

One task per session:

```
TARGET_FRAME_S = 1/60

while not cancelled:
    t0 = perf_counter()
    emulator.core.set_keys(session.held_keys)
    emulator.core.run_frame()
    session.frame_counter += 1

    jpeg = encode_jpeg(emulator.framebuffer)
    await broadcast(session.clients, jpeg)

    # idle auto-stop: 30s after last client disconnect
    if (not session.clients
            and session.last_client_disconnect_at is not None
            and perf_counter() - session.last_client_disconnect_at > 30):
        break

    dt = perf_counter() - t0
    if dt < TARGET_FRAME_S:
        await asyncio.sleep(TARGET_FRAME_S - dt)
```

Thread safety: no lock on `held_keys`. Single writer (WS handler coroutine),
single reader (loop coroutine), both on the same event loop, writes of a
Python `int` are atomic under the GIL.

On any exception in the loop body: log, close all clients, remove from
`app.state.play_sessions`, re-raise so the task terminates.

### `play/encoding.py`

`encode_jpeg(framebuffer) -> bytes` using Pillow:
- Input: 240×160 RGBA from mGBA framebuffer
- Convert to RGB, save JPEG quality=75 to `BytesIO`
- Expected size ~3–8 KB per frame → ~300 KB/s at 60 FPS

### `play/keymap.py`

```python
GBA_KEYS = {"A":0, "B":1, "Select":2, "Start":3,
            "Right":4, "Left":5, "Up":6, "Down":7,
            "R":8, "L":9}

def bit(name: str) -> int: return 1 << GBA_KEYS[name]
```

### Routes (`routes/play.py`)

| Method | Path                            | Behavior                                                                     |
|--------|---------------------------------|------------------------------------------------------------------------------|
| POST   | `/api/play/{run_id}/start`      | Look up `emulator = app.state.manual_sessions[run_id]["emulator"]`. Create session, start loop task. `409` if play session already exists for run_id. `404` if run_id is not an active manual session. |
| POST   | `/api/play/{run_id}/stop`       | Cancel loop task, close all clients, delete session. Returns `{frames: N}`. `404` if no session. |
| WS     | `/ws/play/{run_id}`             | Closes with code 4404 if no active session. Otherwise adds to `session.clients` and sets `session.last_client_disconnect_at = None`. |

### WS protocol

| Dir | Frame type | Payload                                                                 |
|-----|------------|-------------------------------------------------------------------------|
| S→C | binary     | JPEG bytes, one per rendered frame                                      |
| C→S | text JSON  | `{"t":"down","k":"Right"}`                                              |
| C→S | text JSON  | `{"t":"up","k":"Right"}`                                                |
| C→S | text JSON  | `{"t":"reset_keys"}` — clear all held keys (for window blur)            |

Server rejects unknown `k` values and unknown `t` values silently (logged,
not disconnected — misbehaving clients shouldn't kill the session).

### Interaction with existing manual controls

While a play session is active for `run_id`:
- `POST /api/runs/{run_id}/press` → `409 {"error":"play session active"}`
- `POST /api/runs/{run_id}/wait` → same `409`
- `GET /api/runs/{run_id}/frame` continues to work (read-only)
- Save state endpoints (`/save-state`, `/load-state`) continue to work;
  load-state must re-seed the emulator state that the play loop consumes.
  Acceptable under the single-event-loop model — no extra synchronization
  needed.

## Frontend

### New files (no changes to existing manual path)

```
src/
    pages/Play.tsx
    components/PlayCanvas.tsx
    api/play.ts
```

### `pages/Play.tsx`

- Route: `/play/:runId` registered in the existing router
- Full-bleed black background, no Layout chrome
- On mount: `POST /api/play/:runId/start`; on success, mount `<PlayCanvas>`
- On unmount (close / navigate): `POST /api/play/:runId/stop`
- On `window.blur`: send `{"t":"reset_keys"}` so sticky keys don't persist

### `components/PlayCanvas.tsx`

- 240×160 `<canvas>` scaled with CSS `image-rendering: pixelated` to fit
  viewport preserving aspect
- WS connection to `/ws/play/:runId`
- Binary messages decoded with `createImageBitmap(blob)` → `ctx.drawImage`
- `keydown`/`keyup` listeners on `window` send JSON frames
- Ignores auto-repeat (`e.repeat` → skip)

### `api/play.ts`

- Dedicated WS client (not shared with existing `api/websocket.ts`)
- Key mapping (matches existing `ManualControls`):

| Keyboard        | GBA       |
|-----------------|-----------|
| ArrowUp/Down/Left/Right | Up/Down/Left/Right |
| z               | A         |
| x               | B         |
| Enter           | Start     |
| Backspace       | Select    |
| a               | L         |
| s               | R         |

Unmapped keys ignored.

### Entry point

`RunDetail` page, when `run.model_provider === 'manual'`, adds a
"Play in Window" button next to the existing ManualControls. Clicking calls:

```ts
window.open(
  `/play/${runId}`,
  `play_${runId}`,
  'popup=yes,width=720,height=480,resizable=yes'
)
```

`popup=yes` asks browsers to open a chrome-less window. Users can still
interact with the original dashboard tab simultaneously.

## Error handling

| Scenario                          | Behavior                                                 |
|-----------------------------------|----------------------------------------------------------|
| WS client disconnects             | Remove from `session.clients`. If that leaves zero, record `last_client_disconnect_at = perf_counter()`. |
| All clients gone > 30 s           | Loop breaks, session removed.                             |
| Loop raises (emulator crash etc.) | Close all clients with code 1011, remove session, log.   |
| `/play/.../start` on active run   | `409 Conflict`                                            |
| WS connect with no session        | Close with code 4404                                      |
| User force-closes popup           | Browser unload fires; best-effort `/stop`. If it doesn't land, idle auto-stop (30s) handles it. |

## Testing

### Unit (backend)

- `test_session_state.py` — `PlaySession` field defaults, `held_keys`
  bitmask math via `keymap`
- `test_loop_iteration.py` — mock emulator with a frame counter; advance N
  iterations; assert `set_keys(held_keys)` called each iteration, frames
  encoded + broadcast, `frame_counter` increments
- `test_loop_idle_timeout.py` — zero clients + mocked `perf_counter` → loop
  exits after 30 s
- `test_encoding.py` — JPEG output of a known framebuffer round-trips to
  approximately the same RGB pixels

### Integration (backend)

- `test_play_routes.py` — `start`, connect WS, send `{"t":"down","k":"A"}`,
  verify `session.held_keys & bit("A") != 0`; send `up`, verify cleared;
  `stop` returns frame count > 0
- `test_play_conflicts.py` — with active play session, `POST /press` returns
  409; without, returns 200

### Manual QA

- Open a manual run, click "Play in Window", popup opens 720×480
- Walk the character around a room with arrow keys — movement is continuous
  while held, stops cleanly on release
- Close popup → emulator stops within 30 s (observe via backend logs /
  frame counter)
- `window.blur` (click outside popup) → character stops even if key was
  held at the time

## Decisions deferred

- Audio: no path yet; may require pygba audio buffer access + Opus encoding
- Network tuning: if 300 KB/s proves heavy over remote links, add a
  `?fps=30` query param to `/play/.../start` that halves the loop rate.
  Not implemented in this iteration.
