"""Sandboxing for player-authored loadout code.

The UI execs the player's Python (``build_loadout`` and friends). Under Pyodide
that code shares the browser context — it could import ``js``/``os``, reach the
network or DOM, or escape via dunder tricks. And because builds/save-codes are
meant to be shareable, one player's code could otherwise run in another's
browser. So all player code goes through here first.

Three layers of defense:
  * ``check_code`` — an AST allowlist: reject imports outside a tiny set, reject
    underscore and introspection attribute access (``__class__``, ``gi_frame``,
    ``f_back``, ``co_consts`` …) and ``str.format``,
    reject dangerous names (eval/exec/open/__import__ …), and reject class defs
    and ``while`` loops (a loadout needs neither, and ``while`` can hang the tab).
    It also rejects huge constant powers (``10 ** 10 ** 10``), which hang inside
    one line of C code where no loop is visible.
  * ``safe_exec`` — exec with a curated, minimal ``__builtins__`` plus a guarded
    ``__import__`` that only resolves the allowlist (handing back shared
    registries as read-only views, and maps as private copies), so there is
    little to reach even if something slips past the AST pass. Its ``range``
    refuses absurd lengths. It also rewrites the code so ``*``, ``+``, ``sum``
    and a few str/list methods refuse to build a string or list longer than
    MAX_SEQUENCE_LENGTH, and so shared classes/functions can't be changed.
  * ``step_budget`` — counts the lines player code runs and stops it with a
    SafetyError once it passes a budget. On the web the code runs on the browser's
    only thread, so a ``for`` loop over ``range(10**15)`` would freeze the tab just
    like the banned ``while``. Wrap every call into player code in it (safe_exec
    does so for the module body).

Python sandboxing is not provably complete, but this blocks the practical
vectors. Treat it as defense in depth: do not auto-run untrusted *shared* code
without a review step.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import copy
import importlib
import re
import sys
import types
from collections.abc import Callable, Collection, Iterable, Iterator
from contextlib import contextmanager
from typing import Any, NoReturn


class SafetyError(ValueError):
    """Raised when loadout code uses something the sandbox forbids."""


# The filename player code is compiled under. The step budget only counts frames
# from this "file", so the game's own code (World, the editor) runs untraced.
LOADOUT_FILENAME = "<loadout>"

# How many lines player code may run per `with step_budget():` block. Measured
# with this tracer (module body plus every build_* function): the lesson starters
# and solutions run 3-43 lines (43 = the comprehension over 40 slots), the shipped
# loadout.py 20, the web starter 2, and a 120-turret export with modules, gates,
# limiters and a topology 412. 1,000,000 is ~2,400x the largest - room for real
# loops (a 1000 x 1000 grid scan) - and a runaway loop reaches it in about 0.3 s
# on desktop CPython (a few times that in the browser) instead of freezing the tab.
DEFAULT_STEP_BUDGET = 1_000_000

TOO_LONG_MESSAGE = "your code ran too long — is there a very large loop?"

# Longest range() player code may build. A loop over it is caught by the step
# budget, but sum(range(10**15)) runs entirely in C - no lines for the budget to
# count - so the length itself must be capped.
MAX_RANGE_LENGTH = 1_000_000

# Largest constant exponent allowed in `x ** n`. 10 ** 10 ** 10 is one line, but
# computing it would take forever in C (again invisible to the step budget).
MAX_CONST_EXPONENT = 1_000

# Longest string/list/tuple/bytes player code may build in one step. `"x" * 10**9`
# or doubling `s += s` forty times is a handful of lines, but each one asks C for
# gigabytes. No loadout comes close: the lessons, the shipped loadout.py and the
# web starter build nothing longer than a few dozen items, and a 1000 x 1000 grid
# is 1000 rows of 1000. 1,000,000 matches MAX_RANGE_LENGTH.
MAX_SEQUENCE_LENGTH = 1_000_000

SEQUENCE_TOO_LONG_MESSAGE = (
    f"that would make a string or list longer than {MAX_SEQUENCE_LENGTH:,} items"
    " — is a number you multiply or repeat by too big?")


# modules a loadout may import (absolute paths only); everything else is rejected
ALLOWED_IMPORTS = frozenset({
    "chokepoint.arsenal",
    "chokepoint.gates",
    "chokepoint.limiter",
    "chokepoint.parsers",
    "chokepoint.maps",
    "math",
})

# builtins the code may use — a small, side-effect-free set (no import/eval/open)
_SAFE_BUILTIN_NAMES = frozenset({
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float",
    "int", "isinstance", "len", "list", "map", "max", "min", "print", "range",
    "reversed", "round", "set", "frozenset", "sorted", "str", "sum", "tuple", "zip",
    # the common exception classes, so `try: ... except IndexError:` and
    # `raise ValueError(...)` work (without them the name itself is a NameError)
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "ZeroDivisionError", "AttributeError", "StopIteration",
})

# names that must never appear at all — fast, explicit rejection with a clear message
_FORBIDDEN_NAMES = frozenset({
    "__import__", "eval", "exec", "compile", "open", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "__build_class__", "exit", "quit",
})


# Attribute prefixes of Python's introspection objects: generator/coroutine/async-gen
# (gi_/cr_/ag_), frames (f_), tracebacks (tb_) and code objects (co_). They are not
# dunders, but gen.gi_frame.f_back.f_builtins walks from your own frame out to the
# REAL builtins (open, __import__), so none of them may be touched.
_FORBIDDEN_ATTR_PREFIXES = ("_", "gi_", "cr_", "ag_", "f_", "tb_", "co_")

# str.format / format_map can read attributes from inside the format string itself
# ("{0.__class__}".format(x)) - text the AST check never sees - so ban them outright.
# f-strings are fine: their {...} parts are real code that this checker does inspect.
# `mro` is banned too: Exception.mro() hands back BaseException, the one class that
# could catch the step budget's stop signal.
_FORBIDDEN_ATTRS = frozenset({"format", "format_map", "mro"})


def _forbidden_attribute(attr: str) -> bool:
    # str.startswith accepts a tuple and is True if ANY of the prefixes match
    return attr in _FORBIDDEN_ATTRS or attr.startswith(_FORBIDDEN_ATTR_PREFIXES)


# `from __future__ import annotations` is a switch for the compiler, not a real
# import of anything useful - and the game's own exported loadouts start with it.
# Only that from-form is allowed (check_code still refuses "_" names and "*"), but
# the statement also runs at exec time, so the guarded import must let it through.
_FUTURE = "__future__"


# Shared registries a loadout may READ but must not change. Importing the module
# hands back a stand-in where each one is read-only: a dict becomes a
# MappingProxyType (a live read-only view: lookups, `in` and iteration work;
# .clear() and item assignment do not) and a list becomes a tuple copy. The
# game's own imports never come through here, so they still see the real objects.
_READ_ONLY_NAMES: dict[str, tuple[str, ...]] = {
    "chokepoint.arsenal": ("MODULE_LIBRARY", "GUN_LIBRARY", "SYNERGIES"),
    "chokepoint.maps": ("MAPS", "MAP_LIST"),
}

# Registration functions that write into those registries. Copying them onto the
# stand-in is not enough: a function looks names up in the module it was DEFINED
# in, so the copied register_gun would still fill the real GUN_LIBRARY. In the
# sandbox they are swapped for a version that refuses with a clear message.
_REFUSED_NAMES: dict[str, tuple[str, ...]] = {
    "chokepoint.arsenal": ("register_gun", "register_module"),
}

# Registries whose ITEMS can be changed too. A read-only MAPS still hands out the
# real Graph objects, and `MAPS["trunk"].slots.clear()` would edit the map every
# later game starts from. So the sandbox gets a deep copy (copy.deepcopy copies
# the items, the items' lists, and so on all the way down) to read - or change -
# as it likes.
_COPIED_ITEMS = frozenset({("chokepoint.maps", "MAPS")})


def _read_only(value: object) -> object:
    """A read-only stand-in for a shared dict or list registry."""
    if isinstance(value, dict):
        return types.MappingProxyType(value)
    if isinstance(value, list):
        return tuple(value)
    raise TypeError(f"no read-only form for {type(value).__name__}")


def _refuse(func_name: str) -> Callable[..., NoReturn]:
    """A stand-in for a registration function: calling it raises SafetyError."""
    def refused(*args: Any, **kwargs: Any) -> NoReturn:
        raise SafetyError(f"{func_name}() changes the game's shared registry, "
                          "so loadout code may not call it")
    return refused


# ---- size guards: stop a huge string/list BEFORE C is asked to build it ---- #
# Before compiling, safe_exec rewrites player code so `a * b` becomes a call to
# _checked_mul(a, b), `a + b` to _checked_add(a, b), and so on (see _Guard below).
# Each guard works out how long the result would be, refuses past the cap, and
# otherwise does exactly the original operation - so numbers, and every error an
# ordinary mistake raises, behave as before.
_SEQUENCES = (str, bytes, list, tuple)


def _check_length(length: int) -> None:
    if length > MAX_SEQUENCE_LENGTH:
        raise SafetyError(SEQUENCE_TOO_LONG_MESSAGE)


def _repeat_length(a: object, b: object) -> int:
    """How long `a * b` would be if it repeats a sequence (0 if it doesn't)."""
    if isinstance(a, _SEQUENCES) and isinstance(b, int):
        return len(a) * b
    if isinstance(b, _SEQUENCES) and isinstance(a, int):
        return len(b) * a
    return 0


def _concat_length(a: object, b: object) -> int:
    """How long `a + b` would be if it joins two sequences (0 if it doesn't)."""
    if isinstance(a, _SEQUENCES) and isinstance(b, _SEQUENCES):
        return len(a) + len(b)
    return 0


def _checked_mul(a: Any, b: Any) -> Any:
    _check_length(_repeat_length(a, b))
    return a * b


def _checked_add(a: Any, b: Any) -> Any:
    _check_length(_concat_length(a, b))
    return a + b


def _measured(items: Any) -> Any:
    """``items`` in a form whose len() is known and under the cap.

    Anything with a length (list, range, set, dict, str ...) is returned as is. A
    generator, map() or zip() has no length until it is read, so it is read into
    a list here - one item at a time, stopping as soon as it passes the cap - and
    that list is returned for the caller to use instead (a generator can only be
    read once). Anything that isn't iterable at all is returned untouched, so the
    real operation raises its usual TypeError.
    """
    if isinstance(items, Collection):
        _check_length(len(items))
        return items
    if not isinstance(items, Iterable):
        return items
    out: list[Any] = []
    for item in items:
        out.append(item)
        if len(out) > MAX_SEQUENCE_LENGTH:
            raise SafetyError(SEQUENCE_TOO_LONG_MESSAGE)
    return out


def _grown_list(target: Any, value: Any) -> Any:
    """For a list growing by ``value`` (+=, extend, slice assignment): check the
    new length and hand back ``value`` (read into a list if it had no length)."""
    if not isinstance(target, list):
        return value
    value = _measured(value)
    if isinstance(value, Collection):
        _check_length(len(target) + len(value))
    return value


# `t *= v` / `t += v` stay in-place operations (a list is changed, not replaced);
# only the right-hand side goes through these, which check and hand it back.
def _checked_imul_operand(target: Any, value: Any) -> Any:
    _check_length(_repeat_length(target, value))
    return value


def _checked_iadd_operand(target: Any, value: Any) -> Any:
    _check_length(_concat_length(target, value))
    return _grown_list(target, value)   # `l += range(...)` / `l += gen` too


def _checked_slice_value(target: Any, value: Any) -> Any:
    """`l[a:b] = value` can grow l by len(value): check it like extend."""
    return _grown_list(target, value)


def _checked_star(value: Any) -> Any:
    """`[*a, *a]` builds a list from a's items: read a, under the cap."""
    return _measured(value)


# Methods that can build a huge string/list in one call. EVERY read of an
# attribute with one of these names - `s.join(...)`, `j = s.join`, `str.join` -
# becomes _guarded_attribute(obj, "join"), which hands back a checked version.
_GUARDED_METHODS = frozenset({"join", "extend", "replace", "ljust", "rjust", "center",
                              "zfill"})
_WIDTH_METHODS = frozenset({"ljust", "rjust", "center", "zfill"})
_GUARDED_TYPES = (str, bytes, list)


def _check_call(obj: Any, name: str, args: tuple[Any, ...],
                kwargs: dict[str, Any]) -> tuple[Any, ...]:
    """Check one call of ``obj.name(*args, **kwargs)``; returns the args to use."""
    if isinstance(obj, (str, bytes)):
        if name == "join" and len(args) == 1:
            parts = _measured(args[0])
            if isinstance(parts, Collection):
                sizes = sum(len(p) for p in parts if isinstance(p, _SEQUENCES))
                _check_length(sizes + len(obj) * max(len(parts) - 1, 0))
                return (parts,)
        elif name in _WIDTH_METHODS:
            width = args[0] if args else kwargs.get("width")
            if isinstance(width, int):
                _check_length(width)   # the width IS the length of the result
        elif name == "replace":
            old = args[0] if args else kwargs.get("old")
            new = args[1] if len(args) > 1 else kwargs.get("new")
            limit = args[2] if len(args) > 2 else kwargs.get("count", -1)
            if isinstance(old, type(obj)) and isinstance(new, type(obj)):
                # old has obj's type (checked above); mypy can't narrow via type(obj).
                # "" matches len(obj) + 1 times.
                count = obj.count(old)  # type: ignore[arg-type]
                if isinstance(limit, int) and 0 <= limit < count:
                    count = limit
                _check_length(len(obj) + count * (len(new) - len(old)))
    elif isinstance(obj, list) and name == "extend" and len(args) == 1:
        return (_grown_list(obj, args[0]),)
    return args


def _guarded_attribute(obj: Any, name: str) -> Any:
    """``obj.name`` for one of _GUARDED_METHODS, wrapped so every call is checked.

    Two shapes: a bound method (``s.join``: obj is the string) and an unbound one
    (``str.join``: obj is the class, and the string comes as the first argument).
    Any other object's attribute of the same name is handed back unchanged.
    """
    method = getattr(obj, name)   # a missing attribute raises the usual AttributeError
    if isinstance(obj, _GUARDED_TYPES):
        def bound(*args: Any, **kwargs: Any) -> Any:
            return method(*_check_call(obj, name, args, kwargs), **kwargs)
        return bound
    if isinstance(obj, type) and issubclass(obj, _GUARDED_TYPES):
        def unbound(*args: Any, **kwargs: Any) -> Any:
            if args and isinstance(args[0], obj):
                args = (args[0], *_check_call(args[0], name, args[1:], kwargs))
            return method(*args, **kwargs)
        return unbound
    return method


# `"%100000000d" % 5` pads to the width given in the format: check every width
# and precision written in it, and each number fed to a `*` width.
_PERCENT_FIELD = re.compile(r"%(?:\([^)]*\))?[-+ #0]*(\*|\d+)?(?:\.(\*|\d+))?")


def _checked_mod(a: Any, b: Any) -> Any:
    if isinstance(a, (str, bytes)):
        fmt = a if isinstance(a, str) else a.decode("latin-1")
        fields = list(_PERCENT_FIELD.finditer(fmt))
        for match in fields:
            for size in match.groups():
                if size and size != "*":   # more than 7 digits is over the cap anyway
                    _check_length(MAX_SEQUENCE_LENGTH + 1 if len(size) > 7 else int(size))
        if any("*" in match.groups() for match in fields):
            for value in (b if isinstance(b, tuple) else (b,)):
                if isinstance(value, int):
                    _check_length(abs(value))
    return a % b


def _checked_sum(iterable: Any, /, start: Any = 0) -> Any:
    """``sum`` for player code: sum(lists, []) joins lists, so measure it first."""
    if not isinstance(start, _SEQUENCES):
        return sum(iterable, start)
    items = _measured(iterable)
    _check_length(len(start) + sum(len(i) for i in items if isinstance(i, _SEQUENCES)))
    return sum(items, start)


def _checked_prod(iterable: Any, /, *, start: Any = 1) -> Any:
    """``math.prod`` for player code: math.prod(["x", 10**9]) is a string repeat."""
    result = start
    for item in iterable:
        result = _checked_mul(result, item)
    return result


# ---- write guard: shared classes and functions are read-only ---- #
# Player code may set attributes on its own objects (`t.x = 5`), but a class such
# as Turret is shared by the whole game: `Turret.dps = lambda self: 10**6` would
# change every turret, in this run and every later one - and the game would then
# call player code with no step budget around it. So every attribute write or
# delete (`obj.attr = ...`, `del obj.attr`, `obj.attr += ...`) first passes obj
# through this check.
def _writable(obj: Any) -> Any:
    if isinstance(obj, type):
        raise SafetyError(f"{obj.__name__} is a class shared by the whole game, so "
                          "loadout code may not change it; change your own objects")
    if isinstance(obj, types.FunctionType) and obj.__code__.co_filename != LOADOUT_FILENAME:
        raise SafetyError(f"{obj.__name__}() is shared by the whole game, so loadout "
                          "code may not change it")
    return obj


# The names the rewritten code calls the guards by. They contain "<" and ">", so
# they are not valid Python identifiers: player code can never type, rebind or
# shadow them. Only the compiler, given a rewritten tree, can refer to them.
_GUARD_NAMES: dict[str, Callable[..., Any]] = {
    "<mul>": _checked_mul,
    "<add>": _checked_add,
    "<imul>": _checked_imul_operand,
    "<iadd>": _checked_iadd_operand,
    "<mod>": _checked_mod,
    "<attr>": _guarded_attribute,
    "<slice>": _checked_slice_value,
    "<star>": _checked_star,
    "<writable>": _writable,
}

# Module functions swapped for a guarded version in the sandbox's copy of the module.
_REPLACED_NAMES: dict[str, dict[str, Callable[..., Any]]] = {
    "math": {"prod": _checked_prod},
}


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    allowed = name in ALLOWED_IMPORTS or (name == _FUTURE and bool(fromlist))
    if level != 0 or not allowed:
        raise SafetyError(f"import of {name!r} is not allowed")
    module = importlib.import_module(name)
    # Always hand back a fresh module object holding a copy of the real one's
    # names, so `m.X = ...` only rebinds the copy - never the real module's
    # constants (e.g. DEFAULT_GATE_COST) that the game itself reads.
    stand_in = types.ModuleType(name)
    stand_in.__dict__.update(module.__dict__)
    for attr in _READ_ONLY_NAMES.get(name, ()):
        value = getattr(module, attr)
        if (name, attr) in _COPIED_ITEMS:
            value = copy.deepcopy(value)   # a private copy of every item, too
        setattr(stand_in, attr, _read_only(value))
    for attr in _REFUSED_NAMES.get(name, ()):
        setattr(stand_in, attr, _refuse(attr))
    for attr, replacement in _REPLACED_NAMES.get(name, {}).items():
        setattr(stand_in, attr, replacement)
    return stand_in


def _capped_range(*args: int) -> range:
    """The ``range`` player code gets: the real one, refused past MAX_RANGE_LENGTH."""
    r = range(*args)
    try:
        length = len(r)
    except OverflowError:   # len() can't even report lengths past sys.maxsize
        length = MAX_RANGE_LENGTH + 1
    if length > MAX_RANGE_LENGTH:
        raise SafetyError(f"range() is limited to {MAX_RANGE_LENGTH:,} numbers here")
    return r


def _safe_builtins() -> dict:
    b = {n: getattr(_builtins, n) for n in _SAFE_BUILTIN_NAMES if hasattr(_builtins, n)}
    b["__import__"] = _guarded_import   # only resolves ALLOWED_IMPORTS
    b["range"] = _capped_range
    b["sum"] = _checked_sum
    b.update(_GUARD_NAMES)              # what the rewritten code calls (see _Guard)
    return b


def _guard_call(name: str, *args: ast.expr) -> ast.Call:
    return ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=list(args), keywords=[])


