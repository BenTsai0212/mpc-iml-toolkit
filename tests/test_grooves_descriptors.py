"""Rhythm descriptors and the grooves a nod reaches by descriptor distance (#250, PR 2)."""

import math
from pathlib import Path

import pytest
from test_grooves import A, B, C, bar
from test_grooves_offline import recording, write

from mpc_iml.grooves import (
    GROUP_DISTANCE,
    GROUP_SCALE,
    Descriptors,
    Groove,
    Pattern,
    descriptor_distance,
    features,
    rhythm_descriptors,
    syncopation,
)
from mpc_iml.grooves.__main__ import main
from mpc_iml.grooves.offline import descriptor_reach

UNIT = Descriptors(1.0, 1.0, 1.0, 1.0, 1.0)


def steps(row: str) -> frozenset[int]:
    return frozenset(i for i, c in enumerate(row) if c == "x")


def test_syncopation_matches_rhythmtoolbox() -> None:
    # The two patterns of rhythmtoolbox's own tests (tests/fixtures.py), -4 and -10.
    assert syncopation(steps("x..x..x..x..x...")) == -4
    assert syncopation(steps("x..xxxx.x.x.xxx.")) == -10


def test_syncopation_by_hand() -> None:
    assert syncopation(()) == 0
    # A hit before a rest on a weaker step counts below 0: 1 - 5 on the downbeat.
    assert syncopation({0}) == -4
    # A hit before a stronger rest counts above 0; step 15 is followed by step 0.
    assert syncopation({3}) == 3 - 1
    assert syncopation({15}) == 5 - 1
    # Hits followed by hits add nothing: sixteenths have no syncopation.
    assert syncopation(range(16)) == 0
    # Hats on the 8ths: 8 - (5 + 2 + 3 + 2 + 4 + 2 + 3 + 2); off the 8ths the opposite.
    assert syncopation(range(0, 16, 2)) == -15
    assert syncopation(range(1, 16, 2)) == 15


def test_descriptors_by_hand() -> None:
    # A: kick 0, 8, 10 (-4 - 3 - 1), snare 4 and 12, hats on the 8ths.
    assert rhythm_descriptors(A) == Descriptors(-8, 2, 8, 1.0, -15 / 8)
    # B: kick 0, 3, 6, 10, 13 (-4 + 2 - 1 - 1 + 1), hats on the 16ths.
    assert rhythm_descriptors(B) == Descriptors(-3, 2, 16, 1.0, 0.0)
    # C: kick on the 8ths, four snares, no hat.
    assert rhythm_descriptors(C) == Descriptors(-15, 4, 0, 0.0, 0.0)
    # hiness counts steps, not hits: a kick off the hat's steps adds one step.
    p = bar("x..x............", "", "x.x.x.x.x.x.x.x.")
    assert rhythm_descriptors(p).hiness == 8 / 9
    assert rhythm_descriptors(Pattern()) == Descriptors()


def test_descriptors_sit_next_to_features() -> None:
    d = rhythm_descriptors(A)
    assert list(d.as_dict()) == ["lowsync", "midD", "hiD", "hiness", "hisyness"]
    assert d.hiD == features(A).hats


def test_descriptor_distance() -> None:
    assert descriptor_distance(A, A) == 0.0
    assert math.isclose(descriptor_distance(A, B, UNIT), math.sqrt(5**2 + 8**2 + (15 / 8) ** 2))
    d = (7 / 4, 2 / 2, 8 / 4, 1 / 0.25, (15 / 8) / 1)
    expected = math.sqrt(sum(x * x for x in d))
    assert math.isclose(descriptor_distance(A, C), expected)
    assert descriptor_distance(rhythm_descriptors(A), C) == descriptor_distance(A, C)
    assert GROUP_SCALE.as_dict() == {
        "lowsync": 4.0,
        "midD": 2.0,
        "hiD": 4.0,
        "hiness": 0.25,
        "hisyness": 1.0,
    }


def groove(i: int, p: Pattern) -> Groove:
    return Groove(i, p, 4, features(p))


# A2 has kicks on 4, 12 and 14 (lowsync -5): near A by the descriptors (3 / 4), but a
# different groove for the tracker (no kick within a step of A's). C is far from both.
A2 = bar("....x.......x.x.", "....x.......x...", "x.x.x.x.x.x.x.x.")


def test_group_distance() -> None:
    # #253: checked against recorded sessions, 1.0 rather than the proposed 2.0.
    assert GROUP_DISTANCE == 1.0
    assert descriptor_distance(A, A2) < GROUP_DISTANCE < descriptor_distance(A, C)


def test_reach_is_the_grooves_within_the_distance() -> None:
    grooves = [groove(3, C), groove(1, A), groove(2, A2)]
    assert descriptor_reach(grooves) == {1: [(2, 0.75)], 2: [(1, 0.75)], 3: []}
    assert descriptor_reach(grooves, 0.0) == {1: [], 2: [], 3: []}
    assert descriptor_reach([]) == {}


def test_reach_is_not_linked_through_a_groove_between() -> None:
    # Kicks on even steps only, so only lowsync changes: -8, -11 and -14. A to a2 is
    # 0.75, a2 to a3 0.75 more, A to a3 1.5: at 1 a nod on a2 reaches both, a nod on
    # A does not reach a3 through a2. Nearest first.
    a2 = bar("x.x.x...x.x.....", "....x.......x...", "x.x.x.x.x.x.x.x.")
    a3 = bar("x.x.x.x.x.x.x...", "....x.......x...", "x.x.x.x.x.x.x.x.")
    assert math.isclose(descriptor_distance(A, a2), 0.75)
    assert math.isclose(descriptor_distance(A, a3), 1.5)
    grooves = [groove(1, A), groove(2, a2), groove(3, a3)]
    assert descriptor_reach(grooves) == {1: [(2, 0.75)], 2: [(1, 0.75), (3, 0.75)], 3: [(2, 0.75)]}
    assert descriptor_reach(grooves, 2.0) == {
        1: [(2, 0.75), (3, 1.5)],
        2: [(1, 0.75), (3, 0.75)],
        3: [(2, 0.75), (1, 1.5)],
    }
    assert descriptor_reach(grooves, 0.5) == {1: [], 2: [], 3: []}


def test_cli_group_distance(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, recording([A, A, A, A2, A2, A2, C, C, C]))
    assert main([str(path), "--group-distance"]) == 0
    out = capsys.readouterr().out.splitlines()
    start = out.index(next(line for line in out if line.startswith("reach at distance 1.00")))
    assert out[start + 1 : start + 3] == [
        "groove 1  lowsync -8.00  midD 2.00  hiD 8.00  hiness 1.00  hisyness -1.88",
        "  reaches: groove 2 (0.75)",
    ]
    assert out[start + 6].startswith("  reaches: none (nearest: groove ")
    assert out[-1].startswith("spread: lowsync ")
    assert main([str(path), "--group-distance", "0.5"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[
        out.index("groove 1  lowsync -8.00  midD 2.00  hiD 8.00  hiness 1.00  hisyness -1.88") + 1
    ] == ("  reaches: none (nearest: groove 2, 0.75)")


def test_cli_group_distance_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, recording([A, A, A]))
    assert main([str(path), "--group-distance", "--json"]) == 2
    assert main([str(path), "--group-distance", "-1"]) == 2
    assert capsys.readouterr().err.count("error: ") == 2
    # Without the option the output is as before #250.
    assert main([str(path)]) == 0
    assert "groups at distance" not in capsys.readouterr().out
