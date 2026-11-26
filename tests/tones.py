"""Synthetic notes and WAV files for the tests (#268): no audio is kept in the repository."""

import struct
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from mpc_iml.sounds.wav import Samples

RATE = 44100


def tone(
    pitch: float,
    *,
    seconds: float = 2.0,
    lead: float = 0.05,
    harmonics: Sequence[float] = (1.0, 0.5, 0.25, 0.12),
    decay: float = 1.2,
    attack_cents: float = 0.0,
    extra: tuple[float, float] | None = None,
    level: float = 0.5,
) -> Samples:
    """A decaying stereo tone at MIDI pitch `pitch` (60.07 is C4, 7 cents sharp), after
    `lead` seconds of silence.

    `attack_cents` starts the note that much sharp and lets it settle within about
    100 ms, as a plucked string does. `extra` adds one partial that is not a harmonic:
    its frequency as a multiple of the fundamental, and its amplitude."""
    t = np.arange(int(seconds * RATE)) / RATE
    f0 = 440.0 * 2 ** ((pitch - 69) / 12)
    glide = 2 ** (attack_cents / 1200 * np.exp(-t / 0.03))
    phase = 2 * np.pi * np.cumsum(f0 * glide) / RATE
    wave = np.zeros_like(t)
    for number, amplitude in enumerate(harmonics, start=1):
        wave += amplitude * np.sin(number * phase)
    if extra is not None:
        wave += extra[1] * np.sin(2 * np.pi * f0 * extra[0] * t)
    envelope = np.exp(-t / decay) * np.minimum(1.0, t / 0.002)
    mono = np.concatenate([np.zeros(int(lead * RATE)), level * envelope * wave / sum(harmonics)])
    return np.stack([mono, mono], axis=1).astype(np.float32)


def chunk(name: bytes, body: bytes) -> bytes:
    """One RIFF chunk, padded to an even length."""
    return name + struct.pack("<I", len(body)) + body + b"\0" * (len(body) % 2)


def encode(samples: Samples, bits: int, tag: int) -> bytes:
    """The bytes of `samples` as little-endian PCM (`tag` 1) or float (`tag` 3)."""
    if tag == 3:
        return samples.astype("<f4").tobytes()
    scale = float(1 << (bits - 1))
    numbers = np.clip(np.round(samples.astype(np.float64) * scale), -scale, scale - 1)
    if bits == 16:
        return numbers.astype("<i2").tobytes()
    if bits == 32:
        return numbers.astype("<i4").tobytes()
    raw = numbers.astype("<i4").reshape(-1, 1).view(np.uint8)
    return raw[:, :3].tobytes()


def write(
    path: Path,
    samples: Samples,
    *,
    bits: int = 32,
    tag: int = 3,
    before: Sequence[bytes] = (),
    after: Sequence[bytes] = (),
    rate: int = RATE,
) -> Path:
    """Write `samples` as a WAV file; by default 32-bit float with `fact` and `PEAK`
    chunks, as the generated notes are. `before` and `after` are extra chunks around
    `data`."""
    channels = samples.shape[1]
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * block, block, bits)
    chunks = [chunk(b"fmt ", fmt)]
    if tag == 3:
        chunks.append(chunk(b"fact", struct.pack("<I", len(samples))))
        chunks.append(chunk(b"PEAK", b"\1\0\0\0" + b"\0" * (4 + 8 * channels)))
    chunks += [*before, chunk(b"data", encode(samples, bits, tag)), *after]
    body = b"WAVE" + b"".join(chunks)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path
