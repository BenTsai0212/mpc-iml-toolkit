"""Listen to the variation generator's candidates next to their source (#221 PR 3).

`listen` finds a loop (a name or a `.json` loop file, with the user loops of a data
folder, as `python -m mpc_iml.vargen`), builds the model of its corpus, generates
candidates of one variation (`vargen.generate`) and makes a `sim.Song` of the source
and of each candidate: the line repeated over `bars` (at least 4 bars, the loop
twice) on the progression, with a plain boom-bap drum pattern (`DRUM_PATTERN`) under
it unless `drums` is off, so `synth.render` and `roll.draw` play and draw it as the
other tabs.

With `blind` the clips are shuffled with the seed and shown under letters `A`,
`B`, …, so "does this sound like me" is judged before the source is known; `table`
with `reveal` then names each one with its provenance (seed, distance, changes).

Nothing here writes a file or changes how `ensemble` plays; Gradio is not imported.
"""

import random
from dataclasses import dataclass
from pathlib import Path

from mpc_iml.clock import SIXTEENTHS
from mpc_iml.content import ContentError
from mpc_iml.ensemble import PROGRESSIONS
from mpc_iml.loop_midi import OCTAVES
from mpc_iml.loops import STEPS, LoopFile
from mpc_iml.melody import loop_pitch
from mpc_iml.vargen import (
    DEFAULT_CORPUS,
    DEFAULT_NOVELTY,
    Candidate,
    build_model,
    corpus,
    describe,
    find_loop,
    generate,
)
from mpc_iml.webdemo.sim import DRUM_NOTES, TEMPO_RANGE, Note, Settings, Song

__all__ = [
    "DRUM_PATTERN",
    "MAX_COUNT",
    "MIN_BARS",
    "PROVENANCE_HEADERS",
    "Clip",
    "Listing",
    "clip_song",
    "listen",
    "table",
]

MAX_COUNT = 5
"""The most candidates the page shows."""
MIN_BARS = 4
"""Each clip plays at least this many bars (the loop at least twice)."""
DRUM_PATTERN: dict[str, dict[int, int]] = {
    "kick": {0: 100, 7: 80, 10: 100},
    "snare": {4: 95, 12: 95},
    "hat": {step: 70 for step in range(0, STEPS, 2)},
}
"""A plain boom-bap bar, `{drum: {step: velocity}}`, played under every clip for time."""
PROVENANCE_HEADERS = ["clip", "is", "seed", "distance", "changes"]
_PARTS = {"bass": "bass", "melody": "keys"}
_HIDDEN = "?"


@dataclass(frozen=True)
class Clip:
    """One clip on the page: `label` (`source`, `1`, `2`, … or a letter when blind),
    the `candidate` (none for the source) and its `song`."""

    label: str
    candidate: Candidate | None
    song: Song


@dataclass(frozen=True)
class Listing:
    """The clips of one `listen` in the order shown, the source `loop` and
    `variation`, whether it is the musician's (`yours`), and whether it is `blind`."""

    loop: LoopFile
    variation: str
    yours: bool
    blind: bool
    clips: tuple[Clip, ...]


def clip_song(
    loop: LoopFile, variation: str, settings: Settings, drums: bool = True, bars: int = 0
) -> Song:
    """`loop`'s `variation` repeated over `bars` (at least `MIN_BARS` and the loop
    twice) on `settings.progression`, with `DRUM_PATTERN` under it when `drums`."""
    bars = max(bars, MIN_BARS, 2 * loop.bars)
    progression = PROGRESSIONS[settings.progression]

    def chord(bar: int) -> tuple[int, str]:
        c = progression.chord(bar)
        return (progression.tonic + c.root) % 12, c.quality

    notes: list[Note] = []
    for bar in range(bars):
        if drums:
            for drum, hits in DRUM_PATTERN.items():
                for step, velocity in hits.items():
                    tick = (bar * STEPS + step) * SIXTEENTHS
                    notes.append(Note(drum, tick, SIXTEENTHS, DRUM_NOTES[drum], velocity))
        if bar % loop.bars:
            continue
        for n in loop.variations[variation]:
            at = bar + n.bar
            pitch = loop_pitch(n, chord(at), chord(at + 1), OCTAVES[loop.part])
            tick = max(round((at * STEPS + n.step + n.offset) * SIXTEENTHS), 0)
            velocity = max(1, min(127, round(100 * n.velocity)))
            notes.append(Note(_PARTS[loop.part], tick, n.length * SIXTEENTHS, pitch, velocity))
    notes.sort(key=lambda n: (n.tick, n.part, n.pitch))
    return Song(settings, bars, tuple(notes), (), ())


