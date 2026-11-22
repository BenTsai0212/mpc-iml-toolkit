"""Session files of a trial (#197): JSON Lines, appended after each step.

One file per trial, `<data folder>/trials/<YYYYMMDD-HHMMSS>/session.jsonl`, next
to the recordings. A crash keeps what was already answered. The records:

- `header` (first): date, `main` commit, toolkit version, trial file name and
  content, seed, repeats, play order as letters, letter to condition mapping and
  engine options;
- `condition` (one per condition played): letter, position in the order,
  recording file name, bars played, scores, answers and engine errors;
- `ranking` (last, optional): the letters best first.

The tool writes only into the session folder and does not upload or commit
anything (RFC 0005, Scope rules).
"""

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = [
    "SESSION_FILE",
    "SESSION_FORMAT",
    "TRIALS_FOLDER",
    "ConditionRecord",
    "Header",
    "Session",
    "SessionError",
    "SessionWriter",
    "git_commit",
    "read_session",
    "session_folder",
]

SESSION_FORMAT = "mpc-iml-session"
SESSION_FILE = "session.jsonl"
TRIALS_FOLDER = "trials"
"""The folder of sessions in the engine's data folder."""


class SessionError(Exception):
    """A session file is invalid."""


@dataclass(frozen=True)
class Header:
    """The first record of a session file."""

    date: str
    commit: str
    dirty: bool | None
    version: str
    trial_file: str
    trial: Mapping[str, Any]
    seed: int
    repeats: int
    order: Sequence[str]
    mapping: Mapping[str, str]
    engine: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConditionRecord:
    """The record of one condition played."""

    letter: str
    position: int
    recording: str
    bars: int
    scores: Mapping[str, int]
    answers: Mapping[str, str]
    errors: Sequence[str] = ()


@dataclass(frozen=True)
class Session:
    """A session file read back."""

    header: Header
    conditions: tuple[ConditionRecord, ...]
    ranking: tuple[str, ...] | None = None

    def condition_name(self, letter: str) -> str:
        """The condition behind a code letter."""
        return self.header.mapping[letter]


def git_commit(folder: Path) -> tuple[str, bool | None]:
    """The commit checked out at `folder` and whether the tree is dirty; `-` outside git."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=folder, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=folder,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "-", None
    return head, bool(status.strip())


def session_folder(data_folder: Path, now: datetime) -> Path:
    """A new session folder `<data folder>/trials/<YYYYMMDD-HHMMSS>/`, created here."""
    folder = data_folder / TRIALS_FOLDER / now.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=False)
    return folder


class SessionWriter:
    """Appends the records of one session file, flushing after each."""

    def __init__(self, path: Path, header: Header) -> None:
        self.path = path
        self._letters = set(header.mapping)
        self._ranked = False
        with path.open("x", encoding="utf-8") as stream:
            stream.write(_line(_header_record(header)))

    def condition(self, record: ConditionRecord) -> None:
        if record.letter not in self._letters:
            raise SessionError(f"unknown letter {record.letter!r}")
        if self._ranked:
            raise SessionError("the ranking is already written")
        self._append({"type": "condition", **asdict(record), "errors": list(record.errors)})

    def ranking(self, letters: Sequence[str]) -> None:
        if sorted(letters) != sorted(self._letters):
            raise SessionError(f"the ranking must list each letter once: {list(letters)}")
        self._ranked = True
        self._append({"type": "ranking", "ranking": list(letters)})

    def _append(self, record: Mapping[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(_line(record))


def _header_record(header: Header) -> dict[str, Any]:
    data = asdict(header)
    data["order"] = list(header.order)
    return {"type": "header", "format": SESSION_FORMAT, "format_version": 1, **data}


def _line(record: Mapping[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False) + "\n"


def _fields(record: dict[str, Any], names: Sequence[str], origin: str) -> dict[str, Any]:
    missing = [name for name in names if name not in record]
    if missing:
        raise SessionError(f"{origin}: missing {', '.join(missing)}")
    return {name: record[name] for name in names}


def read_session(path: Path) -> Session:
    """Read a session file back; raises `SessionError`."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionError(f"{path}: cannot read: {exc}") from exc
    if not records or not isinstance(records[0], dict) or records[0].get("type") != "header":
        raise SessionError(f"{path}: the first record must be the header")
    first = records[0]
    if first.get("format") != SESSION_FORMAT or first.get("format_version") != 1:
        raise SessionError(f"{path}: not an {SESSION_FORMAT} file of format_version 1")
    names = [f for f in Header.__dataclass_fields__ if f != "engine"]
    header = Header(**_fields(first, names, f"{path}: header"), engine=first.get("engine", {}))
    conditions: list[ConditionRecord] = []
    ranking: tuple[str, ...] | None = None
    for number, record in enumerate(records[1:], start=2):
        origin = f"{path}: record {number}"
        kind = record.get("type") if isinstance(record, dict) else None
        if ranking is not None:
            raise SessionError(f"{origin}: nothing may follow the ranking")
        if kind == "condition":
            names = [f for f in ConditionRecord.__dataclass_fields__ if f != "errors"]
            values = _fields(record, names, origin)
            if values["letter"] not in header.mapping:
                raise SessionError(f"{origin}: unknown letter {values['letter']!r}")
            errors = tuple(record.get("errors", ()))
            conditions.append(ConditionRecord(**values, errors=errors))
        elif kind == "ranking":
            ranking = tuple(_fields(record, ["ranking"], origin)["ranking"])
        else:
            raise SessionError(f"{origin}: unknown record type {kind!r}")
    return Session(header, tuple(conditions), ranking)
