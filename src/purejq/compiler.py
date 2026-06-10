"""Compile AST nodes into Python generator closures.

Every jq filter is compiled once into a closure `f(input, env) -> iterator`;
evaluation never re-walks the AST. Path-producing expressions get a second
compilation `g(input, path, env) -> iterator of (path, value)` used by
`path()`, assignments, and `del()`.
"""
from __future__ import annotations

from . import ops
from .encoder import encode
from .errors import JqBreak, JqError
from .ops import truthy, type_name


class Env:
    __slots__ = ("parent", "vars", "funcs", "labels", "inputs")

    def __init__(self, parent=None, vars=None, funcs=None, labels=None, inputs=None):
        self.parent = parent
        self.vars = vars
        self.funcs = funcs
        self.labels = labels
        self.inputs = inputs

    def lookup_var(self, name):
        e = self
        while e is not None:
            if e.vars is not None and name in e.vars:
                return e.vars[name]
            e = e.parent
        raise JqError("$%s is not defined" % name)

    def lookup_func(self, key):
        e = self
        while e is not None:
            if e.funcs is not None and key in e.funcs:
                return e.funcs[key]
            e = e.parent
        return None

    def lookup_label(self, name):
        e = self
        while e is not None:
            if e.labels is not None and name in e.labels:
                return e.labels[name]
            e = e.parent
        raise JqError("$*label-%s is not defined" % name)

    def get_inputs(self):
        e = self
        while e is not None:
            if e.inputs is not None:
                return e.inputs
            e = e.parent
        return None


class FuncVal:
    """A user-defined function (from `def`) closed over its defining env."""
    __slots__ = ("params", "body", "env", "_cv", "_cp")

    def __init__(self, params, body):
        self.params = params
        self.body = body
        self.env = None
        self._cv = None
        self._cp = None

    def compiled_v(self):
        if self._cv is None:
            self._cv = compile_v(self.body)
        return self._cv

    def compiled_p(self):
        if self._cp is None:
            self._cp = compile_p(self.body)
        return self._cp


class ArgClosure:
    """A filter argument bound to its caller's environment (call-by-name)."""
    __slots__ = ("vfn", "pfn", "env")

    def __init__(self, vfn, pfn, env):
        self.vfn = vfn
        self.pfn = pfn
        self.env = env

    def vals(self, input):
        return self.vfn(input, self.env)

    def paths(self, input, path):
        return self.pfn(input, path, self.env)


class ValueClosure:
    """A `$param` value exposed as a zero-arity function."""
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def vals(self, input):
        yield self.value

    def paths(self, input, path):
        raise JqError("Invalid path expression")


def _invalid_path(ast):
    vfn = compile_v(ast)

    def pfn(input, path, env):
        for v in vfn(input, env):
            raise JqError("Invalid path expression with result %s" % encode(v))
        raise JqError("Invalid path expression")
        yield  # pragma: no cover
    return pfn


# ---------------------------------------------------------------------------
# Value-mode compilation
# ---------------------------------------------------------------------------

def compile_v(ast):
    return _V[ast[0]](ast)


def compile_p(ast):
    handler = _P.get(ast[0])
    if handler is None:
        return _invalid_path(ast)
    return handler(ast)


def _v_identity(ast):
    def vfn(input, env):
        yield input
    return vfn


def _v_const(ast):
    value = ast[1]

    def vfn(input, env):
        yield value
    return vfn


def _v_emptyarray(ast):
    def vfn(input, env):
        yield []
    return vfn


def _v_field(ast):
    base = compile_v(ast[1])
    name = ast[2]

    def vfn(input, env):
        for b in base(input, env):
            if b is None:
                yield None
            elif isinstance(b, dict):
                yield b.get(name)
            else:
                raise JqError('Cannot index %s with %s' % (type_name(b), ops.describe(name)))
    return vfn


