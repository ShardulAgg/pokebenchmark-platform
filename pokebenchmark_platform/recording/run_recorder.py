"""Continuous per-run video recording.

Polls the emulator's framebuffer at a steady cadence regardless of what's
advancing frames — manual presses, the WS play loop, or nothing. One mp4
per run, covering the run's entire lifetime.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from time import perf_counter

from pokebenchmark_platform.recording.recorder import VideoRecorder

log = logging.getLogger(__name__)

RECORDINGS_ROOT = "data/recordings"
DEFAULT_FPS = 30


class RunRecorder:
    def __init__(self, emulator, run_id: str, fps: int = DEFAULT_FPS):
        self._emulator = emulator
        self._run_id = run_id
        self._interval = 1.0 / fps
        run_dir = os.path.join(RECORDINGS_ROOT, run_id)
        os.makedirs(run_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.output_path = os.path.join(run_dir, f"{ts}.mp4")
        self._recorder = VideoRecorder(
            output_path=self.output_path, width=240, height=160, fps=fps
        )
        self._task: "asyncio.Task | None" = None

    def start(self) -> None:
        try:
            self._recorder.start()
        except Exception:
            log.exception("run-recorder: ffmpeg failed to start for run %s", self._run_id)
            return
        self._task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        try:
            while True:
                t0 = perf_counter()
                try:
                    img = self._emulator.framebuffer_image()
                    self._recorder.write_frame(img)
                except Exception:
                    log.exception("run-recorder: frame write failed for run %s", self._run_id)
                    return
                dt = perf_counter() - t0
                if dt < self._interval:
                    await asyncio.sleep(self._interval - dt)
                else:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("run-recorder: poll task errored for run %s", self._run_id)
            self._task = None
        try:
            self._recorder.stop()
        except Exception:
            log.exception("run-recorder: recorder stop failed for run %s", self._run_id)
