"""Loop variations to and from MIDI clips (#173, ADR 0010). No file I/O.

`from_midi` turns the notes of a Standard MIDI File (for example a clip exported
from Live) into one variation of a loop: each pitch becomes the nearest chord tone
over the progression and start bar the clip was written on, steps are rounded to
16ths with the remainder kept as `offset`, and velocities become weights. `to_midi`
writes a variation back as a clip, so a round trip keeps what is heard. The
`python -m mpc_iml.loops` commands that use them come in the next step of #173.
"""

from dataclasses import dataclass, replace

from mpc_iml import smf
from mpc_iml.content import ContentError
from mpc_iml.ensemble import Progression
from mpc_iml.loops import BARS, HOME, STEPS, LoopFile
from mpc_iml.melody import ORNAMENTS, QUALITIES, LoopNote, loop_pitch

__all__ = ["OCTAVES", "ORNAMENT_CHANNEL", "Imported", "from_midi", "to_midi"]

OCTAVES = {"bass": 1, "melody": 4}
"""The base octave of each part (the `ensemble` defaults `octave`, `melody-octave`)."""
ORNAMENT_CHANNEL = 1
"""`to_midi` writes level 2 notes on MIDI channel 2 (0-based 1); `from_midi`
reads them back."""
TICKS = 6
"""Offsets are rounded to 1/6 of a 16th, the 24 PPQN clock's resolution."""


def _chords(progression: Progression, bar: int) -> tuple[int, str]:
    chord = progression.chord(bar)
    return (progression.tonic + chord.root) % 12, chord.quality


def _nearest(
    pitch: int, chord: tuple[int, str], base: int, lower: bool = True
) -> tuple[int, int, int]:
    """(tone, octave, semitones) of the chord tone nearest `pitch`; ties go to the
    lower tone, or with `lower` false to the higher (an approach resolves upwards)."""
    pitch_class, quality = chord
    best: list[tuple[int, int, int, int]] = []
    for tone, above in enumerate(QUALITIES[quality]):
        root = 12 * (base + 1) + pitch_class + above
        octave = (pitch - root + 6) // 12
        for k in (octave - 1, octave, octave + 1):
            semitones = pitch - (root + 12 * k)
            best.append((abs(semitones), -semitones if lower else semitones, tone, k))
    found = min(best)
    return found[2], found[3], -found[1] if lower else found[1]


@dataclass
class Imported:
    """The notes of one variation and the messages for the musician."""

    bars: int
    notes: list[LoopNote]
    messages: list[str]


def from_midi(
    clip: smf.MidiFile,
    part: str,
    progression: Progression,
    start_bar: int = 0,
    bars: int | None = None,
    ornament_below: int = 0,
    octave: int | None = None,
) -> Imported:
    """The notes of `clip` as a variation; raises `ContentError` for a note the
    format cannot hold."""
    sixteenth = clip.division / 4
    if bars is None:
        whole = max(-(-round(clip.length / sixteenth) // STEPS), 1)
        bars = next((b for b in BARS if b >= whole), 0)
        if not bars:
            raise ContentError(f"the clip is {whole} bars long; a loop has 1, 2 or 4 bars")
    end, base = bars * STEPS, OCTAVES[part] if octave is None else octave
    loudest = max([n.velocity for n in clip.notes] + [1])
    notes: list[LoopNote] = []
    messages: list[str] = []
    counts = {"chord tones": 0, "approach notes": 0, "other notes": 0, "offsets": 0}
    for n in clip.notes:
        position = n.start / sixteenth
        start = round(position)
        offset = round((position - start) * TICKS) / TICKS
        where = f"note {n.pitch} at bar {start // STEPS} step {start % STEPS}"
        if start >= end:
            raise ContentError(f"{where} is after the loop's {bars} bar(s); give more bars")
        length = max(round(n.length / sixteenth), 1)
        if start + length > end:
            messages.append(f"{where} crosses the loop's end; shortened")
            length = end - start
        bar, step = divmod(start, STEPS)
        chord = 0
        tone, up, semitones = _nearest(n.pitch, _chords(progression, start_bar + bar), base)
        if semitones and step >= STEPS - 2:
            following = _nearest(n.pitch, _chords(progression, start_bar + bar + 1), base, False)
            if abs(following[2]) <= 2:
                chord, (tone, up, semitones) = 1, following
        kind = "approach notes" if chord else "other notes" if semitones else "chord tones"
        counts[kind] += 1
        if kind == "other notes":
            messages.append(f"{where} is not a chord tone: tone {tone} {semitones:+d}")
        counts["offsets"] += offset != 0
        level = ORNAMENTS if n.channel == ORNAMENT_CHANNEL or n.velocity < ornament_below else 1
        velocity = max(round(n.velocity / loudest * 20) / 20, 0.05)
        notes.append(
            LoopNote(bar, step, tone, length, level, up, velocity, chord, semitones, offset)
        )
    if part == "bass":
        notes = _monophonic(notes, messages)
    if not notes:
        raise ContentError("the clip has no notes")
    summary = ", ".join(f"{count} {kind}" for kind, count in counts.items())
    return Imported(bars, notes, [summary, *messages])


def _monophonic(notes: list[LoopNote], messages: list[str]) -> list[LoopNote]:
    """One note per step (the louder), each ending by the next one's start."""
    by_step: dict[int, LoopNote] = {}
    for n in notes:
        at = n.bar * STEPS + n.step
        if at in by_step:
            messages.append(f"two bass notes at bar {n.bar} step {n.step}; kept the louder")
            if n.velocity <= by_step[at].velocity:
                continue
        by_step[at] = n
    ordered = [by_step[at] for at in sorted(by_step)]
    out = []
    for n, after in zip(ordered, [*ordered[1:], None], strict=True):
        gap = (after.bar - n.bar) * STEPS + after.step - n.step if after else n.length
        if n.length > gap:
            messages.append(f"bass note at bar {n.bar} step {n.step} overlaps the next; shortened")
            n = replace(n, length=gap)
        out.append(n)
    return out


def to_midi(
    loop: LoopFile,
    variation: str,
    progression: Progression,
    start_bar: int = 0,
    octave: int | None = None,
) -> bytes:
    """`variation` of `loop` over `progression` as a format 0 file; ornaments
    (level 2) on channel 2 and velocities relative to 127."""
    sixteenth = smf.DIVISION // 4
    base = OCTAVES[loop.part] if octave is None else octave
    notes = []
    for n in loop.variations.get(variation, loop.variations[HOME]):
        bar = start_bar + n.bar
        chords = _chords(progression, bar), _chords(progression, bar + 1)
        start = round((n.bar * STEPS + n.step + n.offset) * sixteenth)
        channel = ORNAMENT_CHANNEL if n.level == ORNAMENTS else 0
        velocity = max(round(n.velocity * 127), 1)
        pitch = loop_pitch(n, *chords, base)
        notes.append(smf.Note(max(start, 0), n.length * sixteenth, pitch, velocity, channel))
    return smf.write(notes, length=loop.bars * STEPS * sixteenth)
