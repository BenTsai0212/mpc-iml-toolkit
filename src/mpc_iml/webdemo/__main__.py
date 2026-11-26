"""Run the web demo: `uv run python -m mpc_iml.webdemo` (#166).

Opens on `127.0.0.1` only. `--share` asks Gradio for a temporary public link
through its share servers; only a person runs it, never an agent or CI. The grooves
tab (#249) saves in `--data <folder>`, and is left out under `--share`, so a
musician's playing never reaches a public link. The band tab (#280) lists the sound
sets in the subfolders of `--sounds <folder>`, and is left out under `--share` too.
"""

import argparse
import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path

INSTALL_HINT = (
    "the web demo needs the demo extra: run `uv sync --extra demo`, "
    "then `uv run python -m mpc_iml.webdemo`"
)


def gradio_installed() -> bool:
    """Whether Gradio is installed. A folder that Gradio leaves behind after it was
    removed (it writes a file there at run time) imports as an empty namespace
    package, so a module with no file does not count."""
    try:
        spec = importlib.util.find_spec("gradio")
    except (ImportError, ValueError):
        return False
    return spec is not None and spec.origin is not None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.webdemo", description="The ensemble preset without hardware."
    )
    parser.add_argument("--port", type=int, default=7860, help="local port (default 7860)")
    parser.add_argument(
        "--share", action="store_true", help="also make a temporary public link (Gradio)"
    )
    parser.add_argument(
        "--data",
        type=Path,
        help="data folder: the grooves tab reads recordings and saves groups here",
    )
    parser.add_argument(
        "--sounds",
        type=Path,
        help="a folder whose subfolders are sound sets, for the band tab",
    )
    args = parser.parse_args(argv)
    if not gradio_installed():
        print(INSTALL_HINT, file=sys.stderr)
        return 2
    from mpc_iml.webdemo.app import build

    build(args.data, args.share, args.sounds).launch(
        server_name="127.0.0.1", server_port=args.port, share=args.share
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
