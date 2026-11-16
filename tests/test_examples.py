"""Training examples from synthetic recordings: segments, labels, targets, class numbers."""

from pathlib import Path

import pytest

from mpc_iml.events import Event, ExampleEnd, ExampleStart, MidiEvent
from mpc_iml.examples import ExampleError, ExampleSet, labelled_frames
from mpc_iml.frames import OSC_INPUT_COUNT, Frame, frames
from mpc_iml.recording import read_recording

DATA = Path(__file__).parent / "data"


def on(t: float, note: int, velocity: int) -> MidiEvent:
    return MidiEvent(t=t, kind="note_on", channel=1, value=velocity, note=note)


def segment(t0: float, t1: float, label: str, note: int = 36) -> list[Event]:
    return [ExampleStart(t=t0, label=label), on(t0, note, 100), ExampleEnd(t=t1)]


def test_labelled_frames_match_frames_timing() -> None:
    events = read_recording(DATA / "basic.jsonl").events
    labelled = list(labelled_frames(events))
    assert [f for f, _ in labelled] == list(frames(events))


def test_frames_inside_segment_are_kept_with_label() -> None:
    examples = ExampleSet()
    assert examples.add_recording(DATA / "basic.jsonl") == 8
    assert {e.label for e in examples.examples} == {"soft-roll"}
    assert all(len(e.features) == OSC_INPUT_COUNT for e in examples.examples)
    assert examples.outputs() == [[1.0]] * 8


def test_frames_outside_segments_are_dropped_and_targets_carried() -> None:
    examples = ExampleSet()
    assert examples.add_recording(DATA / "regression.jsonl") == 6
    assert examples.outputs() == [[0.0, 1.0]] * 3 + [[1.0, 0.0]] * 3
    held = [e.features[32:34] for e in examples.examples]
    assert held == [(1.0, 0.0)] * 3 + [(0.0, 1.0)] * 3


@pytest.mark.parametrize(
    "events",
    [
        [ExampleStart(t=0.0, label="a"), ExampleStart(t=0.01, label="b"), ExampleEnd(t=0.02)],
        [ExampleEnd(t=0.0)],
        [ExampleStart(t=0.0, label="a"), on(0.01, 36, 10)],
        [ExampleStart(t=0.0), ExampleEnd(t=0.01)],
        [ExampleStart(t=0.0, label="a", targets=(1.0,)), ExampleEnd(t=0.01)],
    ],
    ids=["nested", "end-without-start", "start-without-end", "neither", "both"],
)
def test_malformed_segments_are_rejected_and_nothing_is_added(events: list[Event]) -> None:
    examples = ExampleSet()
    with pytest.raises(ExampleError):
        examples.add_events(events)
    assert len(examples) == 0


def test_mixing_label_and_targets_is_rejected() -> None:
    examples = ExampleSet()
    examples.add_recording(DATA / "basic.jsonl")
    with pytest.raises(ExampleError, match="mix"):
        examples.add_recording(DATA / "regression.jsonl")
    assert len(examples) == 8


def test_targets_of_differing_lengths_are_rejected() -> None:
    examples = ExampleSet()
    examples.add_recording(DATA / "regression.jsonl")
    events: list[Event] = [ExampleStart(t=0.0, targets=(1.0,)), ExampleEnd(t=0.01)]
    with pytest.raises(ExampleError, match="targets"):
        examples.add_events(events)


def test_training_with_no_examples_is_rejected() -> None:
    with pytest.raises(ExampleError, match="no examples"):
        ExampleSet().training_data()


def test_class_numbers_are_stable_after_removal() -> None:
    examples = ExampleSet()
    examples.add_events(segment(0.0, 0.02, "a") + segment(0.02, 0.04, "b", note=37))
    assert examples.classes == {"a": 1, "b": 2}
    assert examples.remove("a") == 2
    examples.add_events(segment(0.0, 0.02, "c"))
    assert examples.classes == {"a": 1, "b": 2, "c": 3}
    assert sorted({row[0] for row in examples.outputs()}) == [2.0, 3.0]
    examples.clear()
    examples.add_events(segment(0.0, 0.01, "a"))
    assert examples.outputs() == [[1.0]]


def test_explicit_class_mapping() -> None:
    examples = ExampleSet(classes={"kick": 3, "snare": 1})
    examples.add_events(segment(0.0, 0.01, "kick") + segment(0.01, 0.02, "hat"))
    assert examples.outputs() == [[3.0], [4.0]]
    with pytest.raises(ExampleError):
        ExampleSet(classes={"a": 1, "b": 1})


def test_custom_features() -> None:
    def bank_only(frame: Frame) -> list[float]:
        return [float(frame.bank)]

    examples = ExampleSet(features=bank_only)
    examples.add_events(segment(0.0, 0.01, "a", note=52))
    assert examples.inputs() == [[1.0]]
