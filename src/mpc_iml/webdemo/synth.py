"""Render a `sim.Song` to audio with a small numpy synth (#166).

No system software: every part is a few lines of numpy. Kick: a sine whose pitch
falls, with a decay. Snare: noise and a short tone. Hat: high-passed noise, short.
Bass: a band-limited saw whose harmonics are weighted by a one-pole low-pass.
Keys: a few sine partials through the same low-pass, its cutoff following the
brightness CC the melody sent, so the hats are heard in the keys.

The noise comes from a seeded generator, so the same song always gives the same
samples. The result is mono `int16` at `RATE`, ready for `gr.Audio` as
`(RATE, samples)`.
"""

from collections.abc import Callable

import numpy as np
import numpy.typing as npt

from mpc_iml.webdemo.sim import Note, Song

__all__ = ["RATE", "TAIL", "render"]

RATE = 22_050
TAIL = 0.5
"""Seconds of release after the song's last tick."""

Samples = npt.NDArray[np.float64]

_GAIN = {"kick": 0.9, "snare": 0.5, "hat": 0.25, "bass": 0.45, "keys": 0.3}
_RELEASE = 0.05
_DEFAULT_BRIGHTNESS = 64


def render(song: Song, seed: int = 0) -> npt.NDArray[np.int16]:
    """The samples of `song`: its length plus `TAIL`, at most full scale."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(round((song.seconds + TAIL) * RATE)))
    spt = song.seconds_per_tick
    for note in song.notes:
        voice = _voice(note, note.ticks * spt, _brightness(song, note.tick), rng)
        voice *= _GAIN[note.part] * note.velocity / 127
        start = int(round(note.tick * spt * RATE))
        end = min(start + len(voice), len(out))
        out[start:end] += voice[: end - start]
    peak = float(np.max(np.abs(out), initial=0.0))
    if peak > 1.0:
        out /= peak
    return np.asarray(np.round(out * 32_767), dtype=np.int16)


def _brightness(song: Song, tick: int) -> int:
    """The brightness CC in effect at `tick`."""
    value = _DEFAULT_BRIGHTNESS
    for at, cc in song.brightness:
        if at > tick:
            break
        value = cc
    return value


def _voice(note: Note, seconds: float, brightness: int, rng: np.random.Generator) -> Samples:
    if note.part == "kick":
        t = _time(0.35)
        sweep = 45 + 75 * np.exp(-t / 0.04)
        return np.sin(2 * np.pi * np.cumsum(sweep) / RATE) * np.exp(-t / 0.12)
    if note.part == "snare":
        t = _time(0.2)
        noise = rng.uniform(-1, 1, len(t)) * np.exp(-t / 0.06)
        return 0.6 * noise + 0.4 * np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)
    if note.part == "hat":
        t = _time(0.06)
        noise = np.diff(rng.uniform(-1, 1, len(t) + 1)) / 2
        return noise * np.exp(-t / 0.02)
    freq = 440.0 * 2 ** ((note.pitch - 69) / 12)
    t = _time(seconds + _RELEASE)
    if note.part == "bass":
        tone = _partials(t, freq, 16, 900.0, lambda k: 1 / k)
        return 0.5 * tone * _envelope(t, seconds, 0.6)
    cutoff = 400.0 + 4_600.0 * brightness / 127
    tone = _partials(t, freq, 6, cutoff, lambda k: 1 / k**1.5)
    return 0.5 * tone * _envelope(t, seconds, 0.8)


def _time(seconds: float) -> Samples:
    return np.arange(int(round(seconds * RATE))) / RATE


def _partials(
    t: Samples, freq: float, count: int, cutoff: float, amp: Callable[[int], float]
) -> Samples:
    """Harmonics 1 to `count` below Nyquist, each weighted by `amp(k)` and by the
    magnitude of a one-pole low-pass at `cutoff`."""
    tone = np.zeros(len(t))
    for k in range(1, count + 1):
        if k * freq >= RATE / 2:
            break
        weight = amp(k) / np.sqrt(1 + (k * freq / cutoff) ** 2)
        tone += weight * np.sin(2 * np.pi * k * freq * t)
    return tone


def _envelope(t: Samples, seconds: float, decay: float) -> Samples:
    """A 5 ms attack, an exponential decay, and a linear release after `seconds`."""
    env = np.minimum(t / 0.005, 1.0) * np.exp(-t / decay)
    release = np.clip(1 - (t - seconds) / _RELEASE, 0.0, 1.0)
    return np.asarray(env * release, dtype=np.float64)
