"""Audition a band with a sound set (#278, RFC 0006 step 2): synthetic tones only."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from tones import RATE, tone, write

from mpc_iml.bands import Band, load_bands
from mpc_iml.sounds import audition, soundset, wav
from mpc_iml.sounds.audition import AuditionError, Played, main, play, played, render_notes
from mpc_iml.sounds.hits import make_hit
from mpc_iml.sounds.instrument import build
from mpc_iml.sounds.notes import measure
from mpc_iml.sounds.soundset import SetInstrument
from mpc_iml.webdemo import sim

STEP = 2.0**-23
"""One 24-bit step."""


def instrument(
    tmp_path: Path, out: Path, name: str, pitches: list[float], **options: Any
) -> SetInstrument:
    """Build `name` into the set `out` from tones at `pitches`; it plays the melody
    part unless `options` say otherwise."""
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    files = [write(source / f"{name}-{p}.wav", tone(p)) for p in pitches]
    options.setdefault("part", "melody")
    build(name, files, out, **options)
    return soundset.load(out).instruments[name]


def hit(tmp_path: Path, out: Path, name: str, pitch: float) -> None:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    path = write(source / f"hit-{name}.wav", tone(pitch, seconds=0.3, decay=0.03, lead=0.01))
    make_hit(name, path, out, seconds=0.1)


def render(i: SetInstrument, *notes: Played, seconds: float = 2.0) -> np.ndarray[Any, Any]:
    return render_notes(i, list(notes), RATE, round(seconds * RATE))


def db(samples: np.ndarray[Any, Any]) -> float:
    return 20 * float(np.log10(np.sqrt(np.mean(samples.astype(np.float64) ** 2))))


@pytest.mark.parametrize(("octave", "sent"), [(0, 50), (1, 38)])
def test_a_note_sounds_at_its_pitch(tmp_path: Path, octave: int, sent: int) -> None:
    """The tone at 48 is 20 cents sharp, so `tune` must be applied too."""
    keys = instrument(tmp_path, tmp_path / "set", "keys", [48.2, 55.0, 60.0], octave=octave)
    out = render(keys, Played(0.0, 1.0, sent, 100))
    m = measure(out, RATE)
    assert m.note == 50
    assert abs(m.cents) < 3


def test_keys_and_min_velocity_choose_the_instrument(tmp_path: Path) -> None:
    out = tmp_path / "set"
    low = instrument(tmp_path, out, "low", [60.0], keys=(0, 71))
    high = instrument(tmp_path, out, "high", [76.0], keys=(72, 127))
    pad = instrument(tmp_path, out, "pad", [60.0], min_velocity=86)
    at_60, at_76 = Played(0.0, 0.5, 60, 100), Played(0.0, 0.5, 76, 100)
    assert np.abs(render(low, at_60)).max() > 0.01
    assert np.abs(render(high, at_60)).max() == 0
    assert np.abs(render(low, at_76)).max() == 0
    assert np.abs(render(high, at_76)).max() > 0.01
    assert np.abs(render(pad, Played(0.0, 0.5, 60, 80))).max() == 0
    assert np.abs(render(pad, Played(0.0, 0.5, 60, 90))).max() > 0.01


def test_the_level_follows_velocity_in_db(tmp_path: Path) -> None:
    keys = instrument(tmp_path, tmp_path / "set", "keys", [60.0])
    loud = render(keys, Played(0.0, 1.0, 60, 127))
    soft = render(keys, Played(0.0, 1.0, 60, 64))
    assert db(loud) - db(soft) == pytest.approx(16 * 63 / 127, abs=0.2)
    assert audition.level(127) == 1.0
    assert audition.level(0) == pytest.approx(10 ** (-16 / 20))


def test_a_note_ends_and_fades_over_the_release(tmp_path: Path) -> None:
    keys = instrument(tmp_path, tmp_path / "set", "keys", [60.0], release=0.1)
    out = render(keys, Played(0.1, 0.5, 60, 100))
    silent = round((0.1 + 0.5 + 0.1) * RATE)
    assert np.abs(out[silent:]).max() == 0
    assert np.abs(out[silent - round(0.06 * RATE) : silent]).max() > 0.001
    assert np.abs(out[: round(0.1 * RATE)]).max() == 0


def test_a_note_of_the_same_pitch_ends_the_one_before(tmp_path: Path) -> None:
    keys = instrument(tmp_path, tmp_path / "set", "keys", [60.0], release=0.1)
    second = Played(0.2, 0.5, 60, 100)
    both = render(keys, Played(0.0, 1.0, 60, 100), second)
    cut = render(keys, Played(0.0, 0.2, 60, 100)) + render(keys, second)
    assert np.allclose(both, cut, atol=1e-6)
    other = render(keys, Played(0.0, 1.0, 60, 100), Played(0.2, 0.5, 64, 100))
    assert np.abs(other[round(0.9 * RATE) : round(1.0 * RATE)]).max() > 0.001


def _onsets(samples: np.ndarray[Any, Any], times: list[float]) -> list[float]:
    """The first frame near each of `times` within 40 dB of the peak, in seconds."""
    level = np.abs(samples).max(axis=1)
    threshold = level.max() * 10 ** (-40 / 20)
    found = []
    for t in times:
        lo, hi = round((t - 0.01) * RATE), round((t + 0.01) * RATE)
        assert level[lo : round((t - 0.002) * RATE)].max() < threshold
        found.append((lo + int(np.argmax(level[lo:hi] >= threshold))) / RATE)
    return found


def test_hits_start_at_their_steps(tmp_path: Path) -> None:
    out = tmp_path / "set"
    hit(tmp_path, out, "kick", 40.0)
    hit(tmp_path, out, "snare", 64.0)
    grid = [{"kick": [100 if s in (0, 6, 11) else 0 for s in range(16)], "hat": [90] * 16}]
    song = sim.simulate(grid, sim.Settings(tempo=120.0))
    notes = played(song)
    assert len(notes["hat"]) == 16
    loaded = soundset.load(out)
    drums = audition.render_hits(loaded, {"kick": notes["kick"]}, RATE, round(song.seconds * RATE))
    step = 60 / 120 / 4
    expected = [s * step for s in (0, 6, 11)]
    for found, t in zip(_onsets(drums, expected[1:]), expected[1:], strict=True):
        assert abs(found - t) <= 0.002
    assert abs(_first(drums) - expected[0]) <= 0.002
    result = audition.audition(song, loaded)
    assert result.silent == ("hat",)
    assert np.array_equal(result.drums, drums * np.float32(result.gain))


def _first(samples: np.ndarray[Any, Any]) -> float:
    level = np.abs(samples).max(axis=1)
    return int(np.argmax(level >= level.max() * 10 ** (-40 / 20))) / RATE


def a_set(tmp_path: Path, band: Band, without: tuple[str, ...] = ()) -> Path:
    """A set with an instrument for each player of `band` (built with what it plays,
    from one tone in its keys) and three hits."""
    out = tmp_path / "set"
    for p in band.players:
        if p.name in without:
            continue
        low, high = p.plays.keys
        centre = min(max(60, low), high)
        instrument(
            tmp_path,
            out,
            p.name,
            [float(centre + 12 * p.plays.octave)],
            part=p.plays.part,
            keys=p.plays.keys,
            min_velocity=p.plays.min_velocity,
            octave=p.plays.octave,
            release=p.release,
        )
    for name, pitch in (("kick", 36.0), ("snare", 62.0), ("hat", 90.0)):
        hit(tmp_path, out, name, pitch)
    return out


def _read(folder: Path) -> dict[str, np.ndarray[Any, Any]]:
    found = {}
    for path in sorted(folder.glob("*.wav")):
        samples, rate = wav.read(path)
        assert rate == RATE
        found[path.stem] = samples.astype(np.float64)
    return found


@pytest.mark.parametrize("name", ["lofi", "trap"])
def test_each_band_renders_with_a_set_for_its_players(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    band = load_bands()[name]
    folder = a_set(tmp_path, band)
    out = tmp_path / "out"
    assert main([name, str(folder), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    files = _read(out)
    assert set(files) == {p.name for p in band.players} | {"drums", "band"}
    song = play(band)
    longest = max(p.release for p in band.players)
    frames = round(song.seconds * RATE) + round(longest * RATE)
    assert {len(x) for x in files.values()} == {frames}
    singles = [x for stem, x in files.items() if stem != "band"]
    assert np.abs(sum(singles) - files["band"]).max() <= len(singles) * STEP
    peak = 20 * np.log10(np.abs(files["band"]).max())
    assert peak == pytest.approx(-1.0, abs=0.1)
    assert "bass: 0 note(s) no instrument played" in printed
    assert "melody: 0 note(s) no instrument played" in printed
    assert "has no instrument" not in printed
    assert "no hit" not in printed
    assert printed.count("wrote ") == len(files)
    for p in band.players:
        assert np.abs(files[p.name]).max() > 0.001, p.name


def test_a_set_without_the_pad_still_renders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    band = load_bands()["lofi"]
    folder = a_set(tmp_path, band, without=("pad",))
    instrument(tmp_path, folder, "spare", [60.0], part=None)
    (folder / "hits" / "hat.wav").unlink()
    document = soundset.read_document(folder)
    del document["hits"]["hat"]
    soundset.write_document(folder, document)
    out = tmp_path / "out"
    assert main(["lofi", str(folder), "--out", str(out), "--bars", "4"]) == 0
    printed = capsys.readouterr().out
    assert "lofi: player 'pad' has no instrument of its name in the set" in printed
    assert "spare: plays no part (part is null), skipped" in printed
    assert "hat: no hit in the set, silent" in printed
    assert "bass: 0 note(s) no instrument played" in printed
    assert sorted(p.stem for p in out.glob("*.wav")) == ["band", "bass", "drums", "keys", "vibes"]


def test_bars_play_only_the_first_bars(tmp_path: Path) -> None:
    band = load_bands()["lofi"]
    folder = a_set(tmp_path, band)
    out = tmp_path / "out"
    assert main(["lofi", str(folder), "--out", str(out), "--bars", "8"]) == 0
    expected = round((8 + 1) * 4 * 60 / band.tempo * RATE) + round(0.5 * RATE)
    for samples in _read(out).values():
        assert abs(len(samples) - expected) <= 1


def test_two_sample_rates_are_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "set"
    instrument(tmp_path, out, "keys", [60.0])
    source = tmp_path / "source" / "bass-48k.wav"
    write(source, tone(48.0), rate=48000)
    build("bass", [source], out, part="bass")
    with pytest.raises(AuditionError, match="44100 Hz .* and 48000 Hz"):
        audition.rate_of(soundset.load(out))
    assert main(["lofi", str(out), "--out", str(tmp_path / "out"), "--bars", "1"]) == 1
    err = capsys.readouterr().err
    assert "44100 Hz" in err and "48000 Hz" in err
    assert not (tmp_path / "out").exists()


def test_an_unknown_band_is_refused_with_the_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["jazz", str(tmp_path), "--out", str(tmp_path / "out")]) == 1
    assert "no built-in band 'jazz'; bands: lofi, trap" in capsys.readouterr().err
