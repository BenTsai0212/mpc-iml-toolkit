"""The model of the offline variation generator (#221 PR 1): tokens, weighted counts,
longest-match backoff, the corpus setting and `python -m mpc_iml.vargen show`."""

import json
from pathlib import Path
from typing import Any

import pytest

from mpc_iml.loops import USER_FOLDER, load_loops, parse_loop
from mpc_iml.melody import LoopNote
from mpc_iml.vargen import (
    GRAMMAR,
    PRIOR,
    build_model,
    corpus,
    find_loop,
    main,
    pitch_token,
    position,
    rhythm_token,
    show,
    velocity_class,
)

A, B, C = (0, 0, 0, 0), (2, 0, 0, 0), (0, 1, -1, 0)

BASS = ["boom", "haze-bass", "knock", "lazy", "midnight-808", "soul", "sub", "walk"]
"""The built-in bass loops, by name (#232, #262)."""
TINY = [
    {"bar": 0, "step": 0, "tone": 0, "length": 4},
    {"bar": 0, "step": 8, "tone": 2, "length": 2, "velocity": 0.7},
    {"bar": 0, "step": 14, "tone": 0, "length": 2, "chord": 1, "semitones": -1, "velocity": 0.9},
]
"""A hand-written line: root, fifth (ghost), approach (mid, a little late)."""
TINY[2]["offset"] = 0.17

GOLDEN = """\
bass model, corpus source; each file's notes total 1:
  tiny: 3 notes, 0.33 each
pitch (tone,chord,semitones,octave), contexts of up to 2 notes:
  order 2:
    (0,0,0,0) (2,0,0,0) -> (0,1,-1,0) 0.33
    (0,1,-1,0) (0,0,0,0) -> (2,0,0,0) 0.33
    (2,0,0,0) (0,1,-1,0) -> (0,0,0,0) 0.33
  order 1:
    (0,0,0,0) -> (2,0,0,0) 0.33
    (0,1,-1,0) -> (0,0,0,0) 0.33
    (2,0,0,0) -> (0,1,-1,0) 0.33
  order 0:
    -> (0,0,0,0) 0.33, (0,1,-1,0) 0.33, (2,0,0,0) 0.33
  prior at order 0: +0.25 each for (0,0,0,0), (1,0,0,0), (2,0,0,0), (3,0,0,0)
rhythm (length,velocity,offset in 1/6 16th) by position:
  downbeat -> (4,full,0) 0.33
  beat -> (2,ghost,0) 0.33
  8th -> (2,mid,+1/6) 0.33"""


def loop_data(name: str, part: str, variations: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "format": "mpc-iml-loop",
        "format_version": 1,
        "name": name,
        "preset": "ensemble",
        "part": part,
        "bars": 1,
        "variations": variations,
    }


def write_loop(folder: Path, name: str, part: str, notes: list[dict[str, Any]]) -> Path:
    path = folder / USER_FOLDER / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(loop_data(name, part, {"home": notes})), encoding="utf-8")
    return path


def tiny() -> Any:
    return parse_loop(loop_data("tiny", "bass", {"home": TINY}))


def test_tokens() -> None:
    note = LoopNote(0, 14, 0, 2, 1, octave=1, velocity=0.9, chord=1, semitones=-1, offset=-0.33)
    assert pitch_token(note) == (0, 1, -1, 1)
    assert rhythm_token(note) == (2, "mid", -2)
    assert [velocity_class(v) for v in (0.7, 0.79, 0.8, 0.94, 0.95, 1.0)] == [
        "ghost",
        "ghost",
        "mid",
        "mid",
        "full",
        "full",
    ]
    assert [position(s) for s in (0, 4, 8, 12, 2, 6, 14, 1, 15)] == (
        ["downbeat"] + ["beat"] * 3 + ["8th"] * 3 + ["16th"] * 2
    )


def test_show_golden() -> None:
    assert show(build_model([tiny()]), "source") == GOLDEN


def test_backoff_takes_the_longest_context_seen() -> None:
    model = build_model([tiny()])
    assert model.continuations([A, B]) == (2, {C: pytest.approx(1 / 3)})
    assert model.continuations([C, B]) == (1, {C: pytest.approx(1 / 3)})
    assert model.continuations([B]) == (1, {C: pytest.approx(1 / 3)})
    order, counts = model.continuations([(3, 0, 0, 0)])
    assert order == 0
    assert counts == {
        A: pytest.approx(1 / 3 + PRIOR),
        B: pytest.approx(1 / 3 + PRIOR),
        C: pytest.approx(1 / 3),
        (1, 0, 0, 0): PRIOR,
        (3, 0, 0, 0): PRIOR,
    }
    assert model.continuations([])[0] == 0


def test_one_note_line_wraps_and_keeps_the_prior() -> None:
    one = parse_loop(loop_data("one", "melody", {"home": [TINY[0]]}))
    model = build_model([one])
    assert model.continuations([A, A]) == (2, {A: 1.0})
    order, counts = model.continuations([B])
    assert order == 0
    assert set(counts) == set(GRAMMAR)
    assert model.rhythms(5) == {(4, "full", 0): 1.0}


def test_each_file_totals_one() -> None:
    installed = load_loops()
    files = [installed.loops[name] for name in installed.names("bass")] + [tiny()]
    model = build_model(files)
    assert sum(model.pitch[()].values()) == pytest.approx(len(files))
    assert sum(sum(c.values()) for c in model.rhythm.values()) == pytest.approx(len(files))
    for order in (1, 2):
        total = sum(sum(c.values()) for k, c in model.pitch.items() if len(k) == order)
        assert total == pytest.approx(len(files))
    assert [name for name, _ in model.files] == [*BASS, "tiny"]


def test_build_model_needs_one_part() -> None:
    installed = load_loops()
    with pytest.raises(ValueError):
        build_model([])
    with pytest.raises(ValueError):
        build_model([installed.loops["boom"], installed.loops["keys"]])


def test_corpus_settings(tmp_path: Path) -> None:
    write_loop(tmp_path, "my-boom", "bass", TINY)
    write_loop(tmp_path, "my-keys", "melody", TINY[:2])
    source, installed, user = find_loop("boom", tmp_path)
    assert sorted(loop.name for loop in user) == ["my-boom", "my-keys"]
    names = {s: [f.name for f in corpus(source, s, installed, user)] for s in ("source", "own")}
    assert names == {"source": ["boom"], "own": ["boom", "my-boom"]}
    assert [f.name for f in corpus(source, "all", installed, user)] == [*BASS, "my-boom"]
    mine, _, _ = find_loop("my-boom", tmp_path)
    assert [f.name for f in corpus(mine, "own", installed, user)] == ["my-boom"]
    assert [f.name for f in corpus(mine, "all", installed, user)] == ["my-boom", *BASS]
    with pytest.raises(ValueError):
        corpus(source, "everything", installed, user)


def test_own_without_user_loops_is_source(tmp_path: Path) -> None:
    source, installed, user = find_loop("keys", tmp_path / "missing")
    assert user == []
    assert corpus(source, "own", installed, user) == (source,)


def test_cli_show(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "tiny.json"
    path.write_text(json.dumps(loop_data("tiny", "bass", {"home": TINY})), encoding="utf-8")
    assert main(["show", str(path), "--corpus", "source", "--data", str(tmp_path)]) == 0
    assert capsys.readouterr().out == GOLDEN + "\n"
    assert main(["show", "boom", "--data", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith("bass model, corpus own;")
    assert main(["show", "nope", "--data", str(tmp_path)]) == 1
    assert "unknown loop 'nope'" in capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tiny.json"]
