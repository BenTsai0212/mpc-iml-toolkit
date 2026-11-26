"""The grooves tab: load, group, save, reopen and export on a data folder (#249, PR 3)."""

import os
from pathlib import Path

import pytest
from test_webdemo_groovecards import folder

from mpc_iml.grooves.groups import read_groups
from mpc_iml.webdemo import __main__ as webdemo_main
from mpc_iml.webdemo.groovecards import cards
from mpc_iml.webdemo.groovetab import (
    NOT_SURE,
    Sort,
    annotate,
    assign,
    choices,
    edit_groups,
    export,
    group_rows,
    reopen,
    resolve,
    save,
    start_sort,
)

CREATED = "2026-11-24T15:00:00+00:00"
LATER = "2026-11-24T15:20:00+00:00"


def started(tmp_path: Path, blind: bool = False) -> Sort:
    folder(tmp_path)
    sort, skipped = start_sort("trials/s1", tmp_path, blind, 7, CREATED)
    assert [Path(s.split(":")[0]).name for s in skipped] == ["engine.log", "session.jsonl"]
    return sort


def grouped(tmp_path: Path) -> Sort:
    sort = started(tmp_path)
    edit = edit_groups(sort.groups, [["", "the basic", "verses"], ["", "the lift", ""]])
    groups = assign(edit.groups, 1, 1)
    groups = annotate(assign(groups, 2, 2), 2, "  my chorus one ")
    return Sort(groups, sort.many)


def test_load_tracks_a_folder_relative_to_the_data_folder(tmp_path: Path) -> None:
    sort = started(tmp_path)
    assert [s.path for s in sort.groups.sources] == ["trials/s1/a.jsonl", "trials/s1/b.jsonl"]
    assert [e.id for e in sort.groups.grooves] == [1, 2, 3]
    assert all(e.group is None for e in sort.groups.grooves)
    assert sort.many is not None and sort.path is None
    assert choices(sort.groups) == [("not sure", NOT_SURE)]
    with pytest.raises(ValueError, match="--data"):
        start_sort("trials/s1", None, False, 0, CREATED)
    assert resolve("x.json", tmp_path) == tmp_path / "x.json"


def test_grooves_go_in_groups_and_change_their_mind(tmp_path: Path) -> None:
    sort = grouped(tmp_path)
    assert [(e.id, e.group, e.note) for e in sort.groups.grooves] == [
        (1, 1, ""),
        (2, 2, "my chorus one"),
        (3, None, ""),
    ]
    assert choices(sort.groups) == [("not sure", 0), ("the basic", 1), ("the lift", 2)]
    back = assign(sort.groups, 1, NOT_SURE)
    assert back.grooves[0].group is None
    with pytest.raises(ValueError, match="no group 9"):
        assign(sort.groups, 1, 9)
    with pytest.raises(ValueError, match="no groove 9"):
        annotate(sort.groups, 9, "x")


def test_editing_groups_renames_adds_and_deletes_after_a_warning(tmp_path: Path) -> None:
    groups = grouped(tmp_path).groups
    rows = group_rows(groups)
    assert rows == [[1, "the basic", "verses"], [2, "the lift", ""], ["", "", ""]]
    rows = rows[:2]
    renamed = edit_groups(
        groups, [[1, "steady", "verses"], [2, "the lift", "choruses"], [None, "", ""]]
    )
    assert not renamed.confirm
    assert [(g.id, g.name, g.purpose) for g in renamed.groups.groups] == [
        (1, "steady", "verses"),
        (2, "the lift", "choruses"),
    ]
    added = edit_groups(groups, [*rows, [float("nan"), "skeleton", "intro"]])
    assert [g.id for g in added.groups.groups] == [1, 2, 3]
    warned = edit_groups(groups, rows[:1])
    assert warned.confirm and warned.groups == groups
    assert "'the lift'" in warned.message and "1 groove to" in warned.message
    deleted = edit_groups(groups, rows[:1], confirmed=True)
    assert [g.id for g in deleted.groups.groups] == [1]
    assert [e.group for e in deleted.groups.grooves] == [1, None, None]
    assert deleted.groups.grooves[1].note == "my chorus one"
    empty = edit_groups(added.groups, rows)
    assert not empty.confirm and len(empty.groups.groups) == 2
    with pytest.raises(ValueError, match="row 2: no group 5"):
        edit_groups(groups, [rows[0], [5, "x", ""]])
    with pytest.raises(ValueError, match="row 2: group 1 is listed twice"):
        edit_groups(groups, [rows[0], rows[0]])
    with pytest.raises(ValueError, match="row 1: id must be"):
        edit_groups(groups, [["one", "x", ""]])


