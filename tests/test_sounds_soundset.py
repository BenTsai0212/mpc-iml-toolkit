"""Sound set folders: `sound-set.json`, drum hits and the check command (#272, ADR 0013)."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from test_sounds_instrument import notes_for_a_bass
from tones import RATE, tone, write

from mpc_iml.sounds import hits, instrument, soundset, wav
from mpc_iml.sounds.hits import make_hit, prepare_hit
from mpc_iml.sounds.instrument import LEAD, Instrument, build
from mpc_iml.sounds.soundset import FILE, Origin, SoundSetError, load

GENERATED = Origin("generated", "some-model", "a round bass note, E2", 7, {"steps": 40})


def document(folder: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((folder / FILE).read_text(encoding="utf-8"))
    return data


def snapshot(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()
    }


def two_instruments(tmp_path: Path) -> tuple[Path, list[Path], list[Path], Instrument, Instrument]:
    out = tmp_path / "band"
    bass_files = notes_for_a_bass(tmp_path)
    silent = write(tmp_path / "silent.wav", np.zeros((RATE, 2), dtype=np.float32))
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not audio")
    keys_files = [
        write(tmp_path / "c4.wav", tone(60.0)),
        write(tmp_path / "g4.wav", tone(67.0)),
        silent,
        broken,
    ]
    bass = build(
        "bass", bass_files, out, release=0.12, span=(40, 60), origins={bass_files[0]: GENERATED}
    )
    keys = build("keys", keys_files, out, prefer="rich")
    return out, bass_files, keys_files, bass, keys


def entry_matches(entry: dict[str, Any], built: Instrument, files: list[Path]) -> None:
    assert entry["sfz"] == built.path.name
    assert [f["file"] for f in entry["files"]] == [p.name for p in files]
    measured = {n.path.name: n.measured for n in built.notes}
    regions = {r.source.name: r for r in built.regions}
    why = {p.name: reason for p, reason in built.dropped}
    for f in entry["files"]:
        if f["file"] in measured:
            m = measured[f["file"]]
            assert f["measured"]["note"] == m.note
            assert f["measured"]["clean"] == m.clean
            assert f["measured"]["start"] == m.start
            assert set(f["measured"]) == set(soundset.MEASURED)
        else:
            assert "measured" not in f
        if f["file"] in regions:
            r = regions[f["file"]]
            assert "left_out" not in f
            assert f["region"] == {
                "sample": r.sample,
                "low": r.low,
                "high": r.high,
                "centre": r.centre,
                "tune": r.tune,
                "gain_db": r.gain_db,
            }
        else:
            assert "region" not in f
            assert f["left_out"] == why[f["file"]]
    assert entry["uncovered"] == [list(gap) for gap in built.uncovered]


def test_two_instruments_are_recorded_in_one_file(tmp_path: Path) -> None:
    out, bass_files, keys_files, bass, keys = two_instruments(tmp_path)
    data = document(out)
    assert data["format"] == "mpc-iml-sound-set"
    assert data["format_version"] == 1
    assert sorted(data["instruments"]) == ["bass", "keys"]
    assert data["hits"] == {}
    entry_matches(data["instruments"]["bass"], bass, bass_files)
    entry_matches(data["instruments"]["keys"], keys, keys_files)
    assert data["instruments"]["bass"]["settings"] == {
        "prefer": "clean",
        "release": 0.12,
        "clean": 0.985,
    }
    assert data["instruments"]["bass"]["span"] == [40, 60]
    assert data["instruments"]["keys"]["span"] is None
    assert data["instruments"]["keys"]["settings"]["prefer"] == "rich"
    by_file = {f["file"]: f for f in data["instruments"]["keys"]["files"]}
    assert by_file["silent.wav"] == {"file": "silent.wav", "left_out": "the recording is silent"}
    assert by_file["broken.wav"]["left_out"] == "broken.wav is not a WAV file"
    assert soundset.problems(out) == []


def test_load_reads_a_built_folder_back(tmp_path: Path) -> None:
    out, bass_files, _, bass, keys = two_instruments(tmp_path)
    make_hit(
        "kick", write(tmp_path / "kick-take-2.wav", tone(36.0, decay=0.05)), out, origin=Origin()
    )
    loaded = load(out)
    assert loaded.instruments["bass"].sfz == out / "bass.sfz"
    assert [
        (r.sample, r.low, r.high, r.centre, r.tune, r.file)
        for r in loaded.instruments["bass"].regions
    ] == [(out / r.sample, r.low, r.high, r.centre, r.tune, r.source.name) for r in bass.regions]
    assert [r.centre for r in loaded.instruments["keys"].regions] == [
        r.centre for r in keys.regions
    ]
    assert loaded.instruments["bass"].span == (40, 60)
    assert loaded.instruments["bass"].uncovered == bass.uncovered
    assert loaded.instruments["bass"].regions[0].origin == GENERATED
    assert loaded.instruments["bass"].regions[1].origin is None
    kick = loaded.hits["kick"]
    assert (kick.sample, kick.file, kick.origin) == (
        out / "hits/kick.wav",
        "kick-take-2.wav",
        Origin(),
    )
    assert document(out)["hits"]["kick"]["origin"] == {"kind": "recorded"}
    assert document(out)["instruments"]["bass"]["files"][0]["origin"] == GENERATED.to_json()


def test_building_again_replaces_the_entry_and_its_unused_samples(tmp_path: Path) -> None:
    out, bass_files, keys_files, _, keys = two_instruments(tmp_path)
    make_hit("kick", write(tmp_path / "kick.wav", tone(36.0, decay=0.05)), out)
    assert (out / "samples/bass-A2.wav").exists()
    others = {
        k: v for k, v in snapshot(out).items() if not k.startswith(("bass", "samples/bass", FILE))
    }
    before = document(out)

    again = build("bass", [bass_files[0], bass_files[3]], out)
    data = document(out)
    entry_matches(data["instruments"]["bass"], again, [bass_files[0], bass_files[3]])
    assert data["instruments"]["keys"] == before["instruments"]["keys"]
    assert data["hits"] == before["hits"]
    assert not (out / "samples/bass-A2.wav").exists()
    assert (out / "samples/bass-E2.wav").exists()
    assert (out / "samples/bass-D3.wav").exists()
    after = {
        k: v for k, v in snapshot(out).items() if not k.startswith(("bass", "samples/bass", FILE))
    }
    assert after == others
    assert soundset.problems(out) == []


def test_a_drum_hit_is_cut_and_levelled(tmp_path: Path) -> None:
    samples = tone(36.0, lead=0.1, decay=0.05, level=0.2)
    hit, gain_db = prepare_hit(samples, RATE, 0.3)
    assert len(hit) == int(0.3 * RATE)
    assert 20 * np.log10(np.abs(hit).max()) == pytest.approx(-3, abs=0.01)
    assert np.abs(hit[-1]).max() == 0
    level = np.abs(hit).max(axis=1)
    assert level[:LEAD].max() < 0.01 * level.max() <= level[LEAD]
    assert gain_db > 0
    with pytest.raises(ValueError, match="silent"):
        prepare_hit(np.zeros((RATE, 2), dtype=np.float32), RATE, 0.3)

    out = tmp_path / "band"
    made = make_hit(
        "kick", write(tmp_path / "kick-take-2.wav", samples[:, :1].copy()), out, seconds=0.3
    )
    written, rate = wav.read(out / "hits/kick.wav")
    assert (rate, written.shape) == (RATE, (int(0.3 * RATE), 1))
    assert 20 * np.log10(np.abs(written).max()) == pytest.approx(-3, abs=0.01)
    assert np.abs(written[-1]).max() == 0
    assert document(out)["hits"]["kick"] == {
        "sample": "hits/kick.wav",
        "file": "kick-take-2.wav",
        "seconds": pytest.approx(0.3),
        "gain_db": made.gain_db,
    }
    assert load(out).hits["kick"].seconds == pytest.approx(0.3)


def test_the_hit_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "band"
    kick = write(tmp_path / "kick.wav", tone(36.0, decay=0.05))
    assert hits.main(["kick", str(kick), "--out", str(out)]) == 0
    assert capsys.readouterr().out.startswith("kick: hits/kick.wav  0.50 s  level ")
    silent = write(tmp_path / "silent.wav", np.zeros((RATE, 2), dtype=np.float32))
    assert hits.main(["snare", str(silent), "--out", str(out)]) == 1
    assert "the recording is silent" in capsys.readouterr().out
    assert hits.main(["Snare", str(kick), "--out", str(out)]) == 1
    assert "not a name" in capsys.readouterr().out
    assert sorted(document(out)["hits"]) == ["kick"]


def test_an_instrument_name_must_be_a_name(tmp_path: Path) -> None:
    files = notes_for_a_bass(tmp_path)
    for name in ("Bass", "bass_1", "../bass", ""):
        with pytest.raises(ValueError, match="not a name"):
            build(name, files, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_a_bad_file_stops_both_commands_before_they_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, bass_files, *_ = two_instruments(tmp_path)
    data = document(out)
    data["instruments"]["keys"]["colour"] = "warm"
    (out / FILE).write_text(json.dumps(data), encoding="utf-8")
    before = snapshot(out)
    kick = write(tmp_path / "kick.wav", tone(36.0, decay=0.05))
    files = [str(p) for p in bass_files[:2]]
    assert instrument.main(["bass", *files, "--out", str(out)]) == 1
    assert "instruments.keys.colour: unknown field" in capsys.readouterr().out
    assert hits.main(["kick", str(kick), "--out", str(out)]) == 1
    assert "instruments.keys.colour: unknown field" in capsys.readouterr().out
    assert snapshot(out) == before
    with pytest.raises(SoundSetError):
        load(out)


def _missing_sample(out: Path, data: dict[str, Any]) -> None:
    (out / "samples/bass-E2.wav").unlink()


def _missing_sfz(out: Path, data: dict[str, Any]) -> None:
    (out / "keys.sfz").unlink()


def _unknown_field(out: Path, data: dict[str, Any]) -> None:
    data["instruments"]["bass"]["files"][0]["region"]["velocity"] = 100


def _wrong_format(out: Path, data: dict[str, Any]) -> None:
    data["format"] = "prompt-a-band-kit"


def _wrong_version(out: Path, data: dict[str, Any]) -> None:
    data["format_version"] = 2


def _both(out: Path, data: dict[str, Any]) -> None:
    data["instruments"]["bass"]["files"][0]["left_out"] = "too dull"


def _absolute(out: Path, data: dict[str, Any]) -> None:
    data["instruments"]["bass"]["files"][0]["region"]["sample"] = str(out / "samples/bass-E2.wav")


def _leaves(out: Path, data: dict[str, Any]) -> None:
    data["instruments"]["keys"]["sfz"] = "../keys.sfz"


def _hit_leaves(out: Path, data: dict[str, Any]) -> None:
    data["hits"]["kick"]["sample"] = "hits/../../kick.wav"


def _separator(out: Path, data: dict[str, Any]) -> None:
    data["instruments"]["bass"]["files"][1]["file"] = "takes/take-2.wav"


def _no_prompt(out: Path, data: dict[str, Any]) -> None:
    del data["instruments"]["bass"]["files"][0]["origin"]["prompt"]


@pytest.mark.parametrize(
    ("spoil", "problem"),
    [
        (
            _missing_sample,
            "instruments.bass.files[0].region.sample: samples/bass-E2.wav is missing",
        ),
        (_missing_sfz, "instruments.keys.sfz: keys.sfz is missing"),
        (_unknown_field, "instruments.bass.files[0].region.velocity: unknown field"),
        (_wrong_format, "format: must be 'mpc-iml-sound-set', not 'prompt-a-band-kit'"),
        (_wrong_version, "format_version: must be 1, not 2"),
        (_both, "instruments.bass.files[0]: has both region and left_out"),
        (_absolute, "instruments.bass.files[0].region.sample: "),
        (_leaves, "instruments.keys.sfz: ../keys.sfz leaves the folder"),
        (_hit_leaves, "hits.kick.sample: hits/../../kick.wav leaves the folder"),
        (_separator, "instruments.bass.files[1].file: takes/take-2.wav holds a path separator"),
        (_no_prompt, "instruments.bass.files[0].origin.prompt: missing"),
    ],
)
def test_check_names_each_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], spoil: Any, problem: str
) -> None:
    out, *_ = two_instruments(tmp_path)
    make_hit("kick", write(tmp_path / "kick.wav", tone(36.0, decay=0.05)), out)
    assert soundset.main(["check", str(out)]) == 0
    assert "ok, 2 instrument(s) with 5 region(s), 1 hit(s)" in capsys.readouterr().out
    data = document(out)
    spoil(out, data)
    (out / FILE).write_text(json.dumps(data), encoding="utf-8")
    assert soundset.main(["check", str(out)]) == 1
    errors = capsys.readouterr().err
    assert problem in errors
    with pytest.raises(SoundSetError, match="cannot be accepted"):
        load(out)


def test_check_reports_every_problem_and_a_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert soundset.main(["check", str(tmp_path)]) == 1
    assert f"no {FILE} in" in capsys.readouterr().err
    (tmp_path / FILE).write_text("{", encoding="utf-8")
    assert soundset.main(["check", str(tmp_path)]) == 1
    assert "not JSON" in capsys.readouterr().err
    data = soundset.empty() | {"format_version": 3, "extra": 1}
    (tmp_path / FILE).write_text(json.dumps(data), encoding="utf-8")
    assert soundset.main(["check", str(tmp_path)]) == 1
    assert len(capsys.readouterr().err.splitlines()) == 2


def test_origins() -> None:
    assert Origin().to_json() == {"kind": "recorded"}
    assert Origin.from_json(GENERATED.to_json()) == GENERATED
    with pytest.raises(ValueError, match="prompt"):
        Origin("generated", "some-model").to_json()
    assert (
        soundset.validate(
            soundset.empty()
            | {
                "hits": {
                    "kick": {
                        "sample": "hits/kick.wav",
                        "file": "k.wav",
                        "seconds": 0.5,
                        "gain_db": 0.0,
                        "origin": {
                            "kind": "generated",
                            "model": "m",
                            "prompt": "p",
                            "seed": 1,
                            "settings": {"anything": [1, {"x": None}]},
                        },
                    }
                }
            }
        )
        == []
    )
