"""Loop files for `ensemble`: format, validation and loading (#173, ADR 0010)."""

import copy
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mpc_iml.content import ContentError, UnknownContentError
from mpc_iml.loops import HOME, PARTS, VARIATIONS, LoopFile, load_loops, parse_loop
from mpc_iml.melody import ORNAMENTS, Loop, LoopNote, loop_pitch
from mpc_iml.progressions import load_progressions

PROGRESSIONS = load_progressions()

DATA = Path(__file__).parent / "data"

LOOP: dict[str, Any] = {
    "format": "mpc-iml-loop",
    "format_version": 1,
    "name": "line",
    "preset": "ensemble",
    "part": "bass",
    "bars": 1,
    "variations": {
        "home": [
            {"bar": 0, "step": 0, "tone": 0, "length": 3, "skeleton": True},
            {"bar": 0, "step": 3, "tone": 0, "length": 1, "level": 2, "velocity": 0.7},
            {"bar": 0, "step": 8, "tone": 2, "length": 2, "offset": 0.25, "skeleton": True},
            {"bar": 0, "step": 14, "tone": 0, "length": 2, "chord": 1, "semitones": -1},
        ],
        "push": [{"bar": 0, "step": 3, "tone": 0, "length": 13}],
    },
}


MELODY: dict[str, Any] = {
    **LOOP,
    "name": "arp",
    "part": "melody",
    "variations": {"home": LOOP["variations"]["home"]},
}


@pytest.fixture(autouse=True)
def _forget_plugin_modules() -> Iterator[None]:
    yield
    for name in ("loop_content", "more_loops"):
        sys.modules.pop(name, None)


def changed(path: str, value: Any, base: dict[str, Any] = LOOP) -> dict[str, Any]:
    """A copy of `base` with `value` at `path` (`a.b.0.c`); `...` deletes it."""
    data = copy.deepcopy(base)
    *parents, last = path.split(".")
    target: Any = data
    for key in parents:
        target = target[int(key)] if isinstance(target, list) else target[key]
    key: Any = int(last) if isinstance(target, list) else last
    if value is ...:
        del target[key]
    else:
        target[key] = value
    return data


# The format


def test_a_loop_file_parses_into_notes_with_defaults() -> None:
    loop = parse_loop(LOOP, "line.json")
    assert (loop.name, loop.part, loop.bars, loop.title) == ("line", "bass", 1, "Line")
    assert list(loop.variations) == ["home", "push"]
    assert loop.variations[HOME][1] == LoopNote(0, 3, 0, 1, 2, velocity=0.7)
    assert loop.variations[HOME][2].offset == 0.25
    assert loop.variations[HOME][3] == LoopNote(0, 14, 0, 2, 1, chord=1, semitones=-1)
    assert [n.step for n in loop.skeleton] == [0, 8]


def test_a_missing_variation_plays_home() -> None:
    loop = parse_loop(LOOP).loop()
    assert [v.name for v in loop.variations] == ["home", "push", "drive"]
    assert loop.variation("drive").notes == loop.variation(HOME).notes
    assert loop.variation("push").notes == (LoopNote(0, 3, 0, 13, 1),)


def test_the_skeleton_is_what_thin_plays() -> None:
    assert [n.step for n in parse_loop(LOOP).loop().bar_notes(0, 1)] == [0, 8]
    unmarked = changed("variations.home.0.skeleton", ...)
    unmarked = changed("variations.home.2.skeleton", ..., unmarked)
    assert [n.step for n in parse_loop(unmarked).loop().bar_notes(0, 1)] == [0, 8, 14]


def test_a_melody_loop_has_the_melody_variations() -> None:
    melody = changed("variations.busy", [{"bar": 0, "step": 0, "tone": 1, "length": 1}], MELODY)
    loop = parse_loop(melody).loop()
    assert [v.name for v in loop.variations] == list(VARIATIONS["melody"])


def played(loop: Loop, progression: str, part: str, level: int) -> list[list[Any]]:
    """[bar, step, pitch, length, velocity] of what `loop` plays in song bars 0-3 up to
    `level`, at the part's default octave."""
    p = PROGRESSIONS[progression]
    out: list[list[Any]] = []
    for bar in range(4):
        now, following = p.chord(bar), p.chord(bar + 1)
        chords = ((p.tonic + now.root, now.quality), (p.tonic + following.root, following.quality))
        for n in loop.bar_notes(bar, level):
            pitch = loop_pitch(n, *chords, 1 if part == "bass" else 4)
            out.append([bar, n.step, pitch, n.length, n.velocity])
    return out


BUILT_IN = (
    ["boom", "haze-bass", "knock", "lazy", "midnight-808", "soul", "sub", "walk"],
    ["bells", "flute", "haze-keys", "horns", "keys", "midnight-keys", "pluck", "rhodes"],
)
"""The built-in bass and melody loops, by name (#173, #232, #262)."""


def test_the_built_in_loop_files_play_the_notes_of_158() -> None:
    """The snapshot was written from the Python tables before they were removed (#173):
    every variation and level, and `thin`, over both progressions. The hip-hop loops
    (#232) came later and are not in it."""
    snapshot = json.loads((DATA / "loops-158.json").read_text())
    library = load_loops()
    assert (library.names("bass"), library.names("melody")) == BUILT_IN
    found: dict[str, list[list[Any]]] = {}
    for part in PARTS:
        for name, loop in library.played(part).items():
            assert library.get(name, part).origin.endswith(f"mpc_iml/loops/ensemble/{name}.json")
            if name not in ("boom", "walk", "keys", "pluck"):
                continue
            for progression in ("minor-two", "minor-four"):
                found[f"{name} {progression} thin"] = played(loop, progression, part, 1)
                for variation in loop.variations:
                    for level in (1, ORNAMENTS):
                        key = f"{name} {progression} {variation.name} {level}"
                        found[key] = played(variation, progression, part, level)
    assert found == snapshot


