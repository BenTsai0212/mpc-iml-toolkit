"""The per-bar log of `ensemble`'s choices (#196 PR 4b, Decision point 7).

With `learn-log 1` `ensemble` writes `<data folder>/learn/log-<time>.jsonl`
(`LOG_FOLDER`), JSON Lines as a recording (ADR 0002): a header line, then one line
per bar in bar order. It works with every `learn` mode, so a trial compares `off`,
`likes` and `demo` with one tool:

    {"format": "mpc-iml-ensemble-log", "format_version": 1, "toolkit": "0.1.0",
     "settings": {"learn": "likes", "bass-loop": "boom", ...}, "seed": null,
     "profile": "learn/ensemble.json"}
    {"bar": 5, "t": 12.5, "learn": "likes",
     "context": {"bass": "push/beat", "melody": "mid/8ths"},
     "choice": {"bass": {"loop": "boom", "variation": "push", "level": 2},
                "melody": null},
     "source": {"bass": "bandit", "melody": "-"},
     "rule": {"bass": "push", "melody": "home"},
     "like": false, "want": {"bass": "auto", "melody": "auto"},
     "example": {"bass": null, "melody": null},
     "groove": {"id": 2, "position": 5, "fill": false, "free": false}}

`bar` counts from song start, as the bars of a `record --clock` recording, so a
trial joins the two files by bar; `t` is the time of the bar line's clock tick on
the engine's input clock (`ClockState.t_tick`, the time base `record --clock` shares
with the pads), `null` before any tick. `context` is the drums of the bar before
(`learn.context`), `choice` what each loop plays (`null` when silent), `source`
where its variation came from (`-` when silent), `rule` what the #158 rules chose,
`like` whether a like referred to the bar (`learn.liked_bar`), `want` the wanted
variations it was planned with and `example` the label of the example the bar
added (`learn demo`). `groove` (#245) is the groove tracker's live decision on the
bar before (`grooves.Tracker`, as the status line shows it): the groove's `id` and
the bar's `position` in it (`null` outside a groove), `fill` and `free`. The field
was added to version 1 without a version bump: a log without it is still a
version 1 log, and `summary` adds its `grooves:` line only when the field is there.
A bar's line is written two bar lines later, once no like can
refer to it, and the lines still waiting when the log stops (`learn-log 0`); when
the engine quits, the last two bars are not written. The file is created at the
first bar, so a `learn-log 1` and `learn-log 0` with no bar between (as when a
trial checks its settings, #217) leave no file.

`python -m mpc_iml.learn summary <log>` prints `summary` of a log.
"""

import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from mpc_iml import __version__
from mpc_iml.learn import PARTS

__all__ = [
    "LOG_FOLDER",
    "LOG_FORMAT",
    "LOG_VERSION",
    "BarLog",
    "log_path",
    "read_log",
    "summary",
]

LOG_FORMAT = "mpc-iml-ensemble-log"
LOG_VERSION = 1
LOG_FOLDER = Path("learn")
"""The logs' folder in the engine's data folder."""
DELAY = 2
"""A bar's line waits this many bar lines for a like that refers to it."""


