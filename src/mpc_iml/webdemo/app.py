"""The Gradio page of the web demo (#166): a step grid or a recording in, the band out.

A teammate places kick, snare and hat hits on a 16-step grid, or uploads a
recording made with `record --clock`, picks the settings, and hears and reads what
`ensemble` plays in answer, bar by bar, with a piano roll and a MIDI file. The page
only gathers input and shows output: `sim.simulate` and `sim.replay` run the real
rules, `synth.render` makes the audio, `roll.draw` the piano roll and
`midifile.write` the MIDI file.

Gradio is imported only in `build`, so the functions the page calls (`resize`,
`play`, `upload`) work, and are tested, without the `demo` extra.

Gradio sends usage analytics to its servers unless `GRADIO_ANALYTICS_ENABLED` is
`"False"`. `build` turns them off unless the environment already sets the variable,
so the demo sends nothing unless a person asks (#172).
"""

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple

import numpy as np
import numpy.typing as npt

from mpc_iml.clock import tag_recording
from mpc_iml.ensemble import MELODY_MODES, PROGRESSIONS
from mpc_iml.grid import COLUMNS, format_hit
from mpc_iml.loops import load_loops
from mpc_iml.melody import NO_DRUMS, ORNAMENTS, BarPlan
from mpc_iml.recording import read_recording
from mpc_iml.webdemo import midifile, roll
from mpc_iml.webdemo.sim import (
    DRUMS,
    STEPS,
    TEMPO_RANGE,
    BarRow,
    Grid,
    Settings,
    Song,
    replay,
    simulate,
)
from mpc_iml.webdemo.synth import RATE, render

if TYPE_CHECKING:
    import gradio as gr

__all__ = [
    "ANALYTICS_ENV",
    "BARS",
    "EXAMPLES",
    "HEADERS",
    "HIT_HEADERS",
    "TABLE_HEADERS",
    "Shown",
    "Uploaded",
    "analytics_default_off",
    "build",
    "play",
    "resize",
    "show",
    "to_table",
    "upload",
]

ANALYTICS_ENV = "GRADIO_ANALYTICS_ENABLED"
"""The environment variable that turns Gradio's usage analytics on or off."""


def analytics_default_off() -> bool:
    """Set `GRADIO_ANALYTICS_ENABLED` to `"False"` unless it is already set, and
    return whether analytics are on (as Gradio reads it: only `"True"` is on)."""
    os.environ.setdefault(ANALYTICS_ENV, "False")
    return os.environ[ANALYTICS_ENV] == "True"


BARS = (4, 8)
"""The fewest and most bars of the grid on the page."""

HEADERS = ["drum", *(str(s + 1) for s in range(STEPS))]
"""The grid's columns: the row's bar and drum, then one column per step."""

TABLE_HEADERS = [
    "bar",
    "kicks",
    "hats",
    "hits",
    "velocity",
    "next chord",
    "bass",
    "bass vel",
    "melody",
    "melody vel",
    "brightness",
    "surprise",
]
"""The bar table: the drums of a bar (as the rules read them), then what the band
plays in the bar after it."""

Table = list[list[str | int]]

HIT_HEADERS = list(COLUMNS)
"""The hits of an uploaded recording, as `python -m mpc_iml.grid` prints them."""


class Shown(NamedTuple):
    """What the page shows for a song: the audio (`(RATE, samples)`), the bar table,
    the piano roll and the MIDI file's bytes."""

    audio: tuple[int, npt.NDArray[np.int16]]
    table: Table
    roll: npt.NDArray[np.uint8]
    midi: bytes


class Uploaded(NamedTuple):
    """What the page shows for a recording: the song, and each pad hit on the grid
    (`HIT_HEADERS`, all as text)."""

    shown: Shown
    hits: list[list[str]]


_DATATYPE: list[Literal["str", "number"]] = [
    "str" if i == 0 else "number" for i in range(STEPS + 1)
]

_KICKS = [100, 0, 0, 0] * 4
_BACKBEAT = [0, 0, 0, 0, 90, 0, 0, 0] * 2
_EIGHTHS = [70, 0] * 8
_BUSY = {"kick": [100, 0, 0, 100] * 4, "snare": _BACKBEAT, "hat": [70] * STEPS}

EXAMPLES: dict[str, Grid] = {
    "sparse": [{"kick": _KICKS}] * 8,
    "off-beat kicks": [{"kick": [0, 0, 100, 0] * 4, "snare": _BACKBEAT, "hat": _EIGHTHS}] * 8,
    "busy": [_BUSY] * 8,
    "drums stop": [_BUSY] * 4 + [{}] * 4,
}
"""Patterns to start from: a sparse and a busy one choose different variations, and
in the last one the band follows `no-drums` once the drums stop."""


