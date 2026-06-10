"""jq-compatible JSON encoding (compact and pretty)."""
from __future__ import annotations

import math

from .errors import JqError

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}

_MAX_DOUBLE = "1.7976931348623157e+308"


def _escape_string(s):
    out = ['"']
    for ch in s:
        esc = _ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif ch < " " or ch == "\x7f":
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def format_number(v):
    if isinstance(v, int):
        return str(v)
    if math.isnan(v):
        return "null"
    if math.isinf(v):
        return _MAX_DOUBLE if v > 0 else "-" + _MAX_DOUBLE
    if v.is_integer() and abs(v) < 1e17:
        return str(int(v))
    return repr(v)


MAX_PRINT_DEPTH = 10000


def encode(v):
    """Encode a JSON value the way jq's compact output (-c) does."""
    out = []
    _enc(v, out, 0)
    return "".join(out)


def _enc(v, out, depth):
    if v is None:
        out.append("null")
    elif v is True:
        out.append("true")
    elif v is False:
        out.append("false")
    elif isinstance(v, (int, float)):
        out.append(format_number(v))
    elif isinstance(v, str):
        out.append(_escape_string(v))
    elif depth > MAX_PRINT_DEPTH:
        out.append('"<skipped: too deep>"')
    elif isinstance(v, list):
        out.append("[")
        for i, item in enumerate(v):
            if i:
                out.append(",")
            _enc(item, out, depth + 1)
        out.append("]")
    elif isinstance(v, dict):
        out.append("{")
        first = True
        for k, item in v.items():
            if not first:
                out.append(",")
            first = False
            if not isinstance(k, str):
                raise JqError("Object keys must be strings")
            out.append(_escape_string(k))
            out.append(":")
            _enc(item, out, depth + 1)
        out.append("}")
    else:
        raise JqError("Cannot encode value of type %s" % type(v).__name__)


def encode_pretty(v, indent=2):
    """Encode a JSON value the way jq's default pretty output does."""
    out = []
    _enc_pretty(v, out, indent, 0)
    return "".join(out)


def _enc_pretty(v, out, indent, depth):
    if isinstance(v, list) and v:
        pad = " " * (indent * (depth + 1))
        out.append("[\n")
        for i, item in enumerate(v):
            if i:
                out.append(",\n")
            out.append(pad)
            _enc_pretty(item, out, indent, depth + 1)
        out.append("\n" + " " * (indent * depth) + "]")
    elif isinstance(v, dict) and v:
        pad = " " * (indent * (depth + 1))
        out.append("{\n")
        first = True
        for k, item in v.items():
            if not first:
                out.append(",\n")
            first = False
            out.append(pad)
            out.append(_escape_string(k))
            out.append(": ")
            _enc_pretty(item, out, indent, depth + 1)
        out.append("\n" + " " * (indent * depth) + "}")
    else:
        _enc(v, out, depth)
