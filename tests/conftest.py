"""
Stub out the pokebenchmark_emulator package so tests that import
orchestrator.routes.runs (which references EmeraldAdapter, FireRedAdapter,
GBAEmulator) can run without the native emulator library installed.
"""
import sys
from types import ModuleType
from unittest.mock import MagicMock


def _stub_emulator():
    """Insert lightweight stub modules into sys.modules if the real package
    is absent.  This must happen before any test module imports runs.py."""
    if "pokebenchmark_emulator" in sys.modules:
        return  # real package already present

    pkg = ModuleType("pokebenchmark_emulator")
    sys.modules["pokebenchmark_emulator"] = pkg

    gba_mod = ModuleType("pokebenchmark_emulator.gba")
    gba_mod.GBAEmulator = MagicMock  # type: ignore[attr-defined]
    sys.modules["pokebenchmark_emulator.gba"] = gba_mod

    adapters_mod = ModuleType("pokebenchmark_emulator.adapters")
    sys.modules["pokebenchmark_emulator.adapters"] = adapters_mod

    emerald_mod = ModuleType("pokebenchmark_emulator.adapters.emerald")
    emerald_mod.EmeraldAdapter = MagicMock  # type: ignore[attr-defined]
    sys.modules["pokebenchmark_emulator.adapters.emerald"] = emerald_mod

    firered_mod = ModuleType("pokebenchmark_emulator.adapters.firered")
    firered_mod.FireRedAdapter = MagicMock  # type: ignore[attr-defined]
    sys.modules["pokebenchmark_emulator.adapters.firered"] = firered_mod


_stub_emulator()
