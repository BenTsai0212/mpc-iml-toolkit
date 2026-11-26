"""The band tab: choose a band, a sound set, listen and set the engine (#280): synthetic
tones only, no audio file in the repository."""

import json
import shutil
import socket
from pathlib import Path
from typing import Any

import pytest
from pythonosc.osc_message import OscMessage
from test_sounds_audition import a_set, instrument
from test_webdemo_groovetab import tabs_of
from tones import RATE, tone, write

from mpc_iml.bands import load_bands
from mpc_iml.sounds import soundset
from mpc_iml.sounds.instrument import build
from mpc_iml.webdemo import __main__ as webdemo_main
from mpc_iml.webdemo.bandtab import (
    list_sets,
    listen,
    load_set,
    match_lines,
    match_text,
    messages,
    play_with,
)


def sounds_folder(tmp_path: Path) -> Path:
    """`sounds/good` (a set for every player of `lofi`), `sounds/empty` (no
    `sound-set.json`) and `sounds/refused` (a `sound-set.json` the checks refuse)."""
    sounds = tmp_path / "sounds"
    sounds.mkdir()
    built = a_set(tmp_path, load_bands()["lofi"])
    shutil.move(built, sounds / "good")
    (sounds / "empty").mkdir()
    (sounds / "refused").mkdir()
    (sounds / "refused" / soundset.FILE).write_text(
        json.dumps({"format": "something else"}), encoding="utf-8"
    )
    return sounds


def test_the_list_holds_the_good_set_and_the_refused_one_with_its_reason(
    tmp_path: Path,
) -> None:
    sounds = sounds_folder(tmp_path)
    listing = list_sets(sounds)
    assert listing.message == ""
    assert [s.name for s in listing.sets] == ["good", "refused"]
    assert listing.choices() == ["good"]
    refused = listing.sets[1]
    assert "format: must be 'mpc-iml-sound-set'" in refused.problem
    assert "instruments: missing" in refused.problem


def test_without_a_folder_or_with_one_gone_the_list_says_so(tmp_path: Path) -> None:
    assert "--sounds" in list_sets(None).message
    gone = list_sets(tmp_path / "gone")
    assert gone.sets == () and "cannot read the sounds folder" in gone.message


def test_the_lines_match_players_and_instruments(tmp_path: Path) -> None:
    """`lofi` and a set with `bass`, `keys`, `vibes` and `extra`; `vibes` is built for
    every note, so it plays other keys than its player."""
    out = tmp_path / "set"
    instrument(tmp_path, out, "bass", [72.0], part="bass", octave=1)
    instrument(tmp_path, out, "keys", [60.0])
    instrument(tmp_path, out, "vibes", [76.0])
    instrument(tmp_path, out, "extra", [60.0])
    lines = match_lines(load_bands()["lofi"], soundset.load(out))
    assert lines[0] == "bass: instrument bass, 1 region(s)"
    assert lines[1] == "keys: instrument keys, 1 region(s)"
    assert lines[2] == (
        "vibes: instrument vibes, 1 region(s); it plays the melody part,"
        " the player plays the melody part, keys C5 to G9 (72-127)"
    )
    assert lines[3] == "pad: no instrument of this name in the set"
    assert lines[4] == "extra: not a player of the band (plays the melody part)"
    assert lines[5] == "drum hits: none"


@pytest.mark.parametrize("name", ["lofi", "trap"])
def test_listening_returns_the_band_each_instrument_and_the_drums(
    tmp_path: Path, name: str
) -> None:
    band = load_bands()[name]
    folder = a_set(tmp_path, band)
    heard = listen(band, folder.parent, folder.name)
    assert heard.message == ""
    assert heard.rate == RATE
    assert set(heard.instruments) == {p.name for p in band.players}
    assert heard.band is not None and heard.drums is not None
    lengths = {len(heard.band), len(heard.drums)} | {len(x) for x in heard.instruments.values()}
    assert len(lengths) == 1
    assert heard.band.shape[1] == 2 and abs(int(heard.band.astype(int).max())) > 1000
    assert "bass: 0 note(s) no instrument played" in heard.lines
    assert "melody: 0 note(s) no instrument played" in heard.lines


def test_the_slider_at_8_returns_9_bars_and_the_release(tmp_path: Path) -> None:
    band = load_bands()["lofi"]
    folder = a_set(tmp_path, band)
    heard = listen(band, folder.parent, folder.name, 8)
    assert heard.band is not None
    expected = round((8 + 1) * 4 * 60 / band.tempo * RATE) + round(0.5 * RATE)
    assert abs(len(heard.band) - expected) <= 1
    assert "bars must be 1-24" in listen(band, folder.parent, folder.name, 25).message


