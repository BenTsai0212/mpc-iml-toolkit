"""The hip-hop library (#232): four bass and four melody loops played through `ensemble`.

The melody loops are the first built-in loops with chords (several notes on one step)
and ninths (`tone 0`, `semitones 2`); every note of a chord must sound, also in the
`no-drums` modes and with the surprises `octave` and `passing`. The songs come from
the web demo's `simulate`, which runs `ensemble` on a step grid.
"""

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from mpc_iml.bass import BASS_VARIATIONS
from mpc_iml.clock import TICKS_PER_BEAT
from mpc_iml.ensemble import PROGRESSIONS
from mpc_iml.loop_midi import main
from mpc_iml.loops import load_loops
from mpc_iml.melody import MELODY_VARIATIONS, LoopNote, loop_pitch
from mpc_iml.webdemo.sim import Settings, Song, simulate

FOLDER = Path(__file__).parents[1] / "src" / "mpc_iml" / "loops" / "ensemble"
BASS = ("knock", "lazy", "soul", "sub")
MELODY = ("rhodes", "flute", "horns", "bells")
LIBRARY = load_loops()
BAR = 4 * TICKS_PER_BEAT
SIXTEENTH = BAR // 16
MELODY_OCTAVE, BASS_OCTAVE = 4, 1
"""The default octaves of `ensemble` (`melody-octave`, `octave`)."""

