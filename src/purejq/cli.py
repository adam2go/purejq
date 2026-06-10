"""Command-line interface, mirroring the common subset of jq's flags."""
from __future__ import annotations

import argparse
import json
import sys

from . import Program
from .encoder import encode, encode_pretty
from .errors import Halt, JqError, JqParseError

try:  # optional accelerator (pip install purejq[speed]); never required
    import orjson as _orjson
except ImportError:
    _orjson = None


def _iter_json(text):
    if _orjson is not None:
        try:
            yield _orjson.loads(text)
            return
        except Exception:
            pass  # multi-document stream, NaN, etc.: use the stdlib decoder
    dec = json.JSONDecoder()
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            return
        value, i = dec.raw_decode(text, i)
        yield value


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="purejq", description="purejq - a pure Python implementation of jq")
    ap.add_argument("program", nargs="?", default=None, help="jq filter to run")
    ap.add_argument("files", nargs="*", help="input files (default: stdin)")
    ap.add_argument("-n", "--null-input", action="store_true",
                    help="use null as the single input value")
    ap.add_argument("-r", "--raw-output", action="store_true",
                    help="output strings without JSON quotes")
    ap.add_argument("-j", "--join-output", action="store_true",
                    help="like -r but without trailing newlines")
    ap.add_argument("-c", "--compact-output", action="store_true",
                    help="compact instead of pretty-printed output")
    ap.add_argument("-s", "--slurp", action="store_true",
                    help="read all inputs into a single array")
    ap.add_argument("-e", "--exit-status", action="store_true",
                    help="set exit status by the last output value")
    ap.add_argument("-f", "--from-file", metavar="FILE",
                    help="read the filter from a file")
    ap.add_argument("--arg", nargs=2, action="append", default=[],
                    metavar=("NAME", "VALUE"), help="bind $NAME to a string value")
    ap.add_argument("--argjson", nargs=2, action="append", default=[],
                    metavar=("NAME", "JSON"), help="bind $NAME to a JSON value")
    args = ap.parse_args(argv)

    if args.from_file:
        with open(args.from_file) as f:
            source = f.read()
        if args.program is not None:
            args.files.insert(0, args.program)
    elif args.program is not None:
        source = args.program
    else:
        ap.error("no filter given")

    try:
        prog = Program(source)
    except JqParseError as e:
        print("purejq: error: %s" % e, file=sys.stderr)
        return 3

    vars = {}
    for name, value in args.arg:
        vars[name] = value
    for name, value in args.argjson:
        try:
            vars[name] = json.loads(value)
        except ValueError as e:
            print("purejq: invalid JSON for --argjson %s: %s" % (name, e), file=sys.stderr)
            return 2

    if args.files:
        text = "".join(open(f).read() for f in args.files)
    elif not args.null_input:
        text = sys.stdin.read()
    else:
        text = ""

    try:
        values = list(_iter_json(text))
    except ValueError as e:
        print("purejq: invalid JSON input: %s" % e, file=sys.stderr)
        return 2

    if args.null_input:
        runs = [(None, iter(values))]
    elif args.slurp:
        runs = [(values, iter(()))]
    else:
        # Each value is one program run; `input`/`inputs` consume the rest.
        shared = iter(values)
        runs = _consume(shared)

    last = None
    had_output = False
    code = 0
    out = sys.stdout
    try:
        for value, inputs in runs:
            for result in prog.run(value, inputs=inputs, vars=vars):
                last = result
                had_output = True
                if (args.raw_output or args.join_output) and isinstance(result, str):
                    out.write(result)
                elif args.compact_output:
                    out.write(encode(result))
                else:
                    out.write(encode_pretty(result))
                if not args.join_output:
                    out.write("\n")
    except JqError as e:
        print("purejq: error: %s" % e, file=sys.stderr)
        code = 5
    except Halt as h:
        if h.payload is not None:
            if isinstance(h.payload, str):
                sys.stderr.write(h.payload)
            else:
                sys.stderr.write(encode(h.payload) + "\n")
        code = h.code
    except BrokenPipeError:
        return 0

    if args.exit_status and code == 0:
        if not had_output:
            code = 4
        elif last is None or last is False:
            code = 1
    return code


def _consume(shared):
    for v in shared:
        yield v, shared


if __name__ == "__main__":
    sys.exit(main())
