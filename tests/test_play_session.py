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
