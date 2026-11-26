"""The band tab of the web demo: choose a band, hear it with a sound set, set the engine
(#280, RFC 0006 step 3, first part).

The functions before `tab` hold the page's logic without Gradio and take and return
plain values: `list_sets` lists the sound sets under the `--sounds` folder (a subfolder
whose `sound-set.json` is refused is listed with the reason, one without the file is
not listed), `match_lines` says which instrument of a set plays each player of a band,
`choose_set` picks the set that has an instrument for the most players of a band
(#282) and `pick_set` reads the sets to choose from,
`listen` renders the band's audition with a set (`sounds.audition`), `messages` are the
band's three controls as the existing `ensemble` preset messages, `send` sends them to
the engine's control port on this machine, and `todo_lines` say what is left to do by
hand. Errors a musician can cause (a folder that is gone, a set that changed on disk,
two sample rates) come back as a message, not an exception.

Its "Make sounds" part (#288) makes a sound set with the generator file given with
`--generator`; its logic is in `webdemo.makesounds`.

`tab` builds the tab; `app.build` leaves it out under `--share`, as it reads folders on
the machine, runs the generator's command and sends messages to the engine.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt
from pythonosc.udp_client import SimpleUDPClient

from mpc_iml.bands import Band, load_bands
from mpc_iml.engine import CONTROL_PORT
from mpc_iml.osc import DEFAULT_HOST
from mpc_iml.plays import Plays
from mpc_iml.sounds import audition, soundset
from mpc_iml.sounds.audition import AuditionError
from mpc_iml.sounds.generate import Generator
from mpc_iml.sounds.instrument import describe
from mpc_iml.sounds.soundset import SoundSet, SoundSetError
from mpc_iml.webdemo import makesounds

if TYPE_CHECKING:
    pass

__all__ = [
    "CONTROL",
    "MAX_INSTRUMENTS",
    "PLAYER_HEADERS",
    "Heard",
    "Listing",
    "SetChoice",
    "band_lines",
    "choose_set",
    "list_sets",
    "listen",
    "load_set",
    "match_lines",
    "match_text",
    "messages",
    "pick_set",
    "players_matched",
    "play_with",
    "player_rows",
    "send",
    "tab",
    "todo_lines",
]

CONTROL = "/mpciml/preset/ensemble/"
"""The address prefix of the `ensemble` preset controls (`docs/ensemble.md`)."""
MAX_INSTRUMENTS = 8
"""The most instruments the page shows an audio player for."""
PLAYER_HEADERS = ["player", "part", "what it plays"]

_ERRORS = (AuditionError, SoundSetError, OSError, ValueError)


@dataclass(frozen=True)
class SetChoice:
    """A subfolder of the sounds folder that holds a `sound-set.json`, and why it
    cannot be chosen (empty when it can)."""

    name: str
    folder: Path
    problem: str = ""


@dataclass(frozen=True)
class Listing:
    """The sets under the sounds folder, and a message when it cannot be read."""

    sets: tuple[SetChoice, ...] = ()
    message: str = ""

    def choices(self) -> list[str]:
        """The names of the sets that can be chosen."""
        return [s.name for s in self.sets if not s.problem]


@dataclass(frozen=True)
class Heard:
    """What `listen` rendered, as 16-bit stereo arrays at `rate`, with the audition's
    lines; or only a `message` when it could not."""

    rate: int = 0
    band: npt.NDArray[np.int16] | None = None
    instruments: Mapping[str, npt.NDArray[np.int16]] = field(default_factory=dict)
    drums: npt.NDArray[np.int16] | None = None
    lines: tuple[str, ...] = ()
    message: str = ""


def list_sets(sounds: Path | None) -> Listing:
    """The subfolders of `sounds` that hold a `sound-set.json`, by name, each with its
    problems (`soundset.problems`) joined, or a message when there is no folder."""
    if sounds is None:
        return Listing(
            message="Start the demo with `--sounds <folder>` to choose a sound set: "
            "a folder whose subfolders are sound sets."
        )
    try:
        folders = sorted(p for p in sounds.iterdir() if (p / soundset.FILE).is_file())
    except OSError as error:
        return Listing(message=f"cannot read the sounds folder {sounds}: {error}")
    sets = []
    for folder in folders:
        found = soundset.problems(folder)
        sets.append(SetChoice(folder.name, folder, "; ".join(found)))
    return Listing(tuple(sets))


def load_set(sounds: Path | None, name: str | None) -> SoundSet:
    """The set `name` under `sounds`, read again from the disk. Raises `SoundSetError`
    when there is no folder or set, or the set is refused now."""
    if sounds is None or not name:
        raise SoundSetError("choose a sound set first")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise SoundSetError(f"{name!r} is not a sound set of {sounds}")
    folder = sounds / name
    if not (folder / soundset.FILE).is_file():
        raise SoundSetError(
            f"{folder}: the set is gone (no {soundset.FILE}); read the folder again"
        )
    return soundset.load(folder)


def band_lines(band: Band) -> list[str]:
    """The band's title, description, tempo and content."""
    content = ", ".join(f"{control} `{name}`" for control, name in band.controls().items())
    return [f"**{band.title}** ({band.name})", band.description, f"{band.tempo} BPM; {content}"]


