# purejq

[![CI](https://github.com/adam2go/purejq/actions/workflows/ci.yml/badge.svg)](https://github.com/adam2go/purejq/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%E2%80%933.14%20%7C%20PyPy-blue)](https://github.com/adam2go/purejq/blob/main/.github/workflows/ci.yml)
[![Conformance](https://img.shields.io/badge/jq%20test%20suite-96.2%25-brightgreen)](tests/conformance/expected_failures.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A pure Python implementation of [jq](https://jqlang.github.io/jq/), the
command-line JSON processor — in the spirit of [gojq](https://github.com/itchyny/gojq) (Go)
and [jaq](https://github.com/01mf02/jaq) (Rust).

**No C extension. No binary. If Python runs, purejq runs** — including
Pyodide/WASM, AWS Lambda layers you can't compile in, restricted sandboxes,
and anywhere `pip install` is all you get.

```sh
$ echo '{"users":[{"name":"alice","age":30},{"name":"bob","age":25}]}' \
    | purejq '.users[] | select(.age > 26) | .name'
"alice"
```

## Why another jq?

| | C jq | `jq` PyPI package | **purejq** |
|---|---|---|---|
| needs a compiled binary / wheel | yes | yes (C bindings) | **no** |
| runs on Pyodide / WASM | no | no | **yes** |
| embeds in Python (call functions, pass dicts) | no | partially | **yes** |
| arbitrary-precision integers | no | no | **yes** |

The existing [`jq` PyPI package](https://pypi.org/project/jq/) is excellent
when you can ship compiled wheels. purejq is for when you can't — or when you
want to read and hack the implementation in one afternoon.

## Install

```sh
pip install purejq            # nothing but Python
pip install 'purejq[speed]'   # + orjson for faster JSON parsing in the CLI
```

*(Not yet published to PyPI — install from source for now: `pip install git+https://github.com/adam2go/purejq`)*

## Usage

### CLI (drop-in for common jq usage)

```sh
purejq '.foo[] | select(.bar > 2)' data.json
cat data.json | purejq -r '.items[].name'     # raw output
purejq -n 'range(3) | . * 2'                  # null input
purejq -c --arg name alice '{user: $name}'    # compact output, variables
```

Supported flags: `-n -r -j -c -s -e -f --arg --argjson`.

### Python API

```python
import purejq

# one-shot
purejq.first(".a.b", {"a": {"b": 42}})          # 42
purejq.all_outputs(".[] | . * 2", [1, 2, 3])    # [2, 4, 6]

# compile once, run on many inputs (the fast way)
prog = purejq.compile("[.[] | select(.score > 50)] | length")
for batch in batches:
    print(prog.first(batch))

# results are a lazy iterator — infinite streams are fine
prog = purejq.compile("repeat(. * 2)")
it = prog.run(1)
next(it), next(it), next(it)                    # 2, 4, 8
```

## Conformance: measured, not claimed

purejq is tested against **jq's own official test suite** (vendored in
[tests/conformance/](tests/conformance/)): **751 of 781 cases pass (96.2%)**.

Every remaining failure is listed with its reason in
[expected_failures.txt](tests/conformance/expected_failures.txt) and falls in
one of these known buckets:

- **module system** (`import` / `include` / `modulemeta`) — not implemented yet
- **number representation** — Python integers are arbitrary-precision, so
  `13911860366432393` stays exact instead of rounding like a C double. This is
  the same deliberate difference gojq made; for AI/data pipelines exactness is
  usually what you want
- **error-message wording** in a handful of edge cases (e.g. Python's JSON
  parser phrases syntax errors differently)

Implemented and conformance-tested: the full expression language (paths,
all assignment operators, `reduce`/`foreach`, `try`/`catch`, `label`/`break`,
destructuring with `?//` alternatives, string interpolation, all `@formats`),
regex builtins (`test`/`match`/`capture`/`scan`/`sub`/`gsub` via Python `re`),
`tostream`/`fromstream`, date builtins, SQL-ish builtins, and jq 1.8 additions
(`pick`, `abs`, `toboolean`, `trim`, `have_decnum`, …).

## Performance

Honest framing: a pure Python jq will not beat the C implementation on raw
throughput. The design keeps it in usable territory:

- **compile once, run many** — programs compile to Python generator closures;
  evaluation never re-walks the AST
- **fully lazy streams** — `first(f)`, `limit`, and infinite generators cost
  only what they consume
- **C-speed JSON parsing** — input parsing uses Python's C-backed `json`
  module (or [orjson](https://github.com/ijl/orjson) if installed via
  `purejq[speed]`), so the parse-heavy part of typical workloads is not
  written in Python at all
- **PyPy as the escape hatch** — purejq is tested on PyPy in CI; interpreter
  workloads typically run ~10x faster there

Run the benchmark yourself (compares against the system `jq` if installed):

```sh
python3 tools/bench.py 100000
```

Reference numbers (M-series MacBook, CPython 3.13, 100k objects):
field-access streams ~11 ms, map+aggregate ~24 ms, group_by ~120 ms,
transform+sort ~220 ms.

## Compatibility

CPython **3.9 – 3.14** and **PyPy**, enforced by the
[CI matrix](.github/workflows/ci.yml) on every push. Zero runtime
dependencies.

## Architecture

```
source ──lexer──▶ tokens ──parser──▶ AST (tuples)
                                      │ compile (once)
                                      ▼
                    generator closures: f(value, env) → iterator
                                      │
              path mode: g(value, path, env) → (path, value) pairs
                        (powers path(), del(), and all assignments)
```

- [lexer.py](src/purejq/lexer.py) / [parser.py](src/purejq/parser.py) — jq grammar, including string interpolation
- [compiler.py](src/purejq/compiler.py) — closure compilation, environments, value & path modes
- [ops.py](src/purejq/ops.py) — jq value semantics: total ordering, arithmetic, path read/write
- [builtins.py](src/purejq/builtins.py) — Python-native builtins (regex, sort, math, dates, formats)
- [prelude.py](src/purejq/prelude.py) — derived builtins defined in jq itself, mirroring jq's `builtin.jq`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: make a conformance
number go up, and `python3 tools/update_expected_failures.py` is your
scoreboard.

## License

[MIT](LICENSE)
