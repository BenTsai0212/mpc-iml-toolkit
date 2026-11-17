"""The general Pure Data front end `patches/mpc-iml.pd` (#66, ADR 0006).

Pure Data is not run here: the patch is parsed and checked against the protocol
tables of ADR 0004, ADR 0005 and ADR 0006 and the shared front-end spec. Opening it
in Pure Data is a manual task (#66).
"""

import re
from collections import deque
from functools import cache
from importlib.resources import files
from pathlib import Path

import pytest
from pd import Box, Canvas, box_rect, overlaps, parse

from mpc_iml.demo import PRESET as DEMO
from mpc_iml.pressure import PRESET as PRESSURE

ADR = Path(__file__).parents[1] / "docs" / "adr"

VANILLA = {
    "bng", "clip", "expr", "f", "fudiparse", "hsl", "list", "loadbang", "makefilename",
    "moses", "netreceive", "netsend", "oscformat", "oscparse", "pack", "pd", "r", "route",
    "s", "sel", "spigot", "symbol", "t", "tgl", "unpack", "until", "v", "vsl", "==",
}  # fmt: skip
"""Object classes of Pd vanilla 0.54 that the patch may use; no external libraries."""


@cache
def patch() -> Canvas:
    return parse(files("mpc_iml").joinpath("patches/mpc-iml.pd").read_text())


def protocol() -> tuple[dict[str, str], set[str]]:
    """Control messages (address -> arguments) and replies of ADR 0004, 0005, 0006."""
    messages: dict[str, str] = {}
    replies: set[str] = set()
    for name in ("0004", "0005", "0006"):
        (adr,) = ADR.glob(f"{name}-*.md")
        table = None
        for line in adr.read_text().splitlines():
            if line.startswith("| Address") or line.startswith("| Reply"):
                table = line.rsplit("|", 2)[-2].strip()
            elif m := re.match(r"\| `(/mpciml/[^`]+)` \| ([^|]+) \|", line):
                if table == "Effect":
                    messages[m[1]] = m[2].strip()
                elif table == "When":
                    replies.add(m[1])
            elif not line.startswith("|"):
                table = None
    return messages, replies


def gui_names(box: Box) -> tuple[str, str]:
    """The send and receive names of a GUI box or atom, `empty` when none."""
    at = {"bng": 5, "tgl": 3, "hsl": 7, "vsl": 7}.get(box.cls)
    if at is not None:
        return box.args[at], box.args[at + 1]
    if box.kind in ("floatatom", "symbolatom"):
        send, receive = box.args[6], box.args[5]
        return ("empty" if send == "-" else send), ("empty" if receive == "-" else receive)
    return "empty", "empty"


def message_targets(box: Box) -> list[str]:
    """The receivers a message box sends to with `; name ...`."""
    return re.findall(r";\s*(\S+)", box.text) if box.kind == "msg" else []


def everything() -> list[tuple[Canvas, int, Box]]:
    return [(c, i, b) for c in patch().walk() for i, b in enumerate(c.boxes)]


def senders() -> set[str]:
    names = set()
    for _, _, box in everything():
        if box.cls == "s":
            names.add(box.args[1])
        names.add(gui_names(box)[0])
        names.update(message_targets(box))
    return names - {"empty"}


def receivers() -> set[str]:
    names = {box.args[1] for _, _, box in everything() if box.cls == "r"}
    return names | {gui_names(box)[1] for _, _, box in everything()} - {"empty"}


def canvas(name: str) -> Canvas:
    return next(c for c in patch().walk() if c.name == name)


def find(c: Canvas, text: str) -> list[int]:
    return [i for i, b in enumerate(c.boxes) if b.text == text]


def reaches(c: Canvas, start: int, text: str) -> bool:
    """Whether a box with `text` can be reached from `start` along connections."""
    seen, todo = {start}, deque([start])
    while todo:
        box = todo.popleft()
        if c.boxes[box].text == text:
            return True
        for sink in set(c.sinks(box)) - seen:
            seen.add(sink)
            todo.append(sink)
    return False


def main_gui() -> dict[str, Box]:
    """GUI boxes of the main window by send name, or by receive name without one."""
    boxes = {}
    for box in patch().boxes:
        send, receive = gui_names(box)
        name = send if send != "empty" else receive
        if name != "empty":
            boxes[name.removeprefix("mpciml-")] = box
    return boxes


# The patch in the package


def test_both_built_in_presets_use_the_patch() -> None:
    for preset in (DEMO, PRESSURE):
        assert preset.patch == "mpc_iml:patches/mpc-iml.pd"
        path = preset.patch_path()
        assert path is not None and path.is_file()
    # It names no preset: the presets come from the engine (ADR 0006).
    text = files("mpc_iml").joinpath("patches/mpc-iml.pd").read_text()
    assert "demo" not in text and "pressure" not in text


