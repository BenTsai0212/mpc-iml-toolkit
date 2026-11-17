"""Example generation from kits and modules, and recording format 2 (ADR 0007, #99)."""

import dataclasses
import json
from itertools import pairwise
from pathlib import Path

import pytest

from mpc_iml.content import NONE, ContentError, PadAssignment, UnknownContentError, load_library
from mpc_iml.events import ExampleEnd, ExampleStart, MidiEvent
from mpc_iml.examples import labelled_frames
from mpc_iml.generation import GeneratedSet, split_generated, with_generated
from mpc_iml.pressure import OUTPUT_NAMES, PRESET
from mpc_iml.recording import Header, RecordingFormatError, read_recording, write_recording

LIBRARY = load_library(PRESET)
FILTER_PLAY = LIBRARY.kit("filter-play")
REST = tuple(FILTER_PLAY.rest[o] for o in OUTPUT_NAMES)
BRIGHTNESS, RESONANCE, LEVEL = 0, 1, 7
REGRESSION = Path(__file__).parent / "data" / "regression.jsonl"


def segments(events: list) -> list[tuple[ExampleStart, list[tuple[float, ...]]]]:
    """Each example with the pressure features (0-127 values) of its frames."""
    result: dict[int, tuple[ExampleStart, list[tuple[float, ...]]]] = {}
    for frame, start in labelled_frames(events):
        if start is not None:
            result.setdefault(id(start), (start, []))[1].append(frame.pressure)
    return list(result.values())


def only_pad(pad: int, generated: GeneratedSet) -> list:
    return [t for t in generated.takes if t.pads == (pad,)]


def test_a_kit_gives_rest_single_and_combined_takes() -> None:
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play")
    assert generated.kit == "filter-play" and generated.combine == "add"
    assert generated.rest == REST
    singles = [t for t in generated.takes if len(t.pads) == 1]
    combined = [t for t in generated.takes if len(t.pads) == 2]
    rests = [t for t in generated.takes if not t.pads]
    assert len(rests) == 1 and rests[0].frames == 20 and rests[0].targets == REST
    assert len(singles) == 16 * 4 and all(t.frames == 20 for t in singles)
    assert len(combined) == 105 * 2 and all(t.frames == 10 for t in combined)
    assert generated.frame_count() == 16 * 80 + 20 + 105 * 20 == 3400
    assert generated.assignments()[15] == (NONE, 1.0)


def test_single_pad_takes_follow_the_module_curve() -> None:
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play")
    takes = only_pad(1, generated)
    assert [t.presses for t in takes] == [((1, 32),), ((1, 64),), ((1, 95),), ((1, 127),)]
    for take, p in zip(takes, (0.25, 0.5, 0.75, 1.0), strict=True):
        assert take.module == "brighten" and take.pad == 1 and take.amount == 1.0
        assert take.targets[BRIGHTNESS] == pytest.approx(REST[BRIGHTNESS] + 0.6 * p)
        assert take.targets[1:] == REST[1:]


def test_none_takes_stay_at_rest() -> None:
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play")
    assert all(t.targets == REST and t.module == NONE for t in only_pad(16, generated))
    assert not [t for t in generated.takes if 16 in t.pads and len(t.pads) == 2]


def test_combined_takes_add_both_offsets_and_clamp() -> None:
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play")
    pair = [t for t in generated.takes if t.pads == (1, 5)]
    assert [t.presses for t in pair] == [((1, 64), (5, 64)), ((1, 127), (5, 127))]
    half, full = pair
    assert half.module == ("brighten", "bite") and half.amount == (1.0, 1.0)
    assert half.targets[BRIGHTNESS] == pytest.approx(0.3 + 0.3 + 0.25)
    assert half.targets[RESONANCE] == pytest.approx(0.2 + 0.25)
    assert full.targets[BRIGHTNESS] == 1.0  # 0.3 + 0.6 + 0.5, clamped
    darker = [t for t in generated.takes if t.pads == (9, 10)][1]
    assert darker.targets[BRIGHTNESS] == 0.0  # 0.3 - 0.6 - 0.6, clamped


def test_assign_replaces_only_that_pads_takes_and_scales_by_amount() -> None:
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play")
    changed = generated.assign(LIBRARY, 1, "push", 0.5)
    assert changed.pads[0] == PadAssignment("push", 0.5)
    full = only_pad(1, changed)[-1]
    assert full.module == "push" and full.amount == 0.5
    assert full.targets[LEVEL] == pytest.approx(REST[LEVEL] + 0.5 * 0.3)
    untouched = [t for t in generated.takes if 1 not in t.pads]
    assert [t for t in changed.takes if 1 not in t.pads] == untouched
    pairs = [t for t in changed.takes if 1 in t.pads and len(t.pads) == 2]
    assert len(pairs) == 14 * 2 and all(t.module[0] == "push" for t in pairs)  # type: ignore[index]
    assert changed.frame_count() == generated.frame_count()


