"""The "Make sounds" part of the band tab: describe each player's sound in words, make
the sound set with the model the musician installed, and try a player again (#288,
RFC 0006 step 3, second part).

The functions take and return plain values, so the tests need no browser and no model:
`rows` are the table of players and hits with their words (recorded in the set when
an instrument or hit was generated, the band's defaults otherwise), `start_seed` is
the seed a name starts from (after the highest recorded for it, so the same words give
new takes), `chosen_at_start` what is chosen to make, `plan_line` what will happen
before anything runs, and `make` makes the chosen players and hits one after the
other with `bandset.generate_band`, yielding the lines of each as it finishes. It can
be given the function that runs one take (`generate.RunTake`).

Errors a musician can cause (a set name that is not a name, empty words, nothing
chosen, a folder that cannot be written, a `sound-set.json` that is refused, every
take failing) come back as lines, not exceptions.
"""

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from mpc_iml.bands import Band
from mpc_iml.sounds import bandset, soundset
from mpc_iml.sounds.generate import Generator, RunTake, run_take, take_lines
from mpc_iml.sounds.soundset import TAKES

__all__ = [
    "HEADERS",
    "HOW_TO_START",
    "chosen_at_start",
    "document",
    "made_lines",
    "make",
    "plan_line",
    "problem",
    "recorded",
    "rows",
    "set_name",
    "start_seed",
    "words_of",
]

HEADERS = ["name", "what", "words"]
HOW_TO_START = (
    "To make sounds from this page, start the demo with a sound sets folder and the "
    "generator file of a model you installed (ADR 0015): "
    "`uv run python -m mpc_iml.webdemo --sounds <folder> --generator <file>`."
)


def document(sounds: Path | None, name: str | None) -> dict[str, Any] | None:
    """The `sound-set.json` of the set `name` under `sounds`, or `None` when there is
    none or it cannot be read or accepted."""
    if sounds is None or not name or not soundset.NAME.fullmatch(name):
        return None
    folder = sounds / name
    if not (folder / soundset.FILE).is_file():
        return None
    try:
        return soundset.read_document(folder)
    except (OSError, ValueError):
        return None


def _entry(band: Band, data: Mapping[str, Any] | None, name: str) -> Mapping[str, Any] | None:
    """The instrument (for a player) or hit entry of `name` in the document `data`."""
    if data is None:
        return None
    group = "hits" if name in band.hits else "instruments"
    entry = data.get(group, {}).get(name)
    return entry if isinstance(entry, Mapping) else None


