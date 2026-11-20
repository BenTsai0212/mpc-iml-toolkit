"""The general Pure Data front end `patches/mpc-iml.pd` (#66, ADR 0006).

Pure Data is not run here: the patch is parsed and checked against the protocol
tables of ADR 0004 to ADR 0009 and the shared front-end spec (ADR 0006, updated by
ADR 0007 with group 2 Kit, #101, by ADR 0008 with the clock display, #130, and by
ADR 0009 with group 8 Ensemble, #153). Opening it in Pure Data is a manual task
(#66, #101, #130, #153).
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
from mpc_iml.ensemble import make_preset as make_ensemble
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
    """Control messages (address -> arguments) and replies of ADR 0004 to 0009."""
    messages: dict[str, str] = {}
    replies: set[str] = set()
    for name in ("0004", "0005", "0006", "0007", "0008", "0009"):
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


def test_the_built_in_presets_use_the_patch() -> None:
    for preset in (DEMO, PRESSURE, make_ensemble()):
        assert preset.patch == "mpc_iml:patches/mpc-iml.pd"
        path = preset.patch_path()
        assert path is not None and path.is_file()
    # The presets come from the engine (ADR 0006); only group 8 names `ensemble`
    # (ADR 0009).
    text = files("mpc_iml").joinpath("patches/mpc-iml.pd").read_text()
    assert "demo" not in text and "pressure" not in text


def test_only_vanilla_objects() -> None:
    used = {box.cls for _, _, box in everything() if box.kind == "obj"}
    assert used <= VANILLA, used - VANILLA
    names = [c.name for c in patch().walk()]
    assert names == ["main", "osc", "controls", "views", "kit", "ensemble"]


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
            if box.cls != "oscformat" or box.args[1:4] == ["mpciml", "preset", "ensemble"]:
                continue  # group 8's preset controls: test_ensemble_controls_...
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
        elif address == "/mpciml/clock/test":
            assert arguments == "`i` 0 or 1"
            assert found == {"r mpciml-clock-test"}, "straight from the toggle: 0 or 1"
        elif arguments == "none":
            assert all(s in bangs or s.startswith("t b") for s in found), (address, found)
        elif address == "/mpciml/pad/module":
            assert arguments.startswith("`i` pad, `s` module, optional `f` amount")
            assert found == {"pack f s f"}, found
        elif arguments.startswith("`s`"):
            assert found <= {"symbol", "list store", "t s s s"}, (address, found)
        else:
            assert arguments.startswith("`f`") and found == {"list split 8"}, (address, found)
    # Everything a musician needs from ADR 0004 to 0008, as listed in ADR 0006 to 0008.
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
        if name == "preset":  # split by length: test_preset_replies_are_split_by_length
            assert reaches(osc, sink, "s mpciml-preset")
            routed.add(("/mpciml/preset", "mpciml-preset"))
            continue
        if box.cls == "s":
            routed.add((f"/mpciml/{name}", box.args[1]))
            continue
        assert box.cls == "route"
        for sub, part in enumerate(box.args[1:]):
            (send,) = osc.sinks(sink, sub)
            routed.add((f"/mpciml/{name}/{part}", osc.boxes[send].args[1]))
    assert {address for address, _ in routed} == replies - {"/mpciml/preset/<name>/<reply>"}
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
        "8 Ensemble", "9 Messages",
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
        8: [
            *(f"ensemble-{n}" for n in ["b1", "b2", "b3", "m1", "m2", "m3"]),
            *(f"ensemble-{n}{k}" for n in ["bl", "l", "p"] for k in range(1, 5)),
            *(f"ensemble-{n}-{s}" for n in ["bass", "melody"] for s in ["now", "next"]),
            *(f"ensemble-{n}-show" for n in ["bass-loop", "loop", "progression"]),
            *(f"ensemble-role{k}" for k in range(1, 17)),
            "ensemble-octave-entry", "ensemble-melody-octave-entry",
        ],
        9: ["clock-test"],
    }  # fmt: skip
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


# The clock display in group 9 Messages (ADR 0008, #130)


def test_the_clock_reply_is_shown_with_a_test_toggle() -> None:
    main, views, controls = patch(), canvas("views"), canvas("controls")
    # /mpciml/clock <status> <bpm> <bar> <beat> becomes one line of text.
    (clock,) = find(views, "r mpciml-clock")
    (to_list,) = views.sinks(clock)
    assert views.boxes[to_list].text == "list", "the status symbol arrives as a selector"
    (show,) = views.sinks(to_list)
    assert views.boxes[show].text == "set clock $1 $2 BPM bar $3 beat $4"
    (send,) = views.sinks(show)
    assert views.boxes[send].text == "s mpciml-clock-set"
    (r,) = find(main, "r mpciml-clock-set")
    (line,) = main.sinks(r)
    (status,) = find(main, "r mpciml-status-set")
    (status_line,) = main.sinks(status)
    assert main.boxes[line].kind == "msg" and main.boxes[line].y == main.boxes[status_line].y
    assert main.boxes[line].x > box_rect(main.boxes[status_line])[2], "right of the status"
    # The toggle sends 0 or 1, which the engine accepts as an int (ADR 0004).
    toggle = main_gui()["clock-test"]
    assert toggle.cls == "tgl" and toggle.args[5] == "test"
    assert gui_names(toggle) == ("mpciml-clock-test", "empty")
    assert toggle.args[13:] == ["0", "1"], "off when the patch opens, 1 when on"
    (test,) = find(controls, "r mpciml-clock-test")
    (fmt,) = controls.sinks(test)
    assert controls.boxes[fmt].text == "oscformat mpciml clock test"


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
    (fanout,) = find(kit, "t l l l")
    assert kit.sources(fanout) and reaches(kit, kits, "t l l l")
    (length,) = (i for i in find(kit, "list length") if kit.sources(i) == [fanout])
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


def gate_for(kit: Canvas, module: str) -> int | None:
    """What reaches the right inlet of the amount's `spigot` for a pad's module.

    Follows the boxes between the pad's module (`t s s s`) and the `spigot`,
    evaluating the few vanilla objects that are allowed there.
    """
    (spigot,) = find(kit, "spigot")
    (fanout,) = find(kit, "t s s s")
    gates = []

    def run(box: int, value: str | int | list[str] | None) -> None:
        if box == spigot:
            gates.append(value)
            return
        text = kit.boxes[box].text
        if text == "sel -":
            outlet, value = (0, None) if value == "-" else (1, value)
        elif text == "list fromsymbol":
            outlet, value = 0, list(str(value))
        elif text == "list length":
            outlet, value = 0, len(value) if isinstance(value, list) else 1
        elif text == "clip 0 1":
            outlet, value = 0, min(max(int(str(value)), 0), 1)
        elif kit.boxes[box].kind == "msg" and text == "0":
            outlet, value = 0, 0
        else:
            raise AssertionError(f"unexpected box on the gate: {text}")
        for sink in kit.sinks(box, outlet):
            run(sink, value)

    for sink in kit.sinks(fanout, 1):
        run(sink, module)
    assert len(gates) <= 1
    return gates[0] if gates else None


def test_amount_sends_nothing_for_a_pad_without_a_module() -> None:
    kit = canvas("kit")
    (spigot,) = find(kit, "spigot")
    (delay,) = find(kit, "delay 300")
    (choice,) = find(kit, "t b s")
    (bang,) = find(kit, "t b b b")
    assert kit.sinks(delay) == [spigot] and kit.sinks(spigot) == [bang]
    assert kit.sinks(choice, 0) == [bang], "a module button is not gated"
    # The spigot starts closed (no /mpciml/pads yet) and follows the pad's module:
    # `""` from /mpciml/pads and the `-` placeholder close it, a module opens it.
    assert kit.boxes[spigot].args == ["spigot"]
    assert gate_for(kit, "") == 0
    assert gate_for(kit, "-") == 0
    assert gate_for(kit, "brighten") == 1
    # The selected pad's module reaches the gate on a new pad and on every pads reply.
    (fanout,) = find(kit, "t s s s")
    (unpack,) = find(kit, "unpack s f")
    assert kit.sinks(unpack, 0) == [fanout]
    (expr,) = find(kit, "expr 2*($f1-1)")
    (pads,) = find(kit, "r mpciml-pads")
    assert reaches(kit, expr, "spigot") and reaches(kit, pads, "spigot")


ROOT = Path(__file__).parents[1]
SHIPPED = sorted([*ROOT.joinpath("src").rglob("*.pd"), *ROOT.joinpath("examples").rglob("*.pd")])
"""Every Pure Data patch under `src/` and `examples/` (#125)."""


def messages(box: Box) -> list[list[str]]:
    """The messages a message box sends, receiver names left out (#125).

    `\\,` separates messages; after `\\;` the first word names the receiver, and
    the messages after it go to that receiver.
    """
    sent: list[list[str]] = []
    words: list[str] = []
    named = False
    for word in [*box.args, "\\,"]:
        if word in ("\\,", "\\;"):
            sent.append(words[1:] if named else words)
            words, named = [], word == "\\;"
        else:
            words.append(word)
    return [m for m in sent if m]


def test_messages_of_a_message_box() -> None:
    args = ["1", "\\,", "f", "2", "\\;", "to", "label", "\\$1", "\\,", "f", "3"]
    assert messages(Box("msg", 0, 0, args)) == [["1"], ["f", "2"], ["label", "\\$1"], ["f", "3"]]


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: str(p.relative_to(ROOT)))
def test_box_widths_are_not_escaped(path: Path) -> None:
    text = path.read_text()
    escaped = re.findall(r"^#X (?:obj|msg|text) .*\\, f \d+;", text, re.MULTILINE)
    assert not escaped, "Pd's width suffix is `, f N`; `\\, f N` is box content"
    for canvas in parse(text).walk():
        for box in canvas.boxes:
            if box.kind == "msg":
                assert all(m[0] != "f" for m in messages(box)), box.text


