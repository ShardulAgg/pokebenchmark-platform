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
