"""Groove recognition in `mpc_iml.grooves` (#245)."""

import itertools
import random

import pytest

from mpc_iml.clock import GridHit
from mpc_iml.ensemble import DEFAULT_ROLES
from mpc_iml.grooves import (
    FREE_BARS,
    Decision,
    Features,
    Pattern,
    Tracker,
    features,
    matched,
    mean_features,
    pattern,
    similarity,
)


def bar(kick: str = "", snare: str = "", hat: str = "") -> Pattern:
    """A pattern from 16-character grids, `x` for a hit."""

    def steps(grid: str) -> frozenset[int]:
        return frozenset(i for i, c in enumerate(grid) if c == "x")

    return Pattern(steps(kick), steps(snare), steps(hat))


A = bar("x.......x.x.....", "....x.......x...", "x.x.x.x.x.x.x.x.")
B = bar("x..x..x...x..x..", "....x.......x...", "xxxxxxxxxxxxxxxx")
C = bar("x.x.x.x.x.x.x.x.", "..x...x...x...x.", "")
FILL = bar("x...............", "..xxxxxxxxxxxxxx", "")
FILL2 = bar("xxxx....xxxx....", "", "....x...x.......")
SILENT = Pattern()


def run(bars: list[Pattern], tracker: Tracker | None = None) -> list[Decision]:
    tracker = tracker or Tracker()
    return [tracker.observe(i, p) for i, p in enumerate(bars)]


def ids(decisions: list[Decision]) -> list[object]:
    def label(d: Decision) -> object:
        if d.free:
            return "free"
        if d.fill:
            return f"fill{d.groove}"
        return d.groove

    return [label(d) for d in decisions]


def jitter(p: Pattern, rng: random.Random, share: float = 0.25) -> Pattern:
    def move(steps: frozenset[int]) -> frozenset[int]:
        out = set()
        for s in steps:
            if rng.random() < share:
                s = min(15, max(0, s + rng.choice((-1, 1))))
            out.add(s)
        return frozenset(out)

    return Pattern(move(p.kick), move(p.snare), move(p.hat))


def hit(pad: int, step: int, velocity: int = 100) -> GridHit:
    return GridHit(0.0, pad, 0, velocity, 0, step, 0.0, 0.0)


def test_pattern_reads_roles_and_leaves_out_control_pads_and_other() -> None:
    hits = [hit(0, 0), hit(0, 0, 20), hit(1, 4), hit(2, 2), hit(6, 6), hit(7, 9)]
    assert pattern(hits, DEFAULT_ROLES) == Pattern(
        frozenset({0}), frozenset({4}), frozenset({2, 6})
    )
    roles = ["kick"] * 16
    assert pattern([hit(15, 3), hit(14, 5), hit(13, 7)], roles) == Pattern(frozenset({7}))
    assert pattern([hit(15, 3), hit(7, 1)], DEFAULT_ROLES).empty


def test_matched_is_the_largest_pairing() -> None:
    assert matched({1}, {0, 2}) == 1
    assert matched({1, 2}, {0, 1}) == 2
    assert matched({0, 2}, {1, 3}) == 2
    assert matched({0, 4}, {2}) == 0
    rng = random.Random(0)
    for _ in range(300):
        a = rng.sample(range(8), rng.randint(0, 5))
        b = rng.sample(range(8), rng.randint(0, 5))
        best = 0
        for k in range(min(len(a), len(b)), 0, -1):
            if any(
                all(abs(x - y) <= 1 for x, y in zip(xs, ys, strict=True))
                for xs in itertools.combinations(sorted(a), k)
                for ys in itertools.permutations(b, k)
            ):
                best = k
                break
        assert matched(a, b) == best, (a, b)


def test_similarity_values() -> None:
    assert similarity(A, A) == 1.0
    assert similarity(SILENT, SILENT) == 1.0
    assert similarity(A, SILENT) == 0.0
    late = bar("x........x.x....", ".....x.......x..", ".x.x.x.x.x.x.x.x")
    assert similarity(A, late) == 1.0
    kicks = bar("x...............")
    assert similarity(kicks, bar("x.......x.......")) == pytest.approx(2 / 3)
    # Equal weights per role: the hats do not outweigh the snare.
    no_snare = bar("x.......x.x.....", "", "x.x.x.x.x.x.x.x.")
    assert similarity(A, no_snare) == pytest.approx(2 / 3)


