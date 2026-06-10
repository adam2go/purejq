#!/usr/bin/env python3
"""Benchmark purejq: in-process engine, end-to-end CLI, and JSON loading.

Usage:
    python3 tools/bench.py [N]          # N objects, default 100000
Optional comparisons, used when available:
    - system `jq` binary (or set JQ_BIN=/path/to/jq)
    - the `jq` PyPI package (C bindings), if importable
    - orjson, if importable
"""
from __future__ import annotations

import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import purejq  # noqa: E402

ENGINE_WORKLOADS = [
    (".[] | .name", "field-access stream"),
    ("[.[] | select(.score > 50)] | length", "filter + count"),
    ("map(.score) | add / length", "map + aggregate"),
    ("reduce .[] as $x (0; . + $x.score)", "reduce sum"),
    ("group_by(.team) | map({team: .[0].team, n: length})", "group_by"),
    ("[.[] | {id, name, big: (.score * 2 + 1)}] | sort_by(.big) | .[:5]", "transform + sort"),
    ("[.[] | .tags[]] | unique | length", "nested iteration + unique"),
    ('[.[] | .name | sub("user"; "u")] | length', "regex sub"),
    ("[.[] | select(.name | test(\"7$\"))] | length", "regex filter"),
    ("map(.score) | sort | .[length / 2 | floor]", "median (sort numbers)"),
    ("[.[] | .name + \"-\" + .team] | length", "string concat"),
    ("(.[0:1000] | map(to_entries)) | length", "to_entries (1k objects)"),
]


def make_data(n):
    random.seed(42)
    return [
        {
            "id": i,
            "name": "user-%d" % i,
            "score": random.randint(0, 100),
            "team": random.choice(["red", "green", "blue", "yellow"]),
            "tags": [random.choice(["a", "b", "c", "d", "e"]) for _ in range(3)],
        }
        for i in range(n)
    ]


def best_of(fn, repeat=5):
    """Median of `repeat` runs (named for history; medians resist outliers)."""
    import statistics
    ts = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return statistics.median(ts)


def verify(data, data_file, jq_bin):
    """Assert purejq's outputs are identical to the jq binary's."""
    from purejq.ops import values_equal
    for program, label in ENGINE_WORKLOADS:
        ours = list(purejq.compile(program).run(data))
        r = subprocess.run([jq_bin, "-c", program, data_file],
                           capture_output=True, text=True, check=True)
        theirs = [json.loads(line) for line in r.stdout.strip().split("\n") if line]
        same = len(ours) == len(theirs) and all(
            values_equal(a, b) for a, b in zip(ours, theirs))
        print("%-7s %s" % ("OK" if same else ">>>DIFF", label))
        if not same:
            raise SystemExit("output mismatch on: " + program)
    print("all outputs identical to %s" % jq_bin)


def main():
    args = [a for a in sys.argv[1:] if a != "--verify"]
    do_verify = "--verify" in sys.argv
    n = int(args[0]) if args else 100000
    data = make_data(n)
    impl = platform.python_implementation()
    print("dataset: %d objects | %s %s | median of 5 runs"
          % (n, impl, platform.python_version()))

    jq_bin = os.environ.get("JQ_BIN") or shutil.which("jq")
    try:
        import jq as jq_binding
    except ImportError:
        jq_binding = None

    fd, data_file = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    size_mb = os.path.getsize(data_file) / 1e6

    if do_verify:
        if not jq_bin:
            raise SystemExit("--verify needs the jq binary (PATH or JQ_BIN)")
        print("\n## Verifying outputs against the jq binary")
        verify(data, data_file, jq_bin)

    # --- 1. in-process engine (pre-parsed data, pure filter evaluation) ----
    print("\n## In-process engine (data already parsed)")
    header = "%-32s %10s" % ("workload", "purejq")
    if jq_binding:
        header += " %12s %7s" % ("jq(C-ext)", "ratio")
    print(header)
    print("-" * len(header))
    for program, label in ENGINE_WORKLOADS:
        prog = purejq.compile(program)
        ours = best_of(lambda: list(prog.run(data)))
        line = "%-32s %8.0fms" % (label, ours * 1000)
        if jq_binding:
            cprog = jq_binding.compile(program)
            theirs = best_of(lambda: cprog.input(data).all())
            line += " %10.0fms %6.1fx" % (theirs * 1000, ours / theirs)
        print(line)

    # --- 2. end-to-end CLI (parse + filter + print, like real usage) -------
    print("\n## End-to-end CLI on a %.0f MB file (parse + filter + output)" % size_mb)
    cli_workloads = [
        (".[42].name", "single lookup"),
        ("[.[] | select(.score > 50)] | length", "filter + count"),
        ("group_by(.team) | map(length)", "group_by"),
    ]
    purejq_cli = [sys.executable, "-m", "purejq.cli"]
    header = "%-32s %10s" % ("workload", "purejq")
    if jq_bin:
        header += " %12s %7s" % ("jq (C)", "ratio")
    print(header)
    print("-" * len(header))
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    for program, label in cli_workloads:
        ours = best_of(lambda: subprocess.run(
            purejq_cli + ["-c", program, data_file],
            stdout=subprocess.DEVNULL, check=True, env=env))
        line = "%-32s %8.0fms" % (label, ours * 1000)
        if jq_bin:
            theirs = best_of(lambda: subprocess.run(
                [jq_bin, "-c", program, data_file],
                stdout=subprocess.DEVNULL, check=True))
            line += " %10.0fms %6.1fx" % (theirs * 1000, ours / theirs)
        print(line)

    # --- 3. JSON loading (this is where big files spend their time) --------
    print("\n## Loading the %.0f MB file into Python" % size_mb)
    with open(data_file) as f:
        text = f.read()
    t = best_of(lambda: json.loads(text))
    print("%-32s %8.0fms  (%.0f MB/s)" % ("stdlib json (C-backed)", t * 1000, size_mb / t))
    try:
        import orjson
        t = best_of(lambda: orjson.loads(text))
        print("%-32s %8.0fms  (%.0f MB/s)" % ("orjson [purejq 'speed' extra]", t * 1000, size_mb / t))
    except ImportError:
        print("%-32s %10s" % ("orjson", "not installed"))

    os.unlink(data_file)


if __name__ == "__main__":
    main()