def _v_index(ast):
    base = compile_v(ast[1])
    idx = compile_v(ast[2])

    def vfn(input, env):
        for b in base(input, env):
            for ix in idx(input, env):
                yield ops.index_value(b, ix)
    return vfn


def _v_slice(ast):
    base = compile_v(ast[1])
    lo = compile_v(ast[2]) if ast[2] is not None else None
    hi = compile_v(ast[3]) if ast[3] is not None else None

    def vfn(input, env):
        for b in base(input, env):
            for l in (lo(input, env) if lo else (None,)):
                for h in (hi(input, env) if hi else (None,)):
                    yield ops.slice_value(b, l, h)
    return vfn


def _v_iterate(ast):
    base = compile_v(ast[1])

    def vfn(input, env):
        for b in base(input, env):
            for v in ops.iterate_value(b):
                yield v
    return vfn


def _v_pipe(ast):
    a = compile_v(ast[1])
    b = compile_v(ast[2])

    def vfn(input, env):
        for av in a(input, env):
            for bv in b(av, env):
                yield bv
    return vfn


def _v_comma(ast):
    a = compile_v(ast[1])
    b = compile_v(ast[2])

    def vfn(input, env):
        for v in a(input, env):
            yield v
        for v in b(input, env):
            yield v
    return vfn


_BINOPS = {
    "+": ops.add_values,
    "-": ops.sub_values,
    "*": ops.mul_values,
    "/": ops.div_values,
    "%": ops.mod_values,
}


def _v_binop(ast):
    op = ast[1]
    a = compile_v(ast[2])
    b = compile_v(ast[3])
    fn = _BINOPS.get(op)
    if fn is not None:
        def vfn(input, env):
            for rv in b(input, env):
                for lv in a(input, env):
                    yield fn(lv, rv)
        return vfn

    if op == "==":
        def test(l, r):
            return ops.values_equal(l, r)
    elif op == "!=":
        def test(l, r):
            return not ops.values_equal(l, r)
    elif op == "<":
        def test(l, r):
            return ops.jq_cmp(l, r) < 0
    elif op == "<=":
        def test(l, r):
            return ops.jq_cmp(l, r) <= 0
    elif op == ">":
        def test(l, r):
            return ops.jq_cmp(l, r) > 0
    else:
        def test(l, r):
            return ops.jq_cmp(l, r) >= 0

    def vfn(input, env):
        for rv in b(input, env):
            for lv in a(input, env):
                yield test(lv, rv)
    return vfn


def _v_and(ast):
    a = compile_v(ast[1])
    b = compile_v(ast[2])

    def vfn(input, env):
        for lv in a(input, env):
            if not truthy(lv):
                yield False
            else:
                for rv in b(input, env):
                    yield truthy(rv)
    return vfn


def _v_or(ast):
    a = compile_v(ast[1])
    b = compile_v(ast[2])

    def vfn(input, env):
        for lv in a(input, env):
            if truthy(lv):
                yield True
            else:
                for rv in b(input, env):
                    yield truthy(rv)
    return vfn


def _v_alt(ast):
    a = compile_v(ast[1])
    b = compile_v(ast[2])

    def vfn(input, env):
        found = False
        it = a(input, env)
        while True:
            try:
                v = next(it)
            except StopIteration:
                break
            except JqError:
                break
            if truthy(v):
                found = True
                yield v
        if not found:
            for v in b(input, env):
                yield v
    return vfn


def _v_neg(ast):
    a = compile_v(ast[1])

    def vfn(input, env):
        for v in a(input, env):
            yield ops.neg_value(v)
    return vfn


def _v_opt(ast):
    body = compile_v(ast[1])

    def vfn(input, env):
        it = body(input, env)
        while True:
            try:
                v = next(it)
            except StopIteration:
                return
            except JqError:
                return
            yield v
    return vfn


