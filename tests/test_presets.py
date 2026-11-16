"""Preset plugin interface (#63): discovery, errors, outputs and an external preset.

The external preset lives in `tests/plugins/` as an installed distribution (a
package plus its `*.dist-info` with `entry_points.txt`); putting that directory on
`sys.path` is all it takes to install it, with no change to the toolkit.
"""

import dataclasses
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from mpc_iml.demo import CLASSES, PRESET, played_features
from mpc_iml.examples import ExampleSet
from mpc_iml.presets import (
    MidiCcOutput,
    OscOutput,
    Preset,
    PresetError,
    available_presets,
    get_preset,
    scale_to_cc,
)
from mpc_iml.sources import ReplaySource

TESTS = Path(__file__).parent
PLUGINS = TESTS / "plugins"
REGRESSION = TESTS / "data" / "regression.jsonl"
TWO_PADS = TESTS / "fixtures" / "recordings" / "two-pads.jsonl"
LOCALHOST = "127.0.0.1"


PLUGIN_MODULES = (
    "mpc_iml_example_preset",
    "made_preset",
    "dup_preset",
    "bad_preset",
    "broken_preset",
)


@pytest.fixture(autouse=True)
def _forget_plugin_modules() -> Iterator[None]:
    """Unload the test plugin modules, so later tests do not see them."""
    yield
    for name in PLUGIN_MODULES:
        sys.modules.pop(name, None)


