"""What a nod counts for, and the nods the band keeps (#250)."""

import pytest
from test_grooves import A, B, C, bar

from mpc_iml.grooves import (
    GROUP_DISTANCE,
    RETURN,
    Decision,
    Features,
    Pattern,
    Tracker,
    descriptor_distance,
    features,
    similarity,
)
from mpc_iml.grooves.nods import GROUP_SHARE, NODS_MAX, Nod, NodMemory, NodTarget, nod_groove

# A near variant of A: the kicks on 6 and 12, within GROUP_DISTANCE of A but below RETURN.
A2 = bar("x.....x.....x...", "....x.......x...", "x.x.x.x.x.x.x.x.")
# A with one kick moved by a step: the same groove (similarity >= RETURN).
A_MOVED = bar("x........xx.....", "....x.......x...", "x.x.x.x.x.x.x.x.")


def groove_bar(n: int, groove: int = 1, new: bool = False) -> Decision:
    return Decision(n, groove=groove, position=3, start=n - 2, new=new)


def fill_bar(n: int, groove: int = 1) -> Decision:
    return Decision(n, groove=groove, position=3, start=n - 2, fill=True)


def keep(memory: NodMemory, groove: int, p: Pattern, variation: str, **kw: str) -> Nod:
    return memory.nod(groove, p, features(p), variation, **kw)


def test_patterns_used_here() -> None:
    assert similarity(A, A_MOVED) >= RETURN
    assert similarity(A, A2) < RETURN
    assert similarity(A2, C) < RETURN
    assert descriptor_distance(A, A2) <= GROUP_DISTANCE
    assert descriptor_distance(A, B) > GROUP_DISTANCE
    assert descriptor_distance(A, C) > GROUP_DISTANCE


# nod_groove


def test_nod_on_a_groove_bar_counts_for_its_groove() -> None:
    assert nod_groove(8, groove_bar(8, 2), groove_bar(7, 2)) == NodTarget(8, 2, 8, "bar")
    # The bar that confirms a new groove is a groove bar of the new groove.
    assert nod_groove(8, groove_bar(8, 3, new=True), fill_bar(7, 2)).groove == 3


@pytest.mark.parametrize(
    "decision",
    [
        fill_bar(9, 2),
        Decision(9, free=True),
        Decision(9),  # no drums, or no groove yet
        None,  # the clock stopped
    ],
)
def test_nod_after_a_groove_bar_counts_for_that_groove(decision: Decision | None) -> None:
    target = nod_groove(9, decision, groove_bar(8, 2))
    assert target == NodTarget(9, 2, 8, "fill", ended=8)


def test_nod_more_than_one_bar_after_the_groove_counts_for_nothing() -> None:
    assert nod_groove(10, fill_bar(10, 2), fill_bar(9, 2)) == NodTarget(10, None, None, "none")
    assert nod_groove(10, Decision(10, free=True), None).groove is None
    assert nod_groove(10, None, None).from_ == "none"


def test_nod_groove_checks_the_bars() -> None:
    with pytest.raises(ValueError, match="bar 7, not 8"):
        nod_groove(8, groove_bar(7), None)
    with pytest.raises(ValueError, match="bar 5, not 7"):
        nod_groove(8, groove_bar(8), groove_bar(5))


def test_nod_groove_on_tracker_decisions() -> None:
    tracker = Tracker()
    bars = [A, A, A, C, B, B, B]
    decisions = [tracker.observe(i, p) for i, p in enumerate(bars)]
    # Bar 3 (C) is a fill of groove 1: a nod there counts for groove 1, bar 2.
    assert nod_groove(3, decisions[3], decisions[2]) == NodTarget(3, 1, 2, "fill", ended=2)
    # Bar 4 (B) is a fill too (the first bar of groove 2), two bars after groove 1.
    assert nod_groove(4, decisions[4], decisions[3]).groove is None
    # Bar 5 confirms groove 2.
    assert nod_groove(5, decisions[5], decisions[4]) == NodTarget(5, 2, 5, "bar")


# NodMemory


