"""Reading Pure Data patches in tests, without Pure Data (#66).

`parse` reads a `.pd` file into canvases of boxes and connections, subpatches
included. `box_rect` estimates where Pd draws a box at font size 12, so tests can
check that nothing overlaps.
"""

import re
import textwrap
from dataclasses import dataclass, field

FONT_WIDTH, FONT_HEIGHT, BOX_HEIGHT = 7, 16, 21
"""Pd's font metrics at font size 12, estimated."""

Rect = tuple[int, int, int, int]
Edge = tuple[int, int, int, int]
"""A connection: source box, outlet, sink box, inlet."""


@dataclass
class Box:
    """One box of a canvas: `kind` is `obj`, `msg`, `text`, `floatatom`, ..."""

    kind: str
    x: int
    y: int
    args: list[str]
    width: int | None = None
    """The fixed width in characters (Pd's suffix `, f N`), or `None`."""

    @property
    def text(self) -> str:
        """The box text, unescaped (`\\;` becomes `;`, `\\$1` becomes `$1`)."""
        return " ".join(unescape(a) for a in self.args)

    @property
    def cls(self) -> str:
        """The object class, such as `route` or `bng`; empty for other kinds."""
        return self.args[0] if self.kind == "obj" and self.args else ""


@dataclass
class Canvas:
    name: str
    boxes: list[Box] = field(default_factory=list)
    edges: set[Edge] = field(default_factory=set)
    children: list["Canvas"] = field(default_factory=list)

    def walk(self) -> list["Canvas"]:
        """This canvas and every subpatch in it."""
        return [self, *(c for child in self.children for c in child.walk())]

    def sinks(self, box: int, outlet: int | None = None) -> list[int]:
        return sorted(d for s, o, d, _ in self.edges if s == box and outlet in (None, o))

    def sources(self, box: int, inlet: int | None = None) -> list[int]:
        return sorted(s for s, _, d, i in self.edges if d == box and inlet in (None, i))


def unescape(word: str) -> str:
    return re.sub(r"\\(.)", r"\1", word)


def records(text: str) -> list[list[str]]:
    """The records of a patch file as words; a record may span several lines."""
    parts = re.split(r"(?<!\\);[ \t]*(?:\r?\n|$)", text)
    return [part.split() for part in parts if part.strip()]


def box_width(args: list[str]) -> tuple[list[str], int | None]:
    """The box words without Pd's width suffix `, f N`, and the width (#125).

    The comma of the suffix is not escaped and may stick to the word before it
    (`-, f 30`). An escaped `\\, f N` is box content, not a width.
    """
    if len(args) < 3 or args[-2] != "f" or not args[-1].isdigit():
        return args, None
    before, width = args[-3], int(args[-1])
    if before == ",":
        return args[:-3], width
    if before.endswith(",") and not before.endswith("\\,"):
        return [*args[:-3], before[:-1]], width
    return args, None


def parse(text: str) -> Canvas:
    """The main canvas of a patch, with its subpatches as `children`."""
    stack: list[Canvas] = []
    root: Canvas | None = None
    for words in records(text):
        head, kind = words[0], words[1]
        if head == "#N" and kind == "canvas":
            canvas = Canvas(words[6] if stack else "main")
            if stack:
                stack[-1].children.append(canvas)
            else:
                root = canvas
            stack.append(canvas)
            continue
        assert head == "#X", words
        if kind == "connect":
            a, o, b, i = (int(w) for w in words[2:6])
            stack[-1].edges.add((a, o, b, i))
            continue
        if kind == "restore":
            stack.pop()
            kind = "obj"
        if kind in ("coords", "declare"):
            continue
        args, width = box_width(words[4:])
        stack[-1].boxes.append(Box(kind, int(words[2]), int(words[3]), args, width))
    assert root is not None and len(stack) == 1, "unbalanced canvases"
    for canvas in root.walk():
        for a, _, b, _ in canvas.edges:
            assert a < len(canvas.boxes) and b < len(canvas.boxes), (canvas.name, a, b)
    return root


def text_width(text: str) -> int:
    return len(text) * FONT_WIDTH


def _lines(box: Box) -> list[str]:
    """The lines Pd shows in a box: a new line after each `;`, wrapped at the width."""
    lines: list[str] = []
    for part in re.split(r"(?<=;) ", box.text):
        if box.width is not None or box.kind == "text":
            lines.extend(textwrap.wrap(part, box.width or 60) or [""])
        else:
            lines.append(part)
    return lines


def box_rect(box: Box) -> Rect:
    """An estimate of where a box is drawn: left, top, right, bottom."""
    x, y, args = box.x, box.y, box.args
    if box.kind == "text":
        rows = _lines(box)
        return x, y, x + max(map(text_width, rows)), y + FONT_HEIGHT * len(rows)
    if box.kind in ("symbolatom", "floatatom", "listbox"):
        width, side, label = int(args[0]), args[3], args[4]
        right = x + text_width("0" * width) + 4
        if label == "-":
            return x, y, right, y + BOX_HEIGHT
        assert side == "0", "labels are drawn on the left"
        return x - text_width(label) - 4, y, right, y + BOX_HEIGHT
    if box.cls in ("bng", "tgl", "hsl", "vsl"):
        if box.cls in ("bng", "tgl"):
            width = height = int(args[1])
            at = 7 if box.cls == "bng" else 5
        else:
            width, height = int(args[1]), int(args[2])
            at = 9
        label, dx, dy = args[at], int(args[at + 1]), int(args[at + 2])
        label_width = 0 if label == "empty" else text_width(label)
        label_left, label_right = x + dx, x + dx + label_width
        label_top, label_bottom = y + dy - FONT_HEIGHT // 2, y + dy + FONT_HEIGHT // 2
        return (
            min(x, label_left),
            min(y, label_top),
            max(x + width, label_right),
            max(y + height, label_bottom),
        )
    rows = _lines(box)
    height = BOX_HEIGHT + FONT_HEIGHT * (len(rows) - 1)
    return x, y, x + max(map(text_width, rows)) + 6, y + height


def overlap(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def overlaps(canvas: Canvas) -> list[tuple[str, str]]:
    """Pairs of boxes of one canvas (not its subpatches) that overlap."""
    rects = [(box, box_rect(box)) for box in canvas.boxes]
    return [
        (a.text, b.text)
        for i, (a, ra) in enumerate(rects)
        for b, rb in rects[i + 1 :]
        if overlap(ra, rb)
    ]
