"""The play order of a trial and its code letters (#197).

The order is a row of a balanced Latin square (a Williams design) of the
conditions, chosen by a seed: over consecutive seeds each condition comes first
equally often and follows every other condition equally often. With two
conditions, even seeds play `0 1` and odd seeds `1 0`. `repeats` plays the row
again, reversed every other time (`0 1 1 0`), so a condition is not always early.
"""

from string import ascii_uppercase

__all__ = ["balanced_latin_square", "letters", "trial_order"]


def balanced_latin_square(n: int) -> list[list[int]]:
    """The rows of a balanced Latin square of `n` conditions: `n` rows, `2n` when odd."""
    if n < 1:
        raise ValueError(f"need at least 1 condition, got {n}")
    first: list[int] = []
    low, high = 0, 0
    for i in range(n):
        if i < 2 or i % 2:
            first.append(low)
            low += 1
        else:
            first.append(n - high - 1)
            high += 1
    rows = [[(value + r) % n for value in first] for r in range(n)]
    if n % 2:
        rows += [row[::-1] for row in rows]
    return rows


def trial_order(n: int, seed: int, repeats: int = 1) -> list[int]:
    """The condition indices in play order for `seed`."""
    if repeats < 1:
        raise ValueError(f"repeats must be at least 1, got {repeats}")
    rows = balanced_latin_square(n)
    row = rows[seed % len(rows)]
    order: list[int] = []
    for repeat in range(repeats):
        order += row[::-1] if repeat % 2 else row
    return order


def letters(order: list[int]) -> dict[int, str]:
    """Code letters by play order: the first condition played is `A`."""
    codes: dict[int, str] = {}
    for index in order:
        if index not in codes:
            codes[index] = ascii_uppercase[len(codes)]
    return codes
