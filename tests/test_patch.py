"""The general Pure Data front end `patches/mpc-iml.pd` (#66, ADR 0006).

Pure Data is not run here: the patch is parsed and checked against the protocol
tables of ADR 0004 to ADR 0007 and the shared front-end spec (ADR 0006, updated by
ADR 0007 with group 2 Kit, #101). Opening it in Pure Data is a manual task (#66,
#101).
"""

import dataclasses
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
    "bng", "clip", "delay", "expr", "f", "fudiparse", "hsl", "list", "loadbang", "makefilename",
    "moses", "netreceive", "netsend", "oscformat", "oscparse", "pack", "pd", "r", "route",
    "s", "sel", "spigot", "symbol", "t", "tgl", "unpack", "until", "v", "vsl", "==",
}  # fmt: skip
"""Object classes of Pd vanilla 0.54 that the patch may use; no external libraries."""


@cache
def patch() -> Canvas:
    return parse(files("mpc_iml").joinpath("patches/mpc-iml.pd").read_text())


def protocol() -> tuple[dict[str, str], set[str]]:
    """Control messages (address -> arguments) and replies of ADR 0004 to 0007."""
    messages: dict[str, str] = {}
    replies: set[str] = set()
    for name in ("0004", "0005", "0006", "0007"):
        (adr,) = ADR.glob(f"{name}-*.md")
        table = None
        for line in adr.read_text().splitlines():
            if line.startswith(("| Address", "| Message", "| Reply")):
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


