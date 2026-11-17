"""The Max for Live device's patcher, `patches/mpc-iml.maxpat` (#86).

Max and Live cannot run here, so these tests read the patcher JSON: the messages it
can send against ADR 0004, ADR 0005 and ADR 0006, the replies it reads, the controls
of ADR 0006's shared front-end spec, the objects it uses and its layout. The messages
are also replayed to a real engine. Loading the device in Live is checked by hand.
"""

import importlib.util
import json
import threading
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from test_engine import TIMEOUT, Front, Receiver
from test_pressure import FakeMidiOut

from mpc_iml.engine import ALLOWED, Engine

ROOT = Path(__file__).parents[1]
DEVICE = files("mpc_iml").joinpath("patches/mpc-iml.maxpat")


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "build_device", ROOT / "tools/m4l/build_device.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = _generator()

CONTROL = {
    "/mpciml/hello": "ii",
    "/mpciml/ping": "",
    "/mpciml/state/get": "",
    "/mpciml/record/start": "",
    "/mpciml/record/stop": "",
    "/mpciml/class": "s",
    "/mpciml/targets": "f+",
    "/mpciml/examples/delete": "s",
    "/mpciml/examples/clear": "",
    "/mpciml/examples/save": "s",
    "/mpciml/examples/load": "s",
    "/mpciml/examples/list": "",
    "/mpciml/train": "",
    "/mpciml/run": "",
    "/mpciml/stop": "",
    "/mpciml/preset/list": "",
    "/mpciml/preset/load": "s",
    "/mpciml/midi/learn": "i",
}
"""Control messages and argument types (ADR 0004, ADR 0005); `+` is one or more."""

REPLIES = {
    "/mpciml/version",
    "/mpciml/pong",
    "/mpciml/state",
    "/mpciml/preset",
    "/mpciml/layout",
    "/mpciml/counts",
    "/mpciml/trained",
    "/mpciml/train/done",
    "/mpciml/train/failed",
    "/mpciml/presets",
    "/mpciml/examples/names",
    "/mpciml/error",
    "/mpciml/midi/sent",
}
"""Every reply of protocol 1.2 (ADR 0004, ADR 0005, ADR 0006)."""

EXAMPLE = {"s": "seed", "f+": [0.5] * 8}
"""Arguments for a `prepend`: a name (also a valid label) or 8 targets for `pressure`."""

OBJECTS = {
    *("udpsend", "udpreceive", "midiin", "midiout", "live.thisdevice", "deferlow"),
    *("route", "prepend", "sprintf", "tosymbol", "symbol", "iter", "t", "unpack", "pak"),
    *("gate", "sel", "if", "+", "-", ">"),
    *("zl.reg", "zl.nth", "zl.group", "zl.iter", "zl.slice", "zl.lookup"),
}
"""Standard Max and Max for Live objects: no externals, no `js` or `node.script`."""
UI = {"comment", "message", "textbutton", "umenu", "textedit", "slider", "multislider"}

GROUPS = {
    "Connect": ["connect", "ping"],
    "Teach": [f"c{k}" for k in range(1, 9)],
    "Examples": ["record", "stop recording", "delete", "clear"],
    "Model": ["train", "run", "stop"],
    "Library": ["save", "load", "list"],
    "Outputs": [f"l{k}" for k in range(1, 9)],
    "Messages": [],
}
"""ADR 0006's groups in order, with their buttons in order."""


def patcher() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DEVICE.read_text())
    return data["patcher"]


def boxes() -> dict[str, dict[str, Any]]:
    return {b["box"]["id"]: b["box"] for b in patcher()["boxes"]}


def cords() -> list[tuple[str, int, str, int]]:
    return [
        (*line["patchline"]["source"], *line["patchline"]["destination"])
        for line in patcher()["lines"]
    ]


def find(text: str) -> str:
    (found,) = [i for i, b in boxes().items() if b.get("text") == text]
    return found


def sent() -> list[tuple[str, list[Any]]]:
    """Every message the device sends: message boxes and `prepend`s into `udpsend`.

    A `prepend` gets example arguments of the type the protocol expects; the test
    for the message boxes checks their literal arguments.
    """
    all_boxes, out = boxes(), find("udpsend 127.0.0.1 6450")
    messages = []
    for source, _, sink, _ in cords():
        if sink != out:
            continue
        box = all_boxes[source]
        if box["maxclass"] == "message":
            for part in box["text"].split(","):
                address, *args = part.split()
                messages.append((address, [int(a) if a.isdigit() else a for a in args]))
        else:
            assert box["text"].startswith("prepend /mpciml/"), box
            address = box["text"].split()[1]
            example = EXAMPLE[CONTROL[address]]
            messages.append((address, example if isinstance(example, list) else [example]))
    return messages


def test_the_file_is_generated_and_inside_the_package() -> None:
    assert DEVICE.is_file()
    assert GENERATOR.render() == DEVICE.read_text()
    assert GENERATOR.main(["--check"]) == 0


