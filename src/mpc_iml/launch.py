"""One command for musicians: start the engine and open the front end (#66, ADR 0006).

`uv run mpc-iml` starts the engine with the data folder `./mpc-iml-data` and opens
the general Pure Data front end `patches/mpc-iml.pd` with the system's default app
for `.pd` files, after the engine listens, so the patch connects as it opens. The
preset is then chosen in the patch. `--no-patch` starts only the engine, for the Max
for Live device or your own front end. The other options are the engine's
(`python -m mpc_iml.engine --help`).

Where the patch cannot be opened (no app for `.pd` files, no opener on the system),
the command prints its path and keeps the engine running.
"""

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path

from mpc_iml.engine import Engine, add_engine_options, run

__all__ = ["DEFAULT_DATA", "build_parser", "main", "open_file", "patch_path"]

DEFAULT_DATA = "mpc-iml-data"
"""Default folder for saved example sets, relative to the current folder."""

PATCH = "patches/mpc-iml.pd"
"""The general front end inside the package (ADR 0006)."""


def patch_path() -> Path:
    """The general Pure Data front end as a file on disk."""
    return Path(str(files("mpc_iml").joinpath(PATCH)))


def open_file(path: Path, platform: str = sys.platform) -> bool:
    """Open `path` with the system's default app; `False` when that is not possible."""
    if platform == "win32":
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            return False
        try:
            startfile(str(path))
        except OSError:
            return False
        return True
    opener = "open" if platform == "darwin" else "xdg-open"
    if shutil.which(opener) is None:
        return False
    try:
        result = subprocess.run([opener, str(path)], check=False, capture_output=True)
    except OSError:
        return False
    return result.returncode == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mpc-iml",
        description="Start the IML engine and open the Pure Data front end (see the README).",
    )
    parser.add_argument(
        "data",
        nargs="?",
        default=DEFAULT_DATA,
        help=f"folder for saved example sets (default {DEFAULT_DATA})",
    )
    parser.add_argument(
        "--no-patch",
        action="store_true",
        help="start only the engine, for example for the Max for Live device",
    )
    add_engine_options(parser)
    return parser


def main(
    argv: Sequence[str] | None = None,
    opener: Callable[[Path], bool] = open_file,
) -> int:
    """Start the engine and, unless `--no-patch`, open the front end."""
    args = build_parser().parse_args(argv)

    def open_patch(engine: Engine) -> None:
        if args.no_patch:
            return
        path = patch_path()
        if opener(path):
            print(f"Opened the front end {path} (Pure Data).")
        else:
            print(f"Open this patch in Pure Data: {path}")

    return run(args, on_started=open_patch)


if __name__ == "__main__":
    raise SystemExit(main())