def test_box_widths_are_read() -> None:
    (comment, *_) = patch().boxes
    assert comment.kind == "text" and comment.width == 120
    assert comment.text.endswith("no externals.")


# Group 8 Ensemble (ADR 0009, #153)

ENSEMBLE_REPLIES = [
    "bass", "melody-mode", "bass-loop", "loop", "progression", "bass-loops", "loops",
    "progressions", "octave", "melody-octave", "roles",
]  # fmt: skip
"""The replies of `ensemble` that group 8 uses; the others are ignored."""

CHOOSERS = [
    ("bl", "bass-loops", "bass-loop"),
    ("l", "loops", "loop"),
    ("p", "progressions", "progression"),
]
"""Button prefix, the reply that labels the buttons, and the control they send."""


def reaches_box(c: Canvas, start: int, target: int) -> bool:
    seen, todo = {start}, deque([start])
    while todo:
        box = todo.popleft()
        if box == target:
            return True
        for sink in set(c.sinks(box)) - seen:
            seen.add(sink)
            todo.append(sink)
    return False


def sets_from(c: Canvas, reply: str) -> dict[str, str]:
    """`<receiver> set <value>` sent by message boxes reached from `[r <reply>]`."""
    (start,) = find(c, reply)
    found = {}
    for box in c.boxes:
        if box.kind == "msg" and reaches(c, start, box.text):
            for part in box.text.split(";"):
                words = part.split()
                if len(words) == 3 and words[1] == "set":
                    found[words[0]] = words[2]
    return found


