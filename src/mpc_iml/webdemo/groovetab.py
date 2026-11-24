"""The grooves tab of the web demo: sort one's own grooves into named groups (#249, PR 3).

The functions before `tab` hold the page's logic without Gradio, on a `Sort` (the
grouping, the tracked recordings when there are any, and the file it was opened from
or saved to). `assign` and `annotate` change one groove; `edit_groups` applies the
groups table, and deleting a group that holds grooves needs a second press after a
warning that says how many grooves move to "not sure". `save` writes
`<data folder>/grooves/groups-<time>.json` (ADR 0012): saving a file that was opened
from there overwrites it, "Save as new" writes a new one. Files are written only in
the data folder. `export` writes the plain text of the sort next to the saved file.
`reopen` reads a file and tracks its recordings again with the saved thresholds; when
a recording is missing or changed, or the tracker finds other grooves, the cards have
the prototype loop only, and the message says why.

`tab` builds the tab; `app.build` leaves it out under `--share`.
"""

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mpc_iml.grooves import Tracker
from mpc_iml.grooves.groups import (
    FOLDER,
    GrooveEntry,
    GrooveGroups,
    Group,
    read_groups,
    write_groups,
)
from mpc_iml.grooves.offline import Many, track_many
from mpc_iml.webdemo import groovecards
from mpc_iml.webdemo.groovecards import audio, cards, export_text, find_recordings, load

if TYPE_CHECKING:
    import gradio as gr

__all__ = [
    "GROUP_HEADERS",
    "NOT_SURE",
    "Edit",
    "Sort",
    "annotate",
    "assign",
    "choices",
    "edit_groups",
    "export",
    "group_rows",
    "now",
    "reopen",
    "resolve",
    "save",
    "start_sort",
    "tab",
]

NOT_SURE = 0
"""The dropdown value of "not sure"."""

GROUP_HEADERS = ["id", "name", "what it is for"]


@dataclass(frozen=True, eq=False)
class Sort:
    """The page's state: the `groups`, the tracked recordings (`many`, `None` when
    reopened without them) and the `path` of the file it was opened from or saved to.
    It compares and hashes by identity, as Gradio hashes a `gr.State` value to see
    whether it changed, and `GrooveGroups` holds dicts."""

    groups: GrooveGroups
    many: Many | None = None
    path: Path | None = None


@dataclass(frozen=True)
class Edit:
    """The result of `edit_groups`: the new `groups` (unchanged when `confirm` is
    needed), a `message`, and whether a second press is needed to delete groups."""

    groups: GrooveGroups
    message: str
    confirm: bool = False


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def resolve(text: str, data: Path | None) -> Path:
    """A path from the page: relative to `data` when there is one, else absolute."""
    given = Path(text.strip())
    if given.is_absolute():
        return given
    if data is None:
        raise ValueError(f"{text.strip()}: give an absolute path, or start the demo with --data")
    return data / given


def start_sort(
    text: str, data: Path | None, blind: bool, seed: int, created: str
) -> tuple[Sort, tuple[str, ...]]:
    """Track the recordings of the path box (`groovecards.find_recordings`) and start
    a sort; also the skipped files of its folders."""
    loaded = load(find_recordings(text, data), created, blind, seed)
    return Sort(loaded.groups, loaded.many), loaded.skipped


def choices(groups: GrooveGroups) -> list[tuple[str, int]]:
    """The dropdown choices of a card: "not sure", then each group."""
    return [("not sure", NOT_SURE)] + [(g.name or f"group {g.id}", g.id) for g in groups.groups]


def _change(groups: GrooveGroups, groove: int, **kwargs: Any) -> GrooveGroups:
    if all(e.id != groove for e in groups.grooves):
        raise ValueError(f"no groove {groove}")
    return replace(
        groups,
        grooves=tuple(replace(e, **kwargs) if e.id == groove else e for e in groups.grooves),
    )