def to_table(grid: Grid) -> Table:
    """The page's grid for `grid`: one row per bar and drum, labelled `bar 1 kick`."""
    return [
        [f"bar {b + 1} {drum}", *bar.get(drum, [0] * STEPS)]
        for b, bar in enumerate(grid)
        for drum in DRUMS
    ]


def resize(table: Sequence[Sequence[object]], bars: int) -> Table:
    """`table` with `bars` bars: extra bars are dropped, missing ones are empty."""
    grid = _grid(table)
    return to_table([*grid[:bars], *[{}] * (bars - len(grid))])


def show(song: Song) -> Shown:
    """The audio, bar table, piano roll and MIDI file of `song`."""
    audio = (RATE, render(song, song.settings.seed))
    return Shown(audio, [_table_row(r) for r in song.rows], roll.draw(song), midifile.write(song))


def play(table: Sequence[Sequence[object]], settings: Settings) -> Shown:
    """What the band plays for the page's grid `table`.

    Raises `ValueError` for a cell that is not a whole number 0-127 or for settings
    `sim.simulate` refuses.
    """
    return show(simulate(_grid(table), settings))


def upload(path: str | Path, settings: Settings) -> Uploaded:
    """What the band plays for the recording at `path` (`sim.replay`; the tempo is
    the recording's) and its pad hits placed on the grid (`tag_recording`, as the
    `grid` command shows them).

    Raises `ValueError` for a file that cannot be read, is not a recording, or that
    `sim.replay` refuses.
    """
    try:
        events = read_recording(path).events
    except OSError as e:
        raise ValueError(f"cannot read the recording: {e}") from e
    hits = [format_hit(h).split("\t") for h in tag_recording(events)]
    return Uploaded(show(replay(events, settings)), hits)


def build() -> "gr.Blocks":
    """The demo page. Needs the `demo` extra (`uv sync --extra demo`). Turns
    Gradio's analytics off unless the environment sets them (`analytics_default_off`)."""
    analytics = analytics_default_off()
    import gradio as gr

    default = Settings()
    library = load_loops()
    page = gr.Blocks(title="mpc-iml ensemble demo", analytics_enabled=analytics)
    with page:
        gr.Markdown(
            "# ensemble without hardware\n"
            "Place drum hits (0 is no hit, 1-127 the velocity) and press **Play**. "
            "The band answers each bar in the bar after it."
        )
        with gr.Row():
            bars = gr.Slider(*BARS, value=BARS[1], step=1, label="bars")
            tempo = gr.Slider(*TEMPO_RANGE, value=default.tempo, step=1, label="tempo")
            progression = gr.Dropdown(
                list(PROGRESSIONS), value=default.progression, label="progression"
            )
            bass_loop = gr.Dropdown(
                library.names("bass"), value=default.bass_loop, label="bass loop"
            )
            loop = gr.Dropdown(library.names("melody"), value=default.loop, label="melody loop")
        with gr.Row():
            mode = gr.Radio(list(MELODY_MODES), value=default.melody_mode, label="melody mode")
            no_drums = gr.Dropdown(list(NO_DRUMS), value=default.no_drums, label="no-drums")
            fade = gr.Slider(0, 32, value=default.fade_bars, step=1, label="fade-bars")
            surprise = gr.Checkbox(value=bool(default.surprise), label="surprise")
            seed = gr.Number(value=default.seed, precision=0, minimum=0, label="seed")
        with gr.Tab("step grid"):
            grid = gr.Dataframe(
                to_table(EXAMPLES["sparse"]),
                headers=HEADERS,
                datatype=_DATATYPE,
                type="array",
                interactive=True,
                label="drums",
            )
            gr.Examples(
                [[len(g), to_table(g)] for g in EXAMPLES.values()],
                [bars, grid],
                example_labels=list(EXAMPLES),
            )
            button = gr.Button("Play", variant="primary")
        with gr.Tab("recording"):
            gr.Markdown(
                "A recording made with `python -m mpc_iml.record --clock`, played at its "
                "own tempo. Pads 1 and 5 are kicks, 2 and 6 snares, 3, 4 and 7 hats."
            )
            recording = gr.File(label="recording (.jsonl)", file_types=[".jsonl"], type="filepath")
            upload_button = gr.Button("Play the recording", variant="primary")
            hits = gr.Dataframe(headers=HIT_HEADERS, type="array", interactive=False)
        audio = gr.Audio(label="the band", type="numpy", interactive=False)
        table = gr.Dataframe(headers=TABLE_HEADERS, type="array", interactive=False)
        image = gr.Image(label="piano roll", type="numpy", interactive=False)
        midi = gr.File(label="MIDI file", interactive=False)
        controls = [progression, bass_loop, loop, mode, no_drums, fade, surprise, seed]

        def settings_of(tempo: float, *values: object) -> Settings:
            progression, bass_loop, loop, mode, no_drums, fade, surprise, seed = values
            return Settings(
                tempo,
                str(progression),
                str(bass_loop),
                str(loop),
                str(mode),
                str(no_drums),
                int(float(str(fade))),
                int(bool(surprise)),
                int(float(str(seed))),
            )

        def outputs(shown: Shown) -> tuple[object, ...]:
            with tempfile.NamedTemporaryFile(
                prefix="ensemble-", suffix=".mid", delete=False
            ) as file:
                file.write(shown.midi)
            return shown.audio, shown.table, shown.roll, file.name

        def on_play(cells: Table, tempo: float, *values: object) -> tuple[object, ...]:
            try:
                return outputs(play(cells, settings_of(tempo, *values)))
            except ValueError as e:
                raise gr.Error(str(e)) from e

        def on_upload(path: str | None, *values: object) -> tuple[object, ...]:
            if path is None:
                raise gr.Error("choose a recording first")
            try:
                shown, rows = upload(path, settings_of(default.tempo, *values))
            except ValueError as e:
                raise gr.Error(str(e)) from e
            return (*outputs(shown), rows)

        bars.change(lambda cells, n: resize(cells, int(n)), [grid, bars], grid)
        results = [audio, table, image, midi]
        button.click(on_play, [grid, tempo, *controls], results)
        upload_button.click(on_upload, [recording, *controls], [*results, hits])
    return page


