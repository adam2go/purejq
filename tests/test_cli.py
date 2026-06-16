"""Tests for the purejq command-line interface."""
import io
import sys

import pytest
from purejq import cli


def run(args, stdin=""):
    """Invoke the CLI with args and captured stdin; return (exit_code, stdout)."""
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(stdin)
    sys.stdout = io.StringIO()
    try:
        code = cli.main(args)
        return code, sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = old_in, old_out


def test_basic_filter():
    assert run([".a"], '{"a": 1}') == (0, "1\n")


def test_compact():
    assert run(["-c", "."], '{"a":[1,2]}') == (0, '{"a":[1,2]}\n')


def test_raw_output():
    assert run(["-r", ".name"], '{"name":"ada"}') == (0, "ada\n")


def test_raw_input():
    code, out = run(["-R", '. + "!"'], "x\ny\n")
    assert code == 0 and out == '"x!"\n"y!"\n'


def test_raw_input_slurp():
    code, out = run(["-Rs", "split(\"\\n\") | length"], "a\nb\nc\n")
    assert code == 0 and out == "4\n"


def test_sort_keys():
    assert run(["-cS", "."], '{"b":1,"a":2}') == (0, '{"a":2,"b":1}\n')


def test_ascii_output():
    assert run(["-ca", ".x"], '{"x":"\\u00e9"}') == (0, '"\\u00e9"\n')


def test_indent():
    code, out = run(["--indent", "4", "."], '{"a":1}')
    assert out == '{\n    "a": 1\n}\n'


def test_indent_zero_is_compact():
    assert run(["--indent", "0", "."], '{"a":[1,2]}') == (0, '{"a":[1,2]}\n')


def test_tab():
    code, out = run(["--tab", "."], '{"a":1}')
    assert out == '{\n\t"a": 1\n}\n'


def test_slurp():
    assert run(["-cs", "."], "1 2 3") == (0, "[1,2,3]\n")


def test_null_input():
    assert run(["-n", "1 + 2"]) == (0, "3\n")


def test_arg():
    assert run(["-c", "--arg", "x", "hi", "{v: $x}"], "null") == (0, '{"v":"hi"}\n')


def test_argjson():
    assert run(["-c", "--argjson", "x", "[1,2]", "$x"], "null") == (0, "[1,2]\n")


def test_exit_status_false():
    code, _ = run(["-e", ".a"], '{"a": false}')
    assert code == 1


def test_parse_error():
    code, _ = run(["."], "{not json}")
    assert code == 2


def test_program_error():
    code, _ = run([".a"], "1")  # cannot index number
    assert code == 5