def assign(groups: GrooveGroups, groove: int, group: int) -> GrooveGroups:
    """Put `groove` in `group` (`NOT_SURE` for not sure)."""
    if group != NOT_SURE and all(g.id != group for g in groups.groups):
        raise ValueError(f"no group {group}")
    return _change(groups, groove, group=None if group == NOT_SURE else group)


def annotate(groups: GrooveGroups, groove: int, note: str) -> GrooveGroups:
    """Set the note of `groove`."""
    return _change(groups, groove, note=note.strip())


def group_rows(groups: GrooveGroups) -> list[list[str | int]]:
    """The groups table: id, name, what it is for; then a blank row for a new group."""
    rows: list[list[str | int]] = [[g.id, g.name, g.purpose] for g in groups.groups]
    return [*rows, ["", "", ""]]


def _cell(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def edit_groups(groups: GrooveGroups, rows: list[list[Any]], confirmed: bool = False) -> Edit:
    """Apply the groups table. A row with no id is a new group (blank rows are
    skipped); a group whose row is gone is deleted and its grooves become "not sure".
    Deleting groups that hold grooves needs `confirmed`. Raises `ValueError` for an
    unknown or repeated id."""
    known = {g.id: g for g in groups.groups}
    kept: list[Group] = []
    next_id = max(known, default=0) + 1
    seen: set[int] = set()
    for i, row in enumerate(rows, start=1):
        cells = [_cell(c) for c in [*row, "", "", ""][:3]]
        ident, name, purpose = cells
        if not ident:
            if name or purpose:
                kept.append(Group(next_id, name, purpose))
                next_id += 1
            continue
        try:
            n = int(float(ident))
        except ValueError:
            raise ValueError(f"row {i}: id must be a group's number, got {ident!r}") from None
        if n not in known:
            raise ValueError(f"row {i}: no group {n}; leave the id empty for a new group")
        if n in seen:
            raise ValueError(f"row {i}: group {n} is listed twice")
        seen.add(n)
        kept.append(Group(n, name, purpose))
    gone = [g for g in groups.groups if g.id not in seen]
    moved = [e for e in groups.grooves if e.group in {g.id for g in gone}]
    names = ", ".join(repr(g.name or f"group {g.id}") for g in gone)
    if moved and not confirmed:
        return Edit(
            groups,
            f"Deleting {names} moves {len(moved)} groove{'s' * (len(moved) != 1)} to "
            "not sure. Press Apply again to delete.",
            confirm=True,
        )
    gone_ids = {g.id for g in gone}
    grooves = tuple(replace(e, group=None) if e.group in gone_ids else e for e in groups.grooves)
    message = f"Deleted {names}." if gone else "Groups updated."
    if moved:
        message = f"Deleted {names}: {len(moved)} groove{'s' * (len(moved) != 1)} now not sure."
    return Edit(replace(groups, groups=tuple(kept), grooves=grooves), message)


def _stamp(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y%m%d-%H%M%S")


def save(sort: Sort, data: Path | None, when: str, as_new: bool = False) -> Sort:
    """Write the sort (module docstring) with `updated` set to `when`; returns the
    sort with its file's path. Raises `ValueError` without a data folder."""
    if data is None:
        raise ValueError("start the demo with --data <folder> to save")
    folder = data / FOLDER
    inside = sort.path is not None and sort.path.parent.resolve() == folder.resolve()
    if inside and not as_new:
        assert sort.path is not None
        path = sort.path
    else:
        stamp = _stamp(when if as_new or not sort.groups.created else sort.groups.created)
        path = folder / f"groups-{stamp}.json"
        n = 2
        while path.exists():
            path = folder / f"groups-{stamp}-{n}.json"
            n += 1
    groups = replace(sort.groups, updated=when)
    write_groups(path, groups)
    return Sort(groups, sort.many, path)


def export(sort: Sort) -> Path:
    """Write the sort's plain text (`groovecards.export_text`) next to its saved
    file, as `<same name>.txt`. Raises `ValueError` before it is saved."""
    if sort.path is None:
        raise ValueError("save the groups first; the text is written next to the file")
    path = sort.path.with_suffix(".txt")
    path.write_text(export_text(sort.groups), encoding="utf-8")
    return path


def reopen(text: str, data: Path | None) -> tuple[Sort, str]:
    """Open a saved file (module docstring). Raises `GroupsFormatError` or `OSError`
    for a file that cannot be read."""
    path = resolve(text, data)
    groups = read_groups(path)
    missing = []
    changed = []
    paths = []
    for s in groups.sources:
        try:
            real = resolve(s.path, data)
        except ValueError:
            missing.append(s.path)
            continue
        if not real.is_file():
            missing.append(s.path)
            continue
        modified = datetime.fromtimestamp(real.stat().st_mtime, UTC)
        if modified.isoformat(timespec="seconds") != s.modified:
            changed.append(s.path)
        paths.append(real)
    if missing or changed:
        why = [f"missing: {', '.join(missing)}"] * bool(missing)
        why += [f"changed: {', '.join(changed)}"] * bool(changed)
        return Sort(groups, None, path), "Prototype only; recordings " + "; ".join(why) + "."
    st = groups.settings
    tracker = Tracker(st["similar"], st["return"], int(st["free_bars"]), st["decay"])
    try:
        many = track_many(paths, tracker)
    except ValueError as error:
        return Sort(groups, None, path), f"Prototype only; the recordings: {error}"
    given = {str(real): s.path for real, s in zip(paths, groups.sources, strict=True)}
    many = replace(many, sources=tuple(replace(s, path=given[s.path]) for s in many.sources))
    found = {g.id: g.prototype for g in many.grooves}
    saved = {e.id: e.prototype for e in groups.grooves}
    if found != saved:
        return Sort(groups, None, path), (
            "Prototype only; the tracker finds other grooves in the recordings now."
        )
    return Sort(groups, many, path), f"Opened {path.name} with its recordings."


def tab(gr: Any, data: Path | None) -> None:
    """The grooves tab, inside the page's `gr.Blocks` (module docstring)."""
    with gr.Tab("grooves"):
        gr.Markdown(
            "Listen to the grooves you played, put each in a group or in *not sure*, "
            "and name the groups. Recordings: a folder or files, one per line"
            + (f", relative to the data folder `{data}`." if data else " (absolute paths).")
            + ("" if data else " Start the demo with `--data <folder>` to save.")
        )
        with gr.Row():
            paths = gr.Textbox(label="recordings (a folder or files, one per line)", lines=2)
            with gr.Column(min_width=160):
                blind = gr.Checkbox(value=False, label="blind (no ids, shuffled)")
                seed = gr.Number(value=0, precision=0, minimum=0, label="seed")
                load_button = gr.Button("Load", variant="primary")
        with gr.Row():
            opened = gr.Textbox(label="or open a saved file (grooves/groups-….json)")
            open_button = gr.Button("Open")
        info = gr.Markdown()
        groups_table = gr.Dataframe(
            headers=GROUP_HEADERS,
            datatype=["str", "str", "str"],
            type="array",
            interactive=True,
            static_columns=[0],
            row_count=1,
            label="groups (add a row with no id for a new group; delete a row to delete it)",
        )
        apply_button = gr.Button("Apply groups")
        with gr.Row():
            save_button = gr.Button("Save", interactive=data is not None)
            new_button = gr.Button("Save as new", interactive=data is not None)
            export_button = gr.Button("Export text", interactive=data is not None)
        download = gr.File(label="text export", interactive=False)
        sort_state = gr.State(None)
        shown = gr.State(None)
        warned = gr.State(None)

        def fail(error: Exception) -> "gr.Error":
            return gr.Error(str(error))

        def shown_of(sort: Sort) -> tuple[Sort, float]:
            return sort, datetime.now(UTC).timestamp()

        def opened_outputs(sort: Sort, message: str) -> tuple[object, ...]:
            lines = [f"**{groovecards.summary(sort.groups)}**"] + ([message] if message else [])
            return sort, shown_of(sort), group_rows(sort.groups), "\n\n".join(lines), None

        def on_load(text: str, blind: bool, seed: float) -> tuple[object, ...]:
            try:
                sort, files = start_sort(text or "", data, bool(blind), int(seed or 0), now())
            except (ValueError, OSError) as e:
                raise fail(e) from e
            skipped = "; ".join(files)
            return opened_outputs(sort, f"Skipped: {skipped}" if skipped else "")

        def on_open(text: str) -> tuple[object, ...]:
            try:
                sort, message = reopen(text or "", data)
            except (ValueError, OSError) as e:
                raise fail(e) from e
            return opened_outputs(sort, message)

        def on_apply(sort: Sort | None, rows: list[list[Any]], last: object) -> tuple[object, ...]:
            if sort is None:
                raise gr.Error("load recordings or open a file first")
            try:
                edit = edit_groups(sort.groups, rows or [], confirmed=last == rows)
            except ValueError as e:
                raise fail(e) from e
            if edit.confirm:
                gr.Warning(edit.message)
                return sort, gr.skip(), gr.skip(), rows
            gr.Info(edit.message)
            new = replace(sort, groups=edit.groups)
            return new, shown_of(new), group_rows(new.groups), None

        def on_save(sort: Sort | None, as_new: bool) -> tuple[Sort, None]:
            if sort is None:
                raise gr.Error("load recordings or open a file first")
            try:
                sort = save(sort, data, now(), as_new)
            except (ValueError, OSError) as e:
                raise fail(e) from e
            assert sort.path is not None
            gr.Info(f"Saved {sort.path.name}")
            return sort, None

        def on_export(sort: Sort | None) -> tuple[Sort, str]:
            if sort is None:
                raise gr.Error("load recordings or open a file first")
            try:
                if sort.path is None:
                    sort = save(sort, data, now())
                return sort, str(export(sort))
            except (ValueError, OSError) as e:
                raise fail(e) from e

        outputs = [sort_state, shown, groups_table, info, warned]
        load_button.click(on_load, [paths, blind, seed], outputs)
        open_button.click(on_open, opened, outputs)
        apply_button.click(
            on_apply, [sort_state, groups_table, warned], [sort_state, shown, groups_table, warned]
        )
        save_button.click(lambda s: on_save(s, False), sort_state, [sort_state, warned])
        new_button.click(lambda s: on_save(s, True), sort_state, [sort_state, warned])
        export_button.click(on_export, sort_state, [sort_state, download])

        def show_cards(view: tuple[Sort, float] | None) -> None:
            if view is None:
                return
            sort = view[0]
            options = choices(sort.groups)
            entries = {e.id: e for e in sort.groups.grooves}
            for card in cards(sort.groups, sort.many):
                entry: GrooveEntry = entries[card.groove]
                with gr.Group():
                    head = f"### {card.title}" + (f"\n{card.counts}" if card.counts else "")
                    gr.Markdown(f"{head}\n```\n{card.grid}\n```\n{card.words}")
                    with gr.Row():
                        for clip in (*card.played, card.loop):
                            gr.Audio(
                                audio(clip),
                                label=clip.label,
                                type="numpy",
                                interactive=False,
                                min_width=200,
                            )
                    with gr.Row():
                        group = gr.Dropdown(
                            options,
                            value=entry.group or NOT_SURE,
                            label="group",
                            min_width=160,
                        )
                        note = gr.Textbox(value=entry.note, label="note", min_width=200)

                def on_group(s: Sort, value: int, groove: int = card.groove) -> Sort:
                    return replace(s, groups=assign(s.groups, groove, int(value)))

                def on_note(s: Sort, value: str, groove: int = card.groove) -> Sort:
                    return replace(s, groups=annotate(s.groups, groove, value or ""))

                group.change(on_group, [sort_state, group], sort_state)
                note.change(on_note, [sort_state, note], sort_state)

        gr.render(inputs=shown)(show_cards)