def test_the_whole_patch_fits_a_14_inch_macbook_screen() -> None:
    """The #153 decision: canvas within about 1500 x 850, no scrolling at 1512 x 982.

    Group 8 has no room above Messages within that height, so it is a new column
    right of group 7 Outputs, in the row of groups 6 and 7.
    """
    header = files("mpc_iml").joinpath("patches/mpc-iml.pd").read_text().splitlines()[0]
    m = re.fullmatch(r"#N canvas (\d+) (\d+) (\d+) (\d+) 12;", header)
    assert m is not None
    x, y, width, height = map(int, m.groups())
    assert (width, height) == (1490, 840)
    assert x + width <= 1512 and y + height <= 982
    for box in patch().boxes:
        _, _, right, bottom = box_rect(box)
        assert right <= width and bottom <= height, box.text
    headings = {b.text: b for b in patch().boxes if re.fullmatch(r"\d \w+", b.text)}
    ensemble, outputs = headings["8 Ensemble"], headings["7 Outputs"]
    assert ensemble.y == outputs.y and ensemble.x > outputs.x
    group7 = [b for b in patch().boxes if outputs.x <= b.x < ensemble.x and b.y >= outputs.y]
    assert all(box_rect(b)[2] < ensemble.x for b in group7 if b.y < headings["9 Messages"].y)


