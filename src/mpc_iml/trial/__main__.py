"""`python -m mpc_iml.trial run <trial file> <data folder>`: a blind trial (#197)."""

import argparse
from collections.abc import Sequence

from mpc_iml.trial.run import add_run_parser, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.trial", description="Blind comparison trials of ensemble."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    add_run_parser(commands.add_parser("run", help="play a trial file under code letters"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
