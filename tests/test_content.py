"""Named outputs, modules, kits and the `mpc_iml.content` entry points (ADR 0007, #99).

The external content lives in `tests/plugins/` as an installed distribution, like
the external preset in `tests/test_presets.py`.
"""

import copy
import dataclasses
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mpc_iml.content import (
    NONE,
    Content,
    ContentError,
    Library,
    PadAssignment,
    UnknownContentError,
    load_library,
    parse_kit,
    parse_module,
)
from mpc_iml.demo import PRESET as DEMO
from mpc_iml.presets import Preset, PresetError
from mpc_iml.pressure import CONTENT, OUTPUT_NAMES
from mpc_iml.pressure import PRESET as PRESSURE

PLUGINS = Path(__file__).parent / "plugins"

FIRST_OFFSETS = {
    "brighten": {"brightness": 0.6},
    "darken": {"brightness": -0.6},
    "bite": {"brightness": 0.5, "resonance": 0.5},
    "push": {"drive": 0.5, "level": 0.3},
    "distance": {"space": 0.6, "brightness": -0.2},
    "wobble": {"motion": 0.7},
    "bend": {"pitch": 0.4},
    "grain": {"texture": 0.6, "drive": 0.2},
    "swell": {"level": 0.4, "space": 0.5},
}

KIT_PADS = {
    "filter-play": ["brighten"] * 4
    + ["bite"] * 4
    + ["darken"] * 4
    + ["wobble", "wobble", "bend", NONE],
    "texture-lab": ["grain"] * 4 + ["push"] * 4 + ["wobble"] * 4 + ["bite", "bite", "darken", NONE],
    "ambient-space": ["swell"] * 4
    + ["distance"] * 4
    + ["darken"] * 4
    + ["wobble", "wobble", "bend", NONE],
}

MODULE: dict[str, Any] = {
    "format": "mpc-iml-module",
    "format_version": 1,
    "name": "lift",
    "preset": "pressure",
    "outputs": {"level": [[0, 0], [1, 0.5]]},
}

KIT: dict[str, Any] = {
    "format": "mpc-iml-kit",
    "format_version": 1,
    "name": "flat",
    "preset": "pressure",
    "rest": dict.fromkeys(OUTPUT_NAMES, 0.5),
    "pads": ["none"] * 16,
}


@pytest.fixture(autouse=True)
def _forget_plugin_modules() -> Iterator[None]:
    yield
    for name in ("mpc_iml_example_content", "dup_content", "bad_content"):
        sys.modules.pop(name, None)