def test_only_vanilla_objects() -> None:
    used = {box.cls for _, _, box in everything() if box.kind == "obj"}
    assert used <= VANILLA, used - VANILLA
    names = [c.name for c in patch().walk()]
    assert names == ["main", "osc", "controls", "views"]


def test_nothing_overlaps() -> None:
    for c in patch().walk():
        assert overlaps(c) == [], c.name
        assert all(box_rect(b)[0] >= 0 and box_rect(b)[1] >= 0 for b in c.boxes), c.name


def test_main_window_has_no_long_cables() -> None:
    """The main window only connects each display to the [r] right above it."""
    main = patch()
    for source, _, sink, _ in main.edges:
        a, b = main.boxes[source], main.boxes[sink]
        assert a.cls == "r" and b.kind == "msg" and a.x == b.x and 0 < b.y - a.y <= 30


# Messages against the protocol


def test_every_control_message_is_in_the_protocol_with_its_arguments() -> None:
    messages, _ = protocol()
    sources: dict[str, set[str]] = {}
    for c in patch().walk():
        for i, box in enumerate(c.boxes):
            if box.cls != "oscformat":
                continue
            address = "/" + "/".join(box.args[1:])
            assert address in messages, address
            assert reaches(c, i, "s mpciml-out")
            sources.setdefault(address, set()).update(c.boxes[s].text for s in c.sources(i))
    bangs = {f"r mpciml-{name}" for name in main_gui()}
    for address, found in sources.items():
        arguments = messages[address]
        if address == "/mpciml/hello":
            assert found == {"1 6451"}, "protocol major 1, replies to the patch's port 6451"
        elif address == "/mpciml/midi/learn":
            assert found == {str(n) for n in range(1, 9)}
        elif arguments == "none":
            assert all(s in bangs or s.startswith("t b") for s in found), (address, found)
        elif arguments.startswith("`s`"):
            assert found <= {"symbol", "list store", "t s s s"}, (address, found)
        else:
            assert arguments.startswith("`f`") and found == {"list split 8"}, (address, found)
    # Everything a musician needs from ADR 0004 and 0005, as listed in ADR 0006.
    needed = set(messages) - {"/mpciml/state/get"}
    assert set(sources) == needed


def test_every_reply_is_routed_to_something_that_shows_it() -> None:
    _, replies = protocol()
    osc = canvas("osc")
    (top,) = (i for i, b in enumerate(osc.boxes) if b.text.startswith("route version"))
    routed = set()
    for outlet, name in enumerate(osc.boxes[top].args[1:]):
        (sink,) = osc.sinks(top, outlet)
        box = osc.boxes[sink]
        if box.cls == "s":
            routed.add((f"/mpciml/{name}", box.args[1]))
            continue
        assert box.cls == "route"
        for sub, part in enumerate(box.args[1:]):
            (send,) = osc.sinks(sink, sub)
            routed.add((f"/mpciml/{name}/{part}", osc.boxes[send].args[1]))
    assert {address for address, _ in routed} == replies
    for address, name in routed:
        assert name == "mpciml-" + address.removeprefix("/mpciml/").replace("/", "-")
        assert name in receivers(), address
    (wek,) = find(osc, "netreceive -u -b 12000")
    assert reaches(osc, wek, "s mpciml-outputs")


def test_sends_and_receives_match() -> None:
    assert senders() == receivers()


def test_connect_on_open_and_on_click() -> None:
    controls = canvas("controls")
    (trigger,) = find(controls, "t b b b b b")
    sources = {controls.boxes[s].text for s in controls.sources(trigger)}
    assert sources == {"loadbang", "r mpciml-connect"}
    order = [controls.boxes[controls.sinks(trigger, o)[0]].text for o in (4, 3, 2, 1, 0)]
    assert order == [
        "disconnect , connect 127.0.0.1 6450",
        "s mpciml-status",
        "1 6451",
        "oscformat mpciml preset list",
        "oscformat mpciml examples list",
    ]


def test_record_sends_the_class_or_exactly_targets_values_first() -> None:
    controls = canvas("controls")
    (trigger,) = controls.sinks(find(controls, "r mpciml-record")[0])
    (first,) = controls.sinks(trigger, 1)
    assert controls.boxes[first].text == "v mpciml-targets"
    (start,) = controls.sinks(trigger, 0)
    assert controls.boxes[start].text == "oscformat mpciml record start"
    (split,) = find(controls, "list split 8")
    (count,) = controls.sources(split, 1)
    assert controls.boxes[count].text == "r mpciml-ntargets"
    (too_many,) = controls.sinks(split, 2)
    assert "up to 8 targets" in controls.boxes[too_many].text


# What the front end shows (ADR 0006)