class _Guard(ast.NodeTransformer):
    """Rewrites player code so size- and write-sensitive operations go through
    the guards above. An ast.NodeTransformer walks the tree and replaces each node
    with whatever its visit_<NodeType> method returns."""

    def visit_BinOp(self, node: ast.BinOp) -> ast.expr:
        self.generic_visit(node)     # rewrite the operands first (a * b * c nests)
        name = {ast.Mult: "<mul>", ast.Add: "<add>", ast.Mod: "<mod>"}.get(type(node.op))
        if name is None:
            return node
        return ast.copy_location(_guard_call(name, node.left, node.right), node)

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AugAssign:
        name = {ast.Mult: "<imul>", ast.Add: "<iadd>"}.get(type(node.op))
        # a second copy of the target, to READ it for the size check. (For
        # `d[k()] += v` that evaluates k() twice; loadouts don't rely on that.)
        current = copy.deepcopy(node.target)
        current.ctx = ast.Load()
        target = node.target
        # `l[:0] += more` writes the grown slice back into l: check l's new length too
        container = copy.deepcopy(target.value) if name == "<iadd>" \
            and isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Slice) \
            else None
        self.generic_visit(node)
        if name is not None:
            node.value = ast.copy_location(
                _guard_call(name, self.visit(current), node.value), node.value)
        if container is not None:
            node.value = ast.copy_location(
                _guard_call("<slice>", self.visit(container), node.value), node.value)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.expr:
        self.generic_visit(node)
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            node.value = ast.copy_location(_guard_call("<writable>", node.value), node.value)
        elif node.attr in _GUARDED_METHODS:
            # any READ of s.join / str.join / l.extend ..., called right away or
            # kept for later, gets the checked version
            call = _guard_call("<attr>", node.value, ast.Constant(node.attr))
            return ast.copy_location(call, node)
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.Assign:
        # `l[a:b] = value` (a slice on the left) grows l by len(value)
        sliced = [t for t in node.targets
                  if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Slice)]
        container = copy.deepcopy(sliced[0].value) if len(node.targets) == 1 and sliced \
            else None
        self.generic_visit(node)
        if container is not None:
            node.value = ast.copy_location(
                _guard_call("<slice>", self.visit(container), node.value), node.value)
        return node

    def visit_Starred(self, node: ast.Starred) -> ast.Starred:
        # `[*a, *a]` reads a's items: check them (only when reading, not `x, *y = ...`)
        self.generic_visit(node)
        if isinstance(node.ctx, ast.Load):
            node.value = ast.copy_location(_guard_call("<star>", node.value), node.value)
        return node