def test_every_message_sent_is_a_control_message() -> None:
    messages = sent()
    for address, args in messages:
        assert address in CONTROL, address
        types = CONTROL[address]
        if types.endswith("+"):
            assert args and all(isinstance(a, float) for a in args), address
        else:
            assert len(args) == len(types), address
            for kind, value in zip(types, args, strict=True):
                assert isinstance(value, int if kind == "i" else str), (address, value)
    # Everything the spec's controls need except state/get (the full state comes with hello).
    assert {a for a, _ in messages} == set(CONTROL) - {"/mpciml/state/get"}
    assert {a.removeprefix("/mpciml/") for a in CONTROL} == set(ALLOWED)
    assert ("/mpciml/hello", [1, 6451]) in messages
    learn = sorted(args[0] for address, args in messages if address == "/mpciml/midi/learn")
    assert learn == list(range(1, 9))


def test_replies_and_ports() -> None:
    reply = find("route " + " ".join(GENERATOR.REPLIES))
    assert set(GENERATOR.REPLIES) == REPLIES
    receive = find("udpreceive 6451")
    assert (receive, 0, reply, 0) in cords()
    outputs = find("route /wek/outputs")
    assert (find("udpreceive 12000"), 0, outputs, 0) in cords()
    # Every reply goes somewhere; unknown replies leave the last outlet, unused.
    used = {outlet for source, outlet, _, _ in cords() if source == reply}
    assert used == set(range(len(REPLIES)))


def test_midi_passes_through() -> None:
    assert (find("midiin"), 0, find("midiout"), 0) in cords()


def test_only_standard_objects() -> None:
    for box in boxes().values():
        if box["maxclass"] == "newobj":
            assert box["text"].split()[0] in OBJECTS, box["text"]
        else:
            assert box["maxclass"] in UI, box["maxclass"]


def test_cords_join_existing_inlets_and_outlets() -> None:
    all_boxes = boxes()
    for source, outlet, sink, inlet in cords():
        assert outlet < all_boxes[source]["numoutlets"], (source, outlet)
        assert inlet < all_boxes[sink]["numinlets"], (sink, inlet)


def shown() -> list[dict[str, Any]]:
    return [b for b in boxes().values() if b.get("presentation")]


def test_controls_follow_the_shared_spec() -> None:
    """ADR 0006: the groups left to right, and the buttons in order inside each group."""
    titles = sorted(
        (b for b in shown() if b["maxclass"] == "comment" and b["text"] in GROUPS),
        key=lambda b: b["presentation_rect"][0],
    )
    assert [b["text"] for b in titles] == list(GROUPS)
    edges = [b["presentation_rect"][0] for b in titles] + [float("inf")]
    buttons = [b for b in shown() if b["maxclass"] == "textbutton"]
    for (group, names), left, right in zip(GROUPS.items(), edges, edges[1:], strict=False):
        inside = [b for b in buttons if left <= b["presentation_rect"][0] < right]
        inside.sort(key=lambda b: (b["presentation_rect"][1], b["presentation_rect"][0]))
        assert [b["text"] for b in inside] == names, group
    labels = {b["text"] for b in shown() if b["maxclass"] == "comment"}
    assert {f"t{k}" for k in range(1, 9)} | {f"o{k}" for k in range(1, 9)} <= labels
    kinds = [b["maxclass"] for b in shown()]
    assert kinds.count("slider") == 8 and kinds.count("textedit") == 2
    assert kinds.count("umenu") == kinds.count("multislider") == 1


def test_the_layout_fits_the_device_without_overlaps() -> None:
    rects = [(b["id"], b["presentation_rect"]) for b in shown()]
    for _, (x, y, w, h) in rects:
        assert x >= 0 and y >= 0 and y + h <= GENERATOR.DEVICE_HEIGHT
        assert x + w <= patcher()["devicewidth"]
    for i, (a, (ax, ay, aw, ah)) in enumerate(rects):
        for b, (bx, by, bw, bh) in rects[i + 1 :]:
            assert not (ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah), (a, b)
    assert patcher()["openinpresentation"] == 1


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Front]:
    replies = Receiver()
    engine = Engine(
        tmp_path / "data",
        preset="pressure",
        control_port=0,
        reply_port=replies.port,
        midi_backend=lambda: FakeMidiOut(),  # type: ignore[arg-type,return-value]
        log=lambda line: None,
    )
    engine.start()
    thread = threading.Thread(target=engine.serve_forever, daemon=True)
    thread.start()
    yield Front(engine, replies)
    engine.close()
    thread.join(TIMEOUT)
    replies.close()


SHAPE = ("expected ", "target values must", "reply port must", "output must be")
"""`bad_arguments` texts about the count or type of the arguments."""


def test_the_engine_accepts_every_message(engine: Front) -> None:
    """No message is unknown or badly shaped; errors about state or files are expected."""
    for address, args in sent():
        if address == "/mpciml/hello":
            args = [1, engine.replies.port]
        for message in engine.ask(address, *args):
            if message[0] == "/mpciml/error":
                code, received, text = message[1]
                assert code != "unknown_message", message
                assert not (code == "bad_arguments" and text.startswith(SHAPE)), message
        engine.ask("/mpciml/stop")