def test_layout_greys_out_what_the_preset_does_not_have() -> None:
    views = canvas("views")
    color = {}
    for box in views.boxes:
        for part in box.text.split(";"):
            words = part.split()
            if len(words) == 5 and words[1] == "color":
                assert words[3] == words[4], "the same colour for the front and the label"
                color.setdefault(words[0], []).append(words[2:4])
    for k in range(1, 9):
        n = 2 * k - 1
        for name in ("t", "o", "l"):
            assert color[f"mpciml-{name}{k}-gui"] == [[f"${n}", f"${n + 1}"]]
        assert len(color[f"mpciml-c{k}-gui"]) == 2, "classes: active or inactive"
    (layout,) = find(views, "r mpciml-layout")
    assert reaches(views, layout, "v mpciml-targets")
    assert reaches(views, layout, "s mpciml-classmode")
    stores = [b for b in views.boxes if b.text.startswith("list store #")]
    assert len(stores) == 2 and all(len(b.args) == 34 for b in stores), "8 on, 8 off pairs"


def test_class_and_preset_buttons_are_labelled_from_the_replies() -> None:
    labels: dict[str, str] = {}
    for _, _, box in everything():
        for part in box.text.split(";"):
            words = part.split()
            if len(words) == 3 and words[1] == "label":
                labels[words[0]] = words[2]
    for k in range(1, 9):
        assert labels[f"mpciml-p{k}-gui"] == f"${k}"
        assert labels[f"mpciml-c{k}-gui"] == f"${2 * k - 1}", "the labels of counts pairs"
    controls = canvas("controls")
    for name, step in (("p", 1), ("c", 2)):
        for k in range(1, 9):
            (r,) = find(controls, f"r mpciml-{name}{k}")
            (get,) = controls.sinks(r)
            assert controls.boxes[get].text == f"get {step * (k - 1)} 1"


@pytest.mark.parametrize("reply", ["r mpciml-error", "r mpciml-train-failed"])
def test_errors_reach_the_status_line(reply: str) -> None:
    views = canvas("views")
    (start,) = find(views, reply)
    assert reaches(views, start, "s mpciml-status")
    (status,) = find(views, "r mpciml-status")
    assert reaches(views, status, "s mpciml-status-set")
    assert "mpciml-status-set" in {b.args[1] for b in patch().boxes if b.cls == "r"}


def test_groups_and_names_follow_the_shared_spec() -> None:
    main = patch()
    headings = [b for b in main.boxes if b.kind == "text" and re.fullmatch(r"\d \w+", b.text)]
    headings.sort(key=lambda b: (b.y, b.x))
    assert [b.text for b in headings] == [
        "1 Connect", "2 Teach", "3 Examples", "4 Model", "5 Library", "6 Outputs", "7 Messages",
    ]  # fmt: skip
    gui = main_gui()

    def group(box: Box) -> int:
        """The heading a box is under: the nearest one above and to its left."""
        above = [h for h in headings if h.y <= box.y and h.x <= box.x]
        return int(max(above, key=lambda h: (h.y, h.x)).text[0])

    expected = {
        1: ["connect", "ping", "pong-show", "preset-show", "state-show"],
        2: ["class-entry", *(f"c{k}" for k in range(1, 9)), *(f"t{k}" for k in range(1, 9))],
        3: ["record", "stop-recording", "delete", "clear"],
        4: ["train", "run", "stop", "trained", "train-done"],
        5: ["name-entry", "save", "load", "list"],
        6: [*(f"o{k}-gui" for k in range(1, 9)), *(f"l{k}" for k in range(1, 9))],
    }
    for number, names in expected.items():
        for name in names:
            assert group(gui[name]) == number, name
    # Pd labels: the spec's names, with `_` for a space.
    for name in ["connect", "ping", "record", "delete", "clear", "train", "run", "stop"]:
        assert gui[name].args[7] == name
    assert gui["stop-recording"].args[7] == "stop_recording"
    for name in ["save", "load", "list"]:
        assert gui[name].args[7] == name
    for k in range(1, 9):
        assert gui[f"t{k}"].args[9] == f"t{k}"
        assert gui[f"o{k}-gui"].args[9] == f"o{k}"
        assert gui[f"l{k}"].args[7] == f"l{k}"
        learn, output = gui[f"l{k}"], gui[f"o{k}-gui"]
        assert learn.x == output.x and learn.y > output.y, "learn buttons under o1-o8"
    assert gui["trained"].args[5] == "trained"
    # The order inside the groups.
    for names in (["record", "stop-recording", "delete", "clear"], ["train", "run", "stop"]):
        ys = [gui[n].y for n in names]
        assert ys == sorted(ys), names
    xs = [gui[n].x for n in ("save", "load", "list")]
    assert xs == sorted(xs)
    (status,) = find(main, "r mpciml-status-set")
    assert main.boxes[status].y > max(h.y for h in headings)
