"""Drum hits for a sound set: one WAV file from one recording (#272, ADR 0013).

The musician puts the hits on their own pads; the set does not map them. A hit starts
32 frames before the sound (the first sample within 40 dB of the peak), lasts the
given seconds, ends with a 30 ms fade and peaks 3 dB under full scale.

`python -m mpc_iml.sounds.hits <name> <file> --out <folder> [--seconds <seconds>]`
writes `<folder>/hits/<name>.wav` and records the hit in `<folder>/sound-set.json`.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from mpc_iml.sounds import soundset, wav
from mpc_iml.sounds.instrument import LEAD
from mpc_iml.sounds.notes import SILENCE_DB
from mpc_iml.sounds.soundset import Origin, SetHit
from mpc_iml.sounds.wav import Samples

SECONDS = 0.5
"""The length of a hit when none is given."""
FADE = 0.03
"""Seconds of fade at the end of a hit."""
PEAK_DB = -3.0
"""The peak of a hit, in dB full scale."""


def prepare_hit(samples: Samples, rate: int, seconds: float) -> tuple[Samples, float]:
    """A drum hit cut from `samples`, and the gain in dB that levelled it.

    Raises `ValueError` for a silent recording or a length that is not above 0."""
    if seconds <= 0:
        raise ValueError(f"a hit must last more than 0 seconds, not {seconds}")
    level = np.abs(samples).max(axis=1) if len(samples) else np.zeros(0, dtype=np.float32)
    if len(level) == 0 or level.max() <= 0:
        raise ValueError("the recording is silent")
    threshold = level.max() * 10 ** (SILENCE_DB / 20)
    start = max(0, int(np.argmax(level >= threshold)) - LEAD)
    hit = samples[start : start + round(seconds * rate)].copy()
    fade = min(int(FADE * rate), len(hit))
    hit[len(hit) - fade :] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    peak = float(np.abs(hit).max())
    if peak <= 0:
        raise ValueError("the recording is silent")
    gain = 10 ** (PEAK_DB / 20) / peak
    return hit * np.float32(gain), 20 * float(np.log10(gain))


def make_hit(
    name: str,
    file: Path,
    out: Path,
    *,
    seconds: float = SECONDS,
    origin: Origin | None = None,
) -> SetHit:
    """Write the hit `name` from the recording `file` as `out/hits/<name>.wav` and record
    it in `out/sound-set.json`, replacing a hit of the same name.

    Raises `ValueError` when `name` is not a name or the recording cannot be used, and
    `SoundSetError` when the folder's `sound-set.json` or `origin` cannot be accepted;
    nothing is written then."""
    soundset.check_name(name)
    document = soundset.read_document(out)
    soundset.check_origins([origin] if origin is not None else [])
    samples, rate = wav.read(file)
    hit, gain_db = prepare_hit(samples, rate, seconds)
    sample = f"hits/{name}.wav"
    (out / "hits").mkdir(parents=True, exist_ok=True)
    wav.write(out / sample, hit, rate)
    entry: dict[str, object] = {
        "sample": sample,
        "file": file.name,
        "seconds": len(hit) / rate,
        "gain_db": gain_db,
    }
    if origin is not None:
        entry["origin"] = origin.to_json()
    document["hits"][name] = entry
    soundset.write_document(out, document)
    return SetHit(name, out / sample, file.name, len(hit) / rate, gain_db, origin)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.sounds.hits",
        description=(__doc__ or "").split("\n\n")[0],
    )
    parser.add_argument("name", help="the hit's name, used for the file name")
    parser.add_argument("file", type=Path, help="a WAV recording of one hit")
    parser.add_argument("--out", type=Path, required=True, help="the sound set folder")
    parser.add_argument(
        "--seconds", type=float, default=SECONDS, help=f"length in seconds ({SECONDS} by default)"
    )
    args = parser.parse_args(argv)
    try:
        hit = make_hit(args.name, args.file, args.out, seconds=args.seconds)
    except (OSError, ValueError) as error:
        print(error)
        return 1
    print(
        f"{hit.name}: hits/{hit.name}.wav  {hit.seconds:.2f} s  level {hit.gain_db:+.1f} dB  "
        f"from {hit.file}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
