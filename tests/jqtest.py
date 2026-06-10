"""Parser and runner for jq's official .test suite format.

A test is a group of consecutive non-blank lines: program, one JSON input,
then zero or more expected outputs (one compact JSON value per line).
`%%FAIL` groups contain a program that must fail to compile/run.
"""
from __future__ import annotations

import json
import os
import sys

sys.setrecursionlimit(100000)
# jq's own test suite runs with PAGER=less in the environment
os.environ.setdefault("PAGER", "less")

HERE = os.path.dirname(os.path.abspath(__file__))
CONFORMANCE_DIR = os.path.join(HERE, "conformance")
EXPECTED_FAILURES_FILE = os.path.join(CONFORMANCE_DIR, "expected_failures.txt")

MAX_OUTPUTS = 100000
CASE_TIMEOUT_SECONDS = 10


class _CaseTimeout(Exception):
    pass


class _time_limit:
    """Abort a runaway case via SIGALRM (no-op where unavailable, e.g. Windows)."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.armed = False

    def __enter__(self):
        import signal
        import threading
        if hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread():
            def handler(signum, frame):
                raise _CaseTimeout()
            self._old = signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, self.seconds)
            self.armed = True
        return self

    def __exit__(self, *exc):
        if self.armed:
            import signal
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._old)
        return False


class Case:
    __slots__ = ("kind", "program", "input_text", "expected", "id")

    def __init__(self, kind, program, input_text, expected, id):
        self.kind = kind  # "ok" or "fail"
        self.program = program
        self.input_text = input_text
        self.expected = expected
        self.id = id


def parse_test_file(path):
    name = os.path.basename(path)
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    cases = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        case_id = "%s:%d" % (name, i + 1)
        if line.startswith("%%FAIL"):
            program = lines[i + 1] if i + 1 < n else ""
            cases.append(Case("fail", program, None, None, case_id))
            i += 2
            while i < n and lines[i].strip():  # error message may span lines
                i += 1
            continue
        program = line
        input_text = lines[i + 1] if i + 1 < n else "null"
        expected = []
        j = i + 2
        while j < n and lines[j].strip():
            if not lines[j].lstrip().startswith("#"):
                expected.append(lines[j])
            j += 1
        cases.append(Case("ok", program, input_text, expected, case_id))
        i = j
    return cases


def load_all_cases():
    cases = []
    for fname in ("jq.test", "man.test"):
        path = os.path.join(CONFORMANCE_DIR, fname)
        if os.path.exists(path):
            cases.extend(parse_test_file(path))
    return cases


def load_expected_failures():
    ids = set()
    if os.path.exists(EXPECTED_FAILURES_FILE):
        with open(EXPECTED_FAILURES_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ids.add(line.split("\t")[0].split(" ")[0])
    return ids


def run_case(case):
    try:
        with _time_limit(CASE_TIMEOUT_SECONDS):
            return _run_case(case)
    except _CaseTimeout:
        return False, "timeout after %ds" % CASE_TIMEOUT_SECONDS


def _run_case(case):
    """Run one case. Returns (ok, detail)."""
    import purejq
    from purejq.encoder import encode
    from purejq.errors import Halt, JqError, JqParseError

    if case.kind == "fail":
        try:
            prog = purejq.compile(case.program)
            outs = []
            for v in prog.run(None):
                outs.append(v)
                if len(outs) > MAX_OUTPUTS:
                    break
        except (JqParseError, JqError, Halt):
            return True, ""
        except RecursionError:
            return True, ""
        except Exception as e:  # internal error: still a bug, surface it
            return False, "internal %s: %s" % (type(e).__name__, e)
        return False, "expected failure, but program ran and produced %d outputs" % len(outs)

    import re
    text = case.input_text.lstrip("﻿")
    # jq's JSON parser accepts nan/-nan/-NaN; Python's only accepts NaN.
    text = re.sub(r'(?<![\w"])-?[nN]a[nN](?![\w"])', "NaN", text)
    try:
        value = json.loads(text)
    except ValueError as e:
        return False, "unparseable test input: %s" % e
    try:
        expected = [json.loads(line) for line in case.expected]
    except ValueError as e:
        return False, "unparseable expected output: %s" % e
    try:
        prog = purejq.compile(case.program)
        outputs = []
        try:
            for v in prog.run(value):
                outputs.append(v)
                if len(outputs) > MAX_OUTPUTS:
                    return False, "too many outputs (>%d)" % MAX_OUTPUTS
        except (JqError, Halt):
            # jq's harness treats a runtime error as end-of-outputs:
            # whatever was produced before the error is compared as usual.
            pass
    except JqParseError as e:
        return False, "JqParseError: %s" % e
    except RecursionError:
        return False, "RecursionError"
    except Exception as e:
        return False, "internal %s: %s" % (type(e).__name__, e)

    # Compare parsed values, exactly like jq's own test harness (jv_equal),
    # so whitespace and key order in the .test files don't matter.
    from purejq.ops import values_equal
    if len(outputs) != len(expected) or not all(
            values_equal(a, b) for a, b in zip(outputs, expected)):
        return False, "expected %r, got %r" % (
            [encode(e) for e in expected], [encode(o) for o in outputs])
    return True, ""