def test_preset_replies_are_split_by_length() -> None:
    """`/mpciml/preset <name> <version>` has 2 elements, a preset reply 3 or more."""
    osc = canvas("osc")
    (top,) = (i for i, b in enumerate(osc.boxes) if b.text.startswith("route version"))
    (to_list,) = osc.sinks(top, osc.boxes[top].args[1:].index("preset"))
    assert osc.boxes[to_list].text == "list"
    (fanout,) = osc.sinks(to_list)
    assert osc.boxes[fanout].text == "t l l"
    (length,) = osc.sinks(fanout, 1)
    assert osc.boxes[length].text == "list length"
    (compare,) = osc.sinks(length)
    assert osc.boxes[compare].text == "expr $f1>=3"
    (both,) = osc.sinks(compare)
    assert osc.boxes[both].text == "t f f"
    gates = osc.sinks(fanout, 0)
    assert [osc.boxes[g].text for g in gates] == ["spigot", "spigot"]
    (core,) = (g for g in gates if osc.boxes[osc.sources(g, 1)[0]].text == "== 0")
    (reply,) = (g for g in gates if osc.sources(g, 1) == [both])
    (inverse,) = osc.sources(core, 1)
    assert osc.sources(inverse) == [both]
    assert [osc.boxes[s].text for s in osc.sinks(core)] == ["s mpciml-preset"]
    assert not reaches(osc, reply, "s mpciml-preset")
    # Preset replies: only ensemble's, each to [s mpciml-preset-ensemble-<reply>].
    (trim,) = osc.sinks(reply)
    assert osc.boxes[trim].text == "list trim", "route matches selectors"
    (by_preset,) = osc.sinks(trim)
    assert osc.boxes[by_preset].text == "route ensemble"
    (by_reply,) = osc.sinks(by_preset, 0)
    assert osc.boxes[by_reply].args[1:] == ENSEMBLE_REPLIES
    for outlet, name in enumerate(ENSEMBLE_REPLIES):
        (send,) = osc.sinks(by_reply, outlet)
        assert osc.boxes[send].text == f"s mpciml-preset-ensemble-{name}"
    assert not osc.sinks(by_reply, len(ENSEMBLE_REPLIES)), "other replies are ignored"
    hook = make_ensemble().state
    assert hook is not None
    state = {name for name, _ in hook()}
    assert set(ENSEMBLE_REPLIES) <= state


def test_ensemble_controls_send_what_the_preset_accepts() -> None:
    ens, preset = canvas("ensemble"), make_ensemble()
    controls = preset.controls
    assert preset.state is not None
    state = dict(preset.state())
    found: dict[str, list[int]] = {}
    for i, box in enumerate(ens.boxes):
        if box.cls == "oscformat":
            assert box.args[1:4] == ["mpciml", "preset", "ensemble"] and len(box.args) == 5
            assert box.args[4] in controls and reaches(ens, i, "s mpciml-out")
            found[box.args[4]] = ens.sources(i)
    assert set(found) == {"bass", "melody-mode", "octave", "melody-octave"} | {
        control for _, _, control in CHOOSERS
    }
    modes = [("bass", ["loop", "rule", "off"]), ("melody-mode", ["follow", "fixed", "off"])]
    for control, values in modes:
        assert {ens.boxes[s].text for s in found[control]} == {f"symbol {v}" for v in values}
        for value in values:
            controls[control]([value])
    for _, reply, control in CHOOSERS:
        (store,) = found[control]
        assert ens.boxes[store].text == "list store"
        (r,) = find(ens, f"r mpciml-preset-ensemble-{reply}")
        (fanout,) = (s for s in ens.sources(store, 1))
        assert reaches_box(ens, r, fanout), "the names come from the reply"
        for name in state[reply]:
            controls[control]([name])
    gui = main_gui()
    for control in ("octave", "melody-octave"):
        (r,) = found[control]
        assert ens.boxes[r].text == f"r mpciml-ensemble-{control}-entry"
        low, high = (int(a) for a in gui[f"ensemble-{control}-entry"].args[1:3])
        for value in range(low, high + 1):
            controls[control]([float(value)])
        for value in (low - 1, high + 1):
            with pytest.raises(ValueError):
                controls[control]([float(value)])


