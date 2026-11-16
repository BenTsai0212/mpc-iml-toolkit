"""Note mapping and frames."""

from pathlib import Path

import pytest

from mpc_iml.events import Event, ExampleStart, MidiEvent, RawMidiEvent
from mpc_iml.frames import Frame, bank_pad_to_note, frames, note_to_bank_pad
from mpc_iml.recording import read_recording

DATA = Path(__file__).parent / "data"


def on(t: float, note: int, value: int) -> MidiEvent:
    return MidiEvent(t=t, kind="note_on", channel=1, note=note, value=value)


def off(t: float, note: int) -> MidiEvent:
    return MidiEvent(t=t, kind="note_off", channel=1, note=note, value=0)


def press(t: float, note: int, value: int) -> MidiEvent:
    return MidiEvent(t=t, kind="poly_pressure", channel=1, note=note, value=value)


@pytest.mark.parametrize(
    ("note", "bank", "pad"),
    [(36, 0, 0), (52, 1, 0), (20, 7, 0), (51, 0, 15), (35, 7, 15)],
)
def test_note_formula(note: int, bank: int, pad: int) -> None:
    assert note_to_bank_pad(note) == (bank, pad)
    assert bank_pad_to_note(bank, pad) == note


def test_note_formula_is_a_bijection() -> None:
    pairs = {note_to_bank_pad(n) for n in range(128)}
    assert len(pairs) == 128


def test_default_rate_is_100_hz() -> None:
    times = [f.t for f in frames([on(0.05, 36, 10)])]
    assert times == pytest.approx([0.0, 0.01, 0.02, 0.03, 0.04, 0.05])


def test_configurable_rate() -> None:
    times = [f.t for f in frames([on(1.0, 36, 10)], rate=2)]
    assert times == [0.0, 0.5, 1.0]


def test_pressure_is_held_until_next_message() -> None:
    events: list[Event] = [on(0.0, 37, 80), press(0.02, 37, 40), press(0.06, 37, 70)]
    pressures = [f.pressure[1] for f in frames(events)]
    assert pressures == [0, 0, 40, 40, 40, 40, 70]
    last = list(frames(events))[-1]
    assert last.held[1] is True
    assert last.velocity[1] == 80


def test_note_off_resets_pressure_and_held() -> None:
    events: list[Event] = [on(0.0, 36, 90), press(0.01, 36, 50), off(0.02, 36)]
    result = list(frames(events))
    assert (result[1].pressure[0], result[1].held[0]) == (50, True)
    assert (result[2].pressure[0], result[2].held[0]) == (0, False)
    assert result[2].velocity[0] == 90


def test_note_on_with_zero_velocity_is_note_off() -> None:
    last = list(frames([on(0.0, 36, 90), press(0.01, 36, 50), on(0.02, 36, 0)]))[-1]
    assert (last.pressure[0], last.held[0], last.velocity[0]) == (0, False, 90)


def test_bank_and_physical_pad() -> None:
    last = list(frames([on(0.0, 20, 64)]))[-1]
    assert last.bank == 7
    assert last.held[0] is True


def test_non_pad_messages_are_ignored() -> None:
    events: list[Event] = [
        ExampleStart(t=0.0, label="x"),
        MidiEvent(t=0.01, kind="control_change", channel=1, control=7, value=90),
        MidiEvent(t=0.01, kind="control_change", channel=1, control=64, value=127),
        MidiEvent(t=0.01, kind="pitch_bend", channel=1, value=8192),
        RawMidiEvent(t=0.02, data=b"\xfa"),
    ]
    empty = Frame(t=0.0, pressure=(0,) * 16, velocity=(0,) * 16, held=(False,) * 16, bank=0)
    for f in frames(events):
        assert (f.pressure, f.velocity, f.held, f.bank) == (
            empty.pressure,
            empty.velocity,
            empty.held,
            empty.bank,
        )


def test_frames_from_fixture() -> None:
    result = list(frames(read_recording(DATA / "basic.jsonl").events))
    assert result[3].pressure[0] == 63
    assert result[3].held[0] is True
    assert result[-1].held[0] is False


def test_osc_values_order_and_normalisation() -> None:
    events: list[Event] = [on(0.0, 52 + 2, 127), press(0.0, 54, 127), on(0.0, 36 + 5, 0)]
    values = list(frames(events))[-1].to_osc_values()
    assert len(values) == 49
    assert values[2] == 1.0
    assert values[16 + 2] == 1.0
    assert values[32 + 2] == 1.0
    assert values[48] == 1.0
    assert all(0.0 <= v <= 1.0 for v in values[:48])
    half = Frame(
        t=0.0, pressure=(0,) * 15 + (127,), velocity=(64,) + (0,) * 15, held=(False,) * 16, bank=3
    )
    hv = half.to_osc_values()
    assert hv[15] == 1.0
    assert hv[16] == pytest.approx(64 / 127)
    assert hv[48] == 3.0