def _v_try(ast):
    body = compile_v(ast[1])
    handler = compile_v(ast[2]) if ast[2] is not None else None

    def vfn(input, env):
        it = body(input, env)
        while True:
            try:
                v = next(it)
            except StopIteration:
                return
            except JqError as e:
                if handler is not None:
                    for hv in handler(e.value, env):
                        yield hv
                return
            yield v
    return vfn


def _v_collect(ast):
    body = compile_v(ast[1])

    def vfn(input, env):
        yield list(body(input, env))
    return vfn


def _v_str(ast):
    fmt = ast[1]
    parts = [p if isinstance(p, str) else compile_v(p) for p in ast[2]]
    from .builtins import apply_format

    def vfn(input, env):
        def go(i, prefix):
            if i == len(parts):
                yield prefix
                return
            part = parts[i]
            if isinstance(part, str):
                for r in go(i + 1, prefix + part):
                    yield r
            else:
                for v in part(input, env):
                    piece = apply_format(fmt or "text", v)
                    for r in go(i + 1, prefix + piece):
                        yield r
        return go(0, "")
    return vfn


def _v_format(ast):
    name = ast[1]
    from .builtins import apply_format

    def vfn(input, env):
        yield apply_format(name, input)
    return vfn


def _v_object(ast):
    entries = [(compile_v(k), compile_v(v)) for k, v in ast[1]]

    def vfn(input, env):
        def go(i, acc):
            if i == len(entries):
                yield dict(acc)
                return
            kc, vc = entries[i]
            for k in kc(input, env):
                if not isinstance(k, str):
                    raise JqError("Object keys must be strings, not %s" % type_name(k))
                for v in vc(input, env):
                    for r in go(i + 1, acc + [(k, v)]):
                        yield r
        return go(0, [])
    return vfn


def _v_if(ast):
    branches = [(compile_v(c), compile_v(t)) for c, t in ast[1]]
    els = compile_v(ast[2]) if ast[2] is not None else _v_identity(None)

    def vfn(input, env):
        def go(i):
            if i == len(branches):
                for v in els(input, env):
                    yield v
                return
            cond, then = branches[i]
            for c in cond(input, env):
                if truthy(c):
                    for v in then(input, env):
                        yield v
                else:
                    for v in go(i + 1):
                        yield v
        return go(0)
    return vfn


def _v_var(ast):
    name = ast[1]

    def vfn(input, env):
        yield env.lookup_var(name)
    return vfn


def _v_loc(ast):
    def vfn(input, env):
        yield {"file": "<top-level>", "line": 1}
    return vfn


def _v_funcdef(ast):
    _, name, params, body, rest = ast
    rest_v = compile_v(rest)
    key = (name, len(params))

    def vfn(input, env):
        fv = FuncVal(params, body)
        env2 = Env(parent=env, funcs={key: fv})
        fv.env = env2
        return rest_v(input, env2)
    return vfn


def _p_funcdef(ast):
    _, name, params, body, rest = ast
    rest_p = compile_p(rest)
    key = (name, len(params))

    def pfn(input, path, env):
        fv = FuncVal(params, body)
        env2 = Env(parent=env, funcs={key: fv})
        fv.env = env2
        return rest_p(input, path, env2)
    return pfn


def _call_funcval(fv, arg_closures, input, env, mode, path=None):
    dollar = [(i, p[1:]) for i, p in enumerate(fv.params) if p.startswith("$")]
    funcs = {}
    for i, p in enumerate(fv.params):
        if not p.startswith("$"):
            funcs[(p, 0)] = arg_closures[i]
    base_env = Env(parent=fv.env, funcs=funcs or None)

    def bind(j, vars):
        if j == len(dollar):
            env2 = base_env
            if vars:
                funcs2 = dict(funcs)
                for n, v in vars.items():
                    funcs2[(n, 0)] = ValueClosure(v)
                env2 = Env(parent=fv.env, vars=vars, funcs=funcs2)
            if mode == "v":
                for r in fv.compiled_v()(input, env2):
                    yield r
            else:
                for r in fv.compiled_p()(input, path, env2):
                    yield r
            return
        i, name = dollar[j]
        for v in arg_closures[i].vals(input):
            nv = dict(vars)
            nv[name] = v
            for r in bind(j + 1, nv):
                yield r
    return bind(0, {})


