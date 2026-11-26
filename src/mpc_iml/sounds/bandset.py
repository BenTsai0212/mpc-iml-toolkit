"""Make a whole sound set for a band with a model the musician installed (#286, RFC 0006
step 5).

Each player of a band file says what it sounds like by default (`sound`: words, seconds
and takes) and the band says which drum hits it needs (`hits`, ADR 0014). From what the
band sends a player in its audition, `ask_notes` chooses the notes to ask the model for;
`generate_band` then calls `generate.generate_notes` for each player and
`generate.generate_hit` for each hit, into one sound set folder.

    python -m mpc_iml.sounds.generate band <band> --generator <file> --out <folder>
        [--words <name>=<words>]... [--only <name>...] [--seed <n>] [--rounds <n>] [--plan]

Only natural note names are asked for: only those were tried with a model so far. The
rounds of `generate_notes` ask again for what was not answered.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mpc_iml.bands import Band, Hit, Player
from mpc_iml.sounds import soundset
from mpc_iml.sounds.audition import play, played
from mpc_iml.sounds.generate import (
    ROUNDS,
    GeneratedHit,
    GeneratedInstrument,
    Generator,
    RunTake,
    generate_hit,
    generate_notes,
    run_take,
)
from mpc_iml.sounds.notes import note_name

__all__ = [
    "NATURAL",
    "STEP",
    "Made",
    "Plan",
    "PlannedHit",
    "PlannedPlayer",
    "ask_notes",
    "generate_band",
    "made_line",
    "next_lines",
    "plan",
    "plan_lines",
    "sounding",
]

NATURAL = frozenset({0, 2, 4, 5, 7, 9, 11})
"""The pitch classes of the natural note names, C D E F G A B."""
STEP = 5
"""Semitones from one note asked for to the next, or one fewer when that note would not
be natural."""
CLOSE = 2
"""The notes stop when the last is within this many semitones of the highest."""


def ask_notes(lowest: int, highest: int) -> list[int]:
    """The notes to ask for to cover `lowest` to `highest`: from the lowest (one semitone
    lower when it is not natural), each next one `STEP` semitones up (one fewer when that
    would not be natural), until the last is within `CLOSE` semitones of the highest or
    above it."""
    note = lowest if lowest % 12 in NATURAL else lowest - 1
    notes = [note]
    while note < highest - CLOSE:
        note += STEP if (note + STEP) % 12 in NATURAL else STEP - 1
        notes.append(note)
    return notes


def sounding(player: Player, sent: Mapping[str, Sequence[tuple[int, int]]]) -> list[int]:
    """The notes `player` sounds in the audition: the notes the band sends its part,
    inside its keys and at or above its `min_velocity`, moved by its octave. `sent` is
    the (pitch, velocity) of each note sent, by part."""
    part = str(player.plays.part)
    shift = 12 * player.plays.octave
    return sorted(
        {pitch + shift for pitch, velocity in sent[part] if player.plays.sends(pitch, velocity)}
    )


@dataclass(frozen=True)
class PlannedPlayer:
    """What `generate_band` asks for one player."""

    player: Player
    words: str
    notes: tuple[int, ...]
    """The notes asked for in round 1; empty when the band sends the player no note."""
    span: tuple[int, int] | None
    """The lowest and the highest note the band sends the player's part (`--low`,
    `--high`)."""

    @property
    def takes(self) -> int:
        return len(self.notes) * self.player.sound.takes


@dataclass(frozen=True)
class PlannedHit:
    """What `generate_band` asks for one drum hit."""

    hit: Hit
    words: str


@dataclass(frozen=True)
class Plan:
    """What `generate_band` will ask for, in the band's order: players, then hits."""

    band: Band
    players: tuple[PlannedPlayer, ...]
    hits: tuple[PlannedHit, ...]

    @property
    def takes(self) -> int:
        """The takes asked for in round 1."""
        return sum(p.takes for p in self.players) + len(self.hits)


def names(band: Band) -> list[str]:
    """The players and then the hits of `band`, by name."""
    return [p.name for p in band.players] + list(band.hits)


def _unknown(band: Band, name: str, where: str) -> ValueError:
    return ValueError(
        f"{where}: {name!r} is neither a player nor a hit of the band {band.name!r};"
        f" players and hits: {', '.join(names(band))}"
    )


def plan(
    band: Band, words: Mapping[str, str] | None = None, only: Sequence[str] | None = None
) -> Plan:
    """What to ask for: each player's words (or its replacement in `words`) and notes,
    and each hit's words. With `only`, only those players and hits. Raises `ValueError`
    when a name in `words` or `only` is neither a player nor a hit of `band`, or a
    replacement is empty."""
    words = dict(words or {})
    known = set(names(band))
    for name, said in words.items():
        if name not in known:
            raise _unknown(band, name, "--words")
        if not said.strip():
            raise ValueError(f"--words: the words for {name!r} are empty")
    for name in only or ():
        if name not in known:
            raise _unknown(band, name, "--only")
    chosen = set(only) if only else known
    song = played(play(band))
    sent = {part: [(n.pitch, n.velocity) for n in song[part]] for part in ("bass", "melody")}
    players = []
    for player in band.players:
        if player.name not in chosen:
            continue
        notes = sounding(player, sent)
        part = [pitch for pitch, _ in sent[str(player.plays.part)]]
        players.append(
            PlannedPlayer(
                player,
                words.get(player.name, player.sound.words),
                tuple(ask_notes(notes[0], notes[-1])) if notes else (),
                (min(part), max(part)) if part else None,
            )
        )
    hits = tuple(
        PlannedHit(hit, words.get(name, hit.words))
        for name, hit in band.hits.items()
        if name in chosen
    )
    return Plan(band, tuple(players), hits)