def player_rows(band: Band) -> list[list[str]]:
    """One row for each player: name, part and the description of what it plays."""
    return [[p.name, str(p.plays.part), p.description] for p in band.players]


def _plays(plays: Plays) -> str:
    return describe(plays) or "every note"


def match_lines(band: Band, sound_set: SoundSet) -> list[str]:
    """For each player of `band`, the instrument of its name in `sound_set` (how many
    regions, and what it plays when that differs from the player) or that there is
    none; then the instruments that are not players of the band, and the drum hits."""
    lines = []
    for player in band.players:
        instrument = sound_set.instruments.get(player.name)
        if instrument is None:
            lines.append(f"{player.name}: no instrument of this name in the set")
            continue
        line = f"{player.name}: instrument {player.name}, {len(instrument.regions)} region(s)"
        if instrument.plays != player.plays:
            line += (
                f"; it plays {_plays(instrument.plays)}, the player plays {_plays(player.plays)}"
            )
        lines.append(line)
    players = {p.name for p in band.players}
    for name, instrument in sound_set.instruments.items():
        if name not in players:
            part = instrument.plays.part
            plays = f"plays the {part} part" if part else "plays no part, skipped"
            lines.append(f"{name}: not a player of the band ({plays})")
    hits = ", ".join(sound_set.hits) or "none"
    lines.append(f"drum hits: {hits}")
    return lines


def players_matched(band: Band, sound_set: SoundSet) -> int:
    """How many players of `band` have an instrument of their name in `sound_set` that
    plays their part."""
    return sum(
        1
        for p in band.players
        if (i := sound_set.instruments.get(p.name)) is not None and i.plays.part == p.plays.part
    )


def choose_set(band: Band, sets: Mapping[str, SoundSet], chosen: str | None) -> str | None:
    """The set of `sets` in which the most players of `band` have an instrument of their
    name that plays their part (`players_matched`); `chosen` when it is among the best
    or when no set has any player of the band; of several best, the first by name."""
    scores = {name: players_matched(band, s) for name, s in sets.items()}
    best = max(scores.values(), default=0)
    if best == 0 or scores.get(chosen or "") == best:
        return chosen
    return min(name for name, score in scores.items() if score == best)


def pick_set(
    band: Band, sounds: Path | None, names: Sequence[str], chosen: str | None
) -> str | None:
    """`choose_set` over the sets `names` under `sounds`, read again from the disk (a
    set that cannot be read is left out); `chosen` when it is in `names`, else the
    first of `names`, when no set has a player of the band."""
    sets = {}
    for name in names:
        try:
            sets[name] = load_set(sounds, name)
        except _ERRORS:
            continue
    fallback = chosen if chosen in names else (names[0] if names else None)
    return choose_set(band, sets, fallback)


def match_text(band: Band, sounds: Path | None, name: str | None) -> str:
    """`match_lines` for the set `name`, read again from the disk, or why it cannot be
    read; empty when no set is chosen."""
    if not name:
        return ""
    try:
        return "\n".join(match_lines(band, load_set(sounds, name)))
    except _ERRORS as error:
        return str(error)


def _pcm(samples: npt.NDArray[np.float32]) -> npt.NDArray[np.int16]:
    return np.asarray(np.round(np.clip(samples, -1.0, 1.0) * 32767), dtype=np.int16)


