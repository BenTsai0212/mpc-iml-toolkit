"""Band files: format, checks, the audition through the simulation (#276, ADR 0014)."""

import ast
import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from mpc_iml import bands
from mpc_iml.bands import Band, load_bands, main, parse_band
from mpc_iml.content import ContentError
from mpc_iml.plays import problems
from mpc_iml.sounds import soundset
from mpc_iml.webdemo import sim

FOLDER = Path(bands.__file__).parent / "bands" / "ensemble"

DIGESTS = {
    "lofi": "5061ac2a89757ac56a15c6add8d5623de030c8936001a6d1af9f9e7bd8423e8a",
    "trap": "e2da6917e751aa7d799be4ed6d45114f9ea17de2eb0f2b8c4f8e7f747d189296",
}
"""SHA-256 of each file as written in #276, parsed and dumped with sorted keys, without
the `sound` of each player and the `hits` added in #286."""

SOUNDS = {
    "lofi": {
        "bass": ("Upright bass, plucked, warm, close mic", 3, 2),
        "keys": ("Rhodes electric piano, sustained, steady tone", 4, 1),
        "vibes": ("Vibraphone, soft mallet, motor off", 4, 1),
        "pad": ("Warm analog synth pad, sustained, slow attack, steady", 6, 1),
    },
    "trap": {
        "808": ("808 bass, long note, saturated with harmonics, long decay", 3, 2),
        "keys": ("Dark felt piano, soft, close mic", 4, 1),
        "bell": ("Music box, bright, delicate", 3, 1),
        "pad": ("Warm analog synth pad, sustained, slow attack, steady", 6, 1),
    },
}
"""The default sound of each player, as written in #286."""

HITS = {
    "lofi": {
        "kick": ("Dusty boom bap kick drum, deep, short decay, close mic", 0.6),
        "snare": ("Crisp snare drum, tight, short tail", 0.45),
        "hat": ("Closed hi-hat, very short, bright, no ring", 0.2),
    },
    "trap": {
        "kick": (
            "Trap kick drum, a hard click at the start, then a tight low thump that stops"
            " quickly, close, no tail",
            0.5,
        ),
        "snare": (
            "Trap snare drum, bright and cracking, short body, a little noise on top, close",
            0.45,
        ),
        "clap": ("Clap made of several hands, tight, bright, short", 0.45),
        "hat": ("Closed hi-hat from a drum machine, thin, crisp, very short, almost no ring", 0.15),
        "openhat": (
            "Open hi-hat from a drum machine, a bright sizzle that fades in half a second",
            0.5,
        ),
    },
}
"""The hits of each band, as written in #286."""


def _data(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FOLDER / f"{name}.json").read_text(encoding="utf-8"))
    return data


def test_the_two_files_are_the_files_of_the_issue() -> None:
    assert sorted(p.stem for p in FOLDER.glob("*.json")) == ["lofi", "trap"]
    for name, digest in DIGESTS.items():
        data = _data(name)
        sounds = {p["name"]: p.pop("sound") for p in data["players"]}
        hits = data.pop("hits")
        dumped = json.dumps(data, sort_keys=True).encode()
        assert hashlib.sha256(dumped).hexdigest() == digest, name
        assert {k: (v["words"], v["seconds"], v["takes"]) for k, v in sounds.items()} == SOUNDS[
            name
        ]
        assert {k: (v["words"], v["seconds"]) for k, v in hits.items()} == HITS[name]
        assert list(hits) == list(HITS[name])


def test_the_sounds_and_hits_are_loaded() -> None:
    loaded = load_bands()
    for name, band in loaded.items():
        assert {
            p.name: (p.sound.words, p.sound.seconds, p.sound.takes) for p in band.players
        } == SOUNDS[name]
        assert {h.name: (h.words, h.seconds) for h in band.hits.values()} == HITS[name]
        assert list(band.hits) == list(HITS[name])


def test_load_bands_reads_both_with_their_players_and_controls() -> None:
    loaded = load_bands()
    assert list(loaded) == ["lofi", "trap"]
    lofi, trap = loaded["lofi"], loaded["trap"]
    assert lofi.tempo == 76 and trap.tempo == 140
    assert lofi.controls() == {"bass-loop": "haze-bass", "loop": "haze-keys", "progression": "haze"}
    assert trap.controls() == {
        "bass-loop": "midnight-808",
        "loop": "midnight-keys",
        "progression": "midnight",
    }
    assert [p.name for p in lofi.players] == ["bass", "keys", "vibes", "pad"]
    assert [p.name for p in trap.part("melody")] == ["keys", "bell", "pad"]
    bass = lofi.players[0]
    assert (bass.plays.octave, bass.release, bass.prefer) == (1, 0.12, "clean")
    assert trap.players[0].prefer == "rich"
    assert len(lofi.grid()) == 24 and len(trap.grid()) == 32
    assert lofi.grid()[12] == {
        "kick": [118] + [0] * 15,
        "snare": [0] * 12 + [116, 0, 0, 0],
        "hat": [0] * 16,
    }


