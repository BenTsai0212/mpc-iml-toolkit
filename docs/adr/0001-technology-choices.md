# ADR 0001: Technology choices, adoption method and licence

- Status: Accepted
- Date: 2026-11-15
- Related: RFC 0001 (project charter)

## Context

RFC 0001 defines mpc-iml-toolkit as a base toolkit for interactive machine learning
with an Akai MPC Sample and a Mac, adopted by separate practice repositories. Four
choices are hard to reverse and shape everything else: the core technology, how
practice repositories adopt the toolkit, the detection tools, and the licence.

Constraints that drive the choices:

- Coding agents and CI cannot reach the MPC hardware, so the core (recording,
  training, running, data handling) must be testable without it.
- The Phase 1 gate is "running within one hour by following the README", and the
  toolkit will be public: few install steps, no paid software.
- All six validation scenarios in RFC 0001 must stay possible, including sound
  classification (3), RAVE (4) and LLM-written mapping code (6).

## Options

### Core technology

- **A. Python core with OSC output.** `python-rtmidi` reads the MPC, `scikit-learn`
  trains and runs models, results are sent over OSC to any synthesiser, Max, Pure
  Data or nn~. Testable with replayed data; clear extension points as Python
  interfaces; free; scenario 6 is natural because mapping code is Python.
  Cost: real-time audio in Python needs care with latency; a higher entry bar for
  musicians who only use Max.
- **B. Max or Pure Data with FluCoMa as the core.** Strong for audio analysis and
  familiar to the NIME community, but patches are hard to diff and test
  automatically, Max is paid, and stable extension points are hard to keep.
- **C. Wekinator as the ML engine with a thin Python bridge.** Fastest path to a
  working loop and a classic IML tool, but the core lives in a GUI that cannot be
  automated or tested, extension points are limited to its features, and it has
  no published releases on GitHub.

### Adoption method

- **A. Installable package plus a practice-repository template.** Practice
  repositories depend on a pinned toolkit version; a small template provides the
  project skeleton only.
- **B. GitHub template repository only.** Practice repositories copy the toolkit
  code, which diverges and cannot follow updates; "do not modify the toolkit"
  cannot be enforced.
- **C. Git submodule.** Pins a commit, but submodules confuse users and the code
  can still be edited in place.

### Licence

- **MIT**: shortest and widely known; same as `python-rtmidi`.
- **Apache-2.0**: adds an explicit patent grant and NOTICE requirements.
- **GPL-3.0**: derivative works must be open source, which deters some researchers
  and musicians.

## Decision

### Core technology: option A

- The core is Python. MIDI input goes through an input interface backed by
  `python-rtmidi`; models use `scikit-learn`; output is OSC via `python-osc`.
- Max, Pure Data, FluCoMa, a Wekinator-compatible adapter, and RAVE / nn~ are
  later extensions, connected through OSC on the output side. They are not part
  of the core.

### Adoption method: option A

- The toolkit is a Python package. While the repository is private, practice
  repositories install it from a git tag (for example
  `mpc-iml-toolkit @ git+https://github.com/<owner>/mpc-iml-toolkit@v0.1.0`);
  after going public (Phase 2) it is published to PyPI.
- Versions follow Semantic Versioning. During `0.x`, breaking changes are allowed
  but each one is recorded in `CHANGELOG.md` with migration notes. From 1.0
  (Phase 3), breaking changes only come with a major version.
- A practice-repository template provides the skeleton (project layout,
  dependency settings, an empty extension-point implementation) and contains no
  toolkit code. Its form (a separate GitHub template repository or a built-in
  command) is decided in the Phase 1 Issue that builds it.

### Detection tools and environment

- Python **3.12**, pinned: the latest version for which `python-rtmidi` publishes
  pre-built macOS wheels.
- **uv** manages the environment; `uv.lock` is committed.
- **ruff** for linting and formatting (`ruff check`, `ruff format --check`).
- **mypy --strict** for type checking `src/`. Re-evaluate ty when it reaches 1.0.
- **pytest** for tests, in two layers:
  - Default tests replay recorded MIDI data through the input interface; CI and
    coding agents run them.
  - Hardware tests are marked `@pytest.mark.hardware`, skipped by default, and run
    by a human with the MPC connected (`uv run pytest -m hardware`). They map to
    `needs-human` follow-ups in Issues.
- CI job `checks` runs, in order: the existing workflow tool tests (Node),
  `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy`, `pytest`.
  It runs on `ubuntu-latest` only while the repository is private; `macos-latest`
  is added after going public.

### Licence: MIT

- The toolkit code is released under the MIT licence. The `LICENSE` file is added
  in the first initialisation pull request.
- Core dependencies are permissive: `python-rtmidi` (MIT), `scikit-learn`
  (BSD-3-Clause), `python-osc` (The Unlicense).
- RAVE and nn~ are licensed CC BY-NC 4.0 (non-commercial only). They stay optional
  extensions: never bundled and never required dependencies. Documentation states
  that practice repositories using them must follow CC BY-NC 4.0.
- Wekinator is GPL-2.0. The toolkit only talks to it over OSC as a separate
  program and never copies or links its code.

## Consequences

Benefits:

- The core can be verified by CI and coding agents without hardware, which serves
  the reproducibility goal in RFC 0001.
- Practice repositories cannot modify the toolkit by accident and can cite an
  exact version in a paper.
- The licence places no limits on community use beyond those of optional
  extensions.

Costs:

- Python 3.12 is pinned; moving to a newer Python, or replacing `python-rtmidi` if
  it stops being maintained, needs a new ADR. The input interface limits the
  impact of such a change.
- Until the repository is public, CI does not run on macOS; behaviour on the Mac
  is verified by hand.
- The public package interface must be designed carefully, since every change
  affects all practice repositories.
- A practice-repository template has to be maintained alongside the toolkit.

Follow-up work:

- First initialisation pull request: `AGENTS.md` section 2 (commands), `ci.yml`,
  README, `LICENSE`.
- Phase 1: a human verifies which USB MIDI messages the MPC Sample sends; the
  example data format is decided in its own ADR; the practice-repository template
  is built.
- Phase 2: publish to PyPI; add `macos-latest` to CI; add `CITATION.cff`.