def test_save_writes_in_the_data_folder_and_saves_again_in_place(tmp_path: Path) -> None:
    sort = grouped(tmp_path)
    with pytest.raises(ValueError, match="--data"):
        save(sort, None, LATER)
    first = save(sort, tmp_path, LATER)
    assert first.path == tmp_path / "grooves" / "groups-20261124-150000.json"
    back = read_groups(first.path)
    assert back == first.groups and back.updated == LATER and back.created == CREATED
    again = save(Sort(assign(first.groups, 3, 1), first.many, first.path), tmp_path, LATER)
    assert again.path == first.path and read_groups(first.path).grooves[2].group == 1
    new = save(again, tmp_path, "2026-11-24T16:00:00+00:00", as_new=True)
    assert new.path == tmp_path / "grooves" / "groups-20261124-160000.json"
    clash = save(again, tmp_path, "2026-11-24T16:00:00+00:00", as_new=True)
    assert clash.path == tmp_path / "grooves" / "groups-20261124-160000-2.json"
    elsewhere = Sort(sort.groups, sort.many, tmp_path / "other" / "groups-x.json")
    moved = save(elsewhere, tmp_path, LATER)
    assert moved.path is not None and moved.path.parent == tmp_path / "grooves"
    assert not (tmp_path / "other").exists()


def test_export_writes_the_text_next_to_the_file(tmp_path: Path) -> None:
    sort = grouped(tmp_path)
    with pytest.raises(ValueError, match="save the groups first"):
        export(sort)
    saved = save(sort, tmp_path, LATER)
    path = export(saved)
    assert path == tmp_path / "grooves" / "groups-20261124-150000.txt"
    text = path.read_text(encoding="utf-8")
    assert "the basic\n  for: verses\n  - groove 1\n" in text
    assert "the lift\n  - groove 2: my chorus one\n" in text
    assert text.endswith("not sure\n  - groove 3\n")


def test_blind_sorts_save_and_export_letters(tmp_path: Path) -> None:
    sort = started(tmp_path, blind=True)
    saved = save(sort, tmp_path, LATER)
    back = read_groups(saved.path or "")
    assert back.blind and back.seed == 7
    assert sorted(e.card or "" for e in back.grooves) == ["A", "B", "C"]
    text = export(saved).read_text(encoding="utf-8")
    assert "groove" not in text.split("\n", 1)[1] and "card A" in text


def test_reopen_with_the_recordings_gets_the_played_audio_back(tmp_path: Path) -> None:
    saved = save(grouped(tmp_path), tmp_path, LATER)
    sort, message = reopen("grooves/groups-20261124-150000.json", tmp_path)
    assert message == "Opened groups-20261124-150000.json with its recordings."
    assert sort.path == saved.path and sort.groups == saved.groups
    assert sort.many is not None
    assert [s.path for s in sort.many.sources] == ["trials/s1/a.jsonl", "trials/s1/b.jsonl"]
    assert all(c.played for c in cards(sort.groups, sort.many))


def test_reopen_without_the_recordings_shows_prototypes_only(tmp_path: Path) -> None:
    saved = save(grouped(tmp_path), tmp_path, LATER)
    assert saved.path is not None
    (tmp_path / "trials" / "s1" / "a.jsonl").unlink()
    sort, message = reopen(str(saved.path), None)
    assert sort.many is None and sort.groups == saved.groups
    assert message == "Prototype only; recordings missing: trials/s1/a.jsonl, trials/s1/b.jsonl."
    sort, message = reopen(str(saved.path), tmp_path)
    assert message == "Prototype only; recordings missing: trials/s1/a.jsonl."
    assert all(not c.played and c.loop.hits for c in cards(sort.groups, sort.many))


def test_reopen_names_a_changed_recording(tmp_path: Path) -> None:
    saved = save(grouped(tmp_path), tmp_path, LATER)
    os.utime(tmp_path / "trials" / "s1" / "b.jsonl", (5_000, 5_000))
    sort, message = reopen(str(saved.path), tmp_path)
    assert sort.many is None and message.endswith("changed: trials/s1/b.jsonl.")


def test_reopen_refuses_a_bad_file_naming_it(tmp_path: Path) -> None:
    (tmp_path / "grooves").mkdir()
    (tmp_path / "grooves" / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.json: not valid JSON"):
        reopen("grooves/bad.json", tmp_path)
    with pytest.raises(OSError):
        reopen("grooves/none.json", tmp_path)


def tabs_of(page: object) -> set[str]:
    blocks = getattr(page, "blocks", {}).values()
    return {getattr(b, "label", "") for b in blocks if type(b).__name__ == "Tab"}


def test_the_grooves_tab_is_on_the_page_but_not_under_share(tmp_path: Path) -> None:
    if not webdemo_main.gradio_installed():
        pytest.skip("needs the demo extra")
    from mpc_iml.webdemo.app import build

    assert tabs_of(build(tmp_path)) == {"step grid", "recording", "variations", "grooves", "band"}
    assert tabs_of(build(tmp_path, share=True)) == {"step grid", "recording", "variations"}
    buttons = {
        getattr(b, "value", None): getattr(b, "interactive", None)
        for b in build().blocks.values()
        if type(b).__name__ == "Button"
    }
    assert buttons["Save"] is False and buttons["Load"] is not False