def listen(
    name: str,
    data: str | Path,
    *,
    variation: str = "home",
    novelty: float = DEFAULT_NOVELTY,
    setting: str = DEFAULT_CORPUS,
    seed: int = 0,
    count: int = 4,
    progression: str = "minor-two",
    tempo: float = 90.0,
    drums: bool = True,
    blind: bool = False,
) -> Listing:
    """The source and up to `count` (1-`MAX_COUNT`) candidates of loop `name`'s
    `variation` as clips; shuffled under letters with `seed` when `blind`.

    Raises `ValueError` for an unknown or unreadable loop, a variation it does not
    have, a progression, a tempo outside `TEMPO_RANGE`, or a count or novelty out of
    range.
    """
    if not 1 <= count <= MAX_COUNT:
        raise ValueError(f"count must be 1-{MAX_COUNT}, got {count}")
    if progression not in PROGRESSIONS:
        raise ValueError(f"unknown progression {progression!r}")
    low, high = TEMPO_RANGE
    if not low <= tempo <= high:
        raise ValueError(f"tempo must be {low:g}-{high:g}, got {tempo:g}")
    try:
        source, installed, user = find_loop(name.strip(), Path(data))
    except ContentError as e:
        raise ValueError(str(e)) from e
    model = build_model(corpus(source, setting, installed, user))
    yours = installed.loops.get(source.name) is not source
    found = generate(
        source,
        variation,
        model,
        novelty=novelty,
        seed=seed,
        count=count,
        setting=setting,
        yours=yours,
    )
    settings = Settings(tempo=tempo, progression=progression, seed=seed)
    songs: list[tuple[Candidate | None, Song]] = [
        (None, clip_song(source, variation, settings, drums))
    ]
    songs += [(c, clip_song(c.as_loop(source.name), "home", settings, drums)) for c in found]
    if blind:
        random.Random(seed).shuffle(songs)
        labels = [chr(ord("A") + i) for i in range(len(songs))]
    else:
        labels = ["source", *(str(i) for i in range(1, len(songs)))]
    clips = tuple(Clip(label, c, song) for label, (c, song) in zip(labels, songs, strict=True))
    return Listing(source, variation, yours, blind, clips)


def table(listing: Listing, reveal: bool = False) -> list[list[str | int]]:
    """One row per clip (`PROVENANCE_HEADERS`): what it is, its seed, its distance
    from the source and its changes; all `?` for a blind listing until `reveal`."""
    owner = "your" if listing.yours else "built-in"
    where = f"{owner} {listing.loop.name}/{listing.variation}"
    rows: list[list[str | int]] = []
    for clip in listing.clips:
        c = clip.candidate
        if listing.blind and not reveal:
            rows.append([clip.label, _HIDDEN, _HIDDEN, _HIDDEN, _HIDDEN])
        elif c is None:
            rows.append([clip.label, f"source: {where}", "-", "0", "-"])
        else:
            changed, ratio = c.distance
            changes = "; ".join(describe(change) for change in c.changes)
            what = f"from {where}, novelty {c.novelty:g}, corpus {c.corpus}"
            rows.append([clip.label, what, c.seed, f"{changed} ({ratio:.0%})", changes])
    return rows