def test_features() -> None:
    p = bar("xx......x.xx....", "..x.x.....x.x..x", "x.x.x.x.")
    assert features(p) == Features(5, 2, 3, 3, 4, 1)
    assert features(SILENT) == Features()
    assert features(C).as_dict()["hat_presence"] == 0
    assert mean_features([Features(kicks=2), Features(kicks=4)]).kicks == 3
    assert mean_features([]) == Features()


def test_jittered_groove_stays_one_groove() -> None:
    rng = random.Random(245)
    decisions = run([jitter(A, rng) for _ in range(8)])
    assert decisions[0] == Decision(0)
    assert ids(decisions[1:]) == [1] * 7
    assert [d.position for d in decisions[1:]] == list(range(2, 9))
    assert decisions[1].new and decisions[1].start == 0


def test_one_fill_keeps_the_groove() -> None:
    decisions = run([A, A, A, FILL, A, A])
    assert ids(decisions) == [None, 1, 1, "fill1", 1, 1]
    assert [d.position for d in decisions[1:]] == [2, 3, 4, 5, 6]


def test_two_different_fill_bars_are_both_fills() -> None:
    assert ids(run([A, A, FILL, FILL2, A])) == [None, 1, "fill1", "fill1", 1]


def test_groove_change_is_confirmed_at_its_second_bar() -> None:
    decisions = run([A, A, A, B, B, B])
    assert ids(decisions) == [None, 1, 1, "fill1", 2, 2]
    assert decisions[4].new and decisions[4].start == 3 and decisions[4].position == 2


def test_return_to_an_earlier_groove_gets_its_id() -> None:
    tracker = Tracker()
    decisions = run([A, A, A, B, B, B, A, A, C, C], tracker)
    assert ids(decisions) == [None, 1, 1, "fill1", 2, 2, "fill2", 1, "fill1", 3]
    assert [g.id for g in tracker.grooves] == [1, 2, 3]
    assert tracker.grooves[0].bars == 5
    assert tracker.grooves[0].prototype == A


def test_slow_drift_keeps_the_id() -> None:
    kicks = [0, 8, 10]
    bars = []
    for i in range(16):
        if i and i % 4 == 0:
            kicks[2] += 1
        bars.append(Pattern(frozenset(kicks), A.snare, A.hat))
    decisions = run(bars)
    assert ids(decisions[1:]) == [1] * 15
    drifted = Pattern(frozenset({0, 8, 13}), A.snare, A.hat)
    assert similarity(drifted, A) < 1.0


def test_two_silent_bars_end_the_groove_and_it_returns() -> None:
    decisions = run([A, A, SILENT, A, A, SILENT, SILENT, A, A])
    assert ids(decisions) == [None, 1, "fill1", 1, 1, "fill1", None, None, 1]
    assert decisions[8].new


def test_only_other_hits_are_no_drums() -> None:
    other = pattern([hit(7, 0), hit(8, 4)], DEFAULT_ROLES)
    assert ids(run([A, A, other, other, A])) == [None, 1, "fill1", None, None]


def test_long_varying_passage_is_free() -> None:
    rng = random.Random(1)
    varying = [
        Pattern(*(frozenset(rng.sample(range(16), rng.randint(1, 6))) for _ in range(3)))
        for _ in range(10)
    ]
    for a, b in itertools.pairwise(varying):
        assert similarity(a, b) < 0.8
    tracker = Tracker()
    decisions = run([A, A, *varying, B, B, A, A], tracker)
    labels = ids(decisions)
    assert labels[2 : 2 + FREE_BARS] == ["fill1"] * FREE_BARS
    assert labels[2 + FREE_BARS : 12] == ["free"] * (10 - FREE_BARS)
    assert labels[12:] == ["free", 2, "fill2", 1]


def test_free_bars_and_silence() -> None:
    fills = [FILL, FILL2] * 3
    decisions = run([A, A, *fills, SILENT, FILL, SILENT, SILENT, FILL], Tracker(free_bars=2))
    assert ids(decisions) == [None, 1, "fill1", "fill1"] + ["free"] * 7 + [None, None]


def test_tracker_settings() -> None:
    assert ids(run([A, A, FILL, FILL2], Tracker(free_bars=1))) == [None, 1, "fill1", "free"]
    with pytest.raises(ValueError):
        Tracker(free_bars=0)
    tracker = Tracker()
    run([A, A], tracker)
    tracker.stop()
    assert ids([tracker.observe(5, A), tracker.observe(6, A)]) == [None, 1]