def test_a_nod_belongs_to_its_groove() -> None:
    memory = NodMemory()
    assert memory.variation(1) is None
    nod = keep(memory, 1, A, "push", loop="boom", day="2026-11-24")
    assert memory.variation(1) == "push"
    assert memory.bound(1) is nod
    assert (nod.part, nod.nods, nod.loop, nod.last) == ("bass", 1, "boom", "2026-11-24")
    assert nod.features == features(A)
    assert memory.variation(2) is None


def test_a_later_nod_replaces_the_variation_and_moves_the_prototype() -> None:
    memory = NodMemory()
    keep(memory, 1, A, "push")
    nod = keep(memory, 1, A2, "drive")
    assert memory.nods == (nod,)
    assert (nod.variation, nod.prototype, nod.nods) == ("drive", A2, 2)


def test_nods_of_matching_prototypes_merge_into_the_newer() -> None:
    memory = NodMemory()
    keep(memory, 1, A, "push")
    keep(memory, 2, B, "home")
    newer = keep(memory, 3, A_MOVED, "drive")
    assert [n.variation for n in memory.nods] == ["drive", "home"]
    assert newer.nods == 2
    # Groove 1 now plays the newer nod.
    assert memory.variation(1) == "drive"
    assert memory.bound(1) is newer


def test_at_most_nods_max_the_least_recent_goes_first() -> None:
    assert NODS_MAX == 64
    memory = NodMemory(nods_max=2)
    keep(memory, 1, A, "push")
    keep(memory, 2, B, "home")
    keep(memory, 1, A, "push")  # A is now more recent than B
    keep(memory, 3, C, "drive")
    assert [n.variation for n in memory.nods] == ["drive", "push"]
    assert memory.variation(2) is None
    assert memory.variation(1) == "push"
    with pytest.raises(ValueError):
        NodMemory(nods_max=0)


def test_a_stored_nod_is_found_by_its_two_starting_bars() -> None:
    memory = NodMemory()
    stored = memory.add(Nod(A, features(A), "push"))
    assert memory.variation(1) is None
    assert memory.match(4, B, B) is None
    assert memory.match(5, A_MOVED, A) is stored
    assert memory.variation(5) == "push"
    # Found once: another groove does not take it.
    assert memory.match(6, A, A) is None
    # The groove keeps it.
    assert memory.match(5, B, B) is stored


def test_match_takes_the_best_and_needs_return_on_average() -> None:
    memory = NodMemory()
    memory.add(Nod(A, features(A), "push"))
    moved = memory.add(Nod(A_MOVED, features(A_MOVED), "drive"))
    assert memory.match(1, A_MOVED, A_MOVED) is moved
    memory = NodMemory()
    memory.add(Nod(A, features(A), "push"))
    # One bar of A and one of C: the mean stays below RETURN.
    assert memory.match(1, A, C) is None


def test_group_is_the_nearest_other_nod_within_the_distance() -> None:
    memory = NodMemory()
    assert memory.group(1, A) is None
    keep(memory, 2, A2, "push")
    keep(memory, 3, C, "home")
    assert memory.group(1, A).variation == "push"  # type: ignore[union-attr]
    assert memory.group(1, B) is None
    # Not the groove's own nod.
    assert memory.group(2, A2) is None
    keep(memory, 1, A, "drive")
    assert memory.group(1, A).variation == "push"  # type: ignore[union-attr]
    assert memory.group(1, A, distance=0.0) is None


def test_draw_is_seeded_per_nod() -> None:
    def draws(seed: int) -> list[bool]:
        memory = NodMemory(seed=seed)
        nod = keep(memory, 1, A, "push")
        return [memory.draw(nod) for _ in range(200)]

    assert draws(3) == draws(3)
    assert draws(3) != draws(4)
    share = sum(draws(3)) / 200
    assert abs(share - GROUP_SHARE) < 0.1


def test_reset_forgets_every_nod() -> None:
    memory = NodMemory()
    keep(memory, 1, A, "push")
    memory.add(Nod(B, Features(), "home"))
    memory.reset()
    assert memory.nods == ()
    assert memory.variation(1) is None
    assert memory.match(2, B, B) is None
