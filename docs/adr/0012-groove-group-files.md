# ADR 0012: Groove group files

- Status: Proposed
- Date: 2026-11-24
- Related: ADR 0009, ADR 0010, RFC 0005, #245, #249, #250

## Context

The groove tracker (#245) finds the drummer's grooves in a session, but its ids last
only for one tracker. In a hand-built prototype of a grouping page, a musician grouped
his own grooves from 300 bars into five groups in about 15 minutes, and named them in
musical terms ("the steady hip-hop basic", "a skeleton for the intro or fade out").
His grouping matched kick, snare and hat comparisons far better than the band's
context did.

#249 builds that page in the web demo. Its result is a new file in the data folder,
which `ensemble` will read to learn by group (#250, `learn-group`). The `## Decision`
on #249 (2026-11-24) accepts the plan with a new ADR rather than an amendment (no
existing ADR covers grooves), and asks that the format serve #250 without a second
format.

## Options

### 1. Where the format is recorded
- **A new ADR (chosen)**: a new file kind in the data folder, read by another
  module later.
- An ADR 0009 amendment: ADR 0009 covers the engine protocol and `ensemble`'s
  controls, not data files.

### 2. What a file holds about each groove
- **Its prototype and mean features (chosen)**: enough to match bars or grooves to
  groups by `grooves.similarity` (or by measures computed from the prototype) with
  no recording.
- The tracker id and the recordings only: matching would need the recordings and
  the same tracker run.

### 3. Merging grooves across recordings
- **One tracker over the recordings in date order, with the `RETURN` rule
  (chosen)**: the same rule as across takes of one recording; no second rule.
- Track each recording alone, then merge prototypes at `RETURN`: independent of
  order, but a second rule.

## Decision

### Format 1

Files are `<data folder>/grooves/groups-<YYYYMMDD-HHMMSS>.json` (the time the sort
started). Saving a file that was opened overwrites it; "Save as new" writes a new
one (#249 PR 3).

```json
{
  "format": "mpc-iml-groove-groups",
  "version": 1,
  "created": "2026-11-24T15:00:00+00:00",
  "updated": "2026-11-24T15:20:00+00:00",
  "sources": [{"path": "trials/20261123-201500/a.jsonl", "modified": "2026-11-23T20:31:02+00:00", "bars": 104}],
  "settings": {"similar": 0.8, "return": 0.8, "free_bars": 4, "decay": 0.8},
  "blind": false,
  "seed": null,
  "counts": {"groove": 80, "fill": 12, "free": 6, "none": 2, "silent": 4},
  "groups": [{"id": 1, "name": "the steady basic", "purpose": "verses"}],
  "grooves": [
    {
      "id": 1, "group": 1, "note": "my usual", "card": null,
      "prototype": {"kick": [0, 8, 10], "snare": [4, 12], "hat": [0, 2, 4, 6, 8, 10, 12, 14]},
      "features": {"kicks": 3.0, "double_kicks": 0.0, "late_kicks": 2.0, "snare_off": 0.0, "hats": 8.0, "hat_presence": 1.0},
      "bars": 40, "sections": 3
    }
  ]
}
```

- Every field shown is required; other fields are errors. A new field means a new
  version. `version` is named as in `mpc-iml-grooves` (#245).
- `sources`: each recording's path as given, its file's modification time (the
  recording header has no date) and its number of complete bars. Recordings are
  tracked in this order: modification time, then path.
- `settings`: the tracker thresholds used (`offline.Result.settings`).
- `blind` and `seed`: a blind sort shuffles the cards with `seed`; `card` is each
  groove's letter then, else `null`.
- `counts`: bars of each kind of `offline.KINDS` in all the recordings. Fills and
  free bars are not cards.
- `groups`: `id` (a whole number from 1, unique), `name` and `purpose` (text, may be
  empty while sorting).
- `grooves`: `id` is the tracker id (unique). `group` is a group's `id`, or `null`
  for "not sure". `prototype` holds the steps per role, from 0, as in
  `mpc-iml-grooves`. `features` are the mean `grooves.Features` of the groove's
  bars. `bars` counts the bars that voted; `sections` its groove sections.
- `grooves.groups.read_groups` checks every field; an error is a `GroupsFormatError`
  naming the file and the field, for example
  `groups-20261124-150000.json: grooves[0].group: no group has id 7`.
  `write_groups` checks the same before writing.

### Use by `ensemble` (#250)

A reader matches a groove to a file's grooves by `grooves.similarity` of the
prototypes at `RETURN` (the best match), and takes that groove's `group`. Measures
such as #250's rhythm descriptors are computed from `prototype`, so they are not
stored. A groove marked "not sure" belongs to no group. The recordings are not
needed.

### Privacy

The file stays in the data folder, on the musician's machine (RFC 0005, Scope
rules). The page that writes it runs on 127.0.0.1 only and is absent under
`--share` (#249 PR 3).

## Consequences

- A musician's grouping outlives the session and the recordings.
- Changing the tracker (its thresholds or rules) does not change a saved file; a
  file records the thresholds that made it.
- Tracker ids in a file are only labels within that file. Reopening a file and
  running the tracker again may find other ids; the page then shows prototype-only
  cards (#249 PR 3).