def log_path(folder: Path, now: datetime | None = None) -> Path:
    """A new log's path in `<folder>/learn/`: `log-<YYYYmmdd-HHMMSS>.jsonl`, with a
    number added when that file exists."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    path = folder / LOG_FOLDER / f"log-{stamp}.jsonl"
    number = 2
    while path.exists():
        path = folder / LOG_FOLDER / f"log-{stamp}-{number}.jsonl"
        number += 1
    return path


class BarLog:
    """An open log: the file and its header are written at the first bar (#217), each
    bar's line once no like can refer to it (module docstring). Not thread-safe;
    `ensemble` holds its lock."""

    def __init__(
        self, path: Path, settings: Mapping[str, str], seed: int | None, profile: str | None
    ) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO | None = None
        self._pending: dict[int, dict[str, Any]] = {}
        self._header = {
            "format": LOG_FORMAT,
            "format_version": LOG_VERSION,
            "toolkit": __version__,
            "settings": dict(settings),
            "seed": seed,
            "profile": profile,
        }

    @property
    def written(self) -> bool:
        """Whether the file exists: a bar was added."""
        return self._file is not None

    def bar(self, record: dict[str, Any]) -> None:
        """Add the line of the bar `record["bar"]`, planned now; write the lines no
        like can refer to any more (all of them after a song restart). The first
        bar creates the file with the header."""
        if self._file is None:
            self._file = self.path.open("x", encoding="utf-8")
            self._write(self._header)
        bar = int(record["bar"])
        record.setdefault("like", False)
        record.setdefault("example", {p: None for p in PARTS})
        if any(b >= bar for b in self._pending):
            self._flush(None)
        self._pending[bar] = record
        self._flush(bar - DELAY)

    def like(self, bar: int) -> None:
        """A like referred to `bar` (written or not yet planned: nothing)."""
        if bar in self._pending:
            self._pending[bar]["like"] = True

    def example(self, bar: int, part: str, label: str) -> None:
        """The bar `bar` added an example of `part` labelled `label`."""
        if bar in self._pending:
            self._pending[bar]["example"][part] = label

    def close(self) -> None:
        """Write the lines still waiting and close the file (none without a bar)."""
        if self._file is None:
            return
        self._flush(None)
        self._file.close()

    def _flush(self, upto: int | None) -> None:
        for bar in sorted(self._pending):
            if upto is not None and bar > upto:
                break
            self._write(self._pending.pop(bar))

    def _write(self, data: Mapping[str, Any]) -> None:
        assert self._file is not None
        self._file.write(json.dumps(data, separators=(",", ":")) + "\n")
        self._file.flush()


def read_log(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The header and the bar lines of the log at `path`. `ValueError` (with the
    reason) for a file that cannot be read or is not a version 1 log."""
    try:
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: {error}") from error
    if not lines or not isinstance(lines[0], dict):
        raise ValueError(f"{path}: not a {LOG_FORMAT} {LOG_VERSION}: no header")
    header = lines[0]
    if header.get("format") != LOG_FORMAT or header.get("format_version") != LOG_VERSION:
        raise ValueError(f"{path}: not a {LOG_FORMAT} {LOG_VERSION}")
    bars = lines[1:]
    for line in bars:
        if not isinstance(line, dict) or not isinstance(line.get("bar"), int):
            raise ValueError(f"{path}: not a {LOG_FORMAT} {LOG_VERSION}: bad line {line!r}")
    return header, bars


def summary(header: Mapping[str, Any], bars: list[dict[str, Any]]) -> str:
    """The text `python -m mpc_iml.learn summary` prints: per `learn` mode the bars,
    the like rate, how often each loop's variation differed from the rules', the
    examples per label, and the grooves, fill bars and free bars (#245) when the
    log has them."""
    lines = [f"log: toolkit {header.get('toolkit')}, {len(bars)} bars"]
    modes = list(dict.fromkeys(str(b.get("learn", "off")) for b in bars))
    for mode in modes:
        mine = [b for b in bars if str(b.get("learn", "off")) == mode]
        likes = sum(1 for b in mine if b.get("like"))
        lines.append(f"{mode}: {len(mine)} bars, {likes} likes ({likes / len(mine):.0%} of bars)")
        for part in PARTS:
            playing = [b for b in mine if (b.get("choice") or {}).get(part)]
            differ = sum(1 for b in playing if b["choice"][part]["variation"] != b["rule"][part])
            rate = f" ({differ / len(playing):.0%})" if playing else ""
            sources = Counter(str(b["source"][part]) for b in playing)
            shown = ", ".join(f"{s} {n}" for s, n in sorted(sources.items()))
            lines.append(
                f"  {part}: {len(playing)} bars playing, {differ} differ from the rules{rate}"
                + (f"; {shown}" if shown else "")
            )
            labels = Counter(
                str(b["example"][part]) for b in mine if (b.get("example") or {}).get(part)
            )
            if labels:
                counted = ", ".join(f"{label} {n}" for label, n in sorted(labels.items()))
                lines.append(f"  {part} examples: {counted}")
    tracked = [b["groove"] for b in bars if isinstance(b.get("groove"), dict)]
    if tracked:
        ids = {g["id"] for g in tracked if g.get("id") is not None}
        fills = sum(1 for g in tracked if g.get("fill"))
        free = sum(1 for g in tracked if g.get("free"))
        lines.append(f"grooves: {len(ids)}, fill bars: {fills}, free bars: {free}")
    return "\n".join(lines)
