"""Grooves of several recordings and the `mpc-iml-groove-groups` file (#249, PR 1)."""

import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest
from test_grooves import FILL, A, B, C
from test_grooves_offline import recording

from mpc_iml.events import MidiEvent, RawMidiEvent
from mpc_iml.grooves import Features, Pattern, Tracker, features
from mpc_iml.grooves.groups import (
    FORMAT,
    GrooveGroups,
    Group,
    GroupsFormatError,
    describe,
    read_groups,
    start,
    to_dict,
    write_groups,
)
from mpc_iml.grooves.offline import track, track_many
from mpc_iml.recording import Header, RecordingFormatError, write_recording

TEMPO = 100.0
BAR_SECONDS = 4 * 60.0 / TEMPO


def save(path: Path, *takes: list[Pattern], mtime: float | None = None) -> Path:
    write_recording(path, Header(), recording(*takes, tempo=TEMPO))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_bars_keep_their_hits_and_bar_lines() -> None:
    result = track(recording([A, A, B, A, A], tempo=TEMPO))
    bars = result.bars
    assert len(bars) == 4
    for b in bars:
        assert b.end - b.line == pytest.approx(BAR_SECONDS, abs=1e-6)
        assert all(b.line - 0.01 <= h.t < b.end for h in b.hits)
        assert all(h.bar == b.bar - 1 for h in b.hits)
    assert [b.line for b in bars[1:]] == pytest.approx([b.end for b in bars[:-1]])
    # Every played hit is kept with its velocity: kick, snare and hat of A.
    assert len(bars[0].hits) == len(A.kick) + len(A.snare) + len(A.hat)
    assert {h.velocity for h in bars[0].hits} == {90}


def test_a_groove_in_two_recordings_merges_to_one_id(tmp_path: Path) -> None:
    first = save(tmp_path / "a.jsonl", [A, A, A, A], mtime=1_000_000)
    second = save(tmp_path / "b.jsonl", [B, B, B, A, A, A, A], mtime=2_000_000)
    many = track_many([second, first])
    assert [s.path for s in many.sources] == [str(first), str(second)]
    assert [g.id for g in many.grooves] == [1, 2]
    later = many.sources[1].result
    assert {b.groove for b in later.bars if b.kind == "groove"} == {1, 2}
    assert [b.groove for b in later.bars][-3:] == [1, 1, 1]
    assert many.settings == later.settings
    assert many.sources[0].modified.startswith("1970-01-12T")


def test_a_different_groove_does_not_merge(tmp_path: Path) -> None:
    first = save(tmp_path / "a.jsonl", [A, A, A, A], mtime=1)
    second = save(tmp_path / "b.jsonl", [C, C, C, C], mtime=2)
    assert [g.id for g in track_many([first, second]).grooves] == [1, 2]


def test_recordings_are_tracked_in_date_order_then_path(tmp_path: Path) -> None:
    a = save(tmp_path / "a.jsonl", [A, A, A, A], mtime=5)
    b = save(tmp_path / "b.jsonl", [B, B, B, B], mtime=1)
    many = track_many([a, b])
    assert [s.path for s in many.sources] == [str(b), str(a)]
    assert similarity_ids(many.grooves) == {1: B, 2: A}
    os.utime(b, (5, 5))
    assert [s.path for s in track_many([b, a]).sources] == [str(a), str(b)]


def similarity_ids(grooves: Any) -> dict[int, Pattern]:
    return {g.id: g.prototype for g in grooves}


def test_the_groove_ends_between_recordings(tmp_path: Path) -> None:
    # Without a Stop at its end the first recording's groove would continue.
    path = tmp_path / "a.jsonl"
    events = recording([A, A, A, A], tempo=TEMPO)
    assert events[-1] == RawMidiEvent(events[-1].t, b"\xfc")
    write_recording(path, Header(), events[:-1])
    os.utime(path, (1, 1))
    later = save(tmp_path / "b.jsonl", [A, A, A], mtime=2)
    tracker = Tracker()
    many = track_many([path, later], tracker)
    first = many.sources[1].result.bars[0]
    assert first.decision.groove is None and first.decision.position is None


def test_errors_name_the_file(tmp_path: Path) -> None:
    no_clock = tmp_path / "no-clock.jsonl"
    write_recording(no_clock, Header(), [MidiEvent(0.0, "note_on", 1, 80, 37)])
    with pytest.raises(ValueError, match=r"no-clock\.jsonl: .*no complete bar"):
        track_many([no_clock])
    log = tmp_path / "engine.log"
    log.write_text("engine started\n", encoding="utf-8")
    with pytest.raises(RecordingFormatError, match=r"engine\.log: "):
        track_many([log])
    with pytest.raises(ValueError, match="no recordings"):
        track_many([])
    with pytest.raises(OSError):
        track_many([tmp_path / "missing.jsonl"])


def sorted_groups(tmp_path: Path) -> GrooveGroups:
    a = save(tmp_path / "a.jsonl", [A, A, A, FILL, A, A], mtime=1)
    b = save(tmp_path / "b.jsonl", [B, B, B, A, A, A], mtime=2)
    return start(track_many([a, b]), "2026-11-24T15:00:00+00:00")


