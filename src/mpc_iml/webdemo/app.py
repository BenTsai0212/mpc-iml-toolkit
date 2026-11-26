"""The Gradio page of the web demo (#166): a step grid or a recording in, the band out.

A teammate places kick, snare and hat hits on a 16-step grid, or uploads a
recording made with `record --clock`, picks the settings, and hears and reads what
`ensemble` plays in answer, bar by bar, with a piano roll and a MIDI file. The page
only gathers input and shows output: `sim.simulate` and `sim.replay` run the real
rules, `synth.render` makes the audio, `roll.draw` the piano roll and
`midifile.write` the MIDI file.

The `learn` setting (#196) shows learning over a scripted session: with `likes` the
bars whose answer is liked, with `demo` the wanted variations and the presses of
pads 16 and 15 (`parse_likes`, `parse_wants`, `parse_presses`, #215), with `nod`
the bars nodded to (`parse_nods`, #250); the table gains the contexts and where each
choice came from, and the page shows the learning log and what was learned. The
`follow-by` setting (#250) makes the band follow each bar or the groove.

The `variations` tab (#221) plays the variation generator's candidates next to their
source loop (`webdemo.variations.listen`), each with its audio and piano roll, over
a plain boom-bap pattern that can be turned off, and a provenance table; in blind
mode the clips are shuffled under letters until **Reveal**. It only reads loop files.

The `grooves` tab (`webdemo.groovetab`, #249) sorts the musician's own grooves into
named groups and saves them in the data folder; it is left out under `--share`.

The `band` tab (`webdemo.bandtab`, #280) plays a built-in band with a sound set of the
`--sounds` folder and sets the engine to the band; it is left out under `--share` too.

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
from mpc_iml.ensemble import FOLLOW_BY, LEARN_MODES, MELODY_SETTINGS
from mpc_iml.grid import COLUMNS, format_hit
from mpc_iml.launch import DEFAULT_DATA
from mpc_iml.loops import VARIATIONS, load_loops
from mpc_iml.melody import NO_DRUMS, ORNAMENTS, BarPlan
from mpc_iml.recording import read_recording
from mpc_iml.rhythm import Taken
from mpc_iml.vargen import CORPORA, DEFAULT_CORPUS, DEFAULT_NOVELTY
from mpc_iml.webdemo import bandtab, groovetab, midifile, roll, variations
from mpc_iml.webdemo.sim import (
    DRUMS,
    STEPS,
    TEMPO_RANGE,
    BarRow,
    Grid,
    Settings,
    Song,
    progressions,
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
    "parse_likes",
    "parse_nods",
    "parse_presses",
    "parse_wants",
    "play",
    "play_variations",
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
    "transform",
    "took",
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
    "context",
    "chose",
]
"""The bar table: after `bar`, `transform` is the bass's and the melody's rhythm
transformation in the bar after it, as the reply `transform` gives them, and `took`
the drums each moved line took and the steps its notes moved to (next to `bar` so
they show without scrolling, #189); then the drums of a bar (as the rules read them)
and what the band plays in the bar after it; `context` is the bass's and the melody's
learning context of the bar and `chose` where their choice came from, `liked` when
the answer was liked (#196) and `pressed` the pads pressed in it (#215)."""

Table = list[list[str | int]]

HIT_HEADERS = list(COLUMNS)
"""The hits of an uploaded recording, as `python -m mpc_iml.grid` prints them."""


class Shown(NamedTuple):
    """What the page shows for a song: the audio (`(RATE, samples)`), the bar table,
    the piano roll, the MIDI file's bytes and the learning log (`learning`)."""

    audio: tuple[int, npt.NDArray[np.int16]]
    table: Table
    roll: npt.NDArray[np.uint8]
    midi: bytes
    learning: str = ""


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
    table = [_table_row(r) for r in song.rows]
    return Shown(audio, table, roll.draw(song), midifile.write(song), learning(song))


def learning(song: Song) -> str:
    """The learning log lines, then `learned: …` (`-` for none); empty with `learn off`."""
    if song.settings.learn == "off":
        return ""
    return "\n".join([*song.learning, "learned: " + (" ".join(song.learned) or "-")])


def parse_likes(text: str) -> tuple[int, ...]:
    """`"2 3 7"`: the grid bars (from 1) whose answer is liked, as `Settings.likes`
    (from 0). Raises `ValueError` for anything but whole numbers from 1."""
    return _parse_bars(text, "likes")


def parse_nods(text: str) -> tuple[int, ...]:
    """`"8 16"`: the grid bars (from 1) nodded to, as `Settings.nods` (from 0), #250.
    Raises `ValueError` for anything but whole numbers from 1."""
    return _parse_bars(text, "nods")


def _parse_bars(text: str, name: str) -> tuple[int, ...]:
    bars: list[int] = []
    for word in text.replace(",", " ").split():
        if not word.isdigit() or int(word) < 1:
            raise ValueError(f"{name}: {word!r} is not a bar number from 1")
        bars.append(int(word) - 1)
    return tuple(sorted(set(bars)))


def parse_wants(text: str) -> tuple[tuple[int, str, str], ...]:
    """`"1 bass push, 6 bass home, 10 bass auto"`: from the answer to each grid bar
    (from 1), the part wants that variation, as `Settings.wants`. Raises
    `ValueError` for an entry that is not `<bar> <part> <want>`; `sim` checks the
    part and the want."""
    wants: list[tuple[int, str, str]] = []
    for entry in filter(None, (e.strip() for e in text.replace(";", ",").split(","))):
        words = entry.split()
        if len(words) != 3 or not words[0].isdigit() or int(words[0]) < 1:
            raise ValueError(f"wants: expected <bar> <part> <want>, got {entry!r}")
        wants.append((int(words[0]) - 1, words[1], words[2]))
    return tuple(wants)


def parse_presses(text: str) -> tuple[tuple[int, str], ...]:
    """`"3 bass, 5 bass, 9 melody"`: in the answer to each grid bar (from 1), the
    musician presses pad 16 (bass) or 15 (melody), as `Settings.presses` (#215).
    Raises `ValueError` for an entry that is not `<bar> <part>`; `sim` checks the
    part."""
    presses: list[tuple[int, str]] = []
    for entry in filter(None, (e.strip() for e in text.replace(";", ",").split(","))):
        words = entry.split()
        if len(words) != 2 or not words[0].isdigit() or int(words[0]) < 1:
            raise ValueError(f"presses: expected <bar> <part>, got {entry!r}")
        presses.append((int(words[0]) - 1, words[1]))
    return tuple(presses)


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


def play_variations(
    listing: variations.Listing,
) -> list[tuple[str, tuple[int, npt.NDArray[np.int16]], npt.NDArray[np.uint8]]]:
    """Each clip of `listing` as its label, audio (`(RATE, samples)`) and piano roll."""
    return [
        (clip.label, (RATE, render(clip.song, clip.song.settings.seed)), roll.draw(clip.song))
        for clip in listing.clips
    ]


def build(data: Path | None = None, share: bool = False, sounds: Path | None = None) -> "gr.Blocks":
    """The demo page. Needs the `demo` extra (`uv sync --extra demo`). Turns
    Gradio's analytics off unless the environment sets them (`analytics_default_off`).
    The grooves tab (`groovetab`, #249) saves in `data`, and the band tab (`bandtab`,
    #280) reads the sound sets in `sounds`; both are left out when `share` makes a
    public link."""
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
                list(progressions()), value=default.progression, label="progression"
            )
            bass_loop = gr.Dropdown(
                library.names("bass"), value=default.bass_loop, label="bass loop"
            )
            loop = gr.Dropdown(library.names("melody"), value=default.loop, label="melody loop")
        with gr.Row():
            mode = gr.Radio(list(MELODY_SETTINGS), value=default.melody_mode, label="melody mode")
            no_drums = gr.Dropdown(list(NO_DRUMS), value=default.no_drums, label="no-drums")
            fade = gr.Slider(0, 32, value=default.fade_bars, step=1, label="fade-bars")
            surprise = gr.Checkbox(value=bool(default.surprise), label="surprise")
            rhythm = gr.Radio(
                [("off", 0), ("bass", 1), ("bass and melody", 2)],
                value=default.rhythm,
                label="rhythm",
            )
            seed = gr.Number(value=default.seed, precision=0, minimum=0, label="seed")
        with gr.Row():
            learn = gr.Radio(list(LEARN_MODES), value=default.learn, label="learn")
            likes = gr.Textbox(label="likes (learn likes): bars whose answer is liked, 2 3 7")
            wants = gr.Textbox(label="wants (learn demo): 1 bass push, 6 bass home, 10 bass auto")
            presses = gr.Textbox(label="presses (learn demo): pads 16 and 15, 3 bass, 9 melody")
        with gr.Row():
            follow_by = gr.Radio(list(FOLLOW_BY), value=default.follow_by, label="follow-by")
            nods = gr.Textbox(label="nods (learn nod): bars nodded to, 8 16")
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
        with gr.Tab("variations"):
            gr.Markdown(
                "New variations grown from a line (`python -m mpc_iml.vargen`), played next "
                "to their source over the progression and tempo above. Nothing is written."
            )
            with gr.Row():
                var_loop = gr.Dropdown(
                    library.names("bass") + library.names("melody"),
                    value=default.bass_loop,
                    allow_custom_value=True,
                    label="loop: a name or a loop file (.json)",
                )
                var_file = gr.File(label="or upload a loop file", file_types=[".json"])
                var_data = gr.Textbox(value=DEFAULT_DATA, label="data folder (your loops)")
            with gr.Row():
                var_variation = gr.Dropdown(
                    sorted({v for names in VARIATIONS.values() for v in names}),
                    value="home",
                    label="variation",
                )
                var_novelty = gr.Slider(0, 1, value=DEFAULT_NOVELTY, step=0.05, label="novelty")
                var_corpus = gr.Radio(list(CORPORA), value=DEFAULT_CORPUS, label="corpus")
                var_count = gr.Slider(1, variations.MAX_COUNT, value=4, step=1, label="candidates")
                var_seed = gr.Number(value=0, precision=0, minimum=0, label="seed")
                var_drums = gr.Checkbox(value=True, label="drums")
                var_blind = gr.Checkbox(value=False, label="blind")
            with gr.Row():
                var_button = gr.Button("Generate", variant="primary")
                reveal = gr.Button("Reveal")
            slots = []
            for _ in range(variations.MAX_COUNT + 1):
                with gr.Column(visible=False) as column:
                    slots.append(
                        (
                            column,
                            gr.Audio(type="numpy", interactive=False),
                            gr.Image(type="numpy", interactive=False, show_label=False),
                        )
                    )
            provenance = gr.Dataframe(
                headers=variations.PROVENANCE_HEADERS, type="array", interactive=False
            )
            listed = gr.State(None)
        if not share:
            groovetab.tab(gr, data)
            bandtab.tab(gr, sounds)
        audio = gr.Audio(label="the band", type="numpy", interactive=False)
        table = gr.Dataframe(headers=TABLE_HEADERS, type="array", interactive=False)
        image = gr.Image(label="piano roll", type="numpy", interactive=False)
        midi = gr.File(label="MIDI file", interactive=False)
        log = gr.Textbox(label="learning", lines=4, interactive=False)
        controls = [
            progression,
            bass_loop,
            loop,
            mode,
            no_drums,
            fade,
            surprise,
            rhythm,
            seed,
            learn,
            likes,
            wants,
            presses,
            follow_by,
            nods,
        ]

        def settings_of(tempo: float, *values: object) -> Settings:
            progression, bass_loop, loop, mode, no_drums, fade, surprise, rhythm, seed = values[:9]
            learn, likes, wants, presses, follow_by, nods = (str(v or "") for v in values[9:])
            return Settings(
                tempo,
                str(progression),
                str(bass_loop),
                str(loop),
                str(mode),
                str(no_drums),
                int(float(str(fade))),
                int(bool(surprise)),
                int(float(str(rhythm))),
                int(float(str(seed))),
                learn,
                parse_likes(likes) if learn == "likes" else (),
                parse_wants(wants) if learn == "demo" else (),
                presses=parse_presses(presses) if learn == "demo" else (),
                follow_by=follow_by or default.follow_by,
                nods=parse_nods(nods) if learn == "nod" else (),
            )

        def outputs(shown: Shown) -> tuple[object, ...]:
            with tempfile.NamedTemporaryFile(
                prefix="ensemble-", suffix=".mid", delete=False
            ) as file:
                file.write(shown.midi)
            return shown.audio, shown.table, shown.roll, file.name, shown.learning

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

        def on_variations(name: str, file: str | None, data: str, *values: object) -> list[object]:
            variation, novelty, setting, count, seed, drums, blind, tempo, chords = values
            try:
                listing = variations.listen(
                    file or str(name or ""),
                    str(data or DEFAULT_DATA),
                    variation=str(variation),
                    novelty=float(str(novelty)),
                    setting=str(setting),
                    seed=int(float(str(seed))),
                    count=int(float(str(count))),
                    progression=str(chords),
                    tempo=float(str(tempo)),
                    drums=bool(drums),
                    blind=bool(blind),
                )
            except ValueError as e:
                raise gr.Error(str(e)) from e
            clips = play_variations(listing)
            shown: list[object] = []
            for i in range(len(slots)):
                if i < len(clips):
                    label, sound, picture = clips[i]
                    shown += [
                        gr.Column(visible=True),
                        gr.Audio(sound, label=label),
                        gr.Image(picture),
                    ]
                else:
                    shown += [gr.Column(visible=False), None, None]
            return [*shown, variations.table(listing), listing]

        def on_reveal(listing: variations.Listing | None) -> list[list[str | int]]:
            if listing is None:
                raise gr.Error("generate the candidates first")
            return variations.table(listing, reveal=True)

        var_inputs = [var_loop, var_file, var_data, var_variation, var_novelty, var_corpus]
        var_inputs += [var_count, var_seed, var_drums, var_blind, tempo, progression]
        var_outputs = [part for slot in slots for part in slot] + [provenance, listed]
        var_button.click(on_variations, var_inputs, var_outputs)
        reveal.click(on_reveal, listed, provenance)
        bars.change(lambda cells, n: resize(cells, int(n)), [grid, bars], grid)
        results = [audio, table, image, midi, log]
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
        f"{_transform(row.bass)} / {_transform(row.melody)}",
        "; ".join(filter(None, (_took("bass", row.bass), _took("melody", row.melody)))) or "-",
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
        " / ".join(row.context),
        " / ".join(row.chose)
        + (", liked" if row.liked else "")
        + "".join(f", pressed {part}" for part in row.pressed),
    ]


def _transform(plan: BarPlan | None) -> str:
    """The transformation a loop plays, `-` when it does not play (as the reply)."""
    return "-" if plan is None or plan.variation is None else plan.transform


def _took(name: str, plan: BarPlan | None) -> str:
    """For example `kick 1 7 11 → bass 7` (steps from 1); empty when `plan` took
    nothing from the drums."""
    taken: Taken | None = None if plan is None or plan.variation is None else plan.taken
    if taken is None:
        return ""
    moved = sorted({m.step for m in taken.moves if m.step != m.start})
    return f"{taken.role} {_steps(taken.steps)} → {name} {_steps(moved)}"


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