def _origins(entry: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """The generated origins of an instrument's files or of a hit."""
    if entry is None:
        return []
    parts = entry.get("files", [entry])
    found = []
    for part in parts if isinstance(parts, list) else []:
        origin = part.get("origin") if isinstance(part, Mapping) else None
        if isinstance(origin, Mapping) and origin.get("kind") == "generated":
            found.append(origin)
    return found


def recorded(band: Band, data: Mapping[str, Any] | None, name: str) -> str | None:
    """The words recorded in the set for the instrument or hit `name` when it was
    generated, or `None`."""
    for origin in _origins(_entry(band, data, name)):
        settings = origin.get("settings")
        words = settings.get("words") if isinstance(settings, Mapping) else None
        if isinstance(words, str) and words.strip():
            return words
    return None


def start_seed(band: Band, data: Mapping[str, Any] | None, name: str) -> int:
    """The seed to start from for `name`: one above the highest seed recorded for it in
    the set, or 1."""
    seeds = [o["seed"] for o in _origins(_entry(band, data, name)) if isinstance(o["seed"], int)]
    return max(seeds, default=0) + 1


def _defaults(band: Band) -> dict[str, tuple[str, str]]:
    """What each player and hit is (the player's part, or `hit`) and its default words."""
    found = {p.name: (str(p.plays.part), p.sound.words) for p in band.players}
    found.update({name: ("hit", hit.words) for name, hit in band.hits.items()})
    return found


def rows(band: Band, data: Mapping[str, Any] | None) -> list[list[str]]:
    """One row for each player and then each drum hit of `band`: name, what it is, and
    its words (recorded in the set `data` when it was generated, the band's otherwise)."""
    return [
        [name, what, recorded(band, data, name) or words]
        for name, (what, words) in _defaults(band).items()
    ]


def _has(band: Band, data: Mapping[str, Any] | None, name: str) -> bool:
    return _entry(band, data, name) is not None


def chosen_at_start(band: Band, data: Mapping[str, Any] | None) -> list[str]:
    """The players and hits the set `data` lacks: all of them when there is no set, none
    when it has them all."""
    return [name for name in bandset.names(band) if not _has(band, data, name)]


def set_name(band: Band, chosen: str | None) -> str:
    """The name of the set to make: the chosen set, or `<band>-set`."""
    return chosen or f"{band.name}-set"


def words_of(table: Sequence[Sequence[Any]]) -> dict[str, str]:
    """The words of each row of the table, by name."""
    return {str(row[0]): str(row[2] if row[2] is not None else "") for row in table if row}


def problem(band: Band, name: str, chosen: Sequence[str], words: Mapping[str, str]) -> str:
    """Why nothing can be made, or empty: a set name that is not a name, nothing
    chosen, a name that is not the band's, empty words for a chosen row."""
    if not soundset.NAME.fullmatch(name or ""):
        return f"The set name {name!r} is not a name: use lower case letters, digits and hyphens."
    if not chosen:
        return "Choose at least one player or hit to make."
    known = bandset.names(band)
    for each in chosen:
        if each not in known:
            return f"{each!r} is neither a player nor a hit of the band {band.name!r}."
        if not words.get(each, "").strip():
            return f"The words for {each!r} are empty: say what it should sound like."
    return ""


def plan_line(
    band: Band,
    data: Mapping[str, Any] | None,
    name: str,
    chosen: Sequence[str],
    words: Mapping[str, str],
) -> str:
    """What Make will do: the takes round 1 asks for, and what of the set it replaces;
    or why nothing can be made."""
    found = problem(band, name, chosen, words)
    if found:
        return found
    planned = bandset.plan(band, {n: words[n] for n in chosen}, list(chosen))
    replaced = [n for n in bandset.names(band) if n in chosen and _has(band, data, n)]
    what = (
        "replaces " + ", ".join(replaced) + f" in the set `{name}`"
        if replaced
        else f"replaces nothing in the set `{name}`"
    )
    return f"Round 1 asks for {planned.takes} take(s); Make {what}."


def made_lines(made: bandset.Made) -> list[str]:
    """The lines of one finished player (each take) or hit, then whether it was made."""
    lines: list[str] = []
    if made.instrument is not None:
        lines += take_lines(made.instrument)
    elif made.hit is not None:
        take = made.hit.take
        if made.hit.hit is None:
            lines.append(f"{made.name}: seed {take.seed}  failed: {made.hit.error}")
            lines += [f"    | {line}" for line in take.output.splitlines()]
        else:
            lines.append(f"{made.name}: seed {take.seed}, from {TAKES}/{made.hit.hit.file}")
    return [*lines, bandset.made_line(made)]


def make(
    band: Band,
    generator: Generator | None,
    sounds: Path | None,
    name: str,
    chosen: Sequence[str],
    words: Mapping[str, str],
    run: RunTake = run_take,
) -> Iterator[list[str]]:
    """Make the chosen players and hits of `band` in the set `name` under `sounds`, one
    after the other, each from `start_seed`; yield the lines of each as it finishes, and
    at the end the line of each (made or not, with the reason). When nothing can be made,
    yield why and run nothing."""
    if generator is None or sounds is None:
        yield [HOW_TO_START]
        return
    found = problem(band, name, chosen, words)
    if found:
        yield [found]
        return
    out = sounds / name
    finished: list[bandset.Made] = []
    for each in [n for n in bandset.names(band) if n in chosen]:
        try:
            data = soundset.read_document(out)
            seed = start_seed(band, data, each)
            results = bandset.generate_band(
                band,
                generator,
                out,
                words={each: words[each]},
                only=[each],
                seeds={each: seed},
                run=run,
            )
        except soundset.SoundSetError as error:
            yield [f"{out}: {error}; nothing more is made"]
            break
        except (OSError, ValueError) as error:
            results = [
                bandset.Made(each, "hit" if each in band.hits else "player", error=str(error))
            ]
        for made in results:
            finished.append(made)
            yield made_lines(made)
    if finished:
        count = sum(1 for m in finished if m.made)
        yield [
            f"{count} of {len(finished)} made in `{name}`:",
            *(bandset.made_line(m) for m in finished),
            "Listen before you keep the set.",
        ]