@pytest.fixture
def external(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the example content package from `tests/plugins/`."""
    monkeypatch.syspath_prepend(str(PLUGINS))


def with_changes(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(base)
    data.update(changes)
    return data


def install(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    name: str,
    files: dict[str, Any],
    entry: str = "CONTENT",
    code: str = "",
) -> None:
    """Install a package `name` whose content folder holds `files` (path: JSON)."""
    package = root / name
    package.mkdir()
    (package / "__init__.py").write_text(
        code or f"from mpc_iml.content import Content\nCONTENT = Content('pressure', '{name}')\n"
    )
    for path, data in files.items():
        target = package / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data if isinstance(data, str) else json.dumps(data))
    info = root / f"{name}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text(f"[mpc_iml.content]\n{name} = {name}:{entry}\n")
    monkeypatch.syspath_prepend(str(root))


# Named outputs


def test_pressure_declares_its_output_names_in_cc_order() -> None:
    assert PRESSURE.output_names == (
        "brightness",
        "resonance",
        "drive",
        "space",
        "motion",
        "pitch",
        "texture",
        "level",
    )


@pytest.mark.parametrize(
    ("targets", "names", "message"),
    [
        (None, ("a",), "1 output names for None targets"),
        (2, ("a",), "1 output names for 2 targets"),
        (2, ("a", "B"), "lower case"),
        (2, ("a", "a b"), "lower case"),
        (2, ("a", "a"), "unique"),
    ],
)
def test_output_names_are_validated(
    targets: int | None, names: tuple[str, ...], message: str
) -> None:
    with pytest.raises(PresetError, match=message):
        Preset(name="named", version="1", targets=targets, output_names=names)


def test_output_names_are_optional() -> None:
    assert Preset(name="plain", version="1", targets=2).output_names is None


# Built-in content


def test_pressure_registers_its_content_as_an_entry_point() -> None:
    assert CONTENT == Content(preset="pressure", root="mpc_iml")


def test_built_in_modules_have_the_adr_first_offsets() -> None:
    library = load_library(PRESSURE)
    assert library.module_ids() == [NONE, *sorted(FIRST_OFFSETS)]
    for name, offsets in FIRST_OFFSETS.items():
        module = library.module(name)
        assert module.title == name.capitalize()
        assert set(module.outputs) == set(offsets)
        for output, offset in offsets.items():
            assert module.outputs[output] == ((0.0, 0.0), (1.0, offset))
    assert library.module(NONE).outputs == {}


def test_built_in_kits_have_the_adr_pads_and_filter_play_is_the_default() -> None:
    library = load_library(PRESSURE)
    assert library.kit_names() == ["filter-play", "ambient-space", "texture-lab"]
    for name, pads in KIT_PADS.items():
        kit = library.kit(name)
        assert [p.module for p in kit.pads] == pads
        assert all(p.amount == 1.0 for p in kit.pads)
        assert set(kit.rest) == set(OUTPUT_NAMES)
        assert kit.combine == "add"
        assert kit.default == (name == "filter-play")


def test_a_preset_without_output_names_lists_no_modules_or_kits() -> None:
    library = load_library(DEMO)
    assert library.module_ids() == []
    assert library.kit_names() == []


def test_unknown_kit_and_module_raise_unknown_content_error() -> None:
    library = load_library(PRESSURE)
    with pytest.raises(UnknownContentError, match="unknown kit 'nope'"):
        library.kit("nope")
    with pytest.raises(UnknownContentError, match="unknown module 'nope'"):
        library.module("nope")


# Module curves


def test_module_offset_interpolates_and_holds_after_the_last_point() -> None:
    data = with_changes(MODULE, outputs={"level": [[0, 0], [0.5, 0.8], [0.8, 0.2]]})
    module = parse_module(data, PRESSURE)
    assert module.offset("level", 0.0) == 0.0
    assert module.offset("level", 0.25) == pytest.approx(0.4)
    assert module.offset("level", 0.65) == pytest.approx(0.5)
    assert module.offset("level", 1.0) == pytest.approx(0.2)
    assert module.offset("space", 1.0) == 0.0
    assert module.title == "Lift"


# Validation


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"format": "other"}, "not an mpc-iml-module file"),
        ({"format_version": 2}, "format_version 1"),
        ({"name": "Lift"}, "name must be lower case"),
        ({"name": NONE}, "built in"),
        ({"preset": "demo"}, "preset is 'demo'"),
        ({"outputs": {}}, "outputs must map"),
        ({"outputs": {"volume": [[0, 0], [1, 1]]}}, "unknown output 'volume'"),
        ({"outputs": {"level": [[0.1, 0], [1, 1]]}}, r"first point must be \[0, 0\]"),
        ({"outputs": {"level": [[0, 0.1], [1, 1]]}}, r"first point must be \[0, 0\]"),
        ({"outputs": {"level": [[0, 0], [0.5, 1], [0.5, 0]]}}, "strictly increasing"),
        ({"outputs": {"level": [[0, 0], [1.5, 1]]}}, "pressure must be 0-1"),
        ({"outputs": {"level": [[0, 0], [1, -1.5]]}}, "offset must be -1-1"),
        ({"outputs": {"level": [[0, 0], [1]]}}, "a point is"),
        ({"outputs": {"level": [[0, 0], [1, True]]}}, "must be a number"),
        ({"title": 3}, "must be strings"),
    ],
)
def test_invalid_modules_are_rejected(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ContentError, match=message):
        parse_module(with_changes(MODULE, **changes), PRESSURE, "lift.json")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"format": "mpc-iml-module"}, "not an mpc-iml-kit file"),
        ({"rest": dict.fromkeys(OUTPUT_NAMES[:-1], 0.5)}, "rest must give a value"),
        ({"rest": {**dict.fromkeys(OUTPUT_NAMES, 0.5), "x": 0}}, "rest must give a value"),
        ({"rest": {**dict.fromkeys(OUTPUT_NAMES, 0.5), "level": 1.2}}, "rest level must be 0-1"),
        ({"pads": ["none"] * 15}, "exactly 16"),
        ({"pads": ["none"] * 15 + [{"module": "bite", "amount": 2}]}, "pad 16: amount"),
        ({"pads": ["none"] * 15 + [{"module": "bite", "gain": 1}]}, "only module and amount"),
        ({"pads": ["none"] * 15 + [3]}, "pad 16: expected a module id"),
        ({"combine": "pairs"}, "combine must be"),
        ({"default": "yes"}, "default must be"),
    ],
)
def test_invalid_kits_are_rejected(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ContentError, match=message):
        parse_kit(with_changes(KIT, **changes), PRESSURE, "flat.json")


def test_kit_pad_entries_take_an_amount() -> None:
    pads = [{"module": "bite", "amount": 0.25}] + ["none"] * 15
    kit = parse_kit(with_changes(KIT, pads=pads), PRESSURE)
    assert kit.pads[0] == PadAssignment("bite", 0.25)
    assert kit.title == "Flat" and kit.combine == "add" and not kit.default


def test_content_needs_output_names() -> None:
    with pytest.raises(ContentError, match="has no output_names"):
        parse_module(MODULE, DEMO)


def test_amount_outside_0_1_is_rejected() -> None:
    with pytest.raises(ContentError, match="amount must be 0-1"):
        PadAssignment("bite", 1.5)


# External content


@pytest.mark.usefixtures("external")
def test_external_content_adds_a_module_and_a_kit_to_pressure() -> None:
    library = load_library(PRESSURE)
    assert "shimmer" in library.module_ids()
    assert library.kit_names() == ["filter-play", "ambient-space", "shimmer-pads", "texture-lab"]
    kit = library.kit("shimmer-pads")
    assert kit.combine == "none"
    assert kit.pads[:2] == (PadAssignment("shimmer"), PadAssignment("bite", 0.5))
    assert library.module("shimmer").title == "Shimmer"


@pytest.mark.usefixtures("external")
def test_content_for_a_preset_that_is_not_installed_is_ignored() -> None:
    """The example package's `not-installed` kit is not even valid JSON."""
    assert isinstance(load_library(PRESSURE), Library)


def test_two_modules_with_the_same_name_are_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install(
        monkeypatch,
        tmp_path,
        "dup_content",
        {"modules/pressure/bite.json": {**MODULE, "name": "bite"}},
    )
    with pytest.raises(ContentError, match="two modules named 'bite'"):
        load_library(PRESSURE)


def test_two_kits_with_the_same_name_are_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    kit = {**KIT, "name": "filter-play"}
    install(monkeypatch, tmp_path, "dup_content", {"kits/pressure/filter-play.json": kit})
    with pytest.raises(ContentError, match="two kits named 'filter-play'"):
        load_library(PRESSURE)


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"kits/pressure/flat.json": {**KIT, "default": True}}, "more than one default kit"),
        ({"kits/pressure/flat.json": {**KIT, "pads": ["nope"] * 16}}, "unknown module 'nope'"),
        ({"kits/pressure/other.json": KIT}, "file name must equal the name"),
        ({"modules/pressure/lift.json": "{ not json"}, "cannot read"),
        ({"modules/pressure/lift.json": {**MODULE, "preset": "demo"}}, "preset is 'demo'"),
    ],
)
def test_invalid_installed_content_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, files: dict[str, Any], message: str
) -> None:
    install(monkeypatch, tmp_path, "bad_content", files)
    with pytest.raises(ContentError, match=message):
        load_library(PRESSURE)


def test_an_entry_that_is_not_content_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install(monkeypatch, tmp_path, "bad_content", {}, code="CONTENT = 42\n")
    with pytest.raises(ContentError, match="is not a Content: int"):
        load_library(PRESSURE)


def test_an_entry_that_fails_to_load_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install(monkeypatch, tmp_path, "bad_content", {}, entry="MISSING")
    with pytest.raises(ContentError, match="cannot load entry point 'bad_content'"):
        load_library(PRESSURE)


def test_content_for_another_preset_is_not_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code = "from mpc_iml.content import Content\nCONTENT = Content('other', 'bad_content')\n"
    install(monkeypatch, tmp_path, "bad_content", {"kits/other/x.json": "{"}, code=code)
    assert load_library(PRESSURE).kit_names() == ["filter-play", "ambient-space", "texture-lab"]
    other = dataclasses.replace(PRESSURE, name="other")
    with pytest.raises(ContentError, match="cannot read"):
        load_library(other)