OPEN = {"kick": [100, 0, 0, 0, 0, 0, 0, 0] * 2}
"""2 hits: the melody plays `open`, level 1."""
HOME_LINE = {"kick": OPEN["kick"], "hat": [70, 0, 0, 0] * 4}
"""6 hits, no 16th hats: `home`, level 1."""
HOME = {"kick": OPEN["kick"], "hat": [70, 0] * 8}
"""10 hits, no 16th hats: `home` with ornaments."""
BUSY = {"kick": [100, 0, 0, 100] * 4, "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2, "hat": [70] * 16}
"""26 hits and 16th hats: `busy` with ornaments."""


def kicks(*steps: int) -> dict[str, list[int]]:
    return {"kick": [100 if s in steps else 0 for s in range(16)]}


def chords(bar: int) -> tuple[tuple[int, str], tuple[int, str]]:
    """(pitch class, quality) of the chord of `bar` and the next bar in `minor-two`."""
    p = PROGRESSIONS["minor-two"]
    now, following = p.chord(bar), p.chord(bar + 1)
    return (p.tonic + now.root, now.quality), (p.tonic + following.root, following.quality)


def tick(note: LoopNote) -> int:
    return note.step * SIXTEENTH + round(note.offset * SIXTEENTH)


def expected(notes: tuple[LoopNote, ...], bar: int, octave: int) -> Counter[tuple[int, int]]:
    """The (tick in the bar, pitch) of `notes` in song `bar`, as written."""
    return Counter((tick(n), loop_pitch(n, *chords(bar), octave)) for n in notes)


def played(song: Song, part: str, bar: int) -> Counter[tuple[int, int]]:
    return Counter(
        (n.tick - bar * BAR, n.pitch) for n in song.notes if n.part == part and n.tick // BAR == bar
    )


def melody_notes(song: Song, name: str, bar: int) -> tuple[LoopNote, ...]:
    """The notes the plan of song `bar` (made at the end of grid bar `bar - 1`) plays."""
    plan = song.rows[bar - 1].melody
    assert plan is not None
    return plan.notes(LIBRARY.played("melody")[name], bar)


@pytest.mark.parametrize("name", [*BASS, *MELODY])
def test_each_file_passes_loops_check(name: str) -> None:
    assert main(["check", str(FOLDER / f"{name}.json")]) == 0
    loop = LIBRARY.get(name, "bass" if name in BASS else "melody")
    variations = BASS_VARIATIONS if name in BASS else MELODY_VARIATIONS
    assert tuple(loop.variations) == variations


def test_the_melody_loops_use_chords_and_ninths() -> None:
    for name in ("rhodes", "horns"):
        notes = [n for v in LIBRARY.played("melody")[name].variations for n in v.notes]
        steps = Counter((n.bar, n.step) for n in notes)
        assert max(steps.values()) >= 2, name
    for name in MELODY:
        notes = [n for v in LIBRARY.played("melody")[name].variations for n in v.notes]
        if name != "horns":
            assert any(n.tone == 0 and n.semitones == 2 for n in notes), name


@pytest.mark.parametrize("name", MELODY)
@pytest.mark.parametrize(
    ("grid", "variation"), [(OPEN, "open"), (HOME, "home"), (HOME_LINE, "home"), (BUSY, "busy")]
)
def test_every_note_of_each_chord_sounds(
    name: str, grid: dict[str, list[int]], variation: str
) -> None:
    """Four bars of the same drums: each bar plays its variation's notes as written,
    every note of a chord at the loop's pitches over `minor-two`, and one brightness
    CC a bar."""
    song = simulate([grid] * 4, Settings(loop=name))
    assert [r.melody.variation for r in song.rows if r.melody] == [variation] * 4
    chord_steps = 0
    for bar in range(1, 5):
        notes = melody_notes(song, name, bar)
        assert played(song, "keys", bar) == expected(notes, bar, MELODY_OCTAVE), bar
        chord_steps += sum(c > 1 for c in Counter(n.step for n in notes).values())
    if name in ("rhodes", "horns"):
        assert chord_steps > 0
    assert len(song.brightness) == 4


@pytest.mark.parametrize("name", ["rhodes", "horns"])
@pytest.mark.parametrize("no_drums", ["lead", "hold", "thin"])
def test_chords_sound_when_the_drums_stop(name: str, no_drums: str) -> None:
    """`lead` and `hold` keep playing; `thin` plays the skeleton for one bar (all
    three notes of `rhodes`' first chord), then rests."""
    song = simulate([HOME, {}, {}, {}], Settings(loop=name, no_drums=no_drums))
    assert [r.melody_rule for r in song.rows] == ["drums", no_drums, no_drums, no_drums]
    sounding = [1, 2] if no_drums == "thin" else [1, 2, 3, 4]
    for bar in range(1, 5):
        notes = melody_notes(song, name, bar)
        assert bool(notes) == (bar in sounding), bar
        assert played(song, "keys", bar) == expected(notes, bar, MELODY_OCTAVE), bar
    thin = song.rows[1].melody
    assert thin is not None and thin.skeleton == (no_drums == "thin")
    if no_drums == "thin" and name == "rhodes":
        assert Counter(n.step for n in melody_notes(song, name, 2)) == {0: 3}


SURPRISES = [
    ("horns", OPEN, 3, "passing"),
    ("rhodes", HOME_LINE, 3, "passing"),
    ("horns", OPEN, 8, "octave"),
    ("rhodes", HOME, 8, "octave"),
]
"""A loop, drums and a seed whose bar 4 (the end of the first phrase) plays the
surprise on a chord: the last onset of `horns` open (level 1) and of `rhodes` home
(level 1) in their second bar is a chord."""


@pytest.mark.parametrize(("name", "grid", "seed", "surprise"), SURPRISES)
def test_a_surprise_on_a_chord_moves_every_note(
    name: str, grid: dict[str, list[int]], seed: int, surprise: str
) -> None:
    song = simulate([grid] * 4, Settings(loop=name, surprise=2, seed=seed))
    assert song.rows[2].surprise == surprise
    bar = 3
    notes = melody_notes(song, name, bar)
    last = max(n.step for n in notes)
    chord = [n for n in notes if n.step == last]
    if surprise == "passing":
        assert len(chord) >= 2
        moved = tuple(replace(n, chord=1, semitones=-1) if n.step == last else n for n in notes)
    else:
        assert any(c > 1 for c in Counter(n.step for n in notes).values())
        moved = tuple(replace(n, octave=n.octave + 1) for n in notes)
    assert played(song, "keys", bar) == expected(moved, bar, MELODY_OCTAVE)
    if surprise == "passing":
        following = chords(bar)[1]
        top = {loop_pitch(n, *chords(bar), MELODY_OCTAVE) for n in moved if n.step == last}
        assert top == {
            loop_pitch(replace(n, chord=0, semitones=0), following, following, MELODY_OCTAVE) - 1
            for n in chord
        }


@pytest.mark.parametrize("name", BASS)
@pytest.mark.parametrize(
    ("grid", "variation"),
    [
        (kicks(0, 8), "home"),
        (kicks(0, 3, 8), "push"),
        (kicks(0, 10), "push"),
        (kicks(0, 2, 4, 6, 8, 10, 12, 14), "drive"),
    ],
)
def test_each_bass_loop_follows_the_kicks(
    name: str, grid: dict[str, list[int]], variation: str
) -> None:
    """Sparse, syncopated and dense kicks choose `home`, `push` and `drive`, and the
    bass plays that variation's notes as written (with `lazy`'s late notes)."""
    song = simulate([grid] * 4, Settings(bass_loop=name, surprise=0))
    loop = LIBRARY.played("bass")[name]
    for bar in range(1, 5):
        plan = song.rows[bar - 1].bass
        assert plan is not None and plan.variation == variation
        notes = plan.notes(loop, bar)
        assert played(song, "bass", bar) == expected(notes, bar, BASS_OCTAVE), bar
    if name == "lazy":
        assert any(n.offset > 0 for n in loop.variation(variation).notes)