def test_the_limits_are_the_simulations() -> None:
    assert bands.DRUMS == sim.DRUMS
    assert bands.STEPS == sim.STEPS
    assert bands.MAX_BARS == sim.MAX_BARS
    assert bands.TEMPO_RANGE == sim.TEMPO_RANGE


def _play(band: Band) -> sim.Song:
    c = band.content
    settings = sim.Settings(
        tempo=band.tempo, progression=c["progression"], bass_loop=c["bass_loop"], loop=c["loop"]
    )
    return sim.simulate(band.grid(), settings)


@pytest.mark.parametrize(
    ("name", "bass", "melody"),
    [
        ("lofi", {"home", "push"}, {"home", "open", "busy"}),
        ("trap", {"home", "push", "drive"}, {"home", "open", "busy"}),
    ],
)
def test_the_audition_plays_the_variations_and_every_note_has_a_player(
    name: str, bass: set[str], melody: set[str]
) -> None:
    band = load_bands()[name]
    song = _play(band)
    assert {r.bass.variation for r in song.rows if r.bass} == bass
    assert {r.melody.variation for r in song.rows if r.melody} == melody
    parts = {"bass": "bass", "keys": "melody"}
    sent = [n for n in song.notes if n.part in parts]
    assert {n.part for n in sent} == set(parts)
    for note in sent:
        players = band.part(parts[note.part])
        assert any(p.plays.sends(note.pitch, note.velocity) for p in players), note


Spoil = Callable[[dict[str, Any]], None]


def _set(path: str, value: Any) -> Spoil:
    def spoil(data: dict[str, Any]) -> None:
        *keys, last = path.split(".")
        target: Any = data
        for key in keys:
            target = target[int(key)] if key.isdigit() else target[key]
        if last.isdigit():
            target[int(last)] = value
        else:
            target[last] = value

    return spoil


def _drop_part(data: dict[str, Any]) -> None:
    data["players"] = [p for p in data["players"] if p["plays"]["part"] != "bass"]


def _no_part(data: dict[str, Any]) -> None:
    del data["players"][0]["plays"]["part"]


def _no_sound(data: dict[str, Any]) -> None:
    del data["players"][0]["sound"]


def _no_hits(data: dict[str, Any]) -> None:
    del data["hits"]


def _no_hat(data: dict[str, Any]) -> None:
    del data["hits"]["hat"]


@pytest.mark.parametrize(
    ("spoil", "problem"),
    [
        (_set("colour", "blue"), "unknown field 'colour'"),
        (_set("players.0.colour", "blue"), "players[0]: unknown field 'colour'"),
        (_set("content.loop", "haze-bass"), "content.loop: 'haze-bass' is not a built-in melody"),
        (_set("content.bass_loop", "nope"), "content.bass_loop: 'nope' is not a built-in bass"),
        (_set("content.progression", "x"), "content.progression: 'x' is not a built-in progr"),
        (_set("players.2.name", "keys"), "players[2]: two players are named 'keys'"),
        (_drop_part, "players: no player plays the bass part"),
        (_no_part, "players[0].plays.part: missing"),
        (_set("players.0.plays.part", None), "players[0].plays.part: must be 'bass' or 'melody'"),
        (_set("players.0.plays.keys", [80, 72]), "players[0].plays.keys: low is above high"),
        (_set("players.0.plays.octave", 5), "players[0].plays.octave: must be from -4 to 4"),
        (_set("patterns.busy.hat", [0] * 15), "patterns.busy.hat must be 16 steps"),
        (_set("patterns.busy.kick.3", 128), "patterns.busy.kick must be 16 steps"),
        (_set("patterns.busy.snare.3", 1.5), "patterns.busy.snare must be 16 steps"),
        (_set("audition.4", "fill"), "audition[4]: 'fill' names no pattern"),
        (_set("tempo", 200), "tempo must be a whole number of BPM, 60-160"),
        (_set("players.1.prefer", "warm"), "players[1].prefer must be 'clean' or 'rich'"),
        (_no_sound, "players[0]: sound is required"),
        (_set("players.1.sound.words", " "), "players[1].sound.words must be words that are not"),
        (_set("players.1.sound.seconds", 0), "players[1].sound.seconds must be a number of sec"),
        (_set("players.1.sound.takes", 0), "players[1].sound.takes must be a whole number, 1 or"),
        (_set("players.1.sound.level", 2), "players[1].sound: unknown field 'level'"),
        (_no_hits, "hits is required"),
        (_no_hat, "hits: hat is required: the audition plays it"),
        (_set("hits.Big Kick", {"words": "w", "seconds": 1}), "hits: 'Big Kick' is not a name"),
        (_set("hits.kick.pitch", 36), "hits.kick: unknown field 'pitch'"),
        (_set("hits.snare.seconds", -1), "hits.snare.seconds must be a number of seconds above"),
        (_set("hits.snare.words", ""), "hits.snare.words must be words that are not empty"),
    ],
)
def test_check_names_each_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], spoil: Spoil, problem: str
) -> None:
    data = copy.deepcopy(_data("lofi"))
    spoil(data)
    path = tmp_path / "lofi.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert main(["check", str(path)]) == 1
    assert problem in capsys.readouterr().err


