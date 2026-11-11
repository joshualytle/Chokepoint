"""Sandboxing for player-authored loadout code.

The UI execs the player's Python (``build_loadout`` and friends). Under Pyodide
that code shares the browser context — it could import ``js``/``os``, reach the
network or DOM, or escape via dunder tricks. And because builds/save-codes are
meant to be shareable, one player's code could otherwise run in another's
browser. So all player code goes through here first.

Two layers of defense:
  * ``check_code`` — an AST allowlist: reject imports outside a tiny set, reject
    underscore and introspection attribute access (``__class__``, ``gi_frame``,
    ``f_back``, ``co_consts`` …) and ``str.format``,
    reject dangerous names (eval/exec/open/__import__ …), and reject class defs
    and ``while`` loops (a loadout needs neither, and ``while`` can hang the tab).
  * ``safe_exec`` — exec with a curated, minimal ``__builtins__`` plus a guarded
    ``__import__`` that only resolves the allowlist (handing back shared
    registries as read-only views), so there is little to reach even if
    something slips past the AST pass.

Python sandboxing is not provably complete, but this blocks the practical
vectors. Treat it as defense in depth: do not auto-run untrusted *shared* code
without a review step.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import importlib
import types
from collections.abc import Callable
from typing import Any, NoReturn


class SafetyError(ValueError):
    """Raised when loadout code uses something the sandbox forbids."""


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
_FORBIDDEN_ATTRS = frozenset({"format", "format_map"})


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
        setattr(stand_in, attr, _read_only(getattr(module, attr)))
    for attr in _REFUSED_NAMES.get(name, ()):
        setattr(stand_in, attr, _refuse(attr))
    return stand_in


def _safe_builtins() -> dict:
    b = {n: getattr(_builtins, n) for n in _SAFE_BUILTIN_NAMES if hasattr(_builtins, n)}
    b["__import__"] = _guarded_import   # only resolves ALLOWED_IMPORTS
    return b


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


def safe_exec(src: str, api: dict | None = None) -> dict:
    """Validate then exec ``src`` in a locked-down namespace, returning its globals.

    ``api`` is injected so loadouts can use the game objects (Turret, make_gun, …)
    without importing anything.
    """
    check_code(src)
    ns: dict = {"__builtins__": _safe_builtins(), "__name__": "loadout", "__package__": None}
    if api:
        ns.update(api)
    exec(compile(src, "<loadout>", "exec"), ns)  # noqa: S102 - checked + locked down above
    return ns
