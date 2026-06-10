import warnings

import pytest
from jqtest import load_all_cases, load_expected_failures, run_case

CASES = load_all_cases()
EXPECTED_FAILURES = load_expected_failures()


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_conformance(case):
    ok, detail = run_case(case)
    if case.id in EXPECTED_FAILURES:
        if ok:
            # Behavior can vary slightly across Python versions, so an
            # unexpected pass is a warning, not a failure. Regenerate the
            # list with tools/update_expected_failures.py to claim it.
            warnings.warn("%s now PASSES - regenerate expected_failures.txt" % case.id)
            return
        pytest.xfail(detail[:200])
    assert ok, "%s | program: %s | %s" % (case.id, case.program, detail)