@pytest.fixture
def external(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the example preset package from `tests/plugins/`."""
    monkeypatch.syspath_prepend(str(PLUGINS))


def install(
    monkeypatch: pytest.MonkeyPatch, root: Path, name: str, entry_points: str, code: str
) -> None:
    """Install a one-module distribution `name` under `root` with the given entry points."""
    (root / f"{name}.py").write_text(code)
    info = root / f"{name}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text(f"[mpc_iml.presets]\n{entry_points}\n")
    monkeypatch.syspath_prepend(str(root))


def test_demo_is_registered_as_a_built_in_preset() -> None:
    preset = available_presets()["demo"]
    assert preset is PRESET
    assert preset.features is played_features
    assert preset.classes == CLASSES
    assert preset.patch_path() is None


@pytest.mark.usefixtures("external")
def test_external_preset_is_discovered_next_to_the_built_in_one() -> None:
    presets = available_presets()
    assert {"demo", "example-pressure"} <= set(presets)
    preset = get_preset("example-pressure")
    assert preset.version == "0.1.0"
    patch = preset.patch_path()
    assert patch is not None and patch.read_text().startswith("#N canvas")


@pytest.mark.usefixtures("external")
def test_external_preset_trains_and_runs_on_a_recorded_fixture() -> None:
    received: list[tuple[str, tuple[object, ...]]] = []
    dispatcher = Dispatcher()
    dispatcher.set_default_handler(lambda address, *args: received.append((address, args)))
    server = BlockingOSCUDPServer((LOCALHOST, 0), dispatcher)
    server.timeout = 0.3
    preset = get_preset("example-pressure")
    declared = preset.outputs[0]
    assert isinstance(declared, OscOutput)
    port = server.server_address[1]
    local = dataclasses.replace(preset, outputs=(dataclasses.replace(declared, port=port),))
    loop = local.build_loop()
    try:
        loop.examples.add_recording(REGRESSION)
        loop.train()
        sent = loop.run(ReplaySource(TWO_PADS), duration=0.5)
        while True:
            before = len(received)
            server.handle_request()
            if len(received) == before:
                break
    finally:
        server.server_close()
        if loop.outputs is not None:
            loop.outputs.close()
    assert sent == 50
    assert len(received) == sent
    assert {address for address, _ in received} == {declared.address}
    assert all(len(args) == 2 for _, args in received)
    targets = {args for _, args in received}
    assert targets <= {(0.0, 1.0), (1.0, 0.0)}


def test_entry_point_returning_a_preset_from_a_callable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code = "from mpc_iml.presets import Preset\ndef make(): return Preset('made', '1')\n"
    install(monkeypatch, tmp_path, "made_preset", "made = made_preset:make", code)
    assert get_preset("made").name == "made"


def test_duplicate_names_are_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code = "from mpc_iml.presets import Preset\nPRESET = Preset('demo', '9')\n"
    install(monkeypatch, tmp_path, "dup_preset", "demo = dup_preset:PRESET", code)
    with pytest.raises(PresetError, match="two presets named 'demo'.*dup_preset"):
        available_presets()


def test_entry_point_that_is_not_a_preset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install(monkeypatch, tmp_path, "bad_preset", "bad = bad_preset:VALUE", "VALUE = 42\n")
    with pytest.raises(PresetError, match="'bad'.*bad_preset.*not a Preset: int"):
        available_presets()


def test_entry_point_that_fails_to_import(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code = "raise ImportError('missing dependency')\n"
    install(monkeypatch, tmp_path, "broken_preset", "broken = broken_preset:PRESET", code)
    with pytest.raises(PresetError, match="cannot load.*broken_preset.*missing dependency"):
        available_presets()


def test_unknown_name() -> None:
    with pytest.raises(PresetError, match="unknown preset 'nope'; available: .*demo"):
        get_preset("nope")


@pytest.mark.parametrize("name", ["", "Demo", "my_preset", "-x", "a--b", "a b"])
def test_invalid_names(name: str) -> None:
    with pytest.raises(PresetError, match="preset name"):
        Preset(name, "1")


def test_patch_needs_a_package() -> None:
    with pytest.raises(PresetError, match="<package>:<path>"):
        Preset("x", "1", patch="patch.pd")


def test_defaults_match_the_existing_extension_points() -> None:
    preset = Preset("plain", "1")
    examples = preset.example_set()
    assert isinstance(examples, ExampleSet)
    assert preset.outputs == (OscOutput(),)
    assert preset.controls == {}
    loop = preset.build_loop()
    try:
        assert not loop.backend_on
        assert loop.outputs is not None and loop.outputs.address == "/wek/outputs"
    finally:
        loop.outputs.close()


def test_no_osc_output_means_no_outputs_sender() -> None:
    preset = Preset("cc-only", "1", outputs=(MidiCcOutput(controllers=(1,)),))
    assert preset.build_loop().outputs is None


@pytest.mark.parametrize(
    ("value", "low", "high", "cc"),
    [(0.0, 0.0, 1.0, 0), (1.0, 0.0, 1.0, 127), (0.5, 0.0, 1.0, 64), (-3.0, 0.0, 1.0, 0)],
)
def test_scale_to_cc(value: float, low: float, high: float, cc: int) -> None:
    assert scale_to_cc(value, low, high) == cc


def test_scale_to_cc_clamps_and_supports_other_ranges() -> None:
    assert scale_to_cc(9.0) == 127
    assert scale_to_cc(5.0, 0.0, 10.0) == 64
    with pytest.raises(ValueError, match="range"):
        scale_to_cc(1.0, 2.0, 2.0)


def test_midi_cc_messages() -> None:
    output = MidiCcOutput(controllers=(20, 21), channel=2, ranges=((0.0, 1.0), (-1.0, 1.0)))
    assert output.messages([1.0, 0.0]) == [bytes([0xB1, 20, 127]), bytes([0xB1, 21, 64])]
    with pytest.raises(ValueError, match="expected 2 values"):
        output.messages([1.0])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"controllers": ()},
        {"controllers": (128,)},
        {"controllers": (1,), "channel": 0},
        {"controllers": (1, 2), "ranges": ((0.0, 1.0),)},
    ],
)
def test_midi_cc_output_validation(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MidiCcOutput(**kwargs)  # type: ignore[arg-type]


def test_external_package_is_not_installed_by_default() -> None:
    assert "example-pressure" not in available_presets()
