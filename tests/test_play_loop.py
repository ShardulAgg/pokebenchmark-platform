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