@dataclass(frozen=True)
class Made:
    """What `generate_band` did for one player or hit."""

    name: str
    kind: str
    """`player` or `hit`."""
    instrument: GeneratedInstrument | None = None
    hit: GeneratedHit | None = None
    error: str | None = None
    """Why it was not made; `None` when it was."""

    @property
    def made(self) -> bool:
        return self.error is None


Done = Callable[[Made], None]
"""Called with each player and hit when it is finished."""


def generate_band(
    band: Band,
    generator: Generator,
    out: Path,
    *,
    words: Mapping[str, str] | None = None,
    only: Sequence[str] | None = None,
    seed: int = 1,
    rounds: int = ROUNDS,
    done: Done | None = None,
    run: RunTake = run_take,
) -> list[Made]:
    """Make the instruments of `band`'s players and its drum hits in the sound set `out`
    with `generator`, as `plan(band, words, only)` says; returns what was done for each,
    in order, and calls `done` with each when it is finished.

    Raises `ValueError` (a `SoundSetError` for the folder) before the generator is run
    when a name is not the band's or the folder's `sound-set.json` cannot be accepted.
    A player or hit that cannot be made does not stop the others."""
    planned = plan(band, words, only)
    if rounds < 1:
        raise ValueError(f"rounds must be 1 or more, not {rounds}")
    soundset.read_document(out)
    results: list[Made] = []

    def finish(made: Made) -> None:
        results.append(made)
        if done is not None:
            done(made)

    for p in planned.players:
        player = p.player
        if not p.notes:
            finish(Made(player.name, "player", error="the band sends it no note in its audition"))
            continue
        try:
            result = generate_notes(
                player.name,
                generator,
                p.words,
                p.notes,
                out,
                seconds=player.sound.seconds,
                takes=player.sound.takes,
                seed=seed,
                rounds=rounds,
                prefer="rich" if player.prefer == "rich" else "clean",
                release=player.release,
                span=p.span,
                part=player.plays.part,
                keys=player.plays.keys,
                min_velocity=player.plays.min_velocity,
                octave=player.plays.octave,
                run=run,
            )
        except ValueError as error:
            finish(Made(player.name, "player", error=str(error)))
            continue
        finish(Made(player.name, "player", instrument=result, error=result.error))
    for h in planned.hits:
        try:
            made = generate_hit(
                h.hit.name, generator, h.words, out, seed=seed, seconds=h.hit.seconds, run=run
            )
        except ValueError as error:
            finish(Made(h.hit.name, "hit", error=str(error)))
            continue
        finish(Made(h.hit.name, "hit", hit=made, error=made.error))
    return results


def plan_lines(planned: Plan) -> list[str]:
    """The plan as printed before anything is asked: each player's words, notes and
    takes, each hit's words, and the takes of round 1."""
    lines = []
    for p in planned.players:
        notes = " ".join(note_name(n) for n in p.notes) or "none"
        each = p.player.sound.takes
        lines.append(
            f"{p.player.name}: {p.words!r}; notes {notes}; {each} take(s) of each, {p.takes}"
            f" take(s); {p.player.sound.seconds:g} s"
        )
    for h in planned.hits:
        lines.append(f"{h.hit.name}: {h.words!r}; hit of {h.hit.seconds:g} s")
    lines.append(f"{planned.band.name}: {planned.takes} take(s) in round 1")
    return lines


def made_line(made: Made) -> str:
    """One line: made (regions, notes not answered, keys no note reaches) or not made,
    with the reason."""
    if not made.made:
        return f"{made.name}: not made: {made.error}"
    if made.instrument is not None and made.instrument.instrument is not None:
        built = made.instrument.instrument
        unanswered = " ".join(note_name(n) for n in made.instrument.unanswered) or "none"
        gaps = (
            " ".join(
                note_name(low) if low == high else f"{note_name(low)}-{note_name(high)}"
                for low, high in built.uncovered
            )
            or "none"
        )
        return (
            f"{made.name}: made, {len(built.regions)} region(s); not answered: {unanswered};"
            f" keys no note reaches: {gaps}"
        )
    assert made.hit is not None and made.hit.hit is not None
    hit = made.hit.hit
    return f"{made.name}: made, hits/{hit.name}.wav {hit.seconds:.2f} s"


def next_lines(band: Band, out: Path) -> list[str]:
    """The two commands to run next for `band` and the set `out`."""
    audition = out.with_name(f"{out.name}-audition")
    return [
        "next: listen before keeping the set:",
        f"  python -m mpc_iml.sounds.soundset check {out}",
        f"  python -m mpc_iml.sounds.audition {band.name} {out} --out {audition}",
    ]
