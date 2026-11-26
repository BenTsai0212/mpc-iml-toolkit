"""From recordings of single notes to an SFZ instrument (#270)."""

import struct
from pathlib import Path

import numpy as np
import pytest
from tones import RATE, tone, write

from mpc_iml.sounds import wav
from mpc_iml.sounds.instrument import (
    LEAD,
    Note,
    Region,
    build,
    choose,
    key_ranges,
    main,
    sfz_text,
    trim,
    uncovered,
)
from mpc_iml.sounds.notes import Measurement


def measured(note: int, clean: float = 0.999, rich: float = 0.1) -> Measurement:
    return Measurement(
        start=0,
        frequency=440.0 * 2 ** ((note - 69) / 12),
        note=note,
        cents=0.0,
        clean=clean,
        rich=rich,
        other=None,
        attack_cents=0.0,
        length=1.0,
        seconds=2.0,
        peak_db=-6.0,
    )


def fmt_of(path: Path) -> tuple[int, int, int, int]:
    """The format tag, channels, rate and bits of a WAV file written by `wav.write`."""
    content = path.read_bytes()
    assert content[12:16] == b"fmt "
    tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", content[20:36])
    return tag, channels, rate, bits


@pytest.mark.parametrize("channels", [1, 2])
def test_wav_write_reads_back_within_one_step(tmp_path: Path, channels: int) -> None:
    samples = tone(45.0, seconds=0.5)[:, :channels].copy()
    samples[10, 0] = 1.5
    samples[11, 0] = -1.5
    path = tmp_path / "x.wav"
    wav.write(path, samples, 48000)
    assert fmt_of(path) == (1, channels, 48000, 24)
    back, rate = wav.read(path)
    assert rate == 48000
    assert back.shape == samples.shape
    expected = np.clip(samples, -1.0, 1.0 - 2**-23)
    assert np.abs(back - expected).max() <= 2**-23
    with pytest.raises(wav.WavError):
        wav.write(path, np.zeros((10, 3), dtype=np.float32), RATE)


def test_key_ranges_split_halfway_and_reach_the_ends() -> None:
    assert key_ranges([40]) == [(0, 127)]
    assert key_ranges([28, 33, 38]) == [(0, 30), (31, 35), (36, 127)]
    assert key_ranges([26, 31, 36, 41, 45]) == [(0, 28), (29, 33), (34, 38), (39, 43), (44, 127)]


def test_keys_that_no_note_reaches() -> None:
    assert uncovered([28, 33], 28, 39) == []
    assert uncovered([28, 33], 28, 45) == [(40, 45)]
    assert uncovered([40, 60], 30, 70) == [(30, 33), (47, 53), (67, 70)]
    assert uncovered([40], 30, 50, reach=12) == []


def test_choose_keeps_one_clean_note_for_each_pitch() -> None:
    a = Note(Path("a.wav"), measured(40, clean=0.990))
    b = Note(Path("b.wav"), measured(40, clean=0.999))
    c = Note(Path("c.wav"), measured(45, clean=0.970))
    d = Note(Path("d.wav"), measured(33))
    kept, dropped = choose([a, b, c, d])
    assert kept == [d, b]
    assert [(note.path.name, why.split(":")[0]) for note, why in dropped] == [
        ("a.wav", "another take of E2 is cleaner"),
        ("c.wav", "not clean"),
    ]


def test_choose_can_prefer_the_richer_take() -> None:
    thin = Note(Path("thin.wav"), measured(26, clean=0.999, rich=0.01))
    rich = Note(Path("rich.wav"), measured(26, clean=0.990, rich=0.30))
    assert choose([thin, rich])[0] == [thin]
    kept, dropped = choose([thin, rich], prefer="rich")
    assert kept == [rich]
    assert dropped == [(thin, "another take of D1 is richer")]


def test_trim_cuts_the_silence_and_fades_the_end() -> None:
    samples = tone(50.0, lead=0.2)
    start = int(0.2 * RATE)
    cut = trim(samples, RATE, start)
    assert len(cut) == len(samples) - start + LEAD
    assert np.abs(cut[:LEAD]).max() == 0
    assert np.abs(cut[-1]).max() == 0
    assert np.abs(samples[-1]).max() > 0