def _v_call(ast):
    _, name, args = ast
    key = (name, len(args))
    compiled_args = [(compile_v(a), compile_p(a)) for a in args]
    from . import builtins as _b

    def vfn(input, env):
        fn = env.lookup_func(key)
        if fn is None:
            pyfn = _b.PY_BUILTINS.get(key)
            if pyfn is None:
                raise JqError("%s/%d is not defined" % (name, len(args)))
            closures = [ArgClosure(cv, cp, env) for cv, cp in compiled_args]
            return pyfn(input, env, *closures)
        if isinstance(fn, FuncVal):
            closures = [ArgClosure(cv, cp, env) for cv, cp in compiled_args]
            return _call_funcval(fn, closures, input, env, "v")
        return fn.vals(input)
    return vfn


def _p_call(ast):
    _, name, args = ast
    key = (name, len(args))
    compiled_args = [(compile_v(a), compile_p(a)) for a in args]
    from . import builtins as _b

    def pfn(input, path, env):
        fn = env.lookup_func(key)
        if fn is None:
            pyfn = _b.PY_BUILTINS_PATH.get(key)
            if pyfn is None:
                pyfn_v = _b.PY_BUILTINS.get(key)
                if pyfn_v is not None:
                    closures = [ArgClosure(cv, cp, env) for cv, cp in compiled_args]
                    for v in pyfn_v(input, env, *closures):
                        raise JqError("Invalid path expression with result %s" % encode(v))
                raise JqError("Invalid path expression near %s" % name)
            closures = [ArgClosure(cv, cp, env) for cv, cp in compiled_args]
            return pyfn(input, path, env, *closures)
        if isinstance(fn, FuncVal):
            closures = [ArgClosure(cv, cp, env) for cv, cp in compiled_args]
            return _call_funcval(fn, closures, input, env, "p", path)
        return fn.paths(input, path)
    return pfn


# --- destructuring -----------------------------------------------------------

def _collect_pattern_vars(pat, out):
    tag = pat[0]
    if tag == "pvar":
        out.add(pat[1])
    elif tag == "parray":
        for p in pat[1]:
            _collect_pattern_vars(p, out)
    else:
        for _k, p, bindvar in pat[1]:
            if bindvar is not None:
                out.add(bindvar)
            _collect_pattern_vars(p, out)


_PATTERN_KEY_CACHE = {}


def destructure(pat, value, env):
    """Yield binding dicts for a pattern matched against a value."""
    tag = pat[0]
    if tag == "pvar":
        yield {pat[1]: value}
        return
    if tag == "parray":
        if value is None:
            value = []
        if not isinstance(value, list):
            raise JqError("Cannot index %s with number" % type_name(value))
        items = pat[1]

        def go(i, acc):
            if i == len(items):
                yield acc
                return
            sub = value[i] if i < len(value) else None
            for b in destructure(items[i], sub, env):
                merged = dict(acc)
                merged.update(b)
                for r in go(i + 1, merged):
                    yield r
        for r in go(0, {}):
            yield r
        return
    # pobject
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise JqError('Cannot index %s with "key"' % type_name(value))
    entries = pat[1]

    def go_obj(i, acc):
        if i == len(entries):
            yield acc
            return
        kast, sub, bindvar = entries[i]
        ck = _PATTERN_KEY_CACHE.get(id(kast))
        if ck is None:
            ck = compile_v(kast)
            _PATTERN_KEY_CACHE[id(kast)] = ck
        for k in ck(value, env):
            if not isinstance(k, str):
                raise JqError("Cannot index object with %s" % type_name(k))
            subvalue = value.get(k)
            for b in destructure(sub, subvalue, env):
                merged = dict(acc)
                merged.update(b)
                if bindvar is not None:
                    merged[bindvar] = subvalue
                for r in go_obj(i + 1, merged):
                    yield r
    for r in go_obj(0, {}):
        yield r


