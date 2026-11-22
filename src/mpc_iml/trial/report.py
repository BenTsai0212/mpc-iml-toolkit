"""Reports of blind trials (#197): `python -m mpc_iml.trial report <session>...`.

Plain text with tab-separated columns, so a table can be pasted into a sheet.

- **Per session**: one row per condition played, under its revealed name, with the
  raw score of each 1-5 question, the rank, and the measures of its recording
  (`mpc_iml.measures`; the response columns are marked exploratory). The text
  answers follow the table.
- **Across sessions**: for each condition and 1-5 question (and the rank), the raw
  scores of every session in date order, with the mean next to them, never alone.
- **Consistent differences**: a pair of conditions is `consistent` on a question
  when one scored higher in two or more sessions and lower in none (for the rank,
  lower is better). No tests of significance.

The report only reads the session folders.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from mpc_iml.measures import EXPLORATORY, format_value, measure, replay_settings
from mpc_iml.recording import RecordingFormatError, read_recording
from mpc_iml.trial.session import SESSION_FILE, Session, SessionError, read_session
from mpc_iml.trial.spec import TrialError, parse_trial
from mpc_iml.webdemo.sim import BEATS_PER_BAR, Settings

__all__ = [
    "MIN_SESSIONS",
    "RANK",
    "Row",
    "add_report_parser",
    "consistent",
    "load_sessions",
    "report",
    "run_report",
    "rows",
    "session_scores",
]

RANK = "rank"
"""The pseudo-question of the ranking (1 is best)."""
MIN_SESSIONS = 2
"""Sessions in which a difference must be seen to be marked consistent."""


@dataclass(frozen=True)
class Row:
    """One condition played in a session."""

    name: str
    letter: str
    recording: str
    scores: dict[str, int]
    answers: dict[str, str]
    rank: int | None
    measures: dict[str, float | int | None]


Loaded = tuple[Path, Session]


def load_sessions(paths: Sequence[Path]) -> list[Loaded]:
    """Read session files (or their folders) and sort them by date."""
    loaded = []
    for path in paths:
        file = path / SESSION_FILE if path.is_dir() else path
        loaded.append((file, read_session(file)))
    return sorted(loaded, key=lambda item: item[1].header.date)


def _beats_per_bar(session: Session) -> int:
    options = list(session.header.engine.get("options", []))
    if "--beats-per-bar" in options[:-1]:
        try:
            return int(options[options.index("--beats-per-bar") + 1])
        except ValueError:
            pass
    return BEATS_PER_BAR


def _replay_settings(session: Session, name: str) -> Settings | None:
    try:
        trial = parse_trial(session.header.trial, session.header.trial_file)
        chosen = next(c for c in trial.conditions if c.name == name)
        return replay_settings(trial.messages(chosen))
    except (TrialError, StopIteration, ValueError):
        return None


def rows(file: Path, session: Session, with_measures: bool = True) -> list[Row]:
    """The rows of one session in play order; a missing recording has no measures."""
    ranking = session.ranking or ()
    beats = _beats_per_bar(session)
    result = []
    for record in session.conditions:
        name = session.condition_name(record.letter)
        values: dict[str, float | int | None] = {}
        if with_measures:
            try:
                events = read_recording(file.parent / record.recording).events
            except (OSError, RecordingFormatError):
                events = None
            if events is not None:
                settings = _replay_settings(session, name)
                values = measure(events, beats, settings=settings).summary()
        rank = ranking.index(record.letter) + 1 if record.letter in ranking else None
        result.append(
            Row(
                name,
                record.letter,
                record.recording,
                dict(record.scores),
                dict(record.answers),
                rank,
                values,
            )
        )
    return result


def _score_ids(sessions: Sequence[Loaded]) -> list[str]:
    ids: list[str] = []
    for _, session in sessions:
        for question in session.header.trial.get("questions", []):
            if question.get("scale") == "1-5" and question.get("id") not in ids:
                ids.append(question["id"])
    return ids


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def session_scores(table: Sequence[Row], question: str) -> dict[str, float]:
    """Per condition, the mean score of one session on `question` (or `RANK`)."""
    found: dict[str, list[float]] = {}
    for row in table:
        value = row.rank if question == RANK else row.scores.get(question)
        if value is not None:
            found.setdefault(row.name, []).append(value)
    return {name: sum(v) / len(v) for name, v in found.items()}


def consistent(
    per_session: Sequence[dict[str, float]], lower_is_better: bool = False
) -> list[tuple[str, str, int, int]]:
    """Pairs `(better, worse, sessions better, sessions both played)` where `better`
    scored higher (lower for the rank) in `MIN_SESSIONS` or more sessions and lower
    in none."""
    names = sorted({name for scores in per_session for name in scores})
    found = []
    for a, b in combinations(names, 2):
        both = [s for s in per_session if a in s and b in s]
        above = sum(s[a] > s[b] for s in both)
        below = sum(s[a] < s[b] for s in both)
        if lower_is_better:
            above, below = below, above
        if above >= MIN_SESSIONS and below == 0:
            found.append((a, b, above, len(both)))
        elif below >= MIN_SESSIONS and above == 0:
            found.append((b, a, below, len(both)))
    return found


def _column(key: str) -> str:
    return f"{key} (exploratory)" if key in EXPLORATORY else key


def _int_or_dash(value: int | None) -> str:
    return "-" if value is None else str(value)


def report(sessions: Sequence[Loaded], with_measures: bool = True) -> list[str]:
    """The report lines for sessions sorted by date."""
    ids = _score_ids(sessions)
    tables = [rows(file, session, with_measures) for file, session in sessions]
    lines: list[str] = []
    for (file, session), table in zip(sessions, tables, strict=True):
        h = session.header
        dirty = " (dirty)" if h.dirty else ""
        lines += [
            f"Session {file.parent.name}\t{h.date}\tcommit {h.commit[:12]}{dirty}",
            f"trial {h.trial_file}\tseed {h.seed}\torder {' '.join(h.order)}",
        ]
        keys = next((list(r.measures) for r in table if r.measures), [])
        lines.append("\t".join(["condition", "letter", *ids, RANK, *map(_column, keys)]))
        for r in table:
            scores = [_int_or_dash(r.scores.get(q)) for q in ids]
            measures = [format_value(r.measures.get(k)) for k in keys]
            lines.append("\t".join([r.name, r.letter, *scores, _int_or_dash(r.rank), *measures]))
        if session.ranking is None:
            lines.append("no ranking: the session ended early")
        for r in table:
            for question, answer in r.answers.items():
                if answer:
                    lines.append(f"{r.name}\t{question}\t{answer}")
        lines.append("")
    lines.append(f"Across {len(sessions)} sessions (raw scores in date order)")
    lines.append("condition\tquestion\tscores\tmean")
    names = sorted({r.name for table in tables for r in table})
    per_question = {q: [session_scores(t, q) for t in tables] for q in [*ids, RANK]}
    for name in names:
        for question, per_session in per_question.items():
            values = [s[name] for s in per_session if name in s]
            raw = " ".join(format_value(int(v) if v == int(v) else v) for v in values)
            lines.append(f"{name}\t{question}\t{raw or '-'}\t{format_value(_mean(values))}")
    lines += ["", f"Consistent differences (higher in {MIN_SESSIONS}+ sessions, lower in none)"]
    marked = 0
    for question, per_session in per_question.items():
        for better, worse, count, both in consistent(per_session, question == RANK):
            lines.append(f"{question}\t{better} > {worse}\tconsistent\t{count} of {both} sessions")
            marked += 1
    if not marked:
        lines.append("none")
    return lines


def add_report_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "sessions", nargs="+", type=Path, help="session files (session.jsonl) or their folders"
    )
    parser.add_argument(
        "--no-measures", action="store_true", help="leave out the measures of the recordings"
    )


def run_report(args: argparse.Namespace, say: Callable[[str], None] = print) -> int:
    """`trial report`: returns the exit status."""
    try:
        sessions = load_sessions(args.sessions)
    except SessionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for line in report(sessions, not args.no_measures):
        say(line)
    return 0