def _grid(table: Sequence[Sequence[object]]) -> list[dict[str, list[int]]]:
    """The `sim.Grid` of the page's grid: rows of a drum label and `STEPS` cells, the
    drums of each bar in `DRUMS` order; an empty cell is no hit."""
    if len(table) % len(DRUMS):
        raise ValueError(f"the grid must have {len(DRUMS)} rows per bar, got {len(table)} rows")
    grid: list[dict[str, list[int]]] = []
    for i, row in enumerate(table):
        if i % len(DRUMS) == 0:
            grid.append({})
        drum = DRUMS[i % len(DRUMS)]
        cells = list(row[1:])
        if len(cells) != STEPS:
            raise ValueError(f"{row[0]}: expected {STEPS} steps, got {len(cells)}")
        grid[-1][drum] = [_velocity(row[0], c) for c in cells]
    return grid


def _velocity(label: object, cell: object) -> int:
    if cell is None or cell == "":
        return 0
    try:
        value = float(str(cell))
    except ValueError:
        raise ValueError(f"{label}: {cell!r} is not a number") from None
    if not value.is_integer() or not 0 <= value <= 127:
        raise ValueError(f"{label}: velocity must be a whole number 0-127, got {cell}")
    return int(value)


def _table_row(row: BarRow) -> list[str | int]:
    return [
        f"{row.bar + 1} → {row.bar + 2}",
        _steps(row.kicks),
        _steps(row.hats),
        row.hits,
        "-" if row.velocity is None else f"{row.velocity:.0f}",
        row.chord,
        _plan(row.bass, row.bass_rule),
        _plan_velocity(row.bass),
        _plan(row.melody, row.melody_rule),
        _plan_velocity(row.melody),
        "-" if row.melody is None or row.melody.cc is None else row.melody.cc,
        row.surprise or "-",
    ]


def _steps(steps: Sequence[int]) -> str:
    """Steps counted from 1, as on the grid."""
    return " ".join(str(s + 1) for s in steps) or "-"


def _plan(plan: BarPlan | None, rule: str) -> str:
    """For example `busy + ornaments`, `open (lead)` or `silent (hold)`."""
    if plan is None:
        return "off"
    if plan.variation is None:
        text = "silent"
    elif plan.skeleton:
        text = f"{plan.variation} level 1"
    else:
        text = plan.variation + (" + ornaments" if plan.level >= ORNAMENTS else "")
    return text if rule == "drums" else f"{text} ({rule})"


def _plan_velocity(plan: BarPlan | None) -> str | int:
    return "-" if plan is None or plan.variation is None else plan.velocity
