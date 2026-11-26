"""Measure one recorded note: its pitch, how clean it is and where it starts (#268).

A generated note is not trusted to be the pitch that was asked for. The pitch is measured
on the sustain, after the attack: the attack of a plucked or struck sound is often sharp,
and a sample tuned by its attack plays flat. A note is clean when almost all the energy of
its spectral peaks lies on whole multiples of one fundamental.

`python -m mpc_iml.sounds.notes <file>...` prints one line per file.
"""

import argparse
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from mpc_iml.sounds import wav
from mpc_iml.sounds.wav import Samples

NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_LETTERS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SIGNS = {"": 0, "#": 1, "s": 1, "b": -1}

SILENCE_DB = -40.0
"""A note starts where its level first comes within this of its peak."""
TOLERANCE = 35.0
"""A peak is on a harmonic when it is within this many cents of it."""


def note_name(number: int) -> str:
    """A MIDI note number as a name: 60 is `C4`."""
    return f"{NAMES[number % 12]}{number // 12 - 1}"


def note_number(name: str) -> int:
    """`E1`, `F#4`, `Fs4` or `Bb2` as a MIDI note number (`C4` is 60)."""
    match = re.fullmatch(r"([A-Ga-g])([#sb]?)(-?\d+)", name.strip())
    if match is None:
        raise ValueError(f"not a note name: {name!r}")
    letter, sign, octave = match.groups()
    return 12 * (int(octave) + 1) + _LETTERS[letter.upper()] + _SIGNS[sign]


@dataclass(frozen=True)
class Measurement:
    """What `measure` found in one recording."""

    start: int
    """The frame where the sound starts."""
    frequency: float
    """The fundamental of the sustain, in Hz."""
    note: int
    """The nearest MIDI note number."""
    cents: float
    """How far the sustain is from that note; positive is sharp."""
    clean: float
    """The share (0 to 1) of spectral-peak energy that lies on harmonics of the fundamental."""
    rich: float
    """The share (0 to 1) of the energy that lies around harmonics 2 to 4."""
    other: tuple[float, float] | None
    """The strongest peak that is not on a harmonic: its frequency and its level in dB
    under the strongest peak. `None` when every peak is on a harmonic."""
    attack_cents: float
    """How far the first 120 ms are from the sustain, in cents."""
    length: float
    """Seconds from the start until the level has fallen 20 dB under its peak."""
    seconds: float
    """The length of the whole recording."""
    peak_db: float
    """The highest sample, in dB under full scale."""

    @property
    def name(self) -> str:
        return note_name(self.note)


def _peaks(
    mono: NDArray[np.float64], rate: int, low: float = 25.0, high: float = 6000.0
) -> list[tuple[float, float]]:
    """The spectral peaks of `mono` between `low` and `high` Hz as (frequency, magnitude),
    within 45 dB of the strongest, one for each main lobe of the window."""
    size = 1 << math.ceil(math.log2(max(len(mono) * 8, 1 << 17)))
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)), size))
    freqs = np.fft.rfftfreq(size, 1 / rate)
    bins = np.flatnonzero((freqs >= low) & (freqs <= high))
    if len(bins) < 3:
        return []
    inner = bins[1:-1]
    floor = spectrum[bins].max() * 10 ** (-45 / 20)
    here, before, after = spectrum[inner], spectrum[inner - 1], spectrum[inner + 1]
    found = inner[(here > before) & (here >= after) & (here > floor)]
    a, b, c = spectrum[found - 1], spectrum[found], spectrum[found + 1]
    curve = a - 2 * b + c
    shift = np.divide(0.5 * (a - c), curve, out=np.zeros_like(curve), where=curve != 0)
    candidates = sorted(
        zip(((found + shift) * rate / size).tolist(), b.tolist(), strict=True),
        key=lambda peak: -peak[1],
    )
    lobe = 2.0 * rate / len(mono)
    kept: list[tuple[float, float]] = []
    for frequency, magnitude in candidates:
        if all(abs(frequency - other) > 0.7 * lobe for other, _ in kept):
            kept.append((frequency, magnitude))
    return sorted(kept)


