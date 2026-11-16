# Replay fixtures from the MPC Sample

Short recordings made by the maintainer with an MPC Sample (firmware 1.3.0) over USB
on 2026-11-16, for replay tests of the input layer and the IML loop (#26). They
contain only the maintainer's own test playing; no research data. Format:
ADR 0002, `format_version` 1. Settings: MIDI Port USB, Pad MIDI Out Always,
Full Level off.

| File | Recorded with | Content |
| --- | --- | --- |
| `strikes.jsonl` | `python -m mpc_iml.record --duration 5` | One strike on each of seven pads (notes 36–42), velocities 38–87; no pressure (quick taps). |
| `hold-pressure.jsonl` | `python -m mpc_iml.record --duration 6` | Pad 1 (note 36) held with rising, falling and then steady pressure (1–101). |
| `two-pads.jsonl` | `python -m mpc_iml.record --duration 6` | Pads 1 and 4 (notes 36, 39) held together with independent pressure (up to 127 and 98). |
| `banks.jsonl` | `python -m mpc_iml.record --duration 10` | Pad 1 struck in banks A, B and H: notes 36, 52, 20. |
| `transport.jsonl` | `python -m mpc_iml.record --duration 6` | A few strikes plus Play (CC 7, value 90) and Stop (CC 64, value 0, twice): non-gesture messages that frames ignore. |
| `examples.jsonl` | `python -m mpc_iml.demo record --seconds 2 --countdown 2` | `example_start` / `example_end` segments labelled rest, soft and hard. Pad 1 was pressed once and held through soft and hard (one `note_on`, velocity 5, no `note_off`), so the two classes differ only in pressure. |

## Observed hardware behaviour

- **Retriggering while held lightly.** In `hold-pressure.jsonl` and
  `two-pads.jsonl` the pad was held the whole time, but whenever the pressure fell to
  its minimum (1, once 3) the MPC sent `note_off`, then a new `note_on` 70–273 ms
  later when the pressure rose again, with a low velocity (1–21). A light hold can
  therefore look like a series of short presses, and the frame's held flag flickers.
  Relevant to feature design (#43).
- Pressure starts about 70 ms after `note_on` and does not return to 0 before
  `note_off`, as found in #10.
- Release sends a real `note_off` (status `0x8n`), not `note_on` with velocity 0.

These files are test data: do not edit them by hand. Record a new file instead and
describe it here.
