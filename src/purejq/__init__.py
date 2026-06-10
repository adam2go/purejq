"""purejq: a pure Python implementation of jq."""
from __future__ import annotations

from .compiler import Env, _names_ctx, collect_defined_names, compile_v
from .encoder import encode, encode_pretty
from .errors import Halt, JqError, JqParseError
from .parser import parse
from .prelude import prelude_env

__version__ = "0.2.0"
__all__ = ["compile", "Program", "first", "all_outputs",
           "JqError", "JqParseError", "Halt", "encode", "encode_pretty"]


class Program:
    """A compiled jq program, reusable across inputs."""

    def __init__(self, source):
        self.source = source
        ast = parse(source)
        prelude_env()  # built first so calls can be statically bound
        with _names_ctx(frozenset(collect_defined_names(ast))):
            self._vfn = compile_v(ast)

    def run(self, value=None, inputs=None, vars=None):
        """Run the program on one input value; returns an iterator of outputs."""
        env = prelude_env()
        if inputs is not None or vars:
            env = Env(parent=env, vars=dict(vars) if vars else None,
                      inputs=iter(inputs) if inputs is not None else None)
        return self._vfn(value, env)

    def all(self, value=None, **kw):
        """Run and collect every output into a list."""
        return list(self.run(value, **kw))

    def first(self, value=None, **kw):
        """Run and return the first output (or None if the program yields nothing)."""
        for v in self.run(value, **kw):
            return v
        return None


def compile(source):
    """Compile a jq program. Returns a reusable Program."""
    return Program(source)


def first(source, value=None):
    return Program(source).first(value)


def all_outputs(source, value=None):
    return Program(source).all(value)
