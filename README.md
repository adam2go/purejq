# purejq

[![CI](https://github.com/adam2go/purejq/actions/workflows/ci.yml/badge.svg)](https://github.com/adam2go/purejq/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/purejq)](https://pypi.org/project/purejq/)
[![Python](https://img.shields.io/badge/python-3.9%E2%80%933.14%20%7C%20PyPy-blue)](.github/workflows/ci.yml)
[![Conformance](https://img.shields.io/badge/jq%20test%20suite-96.2%25-brightgreen)](tests/conformance/expected_failures.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**[jq](https://jqlang.github.io/jq/), as a pure Python library.** No C extension, no
binary: if Python runs, purejq runs — Pyodide/WASM, sandboxes, Lambda,
anywhere `pip install` is all you get.

```sh
pip install purejq
```

```python
import purejq

purejq.first(".users[] | select(.age > 26) | .name", data)   # work on your dicts directly
prog = purejq.compile("group_by(.team) | map(length)")        # compile once, run many
prog.first(batch)
```

```sh
echo '{"a":[1,2,3]}' | purejq '.a | map(. * 2)'               # familiar CLI, same flags
```

## Why purejq

- **Embedding jq in Python? purejq is 6–40x faster than the C bindings.**
  The [`jq` PyPI package](https://pypi.org/project/jq/) serializes your data
  to JSON text and back on every call; purejq evaluates directly on Python
  objects.
- **On big files, the CLI beats the C jq binary end-to-end.** Large-file runs
  are dominated by JSON parsing, and CPython's C-backed parser is faster than
  jq's.
- **It's real jq**: 751/781 cases (96.2%) of jq's own test suite pass —
  the suite is vendored in this repo and run in CI on every commit.

Where C jq still wins: raw filter throughput on already-parsed streams in
shell pipelines. If you can install binaries and that's your workload, use jq.

## Benchmarks

Measured with [tools/bench.py](tools/bench.py): M-series MacBook, CPython
3.13, jq 1.8.1 (native arm64), **median of 7 runs**, and every workload's
output verified byte-identical against the jq binary first. Reproduce both:
`python3 tools/bench.py 1000000 --verify`.

**Embedded in Python** — 100k-object array, already parsed, in-process:

| workload | purejq | `jq` PyPI (C bindings) |
|---|---:|---:|
| field-access stream | 9 ms | 368 ms |
| filter + count | 55 ms | 442 ms |
| map + aggregate | 18 ms | 444 ms |
| group_by | 112 ms | 704 ms |
| transform + sort | 136 ms | 899 ms |
| regex filter | 127 ms | 747 ms |

*The binding numbers are its best case (JSON text input); passing Python
objects, its usual mode, is another ~10% slower.*

**Command line, end to end** — 93 MB file (1M objects), parse + filter + output:

| workload | purejq | jq 1.8 (C binary) |
|---|---:|---:|
| single lookup | 0.51 s | 1.68 s |
| filter + count | 1.08 s | 1.96 s |
| group_by | 2.32 s | 3.89 s |

*purejq CLI measured with the optional [orjson](https://github.com/ijl/orjson)
extra (`pip install 'purejq[speed]'`); with stdlib json alone it is ~25–35%
slower and still ahead on these workloads.*

**Loading large JSON into Python**: the 93 MB file parses in 0.73 s with
stdlib json (128 MB/s) or 0.43 s with orjson (219 MB/s) — input loading is
C-speed either way and scales linearly.

**PyPy** (100k objects, same code, no changes): filter + count 13 ms,
map + aggregate 2 ms, group_by 33 ms, transform + sort 70 ms — roughly
another 2–9x over CPython for heavy workloads.

How it's fast, in one line: programs compile once into Python closures with
static binding and single-output fast paths — evaluation never re-walks the
AST, and common shapes skip generator machinery entirely.

## jq compatibility

751/781 of jq's official test suite. Every remaining difference is listed in
[expected_failures.txt](tests/conformance/expected_failures.txt); they fall
into three buckets:

- the **module system** (`import`/`include`) is not implemented yet
- **integers are exact** (arbitrary precision, like gojq) instead of rounding
  to doubles — deliberate
- a few **error-message wordings** differ

Everything else is there: paths and all assignment operators,
`reduce`/`foreach`, `try`/`catch`, `label`/`break`, `?//` destructuring,
string interpolation, `@formats`, regex builtins, streaming
(`tostream`/`fromstream`), dates, and jq 1.8 additions.

CLI flags: `-n -r -j -c -s -e -f --arg --argjson`. Outputs are lazy
iterators — `purejq.compile("repeat(. * 2)").run(1)` happily yields forever.

## Compatibility

CPython 3.9–3.14 and PyPy, zero runtime dependencies, enforced by
[CI](.github/workflows/ci.yml) on every push.

## Contributing & internals

See [CONTRIBUTING.md](CONTRIBUTING.md) — the conformance suite is the
scoreboard, `tools/bench.py` is the speedometer.

## License

[MIT](LICENSE)