def _bindings_for(patterns, value, env, all_vars):
    """Try each `?//` alternative; fill unbound vars with null."""
    last_err = None
    for i, pat in enumerate(patterns):
        try:
            results = list(destructure(pat, value, env))
        except JqError as e:
            last_err = e
            if i == len(patterns) - 1:
                raise
            continue
        out = []
        for b in results:
            full = dict.fromkeys(all_vars)
            full.update(b)
            out.append(full)
        return out
    raise last_err  # pragma: no cover


def _v_as(ast):
    _, src, patterns, body = ast
    src_v = compile_v(src)
    body_v = compile_v(body)
    all_vars = set()
    for p in patterns:
        _collect_pattern_vars(p, all_vars)

    if len(patterns) == 1:
        def vfn(input, env):
            for sv in src_v(input, env):
                for binding in _bindings_for(patterns, sv, env, all_vars):
                    env2 = Env(parent=env, vars=binding)
                    for r in body_v(input, env2):
                        yield r
        return vfn

    # `?//` alternatives: an error in destructuring OR in the body moves on
    # to the next pattern; only the last pattern's errors propagate.
    def vfn(input, env):
        for sv in src_v(input, env):
            for i, pat in enumerate(patterns):
                is_last = i == len(patterns) - 1
                try:
                    results = []
                    for b in destructure(pat, sv, env):
                        full = dict.fromkeys(all_vars)
                        full.update(b)
                        env2 = Env(parent=env, vars=full)
                        results.extend(body_v(input, env2))
                except JqError:
                    if is_last:
                        raise
                    continue
                for r in results:
                    yield r
                break
    return vfn


def _p_as(ast):
    _, src, patterns, body = ast
    src_v = compile_v(src)
    body_p = compile_p(body)
    all_vars = set()
    for p in patterns:
        _collect_pattern_vars(p, all_vars)

    def pfn(input, path, env):
        for sv in src_v(input, env):
            for binding in _bindings_for(patterns, sv, env, all_vars):
                env2 = Env(parent=env, vars=binding)
                for r in body_p(input, path, env2):
                    yield r
    return pfn


_EMPTY = object()


def _v_reduce(ast):
    _, src, patterns, init, update = ast
    src_v = compile_v(src)
    init_v = compile_v(init)
    update_v = compile_v(update)
    all_vars = set()
    for p in patterns:
        _collect_pattern_vars(p, all_vars)

    def vfn(input, env):
        for iv in init_v(input, env):
            acc = iv
            for sv in src_v(input, env):
                for binding in _bindings_for(patterns, sv, env, all_vars):
                    env2 = Env(parent=env, vars=binding)
                    last = _EMPTY
                    for out in update_v(acc, env2):
                        last = out
                    acc = last
                    if acc is _EMPTY:
                        break
                if acc is _EMPTY:
                    break
            if acc is not _EMPTY:
                yield acc
    return vfn


def _v_foreach(ast):
    _, src, patterns, init, update, extract = ast
    src_v = compile_v(src)
    init_v = compile_v(init)
    update_v = compile_v(update)
    extract_v = compile_v(extract) if extract is not None else None
    all_vars = set()
    for p in patterns:
        _collect_pattern_vars(p, all_vars)

    def vfn(input, env):
        for iv in init_v(input, env):
            acc = iv
            for sv in src_v(input, env):
                for binding in _bindings_for(patterns, sv, env, all_vars):
                    env2 = Env(parent=env, vars=binding)
                    for out in update_v(acc, env2):
                        acc = out
                        if extract_v is not None:
                            for ev in extract_v(acc, env2):
                                yield ev
                        else:
                            yield acc
    return vfn


