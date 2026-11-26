"""Which notes of the band an instrument plays: part, keys, velocity, octave (#274)."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from test_sounds_instrument import measured, notes_for_a_bass
from test_sounds_soundset import document, snapshot, two_instruments
from tones import tone, write

from mpc_iml.sounds import instrument, soundset
from mpc_iml.sounds.instrument import build, describe, main, report
from mpc_iml.sounds.soundset import FILE, Plays, SoundSetError, load

DEFAULT = {"part": None, "keys": [0, 127], "min_velocity": 1, "octave": 0}


def notes(folder: Path, *pitches: int) -> list[Path]:
    return [write(folder / f"n{p}.wav", tone(float(p))) for p in pitches]


def region_lines(sfz: Path) -> list[tuple[str, int, int, int, int]]:
    """Each `<region>` line of `sfz` as (sample, lokey, hikey, pitch_keycenter, tune)."""
    found = []
    for line in sfz.read_text(encoding="utf-8").splitlines():
        if line.startswith("<region>"):
            values = dict(re.findall(r"(\w+)=(\S+)", line))
            found.append(
                (
                    values["sample"],
                    int(values["lokey"]),
                    int(values["hikey"]),
                    int(values["pitch_keycenter"]),
                    int(values["tune"]),
                )
            )
    return found


def test_the_defaults_write_what_build_wrote_before(tmp_path: Path) -> None:
    out = tmp_path / "band"
    bass = build("bass", notes_for_a_bass(tmp_path), out, release=0.12)
    assert bass.path.read_text(encoding="utf-8") == (
        "// bass: one region for each recorded note.\n"
        "// pitch_keycenter and tune come from the measured pitch of each note.\n"
        "<global> ampeg_attack=0.002 ampeg_release=0.12 amp_veltrack=85\n"
        "\n"
        "<region> sample=samples/bass-E2.wav lokey=0 hikey=42 pitch_keycenter=40 tune=-5\n"
        "<region> sample=samples/bass-A2.wav lokey=43 hikey=47 pitch_keycenter=45 tune=0\n"
        "<region> sample=samples/bass-D3.wav lokey=48 hikey=127 pitch_keycenter=50 tune=0\n"
    )
    assert bass.plays == Plays()
    assert document(out)["instruments"]["bass"]["plays"] == DEFAULT
    assert report(bass).splitlines()[0].startswith("bass: samples/bass-E2.wav")

    other = build("bass", notes_for_a_bass(tmp_path), tmp_path / "other", release=0.12, part="bass")
    assert [r.sample for r in other.regions] == [r.sample for r in bass.regions]
    for region in bass.regions:
        assert (out / region.sample).read_bytes() == (
            tmp_path / "other" / region.sample
        ).read_bytes()


def test_octave_moves_the_centres_and_splits_the_keys_between_them(tmp_path: Path) -> None:
    out = tmp_path / "band"
    bass = build("bass", notes(tmp_path, 28, 33, 38), out, octave=1, part="bass")
    assert [(r.low, r.high, r.centre) for r in bass.regions] == [
        (0, 18, 16),
        (19, 23, 21),
        (24, 127, 26),
    ]
    assert [r.sample for r in bass.regions] == [
        "samples/bass-E1.wav",
        "samples/bass-A1.wav",
        "samples/bass-D2.wav",
    ]
    assert region_lines(bass.path)[1][1:4] == (19, 23, 21)
    assert document(out)["instruments"]["bass"]["plays"] == DEFAULT | {
        "part": "bass",
        "octave": 1,
    }
    assert report(bass).splitlines()[0] == (
        "bass: plays the bass part, 1 octave above the notes it is sent"
    )


def test_an_octave_off_the_keyboard_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = notes(tmp_path, 84)
    with pytest.raises(ValueError, match=r"octave -4 moves C6 \(84\) to 132, off the keyboard"):
        build("bell", files, tmp_path / "new", octave=-4)
    assert not (tmp_path / "new").exists()
    # A tone at note 100 is above what `measure` reads as a fundamental (2500 Hz), so the
    # measurement of a note at 100 is given here.
    monkeypatch.setattr(instrument, "measure", lambda samples, rate: measured(100))
    with pytest.raises(ValueError, match=r"octave -4 moves E7 \(100\) to 148, off the keyboard"):
        build("bell", files, tmp_path / "new", octave=-4)
    assert not (tmp_path / "new").exists()
    assert build("bell", files, tmp_path / "new", octave=2).regions[0].centre == 76
    monkeypatch.undo()

    out, *_ = two_instruments(tmp_path)
    before = snapshot(out)
    with pytest.raises(ValueError, match="off the keyboard"):
        build("bell", files, out, octave=-4)
    assert snapshot(out) == before


def test_keys_cut_the_ranges_and_leave_out_a_note_outside_them(tmp_path: Path) -> None:
    out = tmp_path / "band"
    files = notes(tmp_path, 62, 67, 79, 84)
    bell = build("bell", files, out, keys=(72, 127), part="melody")
    assert [(r.low, r.high, r.centre) for r in bell.regions] == [
        (72, 73, 67),
        (74, 81, 79),
        (82, 127, 84),
    ]
    assert [(p.name, why) for p, why in bell.dropped] == [
        (
            "n62.wav",
            "it would play keys 0 to 64, outside the keys the instrument plays, C5 to G9 (72-127)",
        )
    ]
    assert not (out / "samples/bell-D4.wav").exists()
    assert sorted(p.name for p in (out / "samples").iterdir()) == [
        "bell-C6.wav",
        "bell-G4.wav",
        "bell-G5.wav",
    ]
    entry = document(out)["instruments"]["bell"]
    assert entry["plays"] == DEFAULT | {"part": "melody", "keys": [72, 127]}
    assert "C5 to G9" in entry["files"][0]["left_out"]
    assert soundset.problems(out) == []


def test_min_velocity_goes_on_the_global_line(tmp_path: Path) -> None:
    files = notes(tmp_path, 48, 55)
    pad = build("pad", files, tmp_path / "a", min_velocity=86)
    lines = pad.path.read_text(encoding="utf-8").splitlines()
    assert lines[2] == "// plays notes hit at velocity 86 or more."
    assert lines[3] == "<global> ampeg_attack=0.002 ampeg_release=0.25 amp_veltrack=85 lovel=86"
    plain = build("pad", files, tmp_path / "b", min_velocity=1)
    assert "lovel" not in plain.path.read_text(encoding="utf-8")


def test_the_keys_no_note_reaches_are_counted_in_the_span_and_the_keys(tmp_path: Path) -> None:
    files = notes(tmp_path, 28, 33)
    bass = build("bass", files, tmp_path / "a", octave=1, span=(16, 33))
    assert bass.uncovered == ((28, 33),)
    cut = build("bass", files, tmp_path / "b", octave=1, span=(16, 33), keys=(16, 24))
    assert cut.uncovered == ()
    apart = build("bass", files, tmp_path / "c", octave=1, span=(16, 33), keys=(40, 60))
    assert apart.uncovered == ()


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"part": "drums"}, "part must be"),
        ({"keys": (0, 128)}, "keys must be from 0 to 127"),
        ({"keys": (80, 72)}, "above the high key"),
        ({"min_velocity": 0}, "min_velocity must be from 1 to 127"),
        ({"octave": 5}, "octave must be from -4 to 4"),
    ],
)
def test_build_refuses_values_out_of_range(
    tmp_path: Path, values: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build("bass", notes(tmp_path, 40), tmp_path / "out", **values)
    assert not (tmp_path / "out").exists()


def _no_plays(plays: dict[str, Any], entry: dict[str, Any]) -> None:
    del entry["plays"]


def _set(key: str, value: object) -> Any:
    def spoil(plays: dict[str, Any], entry: dict[str, Any]) -> None:
        plays[key] = value

    return spoil


@pytest.mark.parametrize(
    ("spoil", "problem"),
    [
        (_no_plays, "instruments.bass.plays: missing"),
        (_set("part", "drums"), "instruments.bass.plays.part: must be 'bass', 'melody' or null"),
        (_set("part", 1), "instruments.bass.plays.part: must be 'bass', 'melody' or null"),
        (_set("keys", [0, 128]), "instruments.bass.plays.keys: must be from 0 to 127"),
        (_set("keys", [-1, 127]), "instruments.bass.plays.keys: must be from 0 to 127"),
        (_set("keys", [80, 72]), "instruments.bass.plays.keys: low is above high"),
        (_set("keys", 72), "instruments.bass.plays.keys: must be [low, high]"),
        (_set("min_velocity", 0), "instruments.bass.plays.min_velocity: must be from 1 to 127"),
        (_set("min_velocity", 128), "instruments.bass.plays.min_velocity: must be from 1 to 127"),
        (_set("octave", 5), "instruments.bass.plays.octave: must be from -4 to 4"),
        (_set("octave", 1.0), "instruments.bass.plays.octave: must be a whole number"),
        (_set("channel", 2), "instruments.bass.plays.channel: unknown field"),
    ],
)
def test_check_names_each_problem_of_plays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], spoil: Any, problem: str
) -> None:
    out, *_ = two_instruments(tmp_path)
    data = document(out)
    entry = data["instruments"]["bass"]
    spoil(entry["plays"], entry)
    (out / FILE).write_text(json.dumps(data), encoding="utf-8")
    assert soundset.main(["check", str(out)]) == 1
    assert problem in capsys.readouterr().err
    with pytest.raises(SoundSetError, match="cannot be accepted"):
        load(out)
    with pytest.raises(SoundSetError):
        build("keys", notes(tmp_path, 60), out)


def test_load_returns_what_each_instrument_plays_and_the_regions_of_its_sfz(
    tmp_path: Path,
) -> None:
    out = tmp_path / "band"
    build("keys", notes(tmp_path, 48, 55, 62, 67), out, keys=(0, 71), part="melody")
    build("bell", notes(tmp_path, 62, 67, 79, 84), out, keys=(72, 127), part="melody")
    build("pad", notes(tmp_path, 48, 60), out, min_velocity=86, part="melody")
    build("bass", notes(tmp_path, 28, 33, 38), out, octave=1, part="bass")
    loaded = load(out)
    assert {name: i.plays for name, i in loaded.instruments.items()} == {
        "keys": Plays("melody", (0, 71)),
        "bell": Plays("melody", (72, 127)),
        "pad": Plays("melody", min_velocity=86),
        "bass": Plays("bass", octave=1),
    }
    for each in loaded.instruments.values():
        assert [
            (str(r.sample.relative_to(out)), r.low, r.high, r.centre, r.tune) for r in each.regions
        ] == region_lines(each.sfz)


def test_the_command_takes_what_the_instrument_plays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = [str(p) for p in notes(tmp_path, 62, 67, 79, 84)]
    out = tmp_path / "band"
    args = ["bell", *files, "--out", str(out), "--part", "melody", "--keys", "C5", "G9"]
    assert main([*args, "--min-velocity", "86", "--octave", "1"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == (
        "bell: plays the melody part, keys C5 to G9 (72-127), notes hit at velocity 86 "
        "or more, 1 octave above the notes it is sent"
    )
    assert document(out)["instruments"]["bell"]["plays"] == {
        "part": "melody",
        "keys": [72, 127],
        "min_velocity": 86,
        "octave": 1,
    }
    for bad in (
        ["--keys", "G9", "C5"],
        ["--keys", "C5"],
        ["--keys", "C5", "C10"],
        ["--min-velocity", "0"],
        ["--octave", "5"],
        ["--part", "drums"],
    ):
        with pytest.raises(SystemExit):
            main(["bell", *files, "--out", str(tmp_path / "bad"), *bad])
    assert "above the high key" not in capsys.readouterr().out
    assert not (tmp_path / "bad").exists()


def test_describe() -> None:
    assert describe(Plays()) == ""
    assert describe(Plays(octave=-2)) == "2 octaves below the notes it is sent"