def listen(band: Band, sounds: Path | None, name: str | None, bars: int | None = None) -> Heard:
    """The band's audition (its first `bars` bars) rendered with the set `name`: the
    band, each instrument that plays a part and the drums, and the lines of the
    audition command; or a message."""
    try:
        if bars is not None and not 1 <= bars <= len(band.audition):
            raise AuditionError(f"bars must be 1-{len(band.audition)}, got {bars}")
        sound_set = load_set(sounds, name)
        result = audition.audition(audition.play(band, bars), sound_set)
    except _ERRORS as error:
        return Heard(message=str(error))
    return Heard(
        rate=result.rate,
        band=_pcm(result.band),
        instruments={n: _pcm(s) for n, s in result.instruments.items()},
        drums=_pcm(result.drums),
        lines=tuple(audition.report(band, sound_set, result)),
    )


def messages(band: Band) -> list[tuple[str, list[str]]]:
    """The band's three controls as `ensemble` preset messages, in the order of
    `Band.controls`: `bass-loop`, `loop`, `progression`."""
    return [(CONTROL + control, [value]) for control, value in band.controls().items()]


def send(sent: Sequence[tuple[str, list[str]]], port: int = CONTROL_PORT) -> None:
    """Send `sent` to the control port on this machine. Raises `OSError`."""
    client = SimpleUDPClient(DEFAULT_HOST, port)
    for address, args in sent:
        client.send_message(address, args)


def todo_lines(band: Band, sound_set: SoundSet | None) -> list[str]:
    """What the musician still does by hand: the tempo of the DAW, each instrument's
    SFZ file and the part its track receives, and the drum hits."""
    lines = [f"Set the tempo of the DAW to {band.tempo} BPM."]
    if sound_set is None:
        return lines + ["No sound set: load your own instruments on the bass and melody tracks."]
    for name, instrument in sound_set.instruments.items():
        part = instrument.plays.part
        if part is None:
            lines.append(f"{name}: plays no part, not needed ({instrument.sfz})")
        else:
            lines.append(f"{name}: load {instrument.sfz} on a track that receives the {part} part")
    for name, hit in sound_set.hits.items():
        lines.append(f"{name}: drum hit {hit.sample}")
    if not sound_set.hits:
        lines.append("The set has no drum hits.")
    return lines


def play_with(
    band: Band, sounds: Path | None, name: str | None, port: int = CONTROL_PORT
) -> list[str]:
    """Send the band's controls to the engine, then say what is left to do by hand
    with the set `name` (when one is chosen)."""
    sent = messages(band)
    try:
        send(sent, port)
    except OSError as error:
        return [f"could not send to {DEFAULT_HOST}:{port}: {error}"]
    lines = [f"Sent {address} {args[0]} to {DEFAULT_HOST}:{port}." for address, args in sent] + [
        "A UDP message gets no answer: the page cannot tell whether an engine is running. "
        "Check that the band changes."
    ]
    sound_set = None
    if name:
        try:
            sound_set = load_set(sounds, name)
        except _ERRORS as error:
            lines.append(f"The sound set cannot be read: {error}")
    return lines + todo_lines(band, sound_set)


MAKE = "Make"
MAKING = "Making… one run at a time"


