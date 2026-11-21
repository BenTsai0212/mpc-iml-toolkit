"""The web demo's numpy synth (#166)."""

import numpy as np

from mpc_iml.clock import TICKS_PER_BEAT
from mpc_iml.webdemo.sim import Note, Settings, Song, simulate
from mpc_iml.webdemo.synth import RATE, TAIL, render

BAR = 4 * TICKS_PER_BEAT
BUSY = {"kick": [100, 0, 0, 100] * 4, "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2, "hat": [70] * 16}


def song(notes: list[Note], brightness: tuple[tuple[int, int], ...] = ()) -> Song:
    return Song(Settings(tempo=120), 1, tuple(notes), brightness, ())


def high_energy(samples: np.ndarray) -> float:
    """The share of the spectrum's energy above 1 kHz."""
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64))) ** 2
    freqs = np.fft.rfftfreq(len(samples), 1 / RATE)
    return float(spectrum[freqs > 1000].sum() / spectrum.sum())


def test_the_audio_is_the_song_and_a_tail_at_most_full_scale() -> None:
    s = simulate([BUSY] * 4)
    out = render(s)
    assert out.dtype == np.int16
    assert len(out) == round((s.seconds + TAIL) * RATE)
    assert np.abs(out.astype(np.int32)).max() <= 32_767
    assert np.abs(out).max() > 10_000


def test_it_is_silent_where_nothing_plays() -> None:
    s = simulate([{}, {"kick": [100] + [0] * 15}])
    out = render(s)
    bar = round(BAR * s.seconds_per_tick * RATE)
    assert not out[:bar].any()
    assert out[bar : bar + 100].any()


def test_the_same_song_gives_the_same_samples() -> None:
    s = simulate([BUSY, {}])
    assert np.array_equal(render(s), render(s))
    assert not np.array_equal(render(s, seed=0), render(s, seed=1))


def test_every_part_sounds() -> None:
    for part, pitch in [("kick", 36), ("snare", 38), ("hat", 42), ("bass", 45), ("keys", 69)]:
        out = render(song([Note(part, 0, 12, pitch, 100)]))
        assert np.abs(out).max() > 1000, part


def test_the_keys_get_brighter_with_the_brightness_cc() -> None:
    note = [Note("keys", 0, 48, 69, 100)]
    dark = render(song(note, ((0, 0),)))
    bright = render(song(note, ((0, 127),)))
    assert high_energy(bright) > 2 * high_energy(dark)


def test_a_cc_after_the_note_does_not_change_it() -> None:
    note = [Note("keys", 0, 12, 57, 100)]
    assert np.array_equal(render(song(note, ((0, 40),))), render(song(note, ((0, 40), (24, 127)))))
