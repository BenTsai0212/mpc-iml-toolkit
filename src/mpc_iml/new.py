"""Start a practice repository: `python -m mpc_iml.new my-practice [--name NAME]`.

Writes a small project that depends on this toolkit, pinned to the git tag of the
running version (`v<__version__>`), with an empty implementation of the model
extension point (`mpc_iml.model.Model`), a test and a short README. The project
imports `mpc_iml` and contains no copy of toolkit code (ADR 0001).

The skeleton lives in `mpc_iml/project_template/` as `*.tmpl` files rendered with
`string.Template` (`$project`, `$package`, `$version`). In file paths, a directory
named `__package__` becomes the package name and a `dot-` prefix becomes `.`.
"""

import argparse
import keyword
import re
import sys
from collections.abc import Iterator, Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from string import Template

from mpc_iml import __version__

TEMPLATE_DIR = "project_template"
SUFFIX = ".tmpl"
# Longest package name whose rendered lines all stay within the project's ruff
# line length of 100 (Issue #263; `tests/test_new.py` checks a name of this length).
MAX_PACKAGE_LENGTH = 60


def package_name(name: str) -> str:
    """A Python package name from a directory or project name: `my-practice` -> `my_practice`."""
    package = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    if not package.isidentifier() or keyword.iskeyword(package) or package == "mpc_iml":
        raise ValueError(f"not a usable package name: {name!r} -> {package!r}")
    if len(package) > MAX_PACKAGE_LENGTH:
        raise ValueError(
            f"package name longer than {MAX_PACKAGE_LENGTH} characters: {name!r} -> {package!r}"
        )
    return package


def _walk(node: Traversable, path: PurePosixPath) -> Iterator[tuple[PurePosixPath, Traversable]]:
    for child in sorted(node.iterdir(), key=lambda c: c.name):
        if child.is_dir():
            yield from _walk(child, path / child.name)
        elif child.name.endswith(SUFFIX):
            yield path / child.name, child


def template_files() -> Iterator[tuple[PurePosixPath, Traversable]]:
    """`(relative path, file)` for every template file, paths still unrendered."""
    return _walk(files("mpc_iml") / TEMPLATE_DIR, PurePosixPath())


def _output_path(path: PurePosixPath, package: str) -> PurePosixPath:
    parts = []
    for part in path.parts:
        part = package if part == "__package__" else part
        part = "." + part.removeprefix("dot-") if part.startswith("dot-") else part
        parts.append(part.removesuffix(SUFFIX))
    return PurePosixPath(*parts)


def create(target: Path, name: str | None = None, version: str = __version__) -> list[Path]:
    """Write the project into `target` (new or empty); return the files written.

    The package name comes from `name`, or else from the directory name.
    """
    package = package_name(name if name is not None else target.resolve().name)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise FileExistsError(f"{target} exists and is not an empty directory")
    values = {"project": package.replace("_", "-"), "package": package, "version": version}
    written = []
    for path, source in template_files():
        out = target / _output_path(path, package)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(Template(source.read_text(encoding="utf-8")).substitute(values), "utf-8")
        written.append(out)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.new",
        description="Create a practice repository that depends on mpc-iml-toolkit.",
    )
    parser.add_argument("directory", type=Path, help="new or empty directory to create")
    parser.add_argument("--name", help="package name (default: from the directory name)")
    args = parser.parse_args(argv)
    try:
        written = create(args.directory, args.name)
    except (ValueError, FileExistsError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Created {len(written)} files in {args.directory}", file=sys.stderr)
    print(f"Pinned to mpc-iml-toolkit v{__version__}; next: cd {args.directory} && uv sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
