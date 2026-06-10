#!/usr/bin/env python3
"""Regenerate tests/conformance/expected_failures.txt from a full conformance run."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "src"))

from jqtest import EXPECTED_FAILURES_FILE, load_all_cases, run_case  # noqa: E402


def main():
    cases = load_all_cases()
    failures = []
    for case in cases:
        ok, detail = run_case(case)
        if not ok:
            failures.append((case, detail))
    passed = len(cases) - len(failures)
    with open(EXPECTED_FAILURES_FILE, "w", encoding="utf-8") as f:
        f.write("# Conformance cases that purejq does not pass yet.\n")
        f.write("# Format: <case-id>\\t# <program>\n")
        f.write("# Regenerate with: python3 tools/update_expected_failures.py\n")
        f.write("# Passing: %d/%d (%.1f%%)\n" % (passed, len(cases), 100.0 * passed / len(cases)))
        for case, detail in failures:
            f.write("%s\t# %s\n" % (case.id, case.program[:120]))
    print("conformance: %d/%d passing (%.1f%%), %d expected failures written"
          % (passed, len(cases), 100.0 * passed / len(cases), len(failures)))


if __name__ == "__main__":
    main()