def _fundamental(
    peaks: Sequence[tuple[float, float]],
) -> tuple[float, float, tuple[float, float] | None]:
    """The fundamental that explains most of the energy of `peaks`, the share it explains,
    and the strongest peak it does not explain."""
    freqs = np.array([f for f, _ in peaks])
    energy = np.array([m * m for _, m in peaks])
    total = float(energy.sum())

    def on_harmonics(f0: float) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
        number = np.maximum(1, np.round(freqs / f0))
        return number, np.abs(1200 * np.log2(freqs / (number * f0))) <= TOLERANCE

    def is_a_fundamental(f0: float) -> bool:
        # A fundamental is itself a peak, or its second and third harmonics both are.
        # Without this, a fraction of the true fundamental "explains" a stray partial
        # that happens to fall on one of its many harmonics.
        number, on = on_harmonics(f0)
        present = set(number[on].astype(int).tolist())
        return 1 in present or {2, 3} <= present

    strong = freqs[energy > 0.02 * energy.max()]
    every = sorted(
        {round(float(f) / k, 3) for f in strong for k in (1, 2, 3, 4) if 25.0 <= f / k <= 2500.0}
    )
    candidates = [f0 for f0 in every if is_a_fundamental(f0)] or every
    shares = [(float(energy[on_harmonics(f0)[1]].sum()) / total, f0) for f0 in candidates]
    best = max(share for share, _ in shares)
    # Of the candidates that explain about as much, the highest: a fundamental an octave
    # too low explains the same peaks.
    f0 = max(f for share, f in shares if share >= best - 0.03)
    number, on = on_harmonics(f0)
    weight = energy * on * (freqs > 80)  # peaks under 80 Hz are too coarse to tune by
    if weight.sum() <= 0:
        weight = energy * on
    refined = float(np.exp((weight * np.log(freqs / number)).sum() / weight.sum()))
    number, on = on_harmonics(refined)
    off = [
        (float(f), float(10 * np.log10(e / energy.max())))
        for f, e, is_on in zip(freqs, energy, on, strict=True)
        if not is_on
    ]
    other = max(off, key=lambda peak: peak[1]) if off else None
    return refined, float(energy[on].sum()) / total, other


def measure(samples: Samples, rate: int) -> Measurement:
    """Measure the note in `samples` (frames, channels).

    Raises `ValueError` when the recording is silent or too short to measure."""
    mono = samples.astype(np.float64).mean(axis=1)
    level = np.abs(mono)
    if len(mono) == 0 or level.max() <= 0:
        raise ValueError("the recording is silent")
    start = int(np.argmax(level > level.max() * 10 ** (SILENCE_DB / 20)))
    mono = mono[start:]
    hop = int(0.01 * rate)
    frames = len(mono) // hop
    if frames < 30:
        raise ValueError("the recording is too short to measure")
    rms = np.sqrt((mono[: frames * hop].reshape(frames, hop) ** 2).mean(axis=1))
    db = 20 * np.log10(rms / rms.max() + 1e-9)
    loudest = int(np.argmax(rms))
    under = np.flatnonzero(db[loudest:] < -20)
    length = float((loudest + under[0]) * hop / rate) if len(under) else frames * hop / rate

    first = int(0.15 * rate)
    last = int(min(max(0.6, min(length, 1.6)), len(mono) / rate - 0.01) * rate)
    peaks = _peaks(mono[first:last], rate) if last - first >= hop else []
    if not peaks:
        raise ValueError("the recording has no sustain to measure")
    frequency, clean, other = _fundamental(peaks)

    attack = _peaks(mono[: int(0.12 * rate)], rate, low=40.0)
    attack_cents = 1200 * math.log2(_fundamental(attack)[0] / frequency) if attack else 0.0

    body = mono[: int(1.5 * rate)]
    power = np.abs(np.fft.rfft(body * np.hanning(len(body)), 1 << 18)) ** 2
    freqs = np.fft.rfftfreq(1 << 18, 1 / rate)
    band = power[(freqs >= 20) & (freqs < 8000)].sum()
    rich = float(power[(freqs >= 1.6 * frequency) & (freqs < 4.5 * frequency)].sum() / band)

    pitch = 69 + 12 * math.log2(frequency / 440.0)
    return Measurement(
        start=start,
        frequency=frequency,
        note=round(pitch),
        cents=100 * (pitch - round(pitch)),
        clean=clean,
        rich=rich,
        other=other,
        attack_cents=attack_cents,
        length=length,
        seconds=len(samples) / rate,
        peak_db=float(20 * np.log10(np.abs(samples).max() + 1e-9)),
    )


def measure_file(path: Path) -> Measurement:
    """`measure` for a WAV file."""
    return measure(*wav.read(path))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mpc_iml.sounds.notes", description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="WAV recordings of single notes")
    args = parser.parse_args(argv)
    print(f"{'file':<28} {'note':<5} {'Hz':>8} {'cents':>6} {'clean':>7} {'rich':>6} {'attack':>7}")
    failed = 0
    for path in args.files:
        try:
            m = measure_file(path)
        except (OSError, ValueError) as error:
            print(f"{path.name}: {error}", file=sys.stderr)
            failed += 1
            continue
        print(
            f"{path.name:<28} {m.name:<5} {m.frequency:8.1f} {m.cents:+6.0f} "
            f"{100 * m.clean:6.1f}% {100 * m.rich:5.1f}% {m.attack_cents:+6.0f}c"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
