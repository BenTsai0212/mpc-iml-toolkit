"""Measuring one note: pitch on the sustain, cleanliness, start (#268)."""

from pathlib import Path

import numpy as np
import pytest
from tones import RATE, tone, write

from mpc_iml.sounds.notes import main, measure, measure_file, note_name, note_number


def test_note_names() -> None:
    assert note_name(60) == "C4"
    assert note_name(28) == "E1"
    assert note_number("C4") == 60
    assert note_number("E1") == 28
    assert note_number("F#4") == note_number("Fs4") == 66
    assert note_number("Bb1") == 34
    assert note_number("Bb2") == 46
    assert note_number("c-1") == 0
    assert all(note_number(note_name(n)) == n for n in range(128))
    for bad in ["H2", "C", "4C", "C#b3", ""]:
        with pytest.raises(ValueError):
            note_number(bad)


@pytest.mark.parametrize("pitch", [28.0, 33.08, 40.07, 55.94, 72.03, 84.0])
def test_the_pitch_and_how_far_off_it_is(pitch: float) -> None:
    m = measure(tone(pitch), RATE)
    assert m.note == round(pitch)
    assert m.cents == pytest.approx(100 * (pitch - round(pitch)), abs=2)
    assert m.clean > 0.995
    if pitch >= 40:
        assert m.other is None
    else:
        # Known gap: next to a low note, a side lobe of the analysis window is counted as
        # a weak peak off the harmonics, about 30 dB down. It costs a clean low note up to
        # half a percent of `clean`.
        assert m.other is None or m.other[1] < -25


def test_the_pitch_comes_from_the_sustain_not_the_attack() -> None:
    m = measure(tone(45.0, attack_cents=60), RATE)
    assert m.note == 45
    assert abs(m.cents) < 3
    assert m.attack_cents > 5


def test_the_octave_is_measured() -> None:
    assert measure(tone(note_number("C4") + 12), RATE).name == "C5"


def test_the_start_is_where_the_sound_begins() -> None:
    m = measure(tone(50.0, lead=0.2), RATE)
    assert abs(m.start - int(0.2 * RATE)) <= int(0.003 * RATE)
    assert m.seconds == pytest.approx(2.2)
    assert m.peak_db == pytest.approx(20 * np.log10(np.abs(tone(50.0, lead=0.2)).max()))


def test_a_partial_that_is_not_a_harmonic_makes_a_note_unclean() -> None:
    m = measure(tone(50.0, extra=(2.37, 0.5)), RATE)
    assert m.note == 50
    assert m.clean < 0.985
    assert m.other is not None
    assert m.other[0] == pytest.approx(2.37 * 440.0 * 2 ** ((50 - 69) / 12), rel=0.01)


def test_rich_is_the_energy_around_harmonics_two_to_four() -> None:
    plain = measure(tone(33.0, harmonics=(1.0,)), RATE)
    rich = measure(tone(33.0, harmonics=(0.3, 1.0, 1.0, 1.0)), RATE)
    assert plain.rich < 0.05
    assert rich.rich > 0.5
    assert plain.note == rich.note == 33


def test_the_time_to_fall_twenty_decibels() -> None:
    short = measure(tone(60.0, decay=0.1), RATE)
    long = measure(tone(60.0, decay=2.0, seconds=4.0), RATE)
    assert short.length < 0.4
    assert long.length > 2.0


def test_silent_and_short_recordings_are_refused() -> None:
    with pytest.raises(ValueError, match="silent"):
        measure(np.zeros((RATE, 2), dtype=np.float32), RATE)
    with pytest.raises(ValueError, match="too short"):
        measure(tone(60.0, seconds=0.1), RATE)
    with pytest.raises(ValueError, match="too short"):
        measure(tone(60.0, seconds=0.28, lead=0.0), RATE)


def test_a_file_and_the_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path / "bass-E1.wav", tone(28.04))
    m = measure_file(path)
    assert (m.name, round(m.cents)) == ("E1", 4)
    assert main([str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["file", "note", "Hz", "cents", "clean", "rich", "attack"]
    assert lines[1].split()[:2] == ["bass-E1.wav", "E1"]


def test_the_command_reports_a_file_it_cannot_measure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = write(tmp_path / "keys-C4.wav", tone(60.0))
    silent = write(tmp_path / "silent.wav", np.zeros((RATE, 2), dtype=np.float32))
    assert main([str(silent), str(good)]) == 1
    captured = capsys.readouterr()
    assert "silent.wav: the recording is silent" in captured.err
    assert captured.out.splitlines()[1].split()[:2] == ["keys-C4.wav", "C4"]