KIT_ORDER = ["kit-show", "select", "pad-entry", "amount", "module-show"]
"""Group 2 Kit besides the kit and module buttons (ADR 0007)."""


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
    assert names == ["main", "osc", "controls", "views", "kit"]


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
        elif address == "/mpciml/pad/module":
            assert arguments.startswith("`i` pad, `s` module, optional `f` amount")
            assert found == {"pack f s f"}, found
        elif arguments.startswith("`s`"):
            assert found <= {"symbol", "list store", "t s s s"}, (address, found)
        else:
            assert arguments.startswith("`f`") and found == {"list split 8"}, (address, found)
    # Everything a musician needs from ADR 0004 to 0007, as listed in ADR 0006 and 0007.
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
    (trigger,) = find(controls, "t b b b b b b b")
    sources = {controls.boxes[s].text for s in controls.sources(trigger)}
    assert sources == {"loadbang", "r mpciml-connect"}
    order = [controls.boxes[controls.sinks(trigger, o)[0]].text for o in range(6, -1, -1)]
    assert order == [
        "disconnect , connect 127.0.0.1 6450",
        "s mpciml-status",
        "1 6451",
        "oscformat mpciml preset list",
        "oscformat mpciml examples list",
        "oscformat mpciml kit list",
        "oscformat mpciml module list",
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
        "1 Connect", "2 Kit", "3 Teach", "4 Examples", "5 Model", "6 Library", "7 Outputs",
        "8 Messages",
    ]  # fmt: skip
    gui = main_gui()

    def group(box: Box) -> int:
        """The heading a box is under: the nearest one above and to its left."""
        above = [h for h in headings if h.y <= box.y and h.x <= box.x]
        return int(max(above, key=lambda h: (h.y, h.x)).text[0])

    expected = {
        1: ["connect", "ping", "pong-show", "preset-show", "state-show"],
        2: [*KIT_ORDER, *(f"k{k}" for k in range(1, 9)), *(f"m{k}" for k in range(1, 11))],
        3: ["class-entry", *(f"c{k}" for k in range(1, 9)), *(f"t{k}" for k in range(1, 9))],
        4: ["record", "stop-recording", "delete", "clear"],
        5: ["train", "run", "stop", "trained", "train-done"],
        6: ["name-entry", "save", "load", "list"],
        7: [*(f"o{k}-gui" for k in range(1, 9)), *(f"l{k}" for k in range(1, 9))],
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
    assert gui["select"].args[5] == "select_pad"
    assert gui["amount"].args[9] == "amount"
    # The order inside the groups.
    for names in (
        ["record", "stop-recording", "delete", "clear"],
        ["train", "run", "stop"],
        ["k8", "kit-show", "select", "m1", "amount", "module-show"],
    ):
        ys = [gui[n].y for n in names]
        assert ys == sorted(ys), names
    xs = [gui[n].x for n in ("save", "load", "list")]
    assert xs == sorted(xs)
    (status,) = find(main, "r mpciml-status-set")
    assert main.boxes[status].y > max(h.y for h in headings)


# Group 2 Kit and output names (ADR 0007, #101)


def labels_from(c: Canvas, reply: str) -> dict[str, str]:
    """`<receiver> label <value>` set by message boxes reached from `[r <reply>]`."""
    (start,) = find(c, reply)
    labels = {}
    for box in c.boxes:
        if box.kind == "msg" and reaches(c, start, box.text):
            for part in box.text.split(";"):
                words = part.split()
                if len(words) == 3 and words[1] == "label":
                    labels[words[0]] = words[2]
    return labels


def test_output_names_label_the_target_and_output_sliders() -> None:
    views = canvas("views")
    labels = labels_from(views, "r mpciml-names")
    for k in range(1, 9):
        assert labels[f"mpciml-t{k}-gui"] == f"${k}"
        assert labels[f"mpciml-o{k}-gui"] == f"${k}"
    # Without names (or for the sliders past the last name) the labels go back to
    # tN and oN: the names are followed by the rest of the defaults.
    stores = {b.text for b in views.boxes if b.text.startswith("list store ")}
    assert "list store t1 t2 t3 t4 t5 t6 t7 t8" in stores
    assert "list store o1 o2 o3 o4 o5 o6 o7 o8" in stores
    (names,) = find(views, "r mpciml-names")
    assert reaches(views, names, "list length")


def test_pressure_names_fit_without_overlaps() -> None:
    """With the longest names a preset may show, the sliders' labels overlap nothing."""
    names = PRESSURE.output_names
    assert names is not None and len(names) == 8
    longest = max(names, key=len)
    main = patch()
    boxes = []
    for box in main.boxes:
        if box.cls in ("hsl", "vsl") and re.fullmatch(r"[to]\d", box.args[9]):
            box = dataclasses.replace(box, args=[*box.args[:9], longest, *box.args[10:]])
        boxes.append(box)
    assert overlaps(dataclasses.replace(main, boxes=boxes)) == []


def test_kit_and_module_buttons_are_labelled_from_the_replies() -> None:
    kit = canvas("kit")
    kits = labels_from(kit, "r mpciml-kits")
    assert kits == {f"mpciml-k{k}-gui": f"${k}" for k in range(1, 9)}
    modules = labels_from(kit, "r mpciml-modules")
    assert modules == {f"mpciml-m{k}-gui": f"${k}" for k in range(1, 11)}
    for name, count, address in (("k", 8, "kit load"), ("m", 10, "pad module")):
        for k in range(1, count + 1):
            (r,) = find(kit, f"r mpciml-{name}{k}")
            (get,) = kit.sinks(r)
            assert kit.boxes[get].text == f"get {k - 1} 1"
            assert reaches(kit, r, f"oscformat mpciml {address}")


def test_the_group_is_inactive_without_kits() -> None:
    kit = canvas("kit")
    (kits,) = find(kit, "r mpciml-kits")
    (length,) = find(kit, "list length")
    assert reaches(kit, kits, "list length")
    (sel,) = kit.sinks(length)
    assert kit.boxes[sel].text == "sel 0"
    colours = {}
    for outlet in (0, 1):
        (msg,) = kit.sinks(sel, outlet)
        parts = [p.split() for p in kit.boxes[msg].text.split(";") if p.strip()]
        colours[outlet] = {words[0]: words[2:] for words in parts}
    controls = [*(f"k{k}" for k in range(1, 9)), *(f"m{k}" for k in range(1, 11))]
    controls += ["select", "amount"]
    assert set(colours[0]) == set(colours[1]) == {f"mpciml-{c}-gui" for c in controls}
    assert all(c == ["#e4e4e4", "#a0a0a0", "#a0a0a0"] for c in colours[0].values())
    assert all(c == ["#fcfcfc", "#000000", "#000000"] for c in colours[1].values())


def test_kits_and_modules_are_asked_for_again_after_a_preset_loads() -> None:
    kit = canvas("kit")
    (preset,) = find(kit, "r mpciml-preset")
    assert reaches(kit, preset, "oscformat mpciml kit list")
    assert reaches(kit, preset, "oscformat mpciml module list")
    (show,) = find(kit, "r mpciml-kit")
    assert reaches(kit, show, "s mpciml-kit-show")


def test_select_pad_starts_stops_and_turns_off_on_record() -> None:
    kit = canvas("kit")
    (select,) = find(kit, "r mpciml-select")
    (sel,) = kit.sinks(select)
    assert kit.boxes[sel].text == "sel 0"
    (off,) = kit.sinks(sel, 0)
    (on,) = kit.sinks(sel, 1)
    assert reaches(kit, off, "oscformat mpciml pad select stop")
    assert not reaches(kit, off, "oscformat mpciml pad select start")
    assert reaches(kit, on, "oscformat mpciml pad select start")
    for reply in ("r mpciml-record", "r mpciml-layout"):
        (r,) = find(kit, reply)
        (msg,) = kit.sinks(r)
        assert kit.boxes[msg].text == "set 0", "turns the toggle off without sending stop"
        (send,) = kit.sinks(msg)
        assert kit.boxes[send].text == "s mpciml-select-gui"


def test_hits_and_the_pad_box_select_a_pad_and_show_its_module() -> None:
    kit = canvas("kit")
    (clip,) = find(kit, "clip 1 16")
    sources = {kit.boxes[s].text for s in kit.sources(clip)}
    assert sources == {"r mpciml-pad-hit", "r mpciml-pad-entry", "1"}, "1 on open"
    assert reaches(kit, clip, "s mpciml-pad-show")
    assert reaches(kit, clip, "v mpciml-pad")
    # The pad is looked up in /mpciml/pads on a new pad and on every pads reply.
    (pads,) = find(kit, "r mpciml-pads")
    (store,) = (i for i, b in enumerate(kit.boxes) if b.text.startswith("list store -"))
    assert len(kit.boxes[store].args) == 2 + 2 * 16, "16 placeholder (module, amount) pairs"
    assert reaches(kit, pads, kit.boxes[store].text)
    (expr,) = find(kit, "expr 2*($f1-1)")
    assert reaches(kit, expr, "s mpciml-module-show")
    assert reaches(kit, expr, "s mpciml-amount-gui")
    for display in ("s mpciml-pad-show", "s mpciml-module-show", "s mpciml-amount-gui"):
        (send,) = find(kit, display)
        (trim,) = kit.sources(send)
        (prepend,) = kit.sources(trim)
        assert kit.boxes[prepend].text == "list prepend set", "shown without being sent"


def test_a_module_or_a_resting_amount_sends_pad_module() -> None:
    kit = canvas("kit")
    (pack,) = find(kit, "pack f s f")
    (fmt,) = kit.sinks(pack)
    assert kit.boxes[fmt].text == "oscformat mpciml pad module"
    inlets = {i: kit.boxes[s].text for s, _, d, i in kit.edges if d == pack}
    assert inlets == {0: "v mpciml-pad", 1: "symbol", 2: "f 1"}
    (amount,) = find(kit, "r mpciml-amount")
    (delay,) = find(kit, "delay 300")
    assert reaches(kit, amount, "delay 300") and reaches(kit, delay, "pack f s f")
    (choice,) = find(kit, "t b s")
    assert reaches(kit, choice, "pack f s f")
