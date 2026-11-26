"""A small WAV reader: the standard library and `numpy`, no audio library (#268).

Reads PCM of 16, 24 and 32 bits and 32-bit float (format tags 1 and 3, also when
written as `WAVE_FORMAT_EXTENSIBLE`), mono or stereo. Chunks it does not know, such as
`fact`, `PEAK`, `LIST` or `bext`, are skipped wherever they are.
"""

import struct
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

Samples = NDArray[np.float32]
"""Audio as (frames, channels), full scale at 1.0."""

PCM = 1
FLOAT = 3
EXTENSIBLE = 0xFFFE


class WavError(ValueError):
    """The file is not a WAV file this reader can read."""


def _format(chunk: bytes) -> tuple[int, int, int, int]:
    """The format tag, channels, sample rate and bits of a `fmt ` chunk."""
    if len(chunk) < 16:
        raise WavError("the fmt chunk is too short")
    tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", chunk[:16])
    if tag == EXTENSIBLE:
        if len(chunk) < 40:
            raise WavError("the extensible fmt chunk is too short")
        # The sub-format GUID starts with the format tag it stands for.
        tag = struct.unpack("<H", chunk[24:26])[0]
    return tag, channels, rate, bits


SUPPORTED = {(FLOAT, 32), (PCM, 16), (PCM, 24), (PCM, 32)}


def _decode(data: bytes, tag: int, channels: int, bits: int) -> Samples:
    if (tag, bits) not in SUPPORTED:
        kind = {PCM: "PCM", FLOAT: "float"}.get(tag, f"format tag {tag}")
        raise WavError(
            f"cannot read {bits}-bit {kind}: only 16, 24 and 32-bit PCM and 32-bit float"
        )
    width = bits // 8
    usable = len(data) - len(data) % (width * channels)
    data = data[:usable]
    if tag == FLOAT and bits == 32:
        values = np.frombuffer(data, dtype="<f4").astype(np.float32)
    elif tag == PCM and bits == 16:
        values = (np.frombuffer(data, dtype="<i2") / 32768.0).astype(np.float32)
    elif tag == PCM and bits == 24:
        raw = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        number = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
        number = np.where(number >= 1 << 23, number - (1 << 24), number)
        values = (number / float(1 << 23)).astype(np.float32)
    else:
        values = (np.frombuffer(data, dtype="<i4") / float(1 << 31)).astype(np.float32)
    return values.reshape(-1, channels)


def read(path: Path) -> tuple[Samples, int]:
    """The samples of a WAV file as (frames, channels), and its sample rate.

    Raises `WavError` when the file is not a WAV file of a format this reader knows."""
    content = path.read_bytes()
    if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
        raise WavError(f"{path.name} is not a WAV file")
    found: tuple[int, int, int, int] | None = None
    data: bytes | None = None
    at = 12
    while at + 8 <= len(content):
        name = content[at : at + 4]
        size = struct.unpack("<I", content[at + 4 : at + 8])[0]
        body = content[at + 8 : at + 8 + size]
        if name == b"fmt ":
            found = _format(body)
        elif name == b"data":
            data = body
        at += 8 + size + size % 2
    if found is None:
        raise WavError(f"{path.name} has no fmt chunk")
    if data is None:
        raise WavError(f"{path.name} has no data chunk")
    tag, channels, rate, bits = found
    if channels not in (1, 2):
        raise WavError(f"{path.name} has {channels} channels: only mono or stereo")
    if rate <= 0:
        raise WavError(f"{path.name} has no sample rate")
    return _decode(data, tag, channels, bits), rate