def tab(
    gr: Any,
    sounds: Path | None,
    port: int = CONTROL_PORT,
    generator: Generator | None = None,
    page: Any = None,
) -> Any:
    """The band tab, inside the page's `gr.Blocks` (module docstring); returns the
    `gr.Tab`, so the page can wire its selection (#282). The set is chosen with
    `pick_set` when the page is built, when the band changes and when the folder is
    read again and the chosen set is gone; with `page` (the `gr.Blocks`), also each time
    the page is opened, from the folder as it is then (#288). With `generator` and
    `sounds`, part 3 makes sounds (#288); without, it says how to start the demo with
    both."""
    bands = load_bands()
    first = next(iter(bands.values()))
    listing = list_sets(sounds)

    def listing_text(found: Listing) -> str:
        if found.message:
            return found.message
        if not found.sets:
            return f"No sound sets in `{sounds}`."
        refused = [f"- {s.name}: cannot be chosen: {s.problem}" for s in found.sets if s.problem]
        return f"Sound sets in `{sounds}`." + ("\n\n" + "\n".join(refused) if refused else "")

    def made_in(band: Band, chosen: str | None) -> tuple[str, dict[str, Any] | None]:
        """The set name part 3 starts with for `band` when `chosen` is chosen
        (`makesounds.set_name`), and that set's document (`None` when it does not exist)."""
        named = makesounds.set_name(band, chosen, makesounds.document(sounds, chosen))
        return named, makesounds.document(sounds, named)

    choices = listing.choices()
    first_set = pick_set(first, sounds, choices, None)

    with gr.Tab("band") as band_tab:
        gr.Markdown("### 1. Choose a band")
        band_name = gr.Dropdown(list(bands), value=first.name, label="band")
        about = gr.Markdown("\n\n".join(band_lines(first)))
        players = gr.Dataframe(
            player_rows(first), headers=PLAYER_HEADERS, type="array", interactive=False
        )
        gr.Markdown("### 2. Choose a sound set")
        with gr.Row():
            set_name = gr.Dropdown(choices, value=first_set, label="sound set")
            reload_button = gr.Button("Read the folder again", interactive=sounds is not None)
        sets_info = gr.Markdown(listing_text(listing))
        matched = gr.Textbox(
            match_text(first, sounds, first_set),
            label="players and instruments",
            lines=6,
            interactive=False,
        )
        gr.Markdown("### 3. Make sounds")
        can_make = generator is not None and sounds is not None
        if not can_make:
            gr.Markdown(makesounds.HOW_TO_START)
        else:
            assert generator is not None
            first_name, first_data = made_in(first, first_set)
            first_rows = makesounds.rows(first, first_data)
            first_chosen = makesounds.chosen_at_start(first, first_data)
            gr.Markdown(
                f"Made with the generator `{generator.name}` (model `{generator.model}`). "
                "Edit the words, choose what to make and press Make. Making a player the "
                "set already has replaces its instrument, with new seeds."
            )
            make_name = gr.Textbox(first_name, label="set name")
            table = gr.Dataframe(
                first_rows,
                headers=makesounds.HEADERS,
                type="array",
                interactive=True,
                static_columns=[0, 1],
                label="players and hits",
            )
            to_make = gr.CheckboxGroup(
                [row[0] for row in first_rows], value=first_chosen, label="which to make"
            )
            plan_text = gr.Markdown(
                makesounds.plan_line(
                    first, first_data, first_name, first_chosen, makesounds.words_of(first_rows)
                )
            )
            make_button = gr.Button(MAKE, variant="primary")
            made_text = gr.Textbox(label="made", lines=10, interactive=False)
        gr.Markdown("### 4. Listen")
        with gr.Row():
            bars = gr.Slider(
                1, len(first.audition), value=len(first.audition), step=1, label="bars"
            )
            listen_button = gr.Button("Listen", variant="primary", interactive=sounds is not None)
        band_audio = gr.Audio(label="the band", type="numpy", interactive=False)
        slots = []
        for _ in range(MAX_INSTRUMENTS + 1):
            slots.append(gr.Audio(type="numpy", interactive=False, visible=False))
        heard_lines = gr.Textbox(label="audition", lines=4, interactive=False)
        gr.Markdown("### 5. Play with it")
        play_button = gr.Button(f"Set the engine to this band (port {port})")
        todo = gr.Textbox(label="what is left to do", lines=8, interactive=False)

        def on_band(name: str, chosen: str | None) -> tuple[object, ...]:
            band = bands[name]
            picked = pick_set(band, sounds, list_sets(sounds).choices(), chosen)
            return (
                "\n\n".join(band_lines(band)),
                player_rows(band),
                gr.update(maximum=len(band.audition), value=len(band.audition)),
                gr.update(value=picked),
                match_text(band, sounds, picked),
            )

        def on_set(name: str, chosen: str | None) -> str:
            return match_text(bands[name], sounds, chosen)

        def on_reload(name: str, chosen: str | None) -> tuple[object, ...]:
            found = list_sets(sounds)
            names = found.choices()
            value = chosen if chosen in names else pick_set(bands[name], sounds, names, None)
            return gr.update(choices=names, value=value), listing_text(found)

        def on_listen(name: str, chosen: str | None, count: float) -> list[object]:
            heard = listen(bands[name], sounds, chosen, int(count))
            if heard.message:
                gr.Warning(heard.message)
                hidden = [gr.update(value=None, visible=False)] * len(slots)
                return [None, *hidden, heard.message]
            parts: list[tuple[str, object]] = list(heard.instruments.items())
            lines = list(heard.lines)
            if len(parts) > MAX_INSTRUMENTS:
                lines.append(f"only the first {MAX_INSTRUMENTS} instruments are shown")
            parts = parts[:MAX_INSTRUMENTS] + [("drums", heard.drums)]
            updates = [
                gr.update(value=(heard.rate, samples), label=label, visible=True)
                for label, samples in parts
            ]
            updates += [gr.update(value=None, visible=False)] * (len(slots) - len(updates))
            return [(heard.rate, heard.band), *updates, "\n".join(lines)]

        def on_play(name: str, chosen: str | None) -> str:
            return "\n".join(play_with(bands[name], sounds, chosen, port))

        band_name.change(on_band, [band_name, set_name], [about, players, bars, set_name, matched])
        set_name.change(on_set, [band_name, set_name], matched)
        reload_button.click(on_reload, [band_name, set_name], [set_name, sets_info])
        listen_button.click(
            on_listen, [band_name, set_name, bars], [band_audio, *slots, heard_lines]
        )
        play_button.click(on_play, [band_name, set_name], todo)

        def on_open(name: str, chosen: str | None) -> tuple[object, ...]:
            band = bands[name]
            found = list_sets(sounds)
            names = found.choices()
            picked = pick_set(band, sounds, names, chosen if chosen in names else None)
            opened: tuple[object, ...] = (
                gr.update(choices=names, value=picked),
                listing_text(found),
                match_text(band, sounds, picked),
            )
            return opened + (on_source(name, picked) if can_make else ())

        if can_make:

            def on_source(name: str, chosen: str | None) -> tuple[object, ...]:
                band = bands[name]
                named, data = made_in(band, chosen)
                found = makesounds.rows(band, data)
                picked = makesounds.chosen_at_start(band, data)
                return (
                    named,
                    found,
                    gr.update(choices=[row[0] for row in found], value=picked),
                    makesounds.plan_line(band, data, named, picked, makesounds.words_of(found)),
                )

            def on_plan(name: str, named: str, found: list[list[str]], picked: list[str]) -> str:
                band = bands[name]
                data = makesounds.document(sounds, named)
                words = makesounds.words_of(found)
                return makesounds.plan_line(band, data, named, picked or [], words)

            def on_make(
                name: str, named: str, found: list[list[str]], picked: list[str]
            ) -> Iterator[tuple[object, ...]]:
                band = bands[name]
                lines: list[str] = []
                busy = gr.update(value=MAKING, interactive=False)
                keep = (gr.update(),) * 6
                for chunk in makesounds.make(
                    band, generator, sounds, named, picked or [], makesounds.words_of(found)
                ):
                    lines += chunk
                    yield ("\n".join(lines), busy, *keep)
                listing = list_sets(sounds)
                names = listing.choices()
                value = named if named in names else None
                data = makesounds.document(sounds, value)
                rows = makesounds.rows(band, data)
                yield (
                    "\n".join(lines),
                    gr.update(value=MAKE, interactive=True),
                    gr.update(choices=names, value=value),
                    listing_text(listing),
                    match_text(band, sounds, value),
                    rows,
                    gr.update(value=[]),
                    makesounds.plan_line(band, data, named, [], makesounds.words_of(rows)),
                )

            source = [make_name, table, to_make, plan_text]
            band_name.change(on_source, [band_name, set_name], source)
            set_name.change(on_source, [band_name, set_name], source)
            for box in (make_name, table, to_make):
                box.change(on_plan, [band_name, make_name, table, to_make], plan_text)
            make_button.click(
                on_make,
                [band_name, make_name, table, to_make],
                [made_text, make_button, set_name, sets_info, matched, table, to_make, plan_text],
                concurrency_limit=1,
            )
        if page is not None:
            opened = [set_name, sets_info, matched] + (source if can_make else [])
            page.load(on_open, [band_name, set_name], opened)
    return band_tab
