"""60 Hz frame loop + broadcast for play sessions."""
import asyncio
import dataclasses
import json
import logging
from time import perf_counter

from pokebenchmark_platform.orchestrator.play.encoding import encode_jpeg
from pokebenchmark_platform.orchestrator.play.session import PlaySession

log = logging.getLogger(__name__)

TARGET_FRAME_S = 1 / 60
IDLE_TIMEOUT_S = 30.0
STATE_INTERVAL_FRAMES = 30  # ~2 Hz state broadcasts at 60 FPS


async def run_play_loop(session: PlaySession) -> None:
    """Run the play loop for a session until cancelled or idle timeout."""
    try:
        while True:
            t0 = perf_counter()

            session.emulator.set_keys(session.held_keys)
            # Speed > 1 means "fast-forward": run N emulator frames per
            # broadcast tick. The broadcast rate stays at ~60 FPS so we don't
            # flood the network; only the emulator progresses faster.
            speed = max(1, min(session.speed, 16))
            for _ in range(speed):
                session.emulator.run_frame()
            session.frame_counter += speed

            img = session.emulator.framebuffer_image()
            jpeg = encode_jpeg(img)
            await _broadcast_binary(session, jpeg)

            if session.frame_counter % STATE_INTERVAL_FRAMES == 0 and session.adapter is not None:
                try:
                    state = session.adapter.read_state(session.emulator)
                    payload = {"t": "state", "data": dataclasses.asdict(state)}
                    await _broadcast_text(session, json.dumps(payload))
                except Exception:
                    # Never let a bad adapter kill the 60 FPS loop.
                    log.exception("play: state read failed for run %s", session.run_id)

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


async def _broadcast_binary(session: PlaySession, data: bytes) -> None:
    """Send bytes to all clients, dropping any that fail."""
    await _broadcast(session, lambda ws: ws.send_bytes(data))


async def _broadcast_text(session: PlaySession, text: str) -> None:
    """Send text to all clients, dropping any that fail."""
    await _broadcast(session, lambda ws: ws.send_text(text))


async def _broadcast(session: PlaySession, sender) -> None:
    dead = []
    for ws in list(session.clients):
        try:
            await sender(ws)
        except Exception:
            dead.append(ws)
    for ws in dead:
        session.clients.discard(ws)
    if dead and not session.clients and session.last_client_disconnect_at is None:
        session.last_client_disconnect_at = perf_counter()