def test_assign_none_drops_the_pads_combined_takes() -> None:
    changed = GeneratedSet.from_kit(LIBRARY, "filter-play").assign(LIBRARY, 2, NONE)
    assert not [t for t in changed.takes if 2 in t.pads and len(t.pads) == 2]
    assert changed.frame_count() == 3400 - 14 * 20
    back = changed.assign(LIBRARY, 2, "brighten")
    assert back.takes == GeneratedSet.from_kit(LIBRARY, "filter-play").takes


def test_assign_checks_its_arguments() -> None:
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play")
    with pytest.raises(ContentError, match="pad must be 1-16"):
        generated.assign(LIBRARY, 17, "bite")
    with pytest.raises(ContentError, match="amount must be 0-1"):
        generated.assign(LIBRARY, 1, "bite", 1.5)
    with pytest.raises(UnknownContentError, match="unknown module"):
        generated.assign(LIBRARY, 1, "nope")
    no_rest = GeneratedSet(None, (None,) * 16, ())
    with pytest.raises(ContentError, match="load a kit first"):
        no_rest.assign(LIBRARY, 1, "bite")


def test_combine_none_gives_no_combined_takes() -> None:
    kit = dataclasses.replace(FILTER_PLAY, combine="none")
    library = dataclasses.replace(LIBRARY, kits={"x": kit})
    generated = GeneratedSet.from_kit(library, "x")
    assert generated.combine == "none"
    assert generated.frame_count() == 16 * 80 + 20
    changed = generated.assign(library, 16, "bite")
    assert all(len(t.pads) < 2 for t in changed.takes)


def test_events_give_exactly_the_takes_frames_and_targets() -> None:
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play").assign(LIBRARY, 3, "bite", 0.5)
    found = segments(generated.events())
    assert len(found) == len(generated.takes)
    for (start, frames), take in zip(found, generated.takes, strict=True):
        assert start.targets == take.targets and start.module == take.module
        assert len(frames) == take.frames
        expected = [0] * 16
        for pad, value in take.presses:
            expected[pad - 1] = value
        assert all(f == tuple(expected) for f in frames)


def test_takes_are_written_one_frame_apart_on_bank_a() -> None:
    events = GeneratedSet.from_kit(LIBRARY, "filter-play").events()
    notes = {e.note for e in events if isinstance(e, MidiEvent)}
    assert notes == set(range(36, 52))
    assert {e.value for e in events if isinstance(e, MidiEvent) and e.kind == "note_on"} == {100}
    times = [e.t for e in events]
    assert all(a <= b for a, b in pairwise(times))


def test_recorded_demonstrations_come_first_and_are_kept() -> None:
    recorded = list(read_recording(REGRESSION).events)
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play")
    timeline = with_generated(recorded, generated)
    assert timeline[: len(recorded)] == recorded
    found = segments(timeline)
    recorded_takes = [s for s in found if not s[0].generated]
    assert len(recorded_takes) == len(segments(recorded))
    generated_takes = [s for s in found if s[0].generated]
    assert [len(f) for _, f in generated_takes] == [t.frames for t in generated.takes]
    assert with_generated(recorded, None) == recorded


def test_held_pads_are_released_before_the_generated_takes() -> None:
    pad_5 = [
        MidiEvent(0.0, "note_on", 1, 90, note=40),
        MidiEvent(0.0, "poly_pressure", 1, 80, note=40),
    ]
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play")
    for start, frames in segments(with_generated(pad_5, generated)):
        take = next(t for t in generated.takes if t.targets == start.targets and t.pad == start.pad)
        expected = dict(take.presses).get(5, 0)
        assert all(f[4] == expected for f in frames)


