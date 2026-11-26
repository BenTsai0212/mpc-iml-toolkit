"""Which notes of the band an instrument or a player plays (#274, ADR 0013; #276).

`plays` holds the part of the band, the lowest and the highest note, how hard a note
must be hit and the octave it sounds in, all in notes the band sends. A sound set
(`mpc_iml.sounds.soundset`) records it for each instrument and a band file
(`mpc_iml.bands`) for each player; both check it here, so they refuse the same values
with the same words. Standard library only: the core install uses it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

__all__ = ["FIELDS", "OCTAVES", "PARTS", "Plays", "key_pair_problems", "problems"]

PARTS = ("bass", "melody")
"""The parts of the band an instrument can play."""
OCTAVES = 4
"""An instrument sounds at most this many octaves above or below the notes it is sent."""
FIELDS = ("part", "keys", "min_velocity", "octave")
"""The fields of `plays`, all required."""


@dataclass(frozen=True)
class Plays:
    """Which notes of the band an instrument plays (#274), all in notes the band sends.

    `part` is the part of the band (`bass`, `melody` or `None`: not said); `keys` the
    lowest and the highest note it plays; `min_velocity` how hard a note must be hit
    for it to play; `octave` how many octaves above the notes it is sent it sounds."""

    part: Literal["bass", "melody"] | None = None
    keys: tuple[int, int] = (0, 127)
    min_velocity: int = 1
    octave: int = 0

    def check(self) -> "Plays":
        """`self`, or `ValueError` naming the first value out of range."""
        if self.part is not None and self.part not in PARTS:
            raise ValueError(f"part must be 'bass', 'melody' or none, not {self.part!r}")
        low, high = self.keys
        if not (0 <= low <= 127 and 0 <= high <= 127):
            raise ValueError(f"keys must be from 0 to 127, not {low} to {high}")
        if low > high:
            raise ValueError(f"keys: the low key {low} is above the high key {high}")
        if not 1 <= self.min_velocity <= 127:
            raise ValueError(f"min_velocity must be from 1 to 127, not {self.min_velocity}")
        if not -OCTAVES <= self.octave <= OCTAVES:
            raise ValueError(f"octave must be from -{OCTAVES} to {OCTAVES}, not {self.octave}")
        return self

    def sends(self, pitch: int, velocity: int) -> bool:
        """Whether a note the band sends at `pitch` and `velocity` is one it plays."""
        return self.keys[0] <= pitch <= self.keys[1] and velocity >= self.min_velocity

    def to_json(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "keys": list(self.keys),
            "min_velocity": self.min_velocity,
            "octave": self.octave,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Plays":
        low, high = data["keys"]
        return cls(data["part"], (low, high), data["min_velocity"], data["octave"])


def _integer(value: object, where: str, low: int, high: int) -> list[str]:
    if isinstance(value, bool) or not isinstance(value, int):
        return [f"{where}: must be a whole number"]
    if not low <= value <= high:
        return [f"{where}: must be from {low} to {high}"]
    return []


def key_pair_problems(value: object, where: str) -> list[str]:
    """The problems of `[low, high]`, two keys 0 to 127 with low not above high."""
    if not (isinstance(value, list) and len(value) == 2):
        return [f"{where}: must be [low, high]"]
    found = _integer(value[0], where, 0, 127) or _integer(value[1], where, 0, 127)
    if not found and value[0] > value[1]:
        found = [f"{where}: low is above high"]
    return found


def problems(value: object, where: str, part_required: bool = False) -> list[str]:
    """Every problem of the JSON value `value` of a `plays` at `where`, each as
    `<where>.<field>: <problem>`. With `part_required`, a `part` of `null` is one."""
    if not isinstance(value, dict):
        return [f"{where}: must be an object"]
    found = [f"{where}.{key}: unknown field" for key in value if key not in FIELDS]
    found += [f"{where}.{key}: missing" for key in FIELDS if key not in value]
    part = value.get("part")
    if "part" in value and part not in PARTS:
        if part is None and part_required:
            found.append(f"{where}.part: must be 'bass' or 'melody': a player plays a part")
        elif part is not None:
            found.append(f"{where}.part: must be 'bass', 'melody' or null, not {part!r}")
    if "keys" in value:
        found += key_pair_problems(value["keys"], f"{where}.keys")
    if "min_velocity" in value:
        found += _integer(value["min_velocity"], f"{where}.min_velocity", 1, 127)
    if "octave" in value:
        found += _integer(value["octave"], f"{where}.octave", -OCTAVES, OCTAVES)
    return found