def _v_label(ast):
    _, name, body = ast
    body_v = compile_v(body)

    def vfn(input, env):
        token = object()
        env2 = Env(parent=env, labels={name: token})
        it = body_v(input, env2)
        while True:
            try:
                v = next(it)
            except StopIteration:
                return
            except JqBreak as b:
                if b.token is token:
                    return
                raise
            yield v
    return vfn


def _p_label(ast):
    _, name, body = ast
    body_p = compile_p(body)

    def pfn(input, path, env):
        token = object()
        env2 = Env(parent=env, labels={name: token})
        it = body_p(input, path, env2)
        while True:
            try:
                v = next(it)
            except StopIteration:
                return
            except JqBreak as b:
                if b.token is token:
                    return
                raise
            yield v
    return pfn


def _v_break(ast):
    name = ast[1]

    def vfn(input, env):
        raise JqBreak(env.lookup_label(name))
        yield  # pragma: no cover
    return vfn


# --- assignment ---------------------------------------------------------------

def _v_assign(ast):
    _, op, lhs, rhs = ast
    lhs_p = compile_p(lhs)
    rhs_v = compile_v(rhs)

    if op == "=":
        def vfn(input, env):
            for rv in rhs_v(input, env):
                out = input
                for p, _v in lhs_p(input, [], env):
                    out = ops.set_path(out, p, rv)
                yield out
        return vfn

    if op == "|=":
        def vfn(input, env):
            out = input
            deletions = []
            for p, _v in lhs_p(input, [], env):
                cur = ops.get_path(out, p)
                it = rhs_v(cur, env)
                try:
                    first = next(it)
                except StopIteration:
                    # empty update deletes the path; postpone all deletions so
                    # earlier ones don't shift the later paths (like jq 1.8)
                    deletions.append(p)
                    continue
                out = ops.set_path(out, p, first)
            if deletions:
                out = ops.delpaths_impl(out, deletions)
            yield out
        return vfn

    fn = _BINOPS.get(op[:-1])
    if op == "//=":
        def combine(cur, rv):
            return cur if truthy(cur) else rv
    else:
        def combine(cur, rv, _fn=fn):
            return _fn(cur, rv)

    def vfn(input, env):
        for rv in rhs_v(input, env):
            out = input
            for p, _v in lhs_p(input, [], env):
                cur = ops.get_path(out, p)
                out = ops.set_path(out, p, combine(cur, rv))
            yield out
    return vfn




# ---------------------------------------------------------------------------
# Path-mode handlers
# ---------------------------------------------------------------------------

def _p_identity(ast):
    def pfn(input, path, env):
        yield path, input
    return pfn


def _p_field(ast):
    base = compile_p(ast[1])
    name = ast[2]

    def pfn(input, path, env):
        for p, v in base(input, path, env):
            if v is None:
                yield p + [name], None
            elif isinstance(v, dict):
                yield p + [name], v.get(name)
            else:
                raise JqError('Cannot index %s with %s' % (type_name(v), ops.describe(name)))
    return pfn


def _p_index(ast):
    base = compile_p(ast[1])
    idx = compile_v(ast[2])

    def pfn(input, path, env):
        for p, v in base(input, path, env):
            for ix in idx(input, env):
                if isinstance(ix, str):
                    if v is not None and not isinstance(v, dict):
                        raise JqError('Cannot index %s with %s'
                                      % (type_name(v), ops.describe(ix)))
                elif isinstance(ix, (int, float)) and not isinstance(ix, bool):
                    if v is not None and not isinstance(v, list):
                        raise JqError("Cannot index %s with %s"
                                      % (type_name(v), ops.describe(ix)))
                else:
                    raise JqError("Invalid path component: %s" % type_name(ix))
                yield p + [ix], ops.index_value(v, ix)
    return pfn


