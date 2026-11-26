"""The WAV reader of `mpc_iml.sounds` (#268)."""

import ast
import struct
from pathlib import Path

import numpy as np
import pytest
from tones import RATE, chunk, tone, write

from mpc_iml.sounds.wav import WavError, read

SRC = Path(__file__).resolve().parents[1] / "src" / "mpc_iml"


@pytest.mark.parametrize(
    ("bits", "tag", "error"), [(16, 1, 1e-4), (24, 1, 1e-6), (32, 1, 1e-8), (32, 3, 0.0)]
)
@pytest.mark.parametrize("channels", [1, 2])
def test_formats(tmp_path: Path, bits: int, tag: int, error: float, channels: int) -> None:
    samples = tone(45.0, seconds=0.5)[:, :channels].copy()
    samples[100, 0] = -1.0
    path = write(
        tmp_path / "note.wav",
        samples,
        bits=bits,
        tag=tag,
        before=[chunk(b"LIST", b"INFOodd")],
        after=[chunk(b"bext", b"\0" * 12), chunk(b"id3 ", b"x")],
    )
    read_back, rate = read(path)
    assert rate == RATE
    assert read_back.dtype == np.float32
    assert read_back.shape == samples.shape
    assert np.abs(read_back - samples).max() <= error + 1e-9
    assert read_back[100, 0] == -1.0


def test_extensible_float(tmp_path: Path) -> None:
    samples = tone(45.0, seconds=0.5)
    fmt = struct.pack("<HHIIHH", 0xFFFE, 2, RATE, RATE * 8, 8, 32)
    fmt += struct.pack("<HHI", 22, 32, 3) + struct.pack("<H", 3) + b"\0" * 14
    body = b"WAVE" + chunk(b"fmt ", fmt) + chunk(b"data", samples.astype("<f4").tobytes())
    path = tmp_path / "x.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    assert np.array_equal(read(path)[0], samples)


@pytest.mark.parametrize(
    ("bits", "tag", "message"),
    [(8, 1, "8-bit PCM"), (4, 1, "4-bit PCM"), (64, 3, "64-bit float"), (16, 2, "format tag 2")],
)
def test_other_formats_are_refused(tmp_path: Path, bits: int, tag: int, message: str) -> None:
    fmt = struct.pack("<HHIIHH", tag, 1, RATE, RATE * bits // 8, bits // 8, bits)
    body = b"WAVE" + chunk(b"fmt ", fmt) + chunk(b"data", b"\0" * 64)
    path = tmp_path / "x.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    with pytest.raises(WavError, match=message):
        read(path)


def test_broken_files_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.wav"
    path.write_bytes(b"OggS" + b"\0" * 40)
    with pytest.raises(WavError, match="not a WAV file"):
        read(path)
    path.write_bytes(b"RIFF\0\0\0\0WAVE" + chunk(b"data", b"\0" * 4))
    with pytest.raises(WavError, match="no fmt chunk"):
        read(path)
    fmt = struct.pack("<HHIIHH", 1, 1, RATE, RATE * 2, 2, 16)
    path.write_bytes(b"RIFF\0\0\0\0WAVE" + chunk(b"fmt ", fmt))
    with pytest.raises(WavError, match="no data chunk"):
        read(path)
    fmt = struct.pack("<HHIIHH", 1, 6, RATE, RATE * 12, 12, 16)
    path.write_bytes(b"RIFF\0\0\0\0WAVE" + chunk(b"fmt ", fmt) + chunk(b"data", b"\0" * 24))
    with pytest.raises(WavError, match="only mono or stereo"):
        read(path)


def test_the_core_install_does_not_import_sounds() -> None:
    """`mpc_iml.sounds` needs numpy from the `demo` extra; only it imports itself, and
        the web demo's band tab (#280) and its "Make sounds" part (#288), which only
        `webdemo.app` imports, after the demo extra is checked; and `webdemo.__main__`,
        which reads the generator file after the demo extra is checked (#288). An import
    under `if TYPE_CHECKING:` is never run and does not count."""
    tab = SRC / "webdemo" / "bandtab.py"
    make = SRC / "webdemo" / "makesounds.py"
    main = SRC / "webdemo" / "__main__.py"
    for path in SRC.rglob("*.py"):
        if SRC / "sounds" in path.parents or path in (tab, make):
            continue
        if path == main:
            text = path.read_text(encoding="utf-8")
            assert text.index("from mpc_iml.sounds") > text.index("if not gradio_installed()")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        typing_only = {
            id(inner)
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
            for inner in ast.walk(node)
        }
        for node in ast.walk(tree):
            if id(node) in typing_only:
                continue
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            assert not any(n.startswith("mpc_iml.sounds") for n in names), path
            if path != SRC / "webdemo" / "app.py":
                assert not any(n.startswith("mpc_iml.webdemo.bandtab") for n in names), path