def test_ensemble_buttons_are_labelled_from_the_replies() -> None:
    ens, gui = canvas("ensemble"), main_gui()
    for prefix, reply, control in CHOOSERS:
        labels = labels_from(ens, f"r mpciml-preset-ensemble-{reply}")
        assert labels == {f"mpciml-ensemble-{prefix}{k}-gui": f"${k}" for k in range(1, 5)}
        for k in range(1, 5):
            assert gui_names(gui[f"ensemble-{prefix}{k}"])[1] == f"mpciml-ensemble-{prefix}{k}-gui"
            (r,) = find(ens, f"r mpciml-ensemble-{prefix}{k}")
            (get,) = ens.sinks(r)
            assert ens.boxes[get].text == f"get {k - 1} 1"
            assert reaches(ens, r, f"oscformat mpciml preset ensemble {control}")
    for prefix, labels in (("b", ["loop", "rule", "off"]), ("m", ["follow", "fixed", "off"])):
        assert [gui[f"ensemble-{prefix}{k}"].args[7] for k in range(1, 4)] == labels


def test_ensemble_replies_reach_the_displays() -> None:
    ens, gui = canvas("ensemble"), main_gui()
    shown = {
        "bass": {"mpciml-ensemble-bass-next": "$1", "mpciml-ensemble-bass-now": "$2"},
        "melody-mode": {"mpciml-ensemble-melody-next": "$1", "mpciml-ensemble-melody-now": "$2"},
        "roles": {f"mpciml-ensemble-role{k}": f"${k}" for k in range(1, 17)},
    }
    for name in ("bass-loop", "loop", "progression", "octave", "melody-octave"):
        shown[name] = {f"mpciml-ensemble-{name}-show": "$1"}
    main_receivers = {gui_names(b)[1] for b in patch().boxes}
    for reply, expected in shown.items():
        assert sets_from(ens, f"r mpciml-preset-ensemble-{reply}") == expected, reply
        assert set(expected) <= main_receivers
    # Now and next under the mode buttons; the roles laid out like the pads.
    for mode in ("bass", "melody"):
        now, after = gui[f"ensemble-{mode}-now"], gui[f"ensemble-{mode}-next"]
        assert (now.args[4], after.args[4]) == ("now", "next") and now.y < after.y
    roles = [gui[f"ensemble-role{k}"] for k in range(1, 17)]
    for row in range(4):
        pads = roles[4 * row : 4 * row + 4]
        assert len({b.y for b in pads}) == 1 and [b.x for b in pads] == sorted(b.x for b in pads)
    assert roles[12].y < roles[8].y < roles[4].y < roles[0].y, "13-16 on top"


def test_ensemble_displays_reset_when_a_preset_loads() -> None:
    ens = canvas("ensemble")
    (r,) = find(ens, "r mpciml-preset")
    (msg,) = ens.sinks(r)
    sent = {}
    for part in ens.boxes[msg].text.split(";"):
        if words := part.split():
            sent[words[0]] = words[1:]
    name = "mpciml-preset-ensemble-"
    assert sent == {
        f"{name}bass": ["list", "-", "-"],
        f"{name}melody-mode": ["list", "-", "-"],
        f"{name}bass-loop": ["list", "-"],
        f"{name}loop": ["list", "-"],
        f"{name}progression": ["list", "-"],
        f"{name}bass-loops": ["list"],
        f"{name}loops": ["list"],
        f"{name}progressions": ["list"],
        f"{name}roles": ["list", *["-"] * 16],
    }, "the reply chains themselves, fed with empty replies"
    assert all(find(ens, f"r {target}") for target in sent)