def test_start_lists_every_groove_as_not_sure(tmp_path: Path) -> None:
    groups = sorted_groups(tmp_path)
    assert groups.groups == ()
    assert [(e.id, e.group, e.note, e.card) for e in groups.grooves] == [
        (1, None, "", None),
        (2, None, "", None),
    ]
    assert [e.sections for e in groups.grooves] == [2, 1]
    assert [s.bars for s in groups.sources] == [5, 5]
    assert sum(groups.counts.values()) == 10 and groups.counts["fill"] == 1
    assert groups.settings == {"similar": 0.8, "return": 0.8, "free_bars": 4, "decay": 0.8}
    assert groups.grooves[0].features == features(A)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    groups = sorted_groups(tmp_path)
    one, two = groups.grooves
    edited = dataclasses.replace(
        groups,
        groups=(Group(1, "the steady basic", "verses"), Group(3, "busy hats", "")),
        grooves=(
            dataclasses.replace(one, group=1, note="my usual", card="B"),
            dataclasses.replace(two, group=None, note="", card="A"),
        ),
        blind=True,
        seed=42,
        updated="2026-11-24T15:20:00+00:00",
    )
    path = tmp_path / "data" / "grooves" / "groups-20261124-150000.json"
    write_groups(path, edited)
    assert read_groups(path) == edited
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["format"] == FORMAT and document["version"] == 1
    assert document["grooves"][0]["prototype"] == {
        "kick": [0, 8, 10],
        "snare": [4, 12],
        "hat": [0, 2, 4, 6, 8, 10, 12, 14],
    }


def valid() -> dict[str, Any]:
    groups = GrooveGroups(
        sources=(),
        settings={"similar": 0.8, "return": 0.8, "free_bars": 4, "decay": 0.8},
        groups=(Group(1, "basic"),),
        grooves=(),
    )
    document = to_dict(groups)
    document["grooves"] = [
        {
            "id": 1,
            "group": 1,
            "note": "",
            "card": None,
            "prototype": {"kick": [0], "snare": [4], "hat": []},
            "features": Features().as_dict(),
            "bars": 4,
            "sections": 1,
        }
    ]
    return document


def broken(change: str) -> dict[str, Any]:
    d = valid()
    match change:
        case "format":
            d["format"] = "mpc-iml-grooves"
        case "version":
            d["version"] = 2
        case "missing":
            del d["grooves"][0]["features"]
        case "unknown":
            d["colour"] = "red"
        case "group":
            d["grooves"][0]["group"] = 7
        case "duplicate":
            d["groups"].append({"id": 1, "name": "again", "purpose": ""})
        case "step":
            d["grooves"][0]["prototype"]["kick"] = [16]
        case "name":
            d["groups"][0]["name"] = 3
        case "feature":
            d["grooves"][0]["features"]["kicks"] = "three"
    return d


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("format", r"format: must be 'mpc-iml-groove-groups'"),
        ("version", r"version: this toolkit reads version 1, got 2"),
        ("missing", r"grooves\[0\]\.features: missing"),
        ("unknown", r"colour: unknown field"),
        ("group", r"grooves\[0\]\.group: no group has id 7"),
        ("duplicate", r"groups\[1\]\.id: id 1 is used twice"),
        ("step", r"grooves\[0\]\.prototype\.kick\[0\]: must be a step from 0 to 15"),
        ("name", r"groups\[0\]\.name: must be text"),
        ("feature", r"grooves\[0\]\.features\.kicks: must be a number"),
    ],
)
def test_bad_files_name_the_file_and_the_field(tmp_path: Path, change: str, message: str) -> None:
    path = tmp_path / "groups-x.json"
    path.write_text(json.dumps(valid()), encoding="utf-8")
    read_groups(path)
    path.write_text(json.dumps(broken(change)), encoding="utf-8")
    with pytest.raises(GroupsFormatError, match=r"^groups-x\.json: " + message):
        read_groups(path)


def test_invalid_json_and_a_list_are_clear_errors(tmp_path: Path) -> None:
    path = tmp_path / "groups-y.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(GroupsFormatError, match=r"^groups-y\.json: not valid JSON"):
        read_groups(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(GroupsFormatError, match=r"^groups-y\.json: the document must be an object"):
        read_groups(path)


def test_an_invalid_sort_is_never_written(tmp_path: Path) -> None:
    groups = sorted_groups(tmp_path)
    bad = dataclasses.replace(groups, grooves=(dataclasses.replace(groups.grooves[0], group=9),))
    path = tmp_path / "grooves" / "groups-bad.json"
    with pytest.raises(GroupsFormatError, match="no group has id 9"):
        write_groups(path, bad)
    assert not path.exists()


@pytest.mark.parametrize(
    ("values", "text"),
    [
        (
            Features(3, 1, 2, 0, 8, 1),
            "about 3 kicks a bar, a double kick, kicks mostly in the second half, "
            "no snare off the backbeat, about 8 hats a bar",
        ),
        (
            Features(1, 0, 0, 2, 0, 0),
            "about 1 kick a bar, kicks mostly in the first half, "
            "about 2 snare hits off the backbeat, no hat",
        ),
        (
            Features(0, 0, 0, 1, 1, 0.25),
            "no kick, about 1 snare hit off the backbeat, a hat in a few bars",
        ),
        (
            Features(4, 2.2, 2, 0, 16, 1),
            "about 4 kicks a bar, 2 double kicks, kicks in both halves, "
            "no snare off the backbeat, about 16 hats a bar",
        ),
    ],
)
def test_describe_puts_features_in_plain_words(values: Features, text: str) -> None:
    assert describe(values) == text
