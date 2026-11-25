"""The variation generator (#221 PR 2): constraints, novelty, provenance, the
`parse_loop` gate and `python -m mpc_iml.vargen <loop>`."""

import json
from collections import Counter
from pathlib import Path

import pytest
from test_vargen import TINY, loop_data, write_loop

from mpc_iml.loop_midi import dump
from mpc_iml.loops import STEPS, LoopFile, load_loops, parse_loop
from mpc_iml.melody import LoopNote
from mpc_iml.vargen import build_model, corpus, fixed, generate, main

INSTALLED = load_loops()


def _start(note: LoopNote) -> int:
    return note.bar * STEPS + note.step


def _monophonic(notes: tuple[LoopNote, ...], bars: int) -> bool:
    ordered = sorted(notes, key=_start)
    ends = [_start(n) + n.length for n in ordered]
    nexts = [_start(n) for n in ordered[1:]] + [bars * STEPS + _start(ordered[0])]
    return all(end <= after for end, after in zip(ends, nexts, strict=True))


def _check(loop: LoopFile, variation: str, novelty: float, seed: int) -> None:
    model = build_model(corpus(loop, "all", INSTALLED, []))
    source = loop.variations[variation]
    keep = fixed(loop, variation)
    kept = [n for n, k in zip(source, keep, strict=True) if k]
    free = keep.count(False)
    cap = max(1, round(novelty * free))
    octaves = {t[3] for t in model.pitch[()]} | {0}
    for c in generate(loop, variation, model, novelty=novelty, seed=seed, count=2):
        assert all(n in c.notes for n in kept)
        # Without order: approach notes on one step (`haze-keys`, #262) may change places.
        assert Counter(n for n in c.notes if n.chord == 1) == Counter(
            n for n in source if n.chord == 1
        )
        assert all(0 <= n.step < STEPS and 0 <= n.bar < loop.bars for n in c.notes)
        assert all(abs(n.offset) <= 0.5 and n.octave in octaves for n in c.notes)
        assert max(len(source) - cap, len(kept), 1) <= len(c.notes) <= len(source) + cap
        assert 1 <= c.distance[0] <= cap
        assert c.notes != tuple(sorted(source, key=lambda n: (_start(n), n.level)))
        if loop.part == "bass":
            assert _monophonic(c.notes, loop.bars)
        parse_loop(dump(c.as_loop("candidate")))
        if novelty < 0.4:
            starts = sorted((_start(n), n.length, n.level) for n in c.notes)
            assert starts == sorted((_start(n), n.length, n.level) for n in source)


@pytest.mark.parametrize("name", list(INSTALLED.loops))
def test_every_candidate_keeps_the_rules(name: str) -> None:
    loop = INSTALLED.loops[name]
    for variation in loop.variations:
        for novelty in (0.2, 0.5, 1.0):
            for seed in range(0, 40, 2):
                _check(loop, variation, novelty, seed)


def test_fixed_notes() -> None:
    boom = INSTALLED.loops["boom"]
    assert fixed(boom, "home") == [True, False, False, True, False, True]
    assert fixed(boom, "drive") == [True] + [False] * 4 + [True] + [False] * 3 + [True]


def test_deterministic_and_reproducible() -> None:
    walk = INSTALLED.loops["walk"]
    model = build_model([walk])
    first = generate(walk, "push", model, novelty=0.7, seed=3)
    assert first == generate(walk, "push", model, novelty=0.7, seed=3)
    assert [c.notes for c in first] != [c.notes for c in generate(walk, "push", model, seed=90)]
    assert len({c.notes for c in first}) == 4
    for c in first:
        assert generate(walk, "push", model, novelty=0.7, seed=c.seed, count=1) == [c]
        assert (c.source, c.variation, c.yours, c.corpus) == ("walk", "push", False, "own")


def test_novelty_zero_is_the_source() -> None:
    boom = INSTALLED.loops["boom"]
    [same] = generate(boom, "home", build_model([boom]), novelty=0, count=3)
    assert set(same.notes) == set(boom.variations["home"])
    assert same.distance == (0, 0.0)
    assert same.as_loop("x").skeleton == (boom.variations["home"][0],) + boom.skeleton[1:] + (
        boom.variations["home"][5],
    )


def test_tiny_lines_stay_close(tmp_path: Path) -> None:
    for notes in ([TINY[1]], TINY[:2], [TINY[0]]):
        line = parse_loop(loop_data("tiny", "bass", {"home": notes}))
        model = build_model([line])
        for novelty in (0.2, 1.0):
            for c in generate(line, "home", model, novelty=novelty, seed=1):
                assert c.distance[0] <= max(1, round(novelty * len(notes)))
                assert all(n in c.notes for n in line.variations["home"] if n.step == 0)
        [same] = generate(line, "home", model, novelty=0)
        assert same.notes == line.variations["home"]
    one = parse_loop(loop_data("one", "melody", {"home": [TINY[0]]}))
    assert generate(one, "home", build_model([one]), novelty=0.2) == []


def test_bad_settings() -> None:
    boom = INSTALLED.loops["boom"]
    model = build_model([boom])
    for bad in ({"novelty": 1.5}, {"count": 0}):
        with pytest.raises(ValueError):
            generate(boom, "home", model, **bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        generate(boom, "open", model)


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_loop(tmp_path, "my-boom", "bass", TINY)
    data = ["--data", str(tmp_path)]
    assert main(["boom", "--count", "2", *data]) == 0
    out = capsys.readouterr().out
    assert out.startswith("2 candidate(s) of the built-in boom/home, novelty 0.2, corpus own:")
    assert main(["my-boom", "--novelty", "1", "--json", "--midi", *data]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found and all(c["yours"] and c["source"] == "my-boom" for c in found)
    assert {"seed", "distance", "changes", "notes", "corpus", "novelty"} <= set(found[0])
    clips = sorted(p.name for p in (tmp_path / "vargen").iterdir())
    assert "my-boom-home.mid" in clips and len(clips) == len(found) + 1
    assert main(["show", "boom", *data]) == 0
    assert capsys.readouterr().out.startswith("bass model, corpus own;")
    assert main(["boom", "--variation", "open", *data]) == 1
    assert "no variation 'open'" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["boom", "--novelty", "2", *data])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["loops", "vargen"]
