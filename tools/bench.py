#!/usr/bin/env python3
"""Benchmark purejq against the system jq binary on representative workloads."""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import purejq  # noqa: E402

WORKLOADS = [
    (".[] | .name", "stream of field accesses"),
    ("[.[] | select(.score > 50)] | length", "filter + count"),
    ("map(.score) | add / length", "map + aggregate"),
    ("group_by(.team) | map({team: .[0].team, n: length})", "group_by"),
    ("[.[] | {id, name, big: (.score * 2 + 1)}] | sort_by(.big) | .[:5]", "transform + sort"),
    ('[.[] | .tags[]] | unique | length', "nested iteration + unique"),
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


def bench_purejq(program, data, repeat=3):
    prog = purejq.compile(program)
    best = float("inf")
    for _ in range(repeat):
        t = time.perf_counter()
        for _out in prog.run(data):
            pass
        best = min(best, time.perf_counter() - t)
    return best


def bench_jq(jq_bin, program, data_file, repeat=3):
    best = float("inf")
    for _ in range(repeat):
        t = time.perf_counter()
        subprocess.run([jq_bin, "-c", program, data_file],
                       stdout=subprocess.DEVNULL, check=True)
        best = min(best, time.perf_counter() - t)
    return best


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100000
    data = make_data(n)
    print("dataset: %d objects, python %s" % (n, sys.version.split()[0]))

    jq_bin = shutil.which("jq")
    data_file = None
    if jq_bin:
        fd, data_file = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        print("comparing against: %s" % jq_bin)
    else:
        print("system jq not found; benchmarking purejq only")

    header = "%-55s %10s" % ("workload", "purejq")
    if jq_bin:
        header += " %10s %8s" % ("jq (C)", "ratio")
    print(header)
    print("-" * len(header))
    for program, label in WORKLOADS:
        ours = bench_purejq(program, data)
        line = "%-55s %9.0fms" % (label, ours * 1000)
        if jq_bin:
            theirs = bench_jq(jq_bin, program, data_file)
            line += " %9.0fms %7.1fx" % (theirs * 1000, ours / theirs)
        print(line)

    if data_file:
        os.unlink(data_file)


if __name__ == "__main__":
    main()
