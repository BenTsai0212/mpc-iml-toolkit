"""Generate the Max for Live device's patcher, `src/mpc_iml/patches/mpc-iml.maxpat` (#86).

The device is a Max MIDI Effect that passes MIDI through unchanged and drives the
engine over OSC with the core messages of ADR 0004, ADR 0005 and ADR 0006. Its
controls follow the shared front-end spec of ADR 0006: the same groups, names and
order as the Pure Data front end. It uses standard Max and Max for Live objects only,
with no externals and no `js`.

The patcher is generated so that the layout and wiring are readable Python and the
JSON is the same on every run; `tests/test_m4l.py` fails when the committed file
differs from this script's output. Standard library only.

Write the file:   python tools/m4l/build_device.py
Check it:         python tools/m4l/build_device.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "src" / "mpc_iml" / "patches" / "mpc-iml.maxpat"

CONTROL_PORT, REPLY_PORT, OUTPUTS_PORT = 6450, 6451, 12000
DEVICE_HEIGHT = 169
"""Live's fixed device height in pixels; the presentation must fit in it."""
SLOTS = 8
"""Class buttons, target sliders, outputs and learn buttons (ADR 0006)."""

REPLIES = (
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
)
"""Replies the device reads; any other reply leaves `route`'s last outlet, unused."""

GROUPS = (
    ("Connect", 4, 124),
    ("Teach", 134, 140),
    ("Examples", 280, 110),
    ("Model", 396, 90),
    ("Library", 492, 120),
    ("Outputs", 618, 150),
    ("Messages", 774, 200),
)
"""ADR 0006's groups, left to right: title, x and width in the presentation."""

ROW, HEIGHT = 20, 18
TOP = 200.0
"""Where the logic objects start in the patching view, below the controls."""

UI_IO = {
    "comment": (1, 0),
    "message": (2, 1),
    "textbutton": (1, 3),
    "umenu": (1, 3),
    "textedit": (1, 4),
    "slider": (1, 1),
    "multislider": (1, 2),
}

ACTIVE, INACTIVE = "0.2 0.2 0.2 1.", "0.2 0.2 0.2 0.25"
"""Background colours of an active and an inactive control."""


def io(text: str) -> tuple[int, int]:
    """Inlets and outlets of an object box, as Max creates them."""
    name, *args = text.split()
    fixed = {
        "udpsend": (1, 0),
        "udpreceive": (1, 1),
        "prepend": (1, 1),
        "tosymbol": (1, 1),
        "iter": (1, 1),
        "deferlow": (1, 1),
        "midiin": (1, 1),
        "midiout": (1, 0),
        "live.thisdevice": (1, 3),
        "symbol": (2, 1),
        "if": (1, 1),
        "+": (2, 1),
        "-": (2, 1),
        ">": (2, 1),
    }
    if name in fixed:
        return fixed[name]
    if name == "gate":
        return 2, int(args[0])
    if name == "route":
        return 2, len(args) + 1
    if name == "sel":
        return (2 if len(args) == 1 else 1), len(args) + 1
    if name in ("t", "unpack"):
        return 1, len(args)
    if name == "pak":
        return len(args), 1
    if name == "sprintf":
        return max(1, text.count("%") - 2 * text.count("%%")), 1
    if name.startswith("zl."):
        return 2, 2
    raise ValueError(f"unknown object: {text}")


