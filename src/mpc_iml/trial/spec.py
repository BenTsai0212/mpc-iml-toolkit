"""The trial file format `mpc-iml-trial` (#197).

A trial file lists the conditions to compare and the questions asked after each:

    {"format": "mpc-iml-trial", "format_version": 1, "bars": 16,
     "base": {"rhythm": [0], "surprise": [1]},
     "conditions": [{"name": "rhythm-0", "settings": {"rhythm": [0]}},
                    {"name": "rhythm-1", "settings": {"rhythm": [1]}}],
     "questions": [{"id": "heard-me", "text": "It heard me", "scale": "1-5"},
                   {"id": "broken", "text": "A moment that felt broken", "scale": "text"}]}

A setting is an `ensemble` control name (`/mpciml/preset/ensemble/<control>`) with
its argument list; the engine checks the values. `base` is sent before every
condition, then the condition's own settings, so every control a condition sets
must also be in `base`: nothing carries over from the condition played before.
Code letters are not in the file; `order.letters` gives them by play order.

The optional `guide` (#241) is what the musician reads, in musical terms:
`guide.start` once before the first condition, `guide.condition` before every
condition. Each is a string or a list of strings, the same for every condition so
it does not reveal which one plays. Files without it are read as before, so the
field did not need a new format version.

The optional `min_bars` (#243) is the shortest a condition should be: Enter before
it asks the musician whether to end the condition anyway. A positive whole number,
at most `bars`; files without it end at Enter as before.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "BARS",
    "DEFAULT_BARS",
    "SCALES",
    "TRIAL_FORMAT",
    "Condition",
    "Guide",
    "Question",
    "Trial",
    "TrialError",
    "load_trial",
    "parse_trial",
]

TRIAL_FORMAT = "mpc-iml-trial"
DEFAULT_BARS = 16
BARS = (1, 256)
"""The allowed range of `bars`, the length of a condition."""
SCALES = ("1-5", "text")
"""Question scales: a whole score 1-5, or free text."""

_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_KEYS = {
    "format",
    "format_version",
    "title",
    "bars",
    "min_bars",
    "base",
    "conditions",
    "questions",
    "guide",
}
_GUIDE_KEYS = ("start", "condition")

Arg = int | float | str
Settings = Mapping[str, tuple[Arg, ...]]


class TrialError(Exception):
    """A trial file is invalid."""


@dataclass(frozen=True)
class Condition:
    """A named set of `ensemble` controls."""

    name: str
    settings: Settings


@dataclass(frozen=True)
class Question:
    """A question asked after each condition."""

    id: str
    text: str
    scale: str


@dataclass(frozen=True)
class Guide:
    """Lines for the musician: `start` once before the first condition, `condition`
    before every condition."""

    start: tuple[str, ...] = ()
    condition: tuple[str, ...] = ()


@dataclass(frozen=True)
class Trial:
    """A validated trial file."""

    bars: int
    base: Settings
    conditions: tuple[Condition, ...]
    questions: tuple[Question, ...]
    title: str = ""
    guide: Guide = Guide()
    min_bars: int | None = None
    """The shortest a condition should be (#243); `None` when the file has none."""

    def messages(self, condition: Condition) -> list[tuple[str, tuple[Arg, ...]]]:
        """The controls to send before `condition`: `base`, then its own settings."""
        return [*self.base.items(), *condition.settings.items()]


def _fail(origin: str, message: str) -> TrialError:
    return TrialError(f"{origin}: {message}")


def _name(value: Any, origin: str, what: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise _fail(origin, f"{what} must be lower case letters, digits and hyphens: {value!r}")
    return value


def _settings(value: Any, origin: str, what: str) -> dict[str, tuple[Arg, ...]]:
    if not isinstance(value, dict):
        raise _fail(origin, f"{what} must map control names to argument lists")
    settings: dict[str, tuple[Arg, ...]] = {}
    for control, args in value.items():
        _name(control, origin, f"{what}: control")
        if not isinstance(args, list) or not all(
            isinstance(a, int | float | str) and not isinstance(a, bool) for a in args
        ):
            raise _fail(origin, f"{what} {control}: expected a list of numbers and strings")
        settings[control] = tuple(args)
    return settings


def _question(entry: Any, origin: str, index: int) -> Question:
    what = f"question {index + 1}"
    if not isinstance(entry, dict) or set(entry) - {"id", "text", "scale"}:
        raise _fail(origin, f"{what}: expected {{id, text, scale}}")
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _fail(origin, f"{what}: text must be a non-empty string")
    scale = entry.get("scale")
    if scale not in SCALES:
        raise _fail(origin, f"{what}: scale must be one of {', '.join(SCALES)}, got {scale!r}")
    return Question(_name(entry.get("id"), origin, f"{what}: id"), text, str(scale))


def _lines(value: Any, origin: str, what: str) -> tuple[str, ...]:
    lines = [value] if isinstance(value, str) else value
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise _fail(origin, f"{what} must be a string or a list of strings")
    return tuple(lines)


def _guide(value: Any, origin: str) -> Guide:
    if not isinstance(value, dict):
        raise _fail(origin, f"guide must be an object with {' and/or '.join(_GUIDE_KEYS)}")
    if unknown := set(value) - set(_GUIDE_KEYS):
        raise _fail(origin, f"guide: unknown fields: {', '.join(sorted(map(str, unknown)))}")
    start, condition = (_lines(value.get(key, []), origin, f"guide.{key}") for key in _GUIDE_KEYS)
    return Guide(start, condition)


def parse_trial(data: Any, origin: str = "trial") -> Trial:
    """Validate a trial file's JSON object; raises `TrialError`."""
    if not isinstance(data, dict):
        raise _fail(origin, "not a JSON object")
    if data.get("format") != TRIAL_FORMAT or data.get("format_version") != 1:
        raise _fail(origin, f"not an {TRIAL_FORMAT} file of format_version 1")
    if unknown := set(data) - _KEYS:
        raise _fail(origin, f"unknown fields: {', '.join(sorted(unknown))}")
    title = data.get("title", "")
    if not isinstance(title, str):
        raise _fail(origin, "title must be a string")
    bars = data.get("bars", DEFAULT_BARS)
    if isinstance(bars, bool) or not isinstance(bars, int) or not BARS[0] <= bars <= BARS[1]:
        raise _fail(origin, f"bars must be a whole number {BARS[0]}-{BARS[1]}, got {bars!r}")
    min_bars = data.get("min_bars")
    if min_bars is not None and (
        isinstance(min_bars, bool) or not isinstance(min_bars, int) or not 1 <= min_bars <= bars
    ):
        raise _fail(
            origin, f"min_bars must be a whole number 1-{bars} (at most bars), got {min_bars!r}"
        )
    base = _settings(data.get("base", {}), origin, "base")
    entries = data.get("conditions")
    if not isinstance(entries, list) or len(entries) < 2:
        raise _fail(origin, "conditions must be a list of at least 2 conditions")
    if len(entries) > 26:
        raise _fail(origin, "at most 26 conditions (one letter each)")
    conditions: list[Condition] = []
    for index, entry in enumerate(entries):
        what = f"condition {index + 1}"
        if not isinstance(entry, dict) or set(entry) != {"name", "settings"}:
            raise _fail(origin, f"{what}: expected {{name, settings}}")
        name = _name(entry["name"], origin, f"{what}: name")
        settings = _settings(entry["settings"], origin, f"{what} ({name}) settings")
        if missing := sorted(set(settings) - set(base)):
            raise _fail(
                origin,
                f"{what} ({name}) sets {', '.join(missing)}, which base must also set, "
                "so nothing carries over from the condition before",
            )
        conditions.append(Condition(name, settings))
    names = [c.name for c in conditions]
    if len(set(names)) != len(names):
        raise _fail(origin, "condition names must be unique")
    entries = data.get("questions")
    if not isinstance(entries, list) or not entries:
        raise _fail(origin, "questions must be a non-empty list")
    questions = tuple(_question(e, origin, i) for i, e in enumerate(entries))
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        raise _fail(origin, "question ids must be unique")
    guide = _guide(data.get("guide", {}), origin)
    return Trial(bars, base, tuple(conditions), questions, title, guide, min_bars)


def load_trial(path: Path) -> tuple[Trial, dict[str, Any]]:
    """Read and validate a trial file; also return its JSON content for the session file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(str(path), f"cannot read: {exc}") from exc
    return parse_trial(data, str(path)), data