def _guarded_compile(src: str) -> types.CodeType:
    tree = _Guard().visit(ast.parse(src))
    ast.fix_missing_locations(tree)   # give the new nodes line numbers
    return compile(tree, LOADOUT_FILENAME, "exec")


def _check_power(node: ast.BinOp | ast.AugAssign) -> None:
    """Reject `x ** n` with a huge constant n, and powers of powers (10 ** 10 ** 10)."""
    left = node.left if isinstance(node, ast.BinOp) else node.target
    exponent = node.right if isinstance(node, ast.BinOp) else node.value
    if isinstance(exponent, ast.UnaryOp):   # -5 is UnaryOp(USub, 5) in the tree
        exponent = exponent.operand
    if isinstance(exponent, ast.Constant) and isinstance(exponent.value, (int, float)):
        if abs(exponent.value) > MAX_CONST_EXPONENT:
            raise SafetyError(f"exponents above {MAX_CONST_EXPONENT} are not allowed here")
    for side in (left, exponent):
        if isinstance(side, ast.BinOp) and isinstance(side.op, ast.Pow):
            raise SafetyError("a power of a power (like 10 ** 10 ** 10) is not allowed here")


def check_code(src: str) -> None:
    """Raise SafetyError if the source uses anything outside the sandbox."""
    try:
        tree = ast.parse(src)
    except SyntaxError as err:
        raise SafetyError(f"syntax error: {err}") from err
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    raise SafetyError(f"import of {alias.name!r} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0:
                raise SafetyError("relative imports are not allowed")
            if node.module not in ALLOWED_IMPORTS and node.module != _FUTURE:
                raise SafetyError(f"import from {node.module!r} is not allowed")
            # the module may be allowed while the NAME is not: every module has a
            # __builtins__ (the real ones, with open/__import__), so check each name.
            # "*" is refused because it binds names we can't see from here.
            for alias in node.names:
                if alias.name == "*" or alias.name.startswith("_"):
                    raise SafetyError(f"importing {alias.name!r} is not allowed")
        elif isinstance(node, ast.Attribute):
            if _forbidden_attribute(node.attr):
                raise SafetyError(f"access to attribute {node.attr!r} is not allowed")
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise SafetyError(f"use of {node.id!r} is not allowed")
        elif isinstance(node, ast.ClassDef):
            raise SafetyError("defining classes is not allowed here")
        elif isinstance(node, ast.While):
            raise SafetyError("while loops are disabled here; use for/comprehensions")
        # The step budget stops runaway code by raising an exception. A bare
        # `except:` could swallow it, and a `finally:` block still runs after it -
        # with the line counter already switched off - so neither is allowed.
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            raise SafetyError("a bare `except:` is not allowed here; name the error, "
                              "e.g. `except IndexError:`")
        elif isinstance(node, (ast.Try, ast.TryStar)) and node.finalbody:
            raise SafetyError("`finally:` is not allowed here")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            _check_power(node)
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Pow):
            _check_power(node)


