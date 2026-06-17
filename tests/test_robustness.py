"""Robustness: malformed and pathological programs must raise JqParseError,
never an undocumented exception or a stack overflow.

Regression tests for an adversarial fuzz sweep that surfaced a ValueError
from malformed \\u escapes and a RecursionError from deeply nested programs.
"""
import sys

import pytest

import purejq


@pytest.mark.parametrize("program", [
    r'"\u"',            # truncated
    r'"\uZZZZ"',        # non-hex digits
    r'"\u12"',          # too few digits before EOF
    r'"\ud800\uZZZZ"',  # bad low surrogate
    r'"\u   ."',        # spaces where hex expected
])
def test_bad_unicode_escape_raises_parse_error(program):
    with pytest.raises(purejq.JqParseError):
        purejq.compile(program)


def test_valid_unicode_escapes_still_work():
    assert purejq.first(r'"A"') == "A"
    assert purejq.first(r'"A"') == "A"
    assert purejq.first(r'"😀"') == "\U0001f600"  # surrogate pair


@pytest.mark.parametrize("make", [
    lambda d: "[" * d + "1" + "]" * d,     # nested arrays
    lambda d: "(" * d + "1" + ")" * d,     # nested parens
    lambda d: "{a:" * d + "1" + "}" * d,   # nested objects
])
def test_structural_nesting_is_depth_guarded(make):
    # The parser caps structural nesting, so this is safe at any recursion
    # limit - it must NOT deep-recurse even when the limit has been raised.
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(40000)
    try:
        for depth in (100, 5000, 50000):
            with pytest.raises(purejq.JqParseError):
                purejq.compile(make(depth))
    finally:
        sys.setrecursionlimit(old)


@pytest.mark.parametrize("make", [
    lambda d: "|".join(["."] * d),         # long pipe chain
    lambda d: ",".join(["."] * d),         # long comma chain
    lambda d: "+".join(["1"] * d),         # long operator chain
])
def test_long_flat_chains_raise_under_default_limit(make):
    # Flat chains recurse at compile time; under the standard recursion limit
    # they must surface as a clean parse error, never an undocumented one.
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(1000)
    try:
        with pytest.raises(purejq.JqParseError):
            purejq.compile(make(5000))
    finally:
        sys.setrecursionlimit(old)


@pytest.mark.parametrize("program", [".ä", ".é", ".ñoo", ".ßtr", ".ð"])
def test_unicode_after_dot_is_a_clean_parse_error(program):
    # ".ä" etc.: the next char is Unicode-alpha but not a valid ASCII field
    # identifier. Must raise, not crash on a failed regex match.
    with pytest.raises(purejq.JqParseError):
        purejq.compile(program)


def test_ascii_field_access_unaffected():
    assert purejq.first(".foo", {"foo": 7}) == 7
    assert purejq.first(".a.b", {"a": {"b": 5}}) == 5
    assert purejq.first(".", 42) == 42
    assert purejq.first("._x", {"_x": 1}) == 1       # underscore identifier
    assert purejq.all_outputs("..", {"a": 1}) == [{"a": 1}, 1]  # recurse


def test_realistic_nesting_still_compiles():
    purejq.compile("[" * 20 + "1" + "]" * 20).first(None)
    purejq.compile("[.[] | {a: {b: [.x]}}]")
    purejq.compile("|".join(["."] * 40)).first(1)


def test_random_garbage_never_leaks_undocumented_exception():
    import random
    rng = random.Random(1234)
    pool = list('.[]{}()|,:"\'\\+-*/%<>=!?#@ \tabc123')
    for _ in range(3000):
        src = "".join(rng.choice(pool) for _ in range(rng.randint(0, 40)))
        try:
            prog = purejq.compile(src)
        except purejq.JqParseError:
            continue
        for v in (None, 1, "x", [1], {"a": 1}):
            try:
                for _out in prog.run(v):
                    break
            except (purejq.JqError, purejq.Halt):
                pass
