# Contributing to purejq

## Development setup

```sh
git clone https://github.com/adam2go/purejq.git
cd purejq
python3 -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/pytest
```

## How conformance testing works

purejq is verified against jq's official test suites, vendored in
[tests/conformance/](tests/conformance/) (`jq.test` and `man.test`).
Each case is a program, an input, and the exact expected output lines.

- `tests/conformance/expected_failures.txt` lists the cases purejq does not
  pass yet. Tests in that list are reported as **xfail**; everything else must pass.
- If your change makes a listed case pass, the suite fails with an
  "now PASSES" message — regenerate the list (and celebrate):

```sh
python3 tools/update_expected_failures.py
```

The header of `expected_failures.txt` records the current pass rate; that
number should only ever go up.

## Compatibility rules

Code must run on Python 3.9+ and PyPy (enforced by the CI matrix):

- no `match` statements
- `from __future__ import annotations` in every module
- no 3.10+-only stdlib APIs

## Performance rules

- Programs are compiled once into generator closures; never interpret the AST
  per value.
- Everything is lazy: a filter must be able to produce its first output
  without computing the rest (`first(f)`, `limit`, infinite generators).
- Run `python3 tools/bench.py` before and after performance-relevant changes.
