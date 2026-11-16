# ADR 0004: Engine control protocol

- Status: Accepted
- Date: 2026-11-16
- Related: RFC 0002, ADR 0002, #61 (Epic), #62, #63, #64, #69

## Context

RFC 0002 turns the IML loop into a long-running engine that musicians control from
their patching environment. Front ends (Pure Data first, then Max for Live, later an
app) only send and receive OSC control messages, so the control protocol is a
public, versioned interface. ADR 0002 already fixes the data output (`/wek/inputs`
and `/wek/outputs`) and left Wekinator control messages out of Phase 1.

This ADR records the protocol, version 1.0. It stayed `Proposed` until the engine
implementation (#64, #69) confirmed it.

## Options

### Transport and where replies go

- **Fixed default reply port that `hello` can change (chosen).** Pure Data
  (`[netreceive -u -b 6451]`) and Max (`[udpreceive 6451]`) listen on a known port
  without extra setup.
- **Reply to the sender's source address and port.** No configuration, but Pd's
  `[netsend]` sends from a random port that a patch cannot easily receive on.
- Port numbers: **6450/6451 (chosen)**, next to Wekinator's ports, or 9000/9001,
  common in TouchOSC and so more likely to collide.

### Address prefix

- **`/mpciml/` (chosen)**, matching the import name.
- `/engine/`: shorter, but generic and more likely to clash with other software.

### Wekinator control messages as aliases

- **Not now (chosen).** Out of scope, and Wekinator has no state reporting. They can
  be added later as a minor change.
- Accept `/wekinator/control/startRecording` and similar as aliases in 1.0.

### When to report state

- **On change and on request only (chosen).** A front end can use `ping` to check
  that the engine is alive.
- Also a heartbeat once a second. Adding it later is a minor change.

### Major version mismatch

- **Send `version_mismatch` and keep accepting messages (chosen).** The user can
  still see and fix the front end.
- Ignore every message except `hello` until the major versions match. Stricter, but
  a patch that skipped `hello` stops working with no visible cause.

### Messages added by presets

- **Each preset owns the subtree `/mpciml/preset/<name>/…` (chosen).**
- Presets register top-level addresses. Rejected: two presets, or a preset and a
  future core message, could clash.

## Decision

### Transport and ports

- OSC over UDP on `127.0.0.1`. All hosts and ports are configurable; the values
  below are defaults.

| Direction | Default | Contents |
| --- | --- | --- |
| Control in | engine listens on `127.0.0.1:6450` | Messages in the next table |
| Replies out | engine sends to `127.0.0.1:6451` | Replies and state reports; `hello` can change the port |
| Gesture features out | `127.0.0.1:6448` | `/wek/inputs`, unchanged from ADR 0002 |
| Model outputs out | `127.0.0.1:12000` | `/wek/outputs`, unchanged from ADR 0002 |

- Control and data stay on separate ports: existing Wekinator receivers and synth
  patches keep working, and frames at 100 Hz never queue behind control replies.
  `6448` is Wekinator's own listening port, so the engine does not listen there.
- For the engine, this ADR replaces ADR 0002's "Not in Phase 1: Wekinator control
  messages" with its own control protocol. `/wek/inputs` and `/wek/outputs` do not
  change.

### Control messages

All control messages use the prefix `/mpciml/`. OSC type tags: `i` int32, `f`
float32, `s` string; `…` means zero or more of that type.

| Address | Arguments | Effect |
| --- | --- | --- |
| `/mpciml/hello` | `i` protocol major, optional `i` reply port | Sends back `version` and the full state |
| `/mpciml/ping` | none | Sends back `/mpciml/pong` |
| `/mpciml/state/get` | none | Sends back the full state |
| `/mpciml/record/start` | none | Starts an example with the current class or targets |
| `/mpciml/record/stop` | none | Ends the example and adds it to the example set |
| `/mpciml/class` | `s` label | Sets the class for the next recordings (classification) |
| `/mpciml/targets` | `f`… values | Sets the target values (regression); the count must match the model's outputs |
| `/mpciml/examples/delete` | `s` label | Deletes the examples of one class; its class number stays reserved, as in `ExampleSet.remove` |
| `/mpciml/examples/clear` | none | Deletes all examples |
| `/mpciml/examples/save` | `s` name | Saves the example set as a recording (ADR 0002 format) in the engine's data folder; an existing set with that name is replaced |
| `/mpciml/examples/load` | `s` name | Replaces the example set with a saved one |
| `/mpciml/examples/list` | none | Sends back the saved names |
| `/mpciml/train` | none | Trains in the background; a running model is swapped when training finishes |
| `/mpciml/run` | none | Starts sending `/wek/inputs` and `/wek/outputs` |
| `/mpciml/stop` | none | Stops running or recording and returns to `idle` |
| `/mpciml/preset/list` | none | Sends back the installed presets |
| `/mpciml/preset/load` | `s` name | Switches presets; the example set is cleared unless the new preset is the same one |

- Names for `examples/save`, `examples/load` and `preset/load` are names, not paths:
  letters, digits, `-` and `_` only. Saved example sets live in the engine's data
  folder, so anything that sends to the control port cannot read or overwrite other
  files. Any other name is `bad_arguments`.
- `stop` while `recording` discards the example in progress; only `record/stop`
  keeps it.

### Replies and state reports

| Address | Arguments | When |
| --- | --- | --- |
| `/mpciml/version` | `i` major, `i` minor, `s` engine version | Reply to `hello` |
| `/mpciml/pong` | none | Reply to `ping` |
| `/mpciml/state` | `s` one of `idle`, `recording`, `training`, `running` | On every state change and in the full state |
| `/mpciml/preset` | `s` name, `s` preset version | On preset load and in the full state |
| `/mpciml/counts` | pairs of `s` label and `i` count; regression uses the label `""` | After `record/stop`, `examples/delete`, `examples/clear`, `examples/load`, `preset/load` and in the full state |
| `/mpciml/trained` | `i` 0 or 1 | When it changes and in the full state |
| `/mpciml/train/done` | `f` seconds | Training finished |
| `/mpciml/train/failed` | `s` reason | Training failed (for example no examples); the previous model stays in use |
| `/mpciml/presets` | `s`… names | Reply to `preset/list` |
| `/mpciml/examples/names` | `s`… names | Reply to `examples/list` |
| `/mpciml/error` | `s` code, `s` address received, `s` message | See Errors |

- The full state is `state`, `preset`, `counts` and `trained`, sent in that order.
- Reports are sent on change and on request only; there is no heartbeat in 1.0.
- Training from `idle` sets the state to `training` and back to `idle` when it
  ends. Retraining while `running` keeps the state `running` and only sends
  `train/done` or `train/failed` (and `trained` if it changed).

### States

Which messages each state accepts (✓ accepted, ✗ `wrong_state`):

| Message | `idle` | `recording` | `training` | `running` |
| --- | --- | --- | --- | --- |
| `hello`, `ping`, `state/get`, `examples/list`, `preset/list` | ✓ | ✓ | ✓ | ✓ |
| `record/start` | ✓ | ✗ | ✗ | ✗ |
| `record/stop` | ✗ | ✓ | ✗ | ✗ |
| `class`, `targets` | ✓ | ✗ | ✓ | ✓ |
| `examples/delete`, `examples/clear`, `examples/load` | ✓ | ✗ | ✗ | ✓ |
| `examples/save` | ✓ | ✗ | ✓ | ✓ |
| `train` | ✓ | ✗ | ✗ | ✓ (✗ while a retrain is already in progress) |
| `run` | ✓ (✗ before a model is trained) | ✗ | ✗ | ✗ |
| `stop` | ✓ (does nothing) | ✓ | ✗ | ✓ |
| `preset/load` | ✓ | ✗ | ✗ | ✗ |

- A message in the wrong state changes nothing: there is no implicit stop and
  start.
- Messages under `/mpciml/preset/<name>/…` follow the preset's own rules.

### Versioning

- The protocol version is `major.minor`, starting at **1.0**. It is written in this
  ADR and as a constant in the engine code.
- `hello` carries the client's major version. If it differs from the engine's, the
  engine sends `/mpciml/error version_mismatch …`, sends its own `version`, and keeps
  accepting messages.
- **Breaking (new major):** removing or renaming a message or reply, changing the
  type, order or meaning of an argument, changing a default port, or changing the
  state names or the meaning of a state.
- **Minor:** a new message, a new reply, a new optional argument at the end, or a
  new error code.
- Once this ADR is `Accepted`, each new protocol version is recorded in a new ADR,
  as the ADR rules require.

### Preset messages

- Each preset owns the subtree `/mpciml/preset/<name>/…`. The core protocol never
  uses that subtree for anything else; the core messages `/mpciml/preset/list` and
  `/mpciml/preset/load` are not preset names, so presets cannot be named `list` or
  `load`.
- The engine forwards a message there only when `<name>` is the active preset;
  otherwise it sends the error `inactive_preset`.
- A preset's controls map to `/mpciml/preset/<name>/<control>`. The plugin interface
  (#63) keeps its `controls` field provisional until this ADR is accepted.
- A preset's messages are versioned by the preset version reported in
  `/mpciml/preset`, not by the protocol version, so a preset can change without a
  new protocol major.
- Replies from a preset go out on the reply port under the same subtree.

### Errors

The engine never crashes on a control message and never silently drops one. Each
problem produces one `/mpciml/error` with a code from this list:

| Code | Meaning |
| --- | --- |
| `unknown_message` | An address the engine does not know |
| `bad_arguments` | Wrong count or type, an invalid name, or `targets` with the wrong number of values |
| `wrong_state` | Not allowed in the current state (see States); the message text names the current state |
| `not_found` | Unknown preset or saved example set |
| `version_mismatch` | `hello` with a different major version |
| `inactive_preset` | A message to the subtree of a preset that is not active |

### Clarifications from the implementation

The engine (#64, #69) implemented every message, reply, state rule and error code
above as written. Where this ADR was silent, it behaves as follows; none of these
changes a message, reply, state rule or error code.

1. `record/start` with no class or targets set: `bad_arguments` ("send
   /mpciml/class or /mpciml/targets first").
2. Internal failures (for example a disk error during `examples/save`):
   `bad_arguments` with the text `internal error: …`. The engine does not crash.
3. A saved set that cannot be read or does not fit the preset (wrong format,
   classification mixed with regression): `bad_arguments`. `not_found` is used only
   when the file is missing.
4. A preset with `model_factory=None` (Wekinator as the model) cannot `run` in 1.0:
   `run` needs a trained model, and `train` replies `train/failed`.
5. `stop` during a retrain in `running` waits for the training to finish before
   going `idle`, so no training runs in the background in `idle`.
6. Preset controls: an unknown control under the active preset gets
   `unknown_message`; a handler that raises gets `bad_arguments`. Preset replies
   under the subtree are not possible yet, because the provisional `controls` type
   has no reply channel.
7. Argument types: integer arguments (the `hello` major version and reply port)
   also accept a float with a whole-number value, such as `1.0`, because Pure Data
   sends numbers as floats without a type tag; a float that is not a whole number is
   `bad_arguments`. `targets` also accepts `i` values.
8. `stop` in `idle`, `class` and `targets` send no reply. `train` with no examples
   replies `train/failed` without entering `training`.
9. `counts` lists every known class in class-number order, including classes with 0
   examples (a preset's fixed classes, deleted labels).
10. Saved example sets use the ADR 0002 recording format, in which a pad's velocity
    cannot return to 0 once set. So a pad not hit at the start of a later example in
    the same file keeps a velocity from earlier in the file. This only affects
    features that use the velocity of released pads.

## Consequences

Benefits:

- Every front end speaks one documented protocol, so a later app is one more front
  end, not an engine rewrite.
- Existing Wekinator receivers and ADR 0002 data output keep working unchanged.
- Front ends always learn the result of a message: a reply, a state report or an
  error.
- Presets add controls without touching the core protocol or each other.

Costs:

- Front ends cannot drive the engine with Wekinator's own control messages yet.
- Without a heartbeat, a front end only notices that the engine has quit by sending
  `ping`.
- Training cannot be cancelled in 1.0.
- UDP gives no delivery guarantee; on `127.0.0.1` this is accepted.

Follow-up work:

- Done: the engine and its replay tests implement this protocol (#64, #69), and this
  ADR is `Accepted`.
- Open, for a minor protocol version (recorded in a new ADR): an error code for
  internal failures, instead of `bad_arguments` (clarification 2), and a reply
  channel for preset controls, so presets can reply under their subtree
  (clarification 6).
- Build the reference Pure Data front end on ports 6450/6451.
- Finalise the `controls` field of the plugin interface (#63).
