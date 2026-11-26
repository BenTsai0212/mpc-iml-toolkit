"""The built-in lo-fi and trap sets (#262): a bass loop, a melody loop and an 8-bar
progression written to go together, played through `ensemble` on the simulated DAW
clock of `test_ensemble.py` (`Rig`)."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_ensemble import BAR, START, Rig
from test_ensemble_learn import bar_of, reply
from test_ensemble_still import DENSE, SPARSE, SYNCOPATED

from mpc_iml.loops import load_loops
from mpc_iml.progressions import load_progressions

SETS = {
    "lo-fi": ("haze-bass", "haze-keys", "haze"),
    "trap": ("midnight-808", "midnight-keys", "midnight"),
}
"""Each set: its bass loop, melody loop and progression, in the table of #262."""

SRC = Path(__file__).parents[1] / "src" / "mpc_iml"
HASHES = {
    "haze-bass": "5bae039a37465088b9f2a58b72704bae16e285dfbcb41ffcd1ed89436fd1743b",
    "haze-keys": "6df1813d39aa22061d361950665d44a3447fe7d69ad96729230ac82b91fc628d",
    "haze": "9287a1411fdbf11004ad8a5ab871a85232ac1a05aee7c524654f053c65a560a1",
    "midnight-808": "9c0a6d47cc4c461b3d925f3cb6eee0c6302fe2501fda54844983de7d8e6136cb",
    "midnight-keys": "88b5ec7e50eabe996f3d8c5c33e9ca4827159c96e01dc4a338a3db69edc9e931",
    "midnight": "ce7f6078d1cfabc52be03b15955bb62dfb8fbc34c069b687dc06a91f72245d96",
}
"""SHA-256 of each new file's parsed JSON with sorted keys, from #262."""

BARS = [SPARSE, SYNCOPATED, DENSE, SPARSE, DENSE, SYNCOPATED, SPARSE, SPARSE]
"""8 bars, one pass of the progression, over sparse, syncopated and dense drums."""

RULES = [
    ["home", "push", "drive", "home", "drive", "push", "home", "home"],
    ["open", "home", "busy", "open", "busy", "home", "open", "open"],
]
"""The variations the rules choose after each bar of `BARS`: bass (kicks on the beat
`home`, off the beat `push`, 5 kicks `drive`) and melody (5 hits or fewer `open`,
hats on odd steps `busy`, else `home`)."""

BASS_ON, MELODY_ON = 0x91, 0x92
"""A note on, on the bass channel (2) and on the melody channel (3)."""


def played(bass_loop: str, loop: str, progression: str) -> tuple[Rig, list[list[Any]]]:
    """Play `BARS` with the set; the `variation` reply just after each bar line."""
    rig = Rig(melody=True, bass="loop")
    controls = rig.ensemble.controls()
    controls["bass-loop"]([bass_loop])
    controls["loop"]([loop])
    controls["progression"]([progression])
    rig.send(START)
    variations = []
    for bar, hits in enumerate(BARS):
        bar_of(rig, bar, hits=hits)
        rig.until((bar + 1) * BAR + 1)
        variations.append(reply(rig, "variation"))
    return rig, variations


@pytest.mark.parametrize("name", SETS)
def test_each_set_plays_its_files_and_the_variations_the_rules_choose(name: str) -> None:
    bass_loop, loop, progression = SETS[name]
    library = load_loops()
    assert library.get(bass_loop, "bass").part == "bass"
    assert library.get(loop, "melody").part == "melody"
    rig, variations = played(bass_loop, loop, progression)
    assert reply(rig, "bass-loop") == [bass_loop]
    assert reply(rig, "loop") == [loop]
    assert reply(rig, "progression") == [progression]
    assert [list(v) for v in zip(*variations, strict=True)] == RULES
    p = load_progressions()[progression]
    downbeats = {
        t // BAR: m[1] % 12 for t, m in rig.sent if m[0] == BASS_ON and m[2] > 0 and t % BAR == 0
    }
    assert set(downbeats) >= set(range(1, len(BARS)))
    for bar, pitch in downbeats.items():
        assert pitch == (p.tonic + p.chord(bar).root) % 12, f"the root of bar {bar}"
    melody = {t // BAR for t, m in rig.sent if m[0] == MELODY_ON and m[2] > 0}
    assert melody >= set(range(1, len(BARS))), "the melody plays in every bar"


@pytest.mark.parametrize("name", HASHES)
def test_the_files_hold_the_notes_of_262(name: str) -> None:
    folder = "progressions" if name in ("haze", "midnight") else "loops"
    data = json.loads((SRC / folder / "ensemble" / f"{name}.json").read_text(encoding="utf-8"))
    text = json.dumps(data, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(text.encode()).hexdigest() == HASHES[name]
