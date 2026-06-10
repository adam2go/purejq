# purejq

A pure Python implementation of [jq](https://jqlang.github.io/jq/), the command-line JSON processor.

**Status: pre-alpha, under active development.**

## Why

- The existing [`jq` PyPI package](https://pypi.org/project/jq/) is a C binding — it needs compiled wheels and can't run where C extensions can't (Pyodide/WASM, restricted sandboxes).
- `purejq` aims to be pip-installable everywhere Python runs, with zero non-Python dependencies.
- Conformance is verified against the official jq test suite (`tests/conformance/jq.test`).

Inspired by [gojq](https://github.com/itchyny/gojq) (Go) and [jaq](https://github.com/01mf02/jaq) (Rust).

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/pytest
```

## License

MIT