def test_format_2_round_trip_restores_assignments_rest_kit_and_combine(tmp_path: Path) -> None:
    recorded = list(read_recording(REGRESSION).events)
    generated = GeneratedSet.from_kit(LIBRARY, "filter-play").assign(LIBRARY, 3, "swell", 0.25)
    path = tmp_path / "set.jsonl"
    write_recording(path, generated.header(Header()), with_generated(recorded, generated))
    head = json.loads(path.read_text().splitlines()[0])
    assert head["format_version"] == 2 and head["kit"] == "filter-play" and head["combine"] == "add"
    recording = read_recording(path)
    assert recording.header.kit == "filter-play" and recording.header.format_version == 2
    back, restored = split_generated(recording)
    assert back[: len(recorded)] == recorded
    released = back[len(recorded) :]  # the release before the generated takes stays
    assert all(isinstance(e, MidiEvent) and e.kind == "note_off" for e in released)
    assert restored is not None
    assert restored.rest == generated.rest
    assert restored.pads == generated.pads
    assert restored.takes == generated.takes
    assert (restored.kit, restored.combine) == ("filter-play", "add")
    combined = next(
        e for e in recording.events if isinstance(e, ExampleStart) and isinstance(e.pad, tuple)
    )
    assert combined.module == ("brighten", "brighten") and combined.amount == (1.0, 1.0)
    rest = next(e for e in recording.events if isinstance(e, ExampleStart) and e.pad == 0)
    assert (rest.module, rest.amount) == (NONE, 0.0)


def test_a_restored_set_can_change_a_pad(tmp_path: Path) -> None:
    generated = GeneratedSet.from_kit(LIBRARY, "texture-lab")
    path = tmp_path / "set.jsonl"
    write_recording(path, generated.header(Header()), generated.events())
    _, restored = split_generated(read_recording(path))
    assert restored is not None
    assert restored.assign(LIBRARY, 1, "bend").takes == generated.assign(LIBRARY, 1, "bend").takes


def test_files_without_generated_takes_stay_version_1(tmp_path: Path) -> None:
    recorded = list(read_recording(REGRESSION).events)
    path = tmp_path / "plain.jsonl"
    write_recording(path, Header(), recorded)
    head = json.loads(path.read_text().splitlines()[0])
    assert head["format_version"] == 1 and "kit" not in head and "combine" not in head
    assert "module" not in path.read_text()
    events, generated = split_generated(read_recording(path))
    assert generated is None and events == recorded
    with pytest.raises(ValueError, match="only with generated takes"):
        write_recording(path, Header(kit="filter-play"), recorded)


def test_version_1_files_are_read_as_before() -> None:
    recording = read_recording(REGRESSION)
    assert recording.header.format_version == 1 and recording.header.kit is None
    assert not any(isinstance(e, ExampleStart) and e.generated for e in recording.events)


def _write(path: Path, header: dict, *events: dict) -> Path:
    base = {"type": "header", "format": "mpc-iml-recording", "format_version": 2}
    lines = [json.dumps({**base, **header}), *(json.dumps(e) for e in events)]
    path.write_text("\n".join(lines) + "\n")
    return path


START = {"t": 0, "type": "example_start", "targets": [0.5]}


@pytest.mark.parametrize(
    ("header", "start", "message"),
    [
        ({"format_version": 1}, {"module": "bite", "pad": 1, "amount": 1}, "need format_version 2"),
        ({}, {"module": "bite", "pad": 1}, "all of module, pad and amount"),
        ({}, {"module": "bite", "pad": 17, "amount": 1}, "pad must be 0-16"),
        ({}, {"module": ["a"], "pad": [1], "amount": [1]}, "two of each"),
        ({}, {"module": ["a", "b"], "pad": [0, 2], "amount": [1, 1]}, "two of each"),
        ({"combine": "pairs"}, {}, "combine must be"),
        ({"kit": 3}, {}, "kit must be a name"),
    ],
)
def test_malformed_version_2_files_are_rejected(
    tmp_path: Path, header: dict, start: dict, message: str
) -> None:
    path = _write(
        tmp_path / "bad.jsonl", header, {**START, **start}, {"t": 0.1, "type": "example_end"}
    )
    with pytest.raises(RecordingFormatError, match=message):
        read_recording(path)


def test_a_pad_with_two_modules_is_rejected(tmp_path: Path) -> None:
    takes = [
        {**START, "module": m, "pad": 1, "amount": 1, "t": t} for m, t in (("bite", 0), ("bend", 1))
    ]
    path = _write(
        tmp_path / "two.jsonl",
        {},
        takes[0],
        {"t": 0.2, "type": "example_end"},
        takes[1],
        {"t": 1.2, "type": "example_end"},
    )
    with pytest.raises(RecordingFormatError, match="pad 1 has takes of two modules"):
        split_generated(read_recording(path))


def test_a_set_without_a_rest_take_has_no_resting_values(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "norest.jsonl",
        {},
        {**START, "module": "bite", "pad": 1, "amount": 1},
        {"t": 0.2, "type": "example_end"},
    )
    _, generated = split_generated(read_recording(path))
    assert generated is not None and generated.rest is None
    assert generated.assignments()[:2] == [("bite", 1.0), ("", 1.0)]
    assert generated.combine == "add" and generated.kit is None
    assert isinstance(generated.takes[0].events(0)[-1], ExampleEnd)