class _OutOfSteps(BaseException):
    """Raised inside player code when the step budget runs out.

    A BaseException (not an Exception) so the player's own `except Exception:` or
    `except ValueError:` cannot catch it and carry on. step_budget turns it into an
    ordinary SafetyError once it is back out of the player's code.
    """

    def __init__(self, lineno: int) -> None:
        super().__init__(lineno)
        self.lineno = lineno   # webgame reports this as the line to look at


# A context manager is what a `with` block uses: the code before `yield` runs on
# entering the block, the code in `finally` runs on leaving it - even if the block
# raised. @contextmanager turns this generator function into one.
@contextmanager
def step_budget(limit: int | None = None) -> Iterator[None]:
    """Stop player code that runs more than ``limit`` lines, with a SafetyError.

    ``limit`` defaults to DEFAULT_STEP_BUDGET, looked up at call time (so a test
    can shrink it for every caller at once).

    Usage::

        with step_budget():
            turrets = ns["build_loadout"](unlocked, slots)

    It uses ``sys.settrace``, Python's debugger hook: Python then calls a function
    of ours whenever a new frame (function call) starts, and that function can ask
    to hear about every line the frame runs. We only ask for frames compiled from
    player code (LOADOUT_FILENAME), so the game's own code runs at full speed.

    Any tracer already installed (a debugger, coverage) is paused for the block and
    put back afterwards. Blocks don't share a count: a nested step_budget replaces
    the outer one until it ends.
    """
    budget = DEFAULT_STEP_BUDGET if limit is None else limit
    steps = 0

    def count_lines(frame: types.FrameType, event: str, arg: Any) -> Any:
        nonlocal steps   # rebinds the counter in step_budget, not a new local
        if event == "line":
            steps += 1
            if steps > budget:
                # Python unhooks a tracer that raises, so this fires only once
                raise _OutOfSteps(frame.f_lineno)
        return count_lines

    def on_call(frame: types.FrameType, event: str, arg: Any) -> Any:
        # returning None means "don't trace this frame's lines"
        return count_lines if frame.f_code.co_filename == LOADOUT_FILENAME else None

    previous = sys.gettrace()
    sys.settrace(on_call)
    try:
        yield
    except _OutOfSteps as stop:
        raise SafetyError(TOO_LONG_MESSAGE) from stop
    finally:
        sys.settrace(previous)


def safe_exec(src: str, api: dict | None = None, *, max_steps: int | None = None) -> dict:
    """Validate then exec ``src`` in a locked-down namespace, returning its globals.

    ``api`` is injected so loadouts can use the game objects (Turret, make_gun, …)
    without importing anything. The module body runs under ``step_budget``; callers
    must wrap their later calls into the functions it defines the same way.
    """
    check_code(src)
    ns: dict = {"__builtins__": _safe_builtins(), "__name__": "loadout", "__package__": None}
    if api:
        ns.update(api)
    code = _guarded_compile(src)
    with step_budget(max_steps):
        exec(code, ns)  # noqa: S102 - checked + locked down above
    return ns