def _p_slice(ast):
    base = compile_p(ast[1])
    lo = compile_v(ast[2]) if ast[2] is not None else None
    hi = compile_v(ast[3]) if ast[3] is not None else None

    def pfn(input, path, env):
        for p, v in base(input, path, env):
            for l in (lo(input, env) if lo else (None,)):
                for h in (hi(input, env) if hi else (None,)):
                    comp = {"start": l, "end": h}
                    yield p + [comp], ops.slice_value(v, l, h)
    return pfn


def _p_iterate(ast):
    base = compile_p(ast[1])

    def pfn(input, path, env):
        for p, v in base(input, path, env):
            if isinstance(v, list):
                for i, item in enumerate(v):
                    yield p + [i], item
            elif isinstance(v, dict):
                for k, item in v.items():
                    yield p + [k], item
            else:
                raise JqError("Invalid path expression near attempt to iterate through %s"
                              % encode(v))
    return pfn


def _p_pipe(ast):
    a = compile_p(ast[1])
    b = compile_p(ast[2])

    def pfn(input, path, env):
        for p, v in a(input, path, env):
            for r in b(v, p, env):
                yield r
    return pfn


def _p_comma(ast):
    a = compile_p(ast[1])
    b = compile_p(ast[2])

    def pfn(input, path, env):
        for r in a(input, path, env):
            yield r
        for r in b(input, path, env):
            yield r
    return pfn


def _p_if(ast):
    branches = [(compile_v(c), compile_p(t)) for c, t in ast[1]]
    els = compile_p(ast[2]) if ast[2] is not None else _p_identity(None)

    def pfn(input, path, env):
        def go(i):
            if i == len(branches):
                for r in els(input, path, env):
                    yield r
                return
            cond, then = branches[i]
            for c in cond(input, env):
                if truthy(c):
                    for r in then(input, path, env):
                        yield r
                else:
                    for r in go(i + 1):
                        yield r
        return go(0)
    return pfn


def _p_opt(ast):
    body = compile_p(ast[1])

    def pfn(input, path, env):
        it = body(input, path, env)
        while True:
            try:
                r = next(it)
            except StopIteration:
                return
            except JqError:
                return
            yield r
    return pfn


def _p_try(ast):
    body = compile_p(ast[1])

    def pfn(input, path, env):
        it = body(input, path, env)
        while True:
            try:
                r = next(it)
            except StopIteration:
                return
            except JqError:
                return
            yield r
    return pfn


def _p_break(ast):
    name = ast[1]

    def pfn(input, path, env):
        raise JqBreak(env.lookup_label(name))
        yield  # pragma: no cover
    return pfn


_V = {
    "identity": _v_identity,
    "const": _v_const,
    "emptyarray": _v_emptyarray,
    "field": _v_field,
    "index": _v_index,
    "slice": _v_slice,
    "iterate": _v_iterate,
    "pipe": _v_pipe,
    "comma": _v_comma,
    "binop": _v_binop,
    "and": _v_and,
    "or": _v_or,
    "alt": _v_alt,
    "neg": _v_neg,
    "opt": _v_opt,
    "try": _v_try,
    "collect": _v_collect,
    "str": _v_str,
    "format": _v_format,
    "object": _v_object,
    "if": _v_if,
    "var": _v_var,
    "loc": _v_loc,
    "funcdef": _v_funcdef,
    "call": _v_call,
    "as": _v_as,
    "reduce": _v_reduce,
    "foreach": _v_foreach,
    "label": _v_label,
    "break": _v_break,
    "assign": _v_assign,
}

_P = {
    "identity": _p_identity,
    "field": _p_field,
    "index": _p_index,
    "slice": _p_slice,
    "iterate": _p_iterate,
    "pipe": _p_pipe,
    "comma": _p_comma,
    "if": _p_if,
    "opt": _p_opt,
    "try": _p_try,
    "funcdef": _p_funcdef,
    "call": _p_call,
    "as": _p_as,
    "label": _p_label,
    "break": _p_break,
}