def test_check_refuses_a_name_other_than_the_file_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "chill.json"
    path.write_text(json.dumps(_data("lofi")), encoding="utf-8")
    assert main(["check", str(path)]) == 1
    assert "the file name must equal the name 'lofi'" in capsys.readouterr().err


def test_check_passes_the_built_in_files(capsys: pytest.CaptureFixture[str]) -> None:
    files = [str(FOLDER / "lofi.json"), str(FOLDER / "trap.json")]
    assert main(["check", *files]) == 0
    out = capsys.readouterr().out
    assert "band 'lofi', 4 player(s), 3 hit(s), 8 pattern(s), an audition of 24 bar(s)" in out
    assert "band 'trap', 4 player(s), 5 hit(s), 9 pattern(s), an audition of 32 bar(s)" in out


def test_list_prints_the_two_bands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "lofi: 76 BPM, bass-loop haze-bass loop haze-keys progression haze;"
        " players bass (bass), keys (melody), vibes (melody), pad (melody)",
        "trap: 140 BPM, bass-loop midnight-808 loop midnight-keys progression midnight;"
        " players 808 (bass), keys (melody), bell (melody), pad (melody)",
    ]


@pytest.mark.parametrize(
    "plays",
    [
        {"part": "drums", "keys": [0, 127], "min_velocity": 1, "octave": 0},
        {"part": "bass", "keys": [0, 128], "min_velocity": 1, "octave": 0},
        {"part": "bass", "keys": 72, "min_velocity": 1, "octave": 0},
        {"part": "bass", "keys": [0, 127], "min_velocity": 0, "octave": 0},
        {"part": "bass", "keys": [0, 127], "min_velocity": 1, "octave": 1.0},
        {"part": "bass", "keys": [0, 127], "min_velocity": 1, "octave": 0, "channel": 2},
        {"part": "bass", "keys": [0, 127], "min_velocity": 1},
    ],
)
def test_the_band_and_the_sound_set_refuse_a_plays_with_the_same_words(
    plays: dict[str, Any],
) -> None:
    document = soundset.empty()
    document["instruments"]["bass"] = {
        "sfz": "bass.sfz",
        "settings": {"prefer": "clean", "release": 0.25, "clean": 0.5},
        "plays": plays,
        "span": None,
        "uncovered": [],
        "files": [],
    }
    found = soundset.validate(document)
    expected = problems(plays, "plays")
    assert expected
    assert found == [f"instruments.bass.{p}" for p in expected]
    band = copy.deepcopy(_data("lofi"))
    band["players"][0]["plays"] = plays
    with pytest.raises(ContentError) as error:
        parse_band(band, "lofi.json")
    assert str(error.value) == "lofi.json: " + "; ".join(f"players[0].{p}" for p in expected)


ALLOWED = {"mpc_iml", "collections", "dataclasses", "pathlib", "typing"}
"""What `from … import` in `mpc_iml.bands` and `mpc_iml.plays` may name."""


def test_the_band_check_is_in_the_core() -> None:
    """A core install (without the `demo` extra) imports `mpc_iml.bands`: it and
    `mpc_iml.plays` import neither `mpc_iml.sounds` nor `mpc_iml.webdemo`."""
    for module in ("bands", "plays"):
        source = (FOLDER.parent.parent / f"{module}.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(("mpc_iml.sounds", "mpc_iml.webdemo"))
                assert node.module.split(".")[0] in ALLOWED