class Patch:
    """Boxes and patch cords of a patcher."""

    def __init__(self) -> None:
        self.boxes: list[dict[str, Any]] = []
        self.lines: list[dict[str, Any]] = []
        self._x, self._y, self._right = 10.0, TOP, 10.0

    def _add(self, maxclass: str, ins: int, outs: int, rect: list[float], **attrs: Any) -> str:
        box_id = f"obj-{len(self.boxes) + 1}"
        box = {
            "id": box_id,
            "maxclass": maxclass,
            "numinlets": ins,
            "numoutlets": outs,
            "outlettype": [""] * outs,
            "patching_rect": rect,
            **attrs,
        }
        self.boxes.append({"box": box})
        return box_id

    def column(self) -> None:
        """Start a new column of logic objects in the patching view, below the controls."""
        self._x, self._y = self._right + 30, TOP

    def _next(self, width: float) -> list[float]:
        if self._y >= TOP + 30 * 40:
            self.column()
        rect = [self._x, float(self._y), width, 22.0]
        self._y += 30
        self._right = max(self._right, self._x + width)
        return rect

    def obj(self, text: str) -> str:
        ins, outs = io(text)
        return self._add("newobj", ins, outs, self._next(max(40.0, 7.0 * len(text))), text=text)

    def msg(self, text: str) -> str:
        """A message box that is not shown in the device."""
        return self._add("message", 2, 1, self._next(max(40.0, 7.0 * len(text))), text=text)

    def ui(self, maxclass: str, rect: tuple[float, float, float, float], **attrs: Any) -> str:
        """A control shown in the device, at the same place in both views."""
        ins, outs = UI_IO[maxclass]
        place = [float(v) for v in rect]
        return self._add(
            maxclass,
            ins,
            outs,
            place,
            presentation=1,
            presentation_rect=place,
            **{"fontsize": 10.0, **attrs},
        )

    def connect(self, source: str, outlet: int, sink: str, inlet: int = 0) -> None:
        self.lines.append({"patchline": {"source": [source, outlet], "destination": [sink, inlet]}})


def row(index: int) -> float:
    return 4.0 + ROW * index