def test_a_set_that_is_gone_or_refused_now_gives_a_message(tmp_path: Path) -> None:
    sounds = sounds_folder(tmp_path)
    band = load_bands()["lofi"]
    assert list_sets(sounds).choices() == ["good"]
    document = soundset.read_document(sounds / "good")
    document["hits"]["kick"]["sample"] = "hits/gone.wav"
    (sounds / "good" / soundset.FILE).write_text(json.dumps(document), encoding="utf-8")
    heard = listen(band, sounds, "good")
    assert heard.band is None and "hits/gone.wav is missing" in heard.message
    assert "hits/gone.wav is missing" in match_text(band, sounds, "good")
    shutil.rmtree(sounds / "good")
    assert "the set is gone" in listen(band, sounds, "good").message
    assert "the set is gone" in match_text(band, sounds, "good")
    lines = play_with(band, sounds, "good", port=free_port())
    assert any("the set is gone" in line for line in lines)
    assert "is not a sound set" in listen(band, sounds, "../sounds").message
    assert "choose a sound set first" in listen(band, None, None).message


def test_two_sample_rates_give_a_message(tmp_path: Path) -> None:
    out = tmp_path / "set"
    instrument(tmp_path, out, "keys", [60.0])
    source = tmp_path / "source" / "bass-48k.wav"
    write(source, tone(48.0), rate=48000)
    build("bass", [source], out, part="bass")
    heard = listen(load_bands()["lofi"], tmp_path, "set", 1)
    assert "44100 Hz" in heard.message and "48000 Hz" in heard.message


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
    return port


def test_playing_sends_the_three_controls_and_lists_what_is_left(tmp_path: Path) -> None:
    band = load_bands()["lofi"]
    folder = a_set(tmp_path, band)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(5)
        port = listener.getsockname()[1]
        lines = play_with(band, folder.parent, folder.name, port=port)
        received: list[tuple[str, list[Any]]] = []
        for _ in range(3):
            message = OscMessage(listener.recv(65536))
            received.append((message.address, list(message.params)))
        listener.settimeout(0.3)
        with pytest.raises(TimeoutError):
            listener.recv(65536)
    assert received == [
        ("/mpciml/preset/ensemble/bass-loop", ["haze-bass"]),
        ("/mpciml/preset/ensemble/loop", ["haze-keys"]),
        ("/mpciml/preset/ensemble/progression", ["haze"]),
    ]
    assert received == messages(band)
    text = "\n".join(lines)
    assert "cannot tell whether an engine is running" in text
    assert "Set the tempo of the DAW to 76 BPM." in lines
    loaded = load_set(folder.parent, folder.name)
    for name, i in loaded.instruments.items():
        assert f"{name}: load {i.sfz} on a track that receives the {i.plays.part} part" in lines
    for name, hit in loaded.hits.items():
        assert f"{name}: drum hit {hit.sample}" in lines


def test_playing_without_a_set_still_sends_and_gives_the_tempo() -> None:
    band = load_bands()["trap"]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(5)
        lines = play_with(band, None, None, port=listener.getsockname()[1])
        assert OscMessage(listener.recv(65536)).address.endswith("/bass-loop")
    assert "Set the tempo of the DAW to 140 BPM." in lines


def test_the_band_tab_is_on_the_page_but_not_under_share(tmp_path: Path) -> None:
    if not webdemo_main.gradio_installed():
        pytest.skip("needs the demo extra")
    from mpc_iml.webdemo.app import build

    sounds = sounds_folder(tmp_path)
    assert "band" in tabs_of(build(sounds=sounds))
    assert "band" in tabs_of(build())
    assert "band" not in tabs_of(build(sounds=sounds, share=True))


@pytest.mark.parametrize("with_sounds", [False, True])
def test_the_demo_starts_with_and_without_sounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_sounds: bool
) -> None:
    if not webdemo_main.gradio_installed():
        pytest.skip("needs the demo extra")
    import gradio as gr

    launched: list[dict[str, Any]] = []
    monkeypatch.setattr(gr.Blocks, "launch", lambda self, **kw: launched.append(kw))
    argv = ["--sounds", str(sounds_folder(tmp_path))] if with_sounds else []
    assert webdemo_main.main(argv) == 0
    assert launched and launched[0]["server_name"] == "127.0.0.1"
