"""Each tab of the web demo shows only what it uses (#282): the rule, and its wiring on
the built page's configuration (no browser)."""

from typing import Any

import pytest

from mpc_iml.webdemo import __main__ as webdemo_main
from mpc_iml.webdemo.app import EXAMPLES, SHOWN_BY_TAB, to_table, visible

TABS = ["step grid", "recording", "variations", "grooves", "band"]


def test_the_rule_gives_the_table_for_the_five_tabs() -> None:
    assert list(SHOWN_BY_TAB) == TABS
    assert visible("step grid") == (True, True)
    assert visible("recording") == (True, True)
    assert visible("variations") == (True, False)
    assert visible("grooves") == (False, False)
    assert visible("band") == (False, False)
    with pytest.raises(KeyError):
        visible("nothing")


class Page:
    """The built page's blocks, layout and event handlers."""

    def __init__(self, page: Any) -> None:
        self.page = page
        self.config = page.config
        self.blocks = page.blocks

    def ids(self, kind: str, label: str) -> list[int]:
        return [
            i
            for i, b in self.blocks.items()
            if type(b).__name__ == kind and getattr(b, "label", None) == label
        ]

    def one(self, kind: str, label: str) -> int:
        found = self.ids(kind, label)
        assert len(found) == 1, (kind, label, found)
        return found[0]

    def inside(self, child: int, ancestor: int) -> bool:
        def walk(node: dict[str, Any], under: bool) -> bool:
            under = under or node["id"] == ancestor
            if node["id"] == child:
                return under
            return any(walk(c, under) for c in node.get("children", []))

        return walk(self.config["layout"], False)

    def selects(self) -> dict[str, tuple[list[int], Any]]:
        """For each tab's name, the outputs and the handler of its selection."""
        found = {}
        for index, dependency in enumerate(self.config["dependencies"]):
            for target, event in dependency["targets"]:
                if event == "select" and type(self.blocks[target]).__name__ == "Tab":
                    label = self.blocks[target].label
                    found[label] = (dependency["outputs"], self.page.fns[index].fn)
        return found

    def handler(self, button: str) -> tuple[list[int], Any]:
        """The inputs and the handler of the button `button`."""
        found = [
            i
            for i, b in self.blocks.items()
            if type(b).__name__ == "Button" and getattr(b, "value", None) == button
        ]
        assert len(found) == 1, button
        target = found[0]
        for index, dependency in enumerate(self.config["dependencies"]):
            if (target, "click") in [tuple(t) for t in dependency["targets"]]:
                return dependency["inputs"], self.page.fns[index].fn
        raise AssertionError(button)


def built(share: bool = False) -> Page:
    if not webdemo_main.gradio_installed():
        pytest.skip("needs the demo extra")
    from mpc_iml.webdemo.app import build

    return Page(build(share=share))


def boxes(page: Page) -> tuple[int, int]:
    """The ids of the settings' box and the outputs' box: what selecting `step grid`
    shows, checked to hold the tempo and the piano roll."""
    settings, outputs = page.selects()["step grid"][0]
    assert page.inside(page.one("Slider", "tempo"), settings)
    assert page.inside(page.one("Image", "piano roll"), outputs)
    return settings, outputs


def test_the_settings_and_the_outputs_are_each_in_a_box_every_tab_shows_or_hides() -> None:
    page = built()
    settings, outputs = boxes(page)
    assert type(page.blocks[settings]).__name__ == "Column"
    assert type(page.blocks[outputs]).__name__ == "Column"
    for kind, label in [
        ("Slider", "fade-bars"),
        ("Dropdown", "progression"),
        ("Radio", "melody mode"),
        ("Radio", "learn"),
        ("Radio", "follow-by"),
        ("Textbox", "nods (learn nod): bars nodded to, 8 16"),
    ]:
        assert page.inside(page.one(kind, label), settings), label
    intro = [
        i
        for i, b in page.blocks.items()
        if type(b).__name__ == "Markdown" and "press **Play**" in str(getattr(b, "value", ""))
    ]
    assert len(intro) == 1 and page.inside(intro[0], settings)
    title = [
        i
        for i, b in page.blocks.items()
        if type(b).__name__ == "Markdown" and "# ensemble without hardware" in str(b.value)
    ]
    assert len(title) == 1 and not page.inside(title[0], settings)
    for kind, label in [
        ("File", "MIDI file"),
        ("Textbox", "learning"),
    ]:
        assert page.inside(page.one(kind, label), outputs), label
    band = [i for i in page.ids("Audio", "the band") if page.inside(i, outputs)]
    assert len(band) == 1
    selects = page.selects()
    assert sorted(selects) == sorted(TABS)
    for name, (targets, handler) in selects.items():
        assert targets == [settings, outputs], name
        shown = handler()
        assert [dict(u) for u in shown] == [
            {"__type__": "update", "visible": v} for v in visible(name)
        ], name


def test_under_share_the_three_tabs_are_wired() -> None:
    page = built(share=True)
    assert sorted(page.selects()) == ["recording", "step grid", "variations"]


def test_the_settings_keep_their_values_while_hidden() -> None:
    """Selecting a tab only changes the visibility of the two boxes, so a value set
    before going to `band` is the one Play reads after coming back."""
    page = built()
    settings, outputs = boxes(page)
    selects = page.selects()
    inputs, on_play = page.handler("Play")
    tempo = page.one("Slider", "tempo")
    assert inputs[1] == tempo
    values = [page.blocks[i].value for i in inputs]
    values[0] = to_table(EXAMPLES["busy"])
    values[1] = 120
    for name in ("band", "step grid"):
        targets, handler = selects[name]
        assert tempo not in targets and set(targets) == {settings, outputs}
        handler()
    fast = on_play(*values)
    values[1] = 60
    slow = on_play(*values)
    assert len(fast[0][1]) * 2 == pytest.approx(len(slow[0][1]), rel=0.05)