# Bad files


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ("format", "mpc-iml-kit", "not an mpc-iml-loop file of format_version 1"),
        ("format_version", 2, "format_version 1"),
        ("name", "Boom", "name must be lower case"),
        ("preset", "pressure", "preset is 'pressure', expected 'ensemble'"),
        ("tempo", 90, "unknown field 'tempo'"),
        ("part", "drums", "part must be 'bass' or 'melody', got 'drums'"),
        ("bars", 3, "bars must be 1, 2 or 4, got 3"),
        ("bars", True, "bars must be 1, 2 or 4"),
        ("variations", [], "variations must map"),
        ("variations.open", [], "unknown variation 'open' for the bass; variations: home, push"),
        ("variations.home", ..., "variations must include 'home'"),
        ("variations.push", [], "variations.push must be a non-empty list"),
        ("variations.home.1", 3, r"variations.home\[1\]: a note is an object"),
        ("variations.home.1.pitch", 40, r"home\[1\]: unknown field 'pitch'"),
        ("variations.home.1.tone", ..., r"home\[1\]: tone is required"),
        ("variations.push.0.step", 16, r"variations.push\[0\]: step must be 0-15, got 16"),
        ("variations.home.1.bar", 1, r"home\[1\]: bar must be 0-0, got 1"),
        ("variations.home.1.tone", 4, "tone must be 0-3"),
        ("variations.home.1.tone", 1.0, "tone must be a whole number"),
        ("variations.home.1.length", 0, "length must be 1-64"),
        ("variations.home.1.level", 3, "level must be 1-2"),
        ("variations.home.1.octave", 4, "octave must be -2-3"),
        ("variations.home.1.velocity", 0, "velocity must be 0.05-1"),
        ("variations.home.1.chord", 2, "chord must be 0-1"),
        ("variations.home.1.semitones", 12, "semitones must be -11-11"),
        ("variations.home.1.offset", 0.6, "offset must be -0.5-0.5, got 0.6"),
        ("variations.home.1.skeleton", 1, "skeleton must be true or false"),
        ("variations.push.0.skeleton", True, r"push\[0\]: only notes of 'home' can be skeleton"),
        ("variations.home.0.length", 4, r"home\[1\]: overlaps variations.home\[0\]"),
        ("variations.home.3.length", 3, r"home\[3\]: overlaps variations.home\[0\] when the loop"),
        ("variations.push.0.length", 17, r"push\[0\]: overlaps variations.push\[0\] when the"),
    ],
)
def test_bad_loop_files_name_the_file_and_the_note(path: str, value: Any, message: str) -> None:
    with pytest.raises(ContentError, match=f"^line.json: .*{message}"):
        parse_loop(changed(path, value), "line.json")


def test_melody_notes_may_overlap() -> None:
    chord = changed("variations.home.0.length", 16, MELODY)
    assert len(parse_loop(chord).variations[HOME]) == 4


def test_a_file_that_is_not_an_object_is_an_error() -> None:
    with pytest.raises(ContentError, match="not a JSON object"):
        parse_loop([LOOP])


# Loading through `mpc_iml.content`


def install(monkeypatch: pytest.MonkeyPatch, root: Path, name: str, files: dict[str, Any]) -> None:
    """Install a package `name` with loop files `files` (file stem: JSON)."""
    package = root / name
    (package / "loops" / "ensemble").mkdir(parents=True)
    (package / "__init__.py").write_text(
        f"from mpc_iml.content import Content\nCONTENT = Content('ensemble', '{name}')\n"
    )
    for stem, data in files.items():
        text = data if isinstance(data, str) else json.dumps(data)
        (package / "loops" / "ensemble" / f"{stem}.json").write_text(text)
    info = root / f"{name}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text(f"[mpc_iml.content]\n{name} = {name}:CONTENT\n")
    monkeypatch.syspath_prepend(str(root))


def test_installed_loop_files_are_loaded_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install(monkeypatch, tmp_path, "loop_content", {"line": LOOP, "arp": MELODY, "zed": {}})
    with pytest.raises(ContentError, match="file name must equal the name"):
        load_loops()
    (tmp_path / "loop_content" / "loops" / "ensemble" / "zed.json").unlink()
    library = load_loops()
    assert library.names("bass")[-1:] == ["line"]
    assert library.names("melody")[-1:] == ["arp"]
    assert isinstance(library.get("line", "bass"), LoopFile)
    with pytest.raises(UnknownContentError, match="unknown melody loop 'line'"):
        library.get("line", "melody")


def test_two_loops_with_the_same_name_are_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install(monkeypatch, tmp_path, "loop_content", {"line": LOOP})
    install(monkeypatch, tmp_path, "more_loops", {"line": LOOP})
    with pytest.raises(ContentError, match="two loops named 'line'"):
        load_loops()


def test_a_bad_installed_loop_file_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install(monkeypatch, tmp_path, "loop_content", {"line": "{ not json"})
    with pytest.raises(ContentError, match="cannot read"):
        load_loops()
