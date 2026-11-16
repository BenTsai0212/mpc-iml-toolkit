# Dependency licences

The toolkit is released under the [MIT licence](../LICENSE) (ADR 0001). This
document lists every runtime dependency resolved in `uv.lock`, direct and
indirect, with its licence, and records whether it is compatible with MIT.

Development-only dependencies (ruff, mypy, pytest and their dependencies) and the
build backend (hatchling) are not installed with the toolkit and are not listed.

## Runtime dependencies

Versions are the ones pinned in `uv.lock`. Licences are taken from each
package's metadata (`License-Expression`, `License` or classifiers) and the
licence file shipped in its wheel.

| Package | Version | Required by | Licence |
| --- | --- | --- | --- |
| python-osc | 1.10.3 | toolkit (direct) | Unlicense (public-domain dedication) |
| python-rtmidi | 1.5.8 | toolkit (direct) | MIT; bundles RtMidi under a modified MIT licence (see below) |
| scikit-learn | 1.9.1 | toolkit (direct) | BSD-3-Clause |
| joblib | 1.6.0 | scikit-learn | BSD-3-Clause |
| cloudpickle | 3.1.2 | joblib | BSD-3-Clause |
| narwhals | 2.28.0 | scikit-learn | MIT |
| numpy | 2.5.5 | scikit-learn, scipy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| scipy | 1.18.1 | scikit-learn | BSD-3-Clause |
| threadpoolctl | 3.8.0 | scikit-learn | BSD-3-Clause |

No runtime dependency has a platform marker in `uv.lock`, so the same nine
packages are installed on macOS and Linux.

### Notes

- **python-osc** has no licence file in its wheel; its metadata contains the
  full Unlicense text ("free and unencumbered software released into the public
  domain"), with the classifier `License :: Freely Distributable`.
- **RtMidi**, the C++ library inside python-rtmidi, uses the MIT licence with
  one extra sentence asking people who distribute modifications to send them
  upstream. The licence states that this request is "not a binding provision".
- **Native libraries bundled in binary wheels.** Some wheels ship compiled
  libraries and list their licences in the wheel's own licence file. In the
  Linux x86-64 wheels checked for this document:
  - numpy and scipy bundle OpenBLAS (BSD-3-Clause) with LAPACK
    (BSD-3-Clause-Open-MPI) and the GCC runtime library libgfortran
    (GPL-3.0-or-later WITH GCC-exception-3.1).
  - scipy also bundles libquadmath (LGPL-2.1-or-later), dynamically linked.
  - scikit-learn bundles the GCC runtime library libgomp
    (GPL-3.0-or-later WITH GCC-exception-3.1).

  Wheels for other platforms (for example macOS) may bundle a different set;
  check the licence file in the installed `*.dist-info` folder. These libraries
  are part of the numpy, scipy and scikit-learn distributions, which users
  install from PyPI. The toolkit does not copy, modify or redistribute them.

## Conclusion

All runtime dependencies are under permissive licences (MIT, BSD-3-Clause,
0BSD, Zlib, CC0-1.0, Unlicense) that allow use from an MIT-licensed project,
including commercial use. The toolkit depends on these packages and does not
bundle them, so it can stay under MIT.

The native libraries bundled inside the numpy, scipy and scikit-learn wheels
(GCC runtime libraries under the GCC Runtime Library Exception, libquadmath
under LGPL-2.1-or-later) are distributed by those projects, not by the toolkit,
and do not change the toolkit's licence. If the toolkit is ever distributed
together with its dependencies (for example as a standalone app bundle), review
these licences again for that distribution.

## Optional extensions

Optional extensions such as RAVE and nn~ are licensed under CC BY-NC 4.0
(non-commercial only). They are neither bundled with nor required by the
toolkit, are not in `uv.lock`, and are not covered by this document. Anyone who
installs them must follow their licences separately.

## Updating this document

Update this document in the same pull request whenever `pyproject.toml` or
`uv.lock` changes the runtime dependencies (added, removed or upgraded
packages).

1. List the runtime dependencies and their versions:

   ```bash
   uv sync --locked
   uv tree --no-dev
   ```

2. Read each package's licence from its installed metadata:

   ```bash
   uv run python -c "from importlib.metadata import distribution as d; import sys; [print(n, d(n).version, d(n).metadata.get('License-Expression') or d(n).metadata.get('License', '').splitlines()[:1], [c for c in d(n).metadata.get_all('Classifier') or [] if c.startswith('License')]) for n in sys.argv[1:]]" python-osc python-rtmidi scikit-learn joblib cloudpickle narwhals numpy scipy threadpoolctl
   ```

   Replace the package names with the ones from `uv tree --no-dev`. When the
   metadata is missing or unclear, read the licence file in the package's
   `*.dist-info` folder or the project's repository.

3. Update the table and notes. If a licence is not permissive (for example GPL,
   AGPL, LGPL or a non-commercial licence), or cannot be determined, do not add the dependency; ask the decider first.
