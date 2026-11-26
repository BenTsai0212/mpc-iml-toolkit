"""A generator for the tests (#284): a script run with the test's Python that writes a
synthetic tone for the note named in the prompt. No model is run in CI.

    fake_generator.py --prompt <prompt> --out <file> [--seconds <s>] [--seed <n>]
        [--log <file>] [--high <note>,...] [--fail <note>,...] [--silent <note>,...]
        [--sleep <note>,...] [--nothing <note>,...]

A prompt that ends in `note <name>` asks for that note; any other prompt asks for a
drum hit. `--high` answers those notes an octave high, `--fail` prints two lines and
ends with status 3, `--silent` writes silence, `--sleep` sleeps 30 seconds, and
`--nothing` writes no file. `--log` appends each call's arguments as a JSON line.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from tones import RATE, tone  # noqa: E402

from mpc_iml.sounds import wav  # noqa: E402
from mpc_iml.sounds.notes import note_number  # noqa: E402


def names(value: str) -> set[int]:
    return {note_number(name) for name in value.split(",") if name}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--log", type=Path)
    for flag in ("high", "fail", "silent", "sleep", "nothing"):
        parser.add_argument(f"--{flag}", type=names, default=set())
    args = parser.parse_args()
    if args.log is not None:
        with args.log.open("a", encoding="utf-8") as log:
            log.write(json.dumps(sys.argv[1:]) + "\n")
    match = re.search(r"note (\S+)$", args.prompt)
    note = note_number(match.group(1)) if match else None
    if note in args.fail:
        print("loading the model")
        print("error: out of memory")
        return 3
    if note in args.sleep:
        time.sleep(30)
    if note in args.nothing:
        return 0
    frames = int(args.seconds * RATE)
    if note in args.silent:
        samples = np.zeros((frames, 2), dtype=np.float32)
    elif note is None:
        rng = np.random.default_rng(args.seed)
        t = np.arange(frames) / RATE
        mono = 0.5 * rng.standard_normal(frames) * np.exp(-t / 0.05)
        samples = np.stack([mono, mono], axis=1).astype(np.float32)
    else:
        pitch = note + (12 if note in args.high else 0)
        samples = tone(float(pitch), seconds=args.seconds)
    wav.write(args.out, samples, RATE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
