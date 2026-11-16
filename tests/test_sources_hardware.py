"""Live input from a connected MPC Sample; run with `uv run pytest -m hardware`."""

import pytest

from mpc_iml.events import MidiEvent
from mpc_iml.frames import bank_pad_to_note
from mpc_iml.sources import LiveSource, RtMidiBackend

pytestmark = pytest.mark.hardware

TIMEOUT = 10.0


def test_mpc_port_is_found() -> None:
    names = RtMidiBackend().port_names()
    assert any("mpc" in name.casefold() for name in names), f"MIDI input ports: {names}"


def test_pad_press_arrives_as_note_on_and_note_off(capsys: pytest.CaptureFixture[str]) -> None:
    note = bank_pad_to_note(0, 0)
    with capsys.disabled():
        print(f"\nPress and release pad A01 (note {note}) within {TIMEOUT:.0f} s...")
    kinds: list[str] = []
    with LiveSource() as source:
        for event in source.events(duration=TIMEOUT):
            if not isinstance(event, MidiEvent) or event.note != note:
                continue
            if event.kind == "note_on" and event.value > 0 and not kinds:
                kinds.append("note_on")
            elif event.kind == "note_off" and kinds:
                kinds.append("note_off")
                break
    assert kinds == ["note_on", "note_off"]