def test_the_sfz_text() -> None:
    region = Region("samples/bass-E1.wav", 0, 30, 28, -2, Path("take.wav"), 1.5)
    assert sfz_text("bass", [region], 0.12).splitlines()[2:] == [
        "<global> ampeg_attack=0.002 ampeg_release=0.12 amp_veltrack=85",
        "",
        "<region> sample=samples/bass-E1.wav lokey=0 hikey=30 pitch_keycenter=28 tune=-2",
    ]


def notes_for_a_bass(folder: Path) -> list[Path]:
    return [
        write(folder / "take-1.wav", tone(40.05, lead=0.3)),
        write(folder / "take-2.wav", tone(45.0, level=0.1)),
        write(folder / "take-3.wav", tone(45.0, extra=(2.37, 0.5))),
        write(folder / "take-4.wav", tone(50.0, level=0.9)),
    ]


def test_build_writes_the_instrument(tmp_path: Path) -> None:
    files = notes_for_a_bass(tmp_path)
    out = tmp_path / "bass-set"
    instrument = build("bass", files, out, release=0.12, span=(40, 60))

    assert instrument.path == out / "bass.sfz"
    assert [(r.sample, r.low, r.high, r.centre, r.tune) for r in instrument.regions] == [
        ("samples/bass-E2.wav", 0, 42, 40, -5),
        ("samples/bass-A2.wav", 43, 47, 45, 0),
        ("samples/bass-D3.wav", 48, 127, 50, 0),
    ]
    assert [r.source for r in instrument.regions] == [files[0], files[1], files[3]]
    assert instrument.path.read_text() == sfz_text("bass", instrument.regions, 0.12)
    assert [(p.name, why.split(":")[0]) for p, why in instrument.dropped] == [
        ("take-3.wav", "not clean")
    ]
    assert instrument.uncovered == ((57, 60),)
    assert [n.path for n in instrument.notes] == files
    assert instrument.notes[0].measured.note == 40

    for region in instrument.regions:
        path = out / region.sample
        assert fmt_of(path) == (1, 2, RATE, 24)
        samples, _ = wav.read(path)
        assert np.abs(samples).max() <= 10 ** (-1 / 20) + 1e-6
        loud = np.flatnonzero(np.abs(samples).max(axis=1) > 0.01 * np.abs(samples).max())
        assert loud[0] <= LEAD + int(0.003 * RATE)
    quiet, loud_take = instrument.regions[1], instrument.regions[2]
    assert quiet.gain_db > 0 > loud_take.gain_db


def test_a_mono_source_gives_a_mono_sample(tmp_path: Path) -> None:
    mono = write(tmp_path / "c4.wav", tone(60.0)[:, :1].copy())
    instrument = build("keys", [mono], tmp_path / "out")
    assert [r.sample for r in instrument.regions] == ["samples/keys-C4.wav"]
    assert fmt_of(tmp_path / "out" / "samples" / "keys-C4.wav") == (1, 1, RATE, 24)


def test_sharps_are_written_as_s(tmp_path: Path) -> None:
    instrument = build("keys", [write(tmp_path / "f.wav", tone(66.0))], tmp_path / "out")
    assert [r.sample for r in instrument.regions] == ["samples/keys-Fs4.wav"]


def test_bad_files_are_left_out(tmp_path: Path) -> None:
    silent = write(tmp_path / "silent.wav", np.zeros((RATE, 2), dtype=np.float32))
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not audio")
    keys = build("keys", [write(tmp_path / "c4.wav", tone(60.0)), silent, broken], tmp_path / "o")
    assert [r.centre for r in keys.regions] == [60]
    assert [(p.name, why) for p, why in keys.dropped] == [
        ("silent.wav", "the recording is silent"),
        ("broken.wav", "broken.wav is not a WAV file"),
    ]
    with pytest.raises(ValueError, match="none of the 1 recordings"):
        build("pad", [silent], tmp_path / "o")


def test_the_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = [str(p) for p in notes_for_a_bass(tmp_path)]
    out = tmp_path / "bass-set"
    assert main(["bass", *files, "--out", str(out), "--low", "E2", "--high", "A3"]) == 0
    printed = capsys.readouterr().out
    assert "bass: samples/bass-E2.wav" in printed
    assert "left out take-3.wav: not clean" in printed
    assert "no note within 6 semitones of A3 to A3" in printed
    assert (out / "bass.sfz").exists()

    silent = write(tmp_path / "silent.wav", np.zeros((RATE, 2), dtype=np.float32))
    assert main(["pad", str(silent), "--out", str(out)]) == 1
    assert "none of the 1 recordings can be used" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["pad", str(silent), "--out", str(out), "--low", "C2"])