def build() -> dict[str, Any]:
    p = Patch()
    x = {title: left for title, left, _ in GROUPS}

    def button(text: str, left: float, r: int, width: float) -> str:
        return p.ui("textbutton", (left, row(r), width, HEIGHT), text=text, mode=0)

    def display(text: str, left: float, r: int, width: float, rows: int = 1) -> str:
        return p.ui("message", (left, row(r), width, HEIGHT + ROW * (rows - 1)), text=text)

    for title, left, width in GROUPS:
        p.ui("comment", (left, row(0), width, HEIGHT), text=title, fontface=1)

    # Network: control out, replies in, model outputs in; MIDI passes through.
    p.column()
    out = p.obj(f"udpsend 127.0.0.1 {CONTROL_PORT}")
    reply = p.obj("route " + " ".join(REPLIES))
    p.connect(p.obj(f"udpreceive {REPLY_PORT}"), 0, reply)
    outputs = p.obj("route /wek/outputs")
    p.connect(p.obj(f"udpreceive {OUTPUTS_PORT}"), 0, outputs)
    p.connect(p.obj("midiin"), 0, p.obj("midiout"))

    def on(address: str) -> tuple[str, int]:
        return reply, REPLIES.index(address)

    def send(text: str, *sources: str) -> str:
        """A hidden message box that sends `text` to the engine when a source fires."""
        box = p.msg(text)
        p.connect(box, 0, out)
        for source in sources:
            p.connect(source, 0, box)
        return box

    def sender(address: str) -> str:
        """`prepend <address>` into `udpsend`: sends its input as the arguments."""
        box = p.obj(f"prepend {address}")
        p.connect(box, 0, out)
        return box

    def relay(source: tuple[str, int], text: str, sink: str, inlet: int = 0) -> None:
        """A hidden message box between `source` and `sink`: `source` fires `text`."""
        box = p.msg(text)
        p.connect(*source, box)
        p.connect(box, 0, sink, inlet)

    def show(source: tuple[str, int], fmt: str, target: str) -> None:
        box = p.obj(f"sprintf set {fmt}")
        p.connect(*source, box)
        p.connect(box, 0, target)

    # 7 Messages: one status line.
    status = display("", x["Messages"], 1, 196, rows=2)
    show(on("/mpciml/error"), "%s %s: %s", status)
    show(on("/mpciml/train/failed"), "train failed: %s", status)

    # 1 Connect
    p.column()
    left = x["Connect"]
    connect = p.obj("t b b")
    p.connect(button("connect", left, 1, 60), 0, connect)
    send("/mpciml/hello 1 6451, /mpciml/preset/list, /mpciml/examples/list", connect)
    relay((connect, 1), "set", status)
    ping = p.obj("t b b")
    p.connect(button("ping", left + 64, 1, 56), 0, ping)
    send("/mpciml/ping", ping)
    menu = p.ui("umenu", (left, row(2), 120, HEIGHT), items=[])
    p.connect(menu, 1, sender("/mpciml/preset/load"))
    version = display("protocol -", left, 3, 120)
    preset = display("preset -", left, 4, 120)
    state = display("state -", left, 5, 120)
    pong = display("no pong yet", left, 6, 120)
    relay((ping, 1), "set waiting for pong", pong)
    relay(on("/mpciml/pong"), "set pong", pong)
    show(on("/mpciml/version"), "protocol %d.%d engine %s", version)
    show(on("/mpciml/preset"), "preset %s %s", preset)
    show(on("/mpciml/state"), "state %s", state)
    presets = p.obj("route bang")
    p.connect(*on("/mpciml/presets"), presets)
    refill = p.obj("t l b")
    p.connect(presets, 1, refill)
    relay((refill, 1), "clear", menu)
    each = p.obj("iter")
    p.connect(refill, 0, each)
    append = p.obj("prepend append")
    p.connect(each, 0, append)
    p.connect(append, 0, menu)
    preset_name = p.obj("unpack s s")
    p.connect(*on("/mpciml/preset"), preset_name)
    choose = p.obj("prepend setsymbol")
    p.connect(preset_name, 0, choose)
    p.connect(choose, 0, menu)

    # Layout: the number of targets and MIDI controllers of the active preset.
    layout = p.obj("unpack i i")
    p.connect(*on("/mpciml/layout"), layout)
    targets = p.obj("t i i i")
    p.connect(layout, 0, targets)
    regression = p.obj("> 0")
    p.connect(targets, 0, regression)
    mode = p.obj("+ 1")
    p.connect(regression, 0, mode)
    too_many = p.obj("> 8")
    p.connect(targets, 1, too_many)
    say = p.obj("sel 1")
    p.connect(too_many, 0, say)
    relay((say, 0), "set targets above 8: this device supports up to 8", status)

    def activate(source: tuple[str, int], condition: str, control: str) -> None:
        """Make `control` clickable while `condition` (an `if` test of `$i1`) holds."""
        test = p.obj(f"if {condition} then 0 else 1")
        p.connect(*source, test)
        split = p.obj("t i i")
        p.connect(test, 0, split)
        ignore = p.obj("prepend ignoreclick")
        p.connect(split, 0, ignore)
        p.connect(ignore, 0, control)
        pick = p.obj("sel 0 1")
        p.connect(split, 1, pick)
        for outlet, colour in enumerate((ACTIVE, INACTIVE)):
            relay((pick, outlet), f"bgcolor {colour}", control)

    # 2 Teach: the class field and buttons c1-c8, or the target sliders t1-t8.
    p.column()
    left = x["Teach"]
    field = p.ui("textedit", (left, row(1), 136, HEIGHT), keymode=1, lines=1)
    typed = p.obj("route text")
    p.connect(field, 0, typed)
    label = p.obj("tosymbol")
    p.connect(typed, 0, label)
    p.connect(typed, 1, label)
    current = p.obj("t s s s s")
    p.connect(label, 0, current)
    p.connect(current, 0, sender("/mpciml/class"))
    record_class, delete_class = p.obj("symbol"), p.obj("symbol")
    p.connect(current, 1, record_class, 1)
    p.connect(current, 2, delete_class, 1)
    shown = p.obj("prepend set")
    p.connect(current, 3, shown)
    p.connect(shown, 0, field)

    labels = p.obj("zl.reg")
    nth = p.obj("zl.nth")
    p.connect(labels, 0, nth)
    p.connect(nth, 0, label)
    counts = p.obj("route bang")
    p.connect(*on("/mpciml/counts"), counts)
    collect = p.obj("t b l b")
    p.connect(counts, 1, collect)
    group = p.obj("zl.group 256")
    relay((collect, 2), "zlclear", group)
    pairs = p.obj("zl.iter 2")
    p.connect(collect, 1, pairs)
    first = p.obj("zl.nth 1")
    p.connect(pairs, 0, first)
    p.connect(first, 0, group)
    p.connect(collect, 0, group)
    named = p.obj("t l l b")
    p.connect(group, 0, named)
    p.connect(named, 1, labels, 1)
    for k in range(1, SLOTS + 1):
        column, line = (k - 1) % 4, 2 + (k - 1) // 4
        c = button(f"c{k}", left + 34 * column, line, 32)
        pick = p.obj("t b i")
        relay((c, 0), str(k), pick)
        p.connect(pick, 1, nth, 1)
        p.connect(pick, 0, labels)
        relay((named, 2), f"text c{k}", c)
        name = p.obj(f"zl.nth {k}")
        p.connect(named, 0, name)
        text = p.obj("prepend text")
        p.connect(name, 0, text)
        p.connect(text, 0, c)
        activate((targets, 2), "$i1 == 0", c)

    values = p.obj("pak " + " ".join(["0."] * SLOTS))
    held = p.obj("zl.reg")
    p.connect(values, 0, held, 1)
    zero = p.msg("0.")
    for k in range(1, SLOTS + 1):
        slider = p.ui(
            "slider",
            (left + 17 * (k - 1), row(4), 15, HEIGHT + 2 * ROW),
            floatoutput=1,
            size=1.0,
        )
        p.ui("comment", (left + 17 * (k - 1), row(7), 17, HEIGHT), text=f"t{k}")
        p.connect(slider, 0, values, k - 1)
        p.connect(zero, 0, slider)
        activate((targets, 2), f"$i1 >= {k}", slider)
    cut = p.obj(f"zl.slice {SLOTS}")
    p.connect(held, 0, cut)
    p.connect(targets, 2, cut, 1)

    # 3 Examples
    p.column()
    left = x["Examples"]
    record = p.obj("t b b")
    p.connect(button("record", left, 1, 50), 0, record)
    task = p.obj("gate 2 1")
    p.connect(mode, 0, task)
    p.connect(record, 1, task, 1)
    p.connect(task, 0, record_class)
    p.connect(record_class, 0, sender("/mpciml/class"))
    p.connect(task, 1, held)
    p.connect(cut, 0, sender("/mpciml/targets"))
    send("/mpciml/record/start", record)
    send("/mpciml/record/stop", button("stop recording", left, 2, 100))
    p.connect(button("delete", left, 3, 50), 0, delete_class)
    p.connect(delete_class, 0, sender("/mpciml/examples/delete"))
    send("/mpciml/examples/clear", button("clear", left + 54, 3, 50))
    tally = display("no examples", left, 4, 106, rows=4)
    relay((counts, 0), "set no examples", tally)
    listed = p.obj("prepend set")
    p.connect(counts, 1, listed)
    p.connect(listed, 0, tally)

    # 4 Model
    p.column()
    left = x["Model"]
    send("/mpciml/train", button("train", left, 1, 60))
    send("/mpciml/run", button("run", left, 2, 60))
    send("/mpciml/stop", button("stop", left, 3, 60))
    trained = display("not trained", left, 4, 88)
    flag = p.obj("sel 0 1")
    p.connect(*on("/mpciml/trained"), flag)
    for outlet, text in enumerate(("set not trained", "set trained")):
        relay((flag, outlet), text, trained)
    took = display("-", left, 5, 88)
    show(on("/mpciml/train/done"), "trained in %.2f s", took)

    # 5 Library
    p.column()
    left = x["Library"]
    name_field = p.ui("textedit", (left, row(1), 116, HEIGHT), keymode=1, lines=1)
    entered = p.obj("route text")
    p.connect(name_field, 0, entered)
    as_name = p.obj("tosymbol")
    p.connect(entered, 0, as_name)
    p.connect(entered, 1, as_name)
    store = p.obj("t s s")
    p.connect(as_name, 0, store)
    save_name, load_name = p.obj("symbol"), p.obj("symbol")
    p.connect(store, 0, save_name, 1)
    p.connect(store, 1, load_name, 1)
    p.connect(button("save", left, 2, 36), 0, save_name)
    p.connect(save_name, 0, sender("/mpciml/examples/save"))
    p.connect(button("load", left + 40, 2, 36), 0, load_name)
    p.connect(load_name, 0, sender("/mpciml/examples/load"))
    send("/mpciml/examples/list", button("list", left + 80, 2, 36))
    default = p.obj("sprintf symout %s-examples")
    p.connect(preset_name, 0, default)
    named_default = p.obj("t s s")
    p.connect(default, 0, named_default)
    p.connect(named_default, 0, store)
    fill = p.obj("prepend set")
    p.connect(named_default, 1, fill)
    p.connect(fill, 0, name_field)
    saved = display("no saved sets", left, 3, 116, rows=5)
    names = p.obj("route bang")
    p.connect(*on("/mpciml/examples/names"), names)
    relay((names, 0), "set no saved sets", saved)
    names_set = p.obj("prepend set")
    p.connect(names, 1, names_set)
    p.connect(names_set, 0, saved)

    # 6 Outputs: o1-o8 (regression) or the predicted class, and learn buttons l1-l8.
    p.column()
    left = x["Outputs"]
    bars = p.ui(
        "multislider",
        (left, row(1), 18 * SLOTS, HEIGHT + 2 * ROW),
        size=SLOTS,
        setminmax=[0.0, 1.0],
        ignoreclick=1,
    )
    predicted = display("class -", left, 6, 150)
    learned = display("learn: click lN, then move", left, 7, 150)
    route_out = p.obj("gate 2 1")
    p.connect(mode, 0, route_out)
    p.connect(outputs, 0, route_out, 1)
    p.connect(route_out, 1, bars)
    number = p.obj("t i i b")
    p.connect(route_out, 0, number)
    position = p.obj("- 1")
    p.connect(number, 1, position)
    lookup = p.obj("zl.lookup")
    p.connect(position, 0, lookup)
    p.connect(named, 1, lookup, 1)
    line = p.obj("sprintf set class %d %s")
    relay((number, 2), "symbol -", line, 1)
    p.connect(lookup, 0, line, 1)
    p.connect(number, 0, line)
    p.connect(line, 0, predicted)
    controllers = p.obj("t i")
    p.connect(layout, 1, controllers)
    for k in range(1, SLOTS + 1):
        p.ui("comment", (left + 18 * (k - 1), row(4), 18, HEIGHT), text=f"o{k}", fontsize=9.0)
        learn = button(f"l{k}", left + 18 * (k - 1), 5, 17)
        send(f"/mpciml/midi/learn {k}", learn)
        activate((controllers, 0), f"$i1 >= {k}", learn)
    show(on("/mpciml/midi/sent"), "output %d on CC %d", learned)

    # Start: zero the sliders, then connect, once Live has loaded the device.
    p.column()
    ready = p.obj("live.thisdevice")
    later = p.obj("deferlow")
    p.connect(ready, 0, later)
    start = p.obj("t b b")
    p.connect(later, 0, start)
    p.connect(start, 1, zero)
    p.connect(start, 0, connect)

    width = max(left + w for _, left, w in GROUPS) + 4
    return {
        "patcher": {
            "fileversion": 1,
            "appversion": {
                "major": 8,
                "minor": 6,
                "revision": 0,
                "architecture": "x64",
                "modernui": 1,
            },
            "classnamespace": "box",
            "rect": [100.0, 100.0, 1960.0, 900.0],
            "openinpresentation": 1,
            "devicewidth": float(width),
            "default_fontsize": 10.0,
            "default_fontface": 0,
            "default_fontname": "Arial",
            "gridsize": [8.0, 8.0],
            "description": "mpc-iml: record, train, run and map the engine (ADR 0006)",
            "boxes": p.boxes,
            "lines": p.lines,
        }
    }


def render() -> str:
    """The patcher as JSON, one box or patch cord per line so diffs stay readable."""
    patcher = build()["patcher"]
    head = {k: v for k, v in patcher.items() if k not in ("boxes", "lines")}
    parts = [f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in head.items()]
    for key in ("boxes", "lines"):
        items = ",\n".join(f"    {json.dumps(item)}" for item in patcher[key])
        parts.append(f'  "{key}": [\n{items}\n  ]')
    return '{\n "patcher": {\n' + ",\n".join(parts) + "\n }\n}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text() != text:
            print(f"{OUTPUT.relative_to(ROOT)} is out of date; run {Path(__file__).name}")
            return 1
        return 0
    OUTPUT.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
