"""Sandboxing for player-authored loadout code.

The UI execs the player's Python (``build_loadout`` and friends). Under Pyodide
that code shares the browser context — it could import ``js``/``os``, reach the
network or DOM, or escape via dunder tricks. And because builds/save-codes are
meant to be shareable, one player's code could otherwise run in another's
browser. So all player code goes through here first.

Two layers of defense:
  * ``check_code`` — an AST allowlist: reject imports outside a tiny set, reject
    dunder attribute access (``__class__``/``__globals__``/``__subclasses__`` …),
    reject dangerous names (eval/exec/open/__import__ …), and reject class defs
    and ``while`` loops (a loadout needs neither, and ``while`` can hang the tab).
  * ``safe_exec`` — exec with a curated, minimal ``__builtins__`` plus a guarded
    ``__import__`` that only resolves the allowlist, so there is little to reach
    even if something slips past the AST pass.

Python sandboxing is not provably complete, but this blocks the practical
vectors. Treat it as defense in depth: do not auto-run untrusted *shared* code
without a review step.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import importlib


class SafetyError(ValueError):
    """Raised when loadout code uses something the sandbox forbids."""


# modules a loadout may import (absolute paths only); everything else is rejected
ALLOWED_IMPORTS = frozenset({
    "chokepoint.arsenal",
    "chokepoint.parsers",
    "chokepoint.maps",
    "math",
})

# builtins the code may use — a small, side-effect-free set (no import/eval/open)
_SAFE_BUILTIN_NAMES = frozenset({
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float",
    "int", "isinstance", "len", "list", "map", "max", "min", "print", "range",
    "reversed", "round", "set", "frozenset", "sorted", "str", "sum", "tuple", "zip",
})

# names that must never appear at all — fast, explicit rejection with a clear message
_FORBIDDEN_NAMES = frozenset({
    "__import__", "eval", "exec", "compile", "open", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "__build_class__", "exit", "quit",
})


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    if level != 0 or name not in ALLOWED_IMPORTS:
        raise SafetyError(f"import of {name!r} is not allowed")
    return importlib.import_module(name)


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
            if node.module not in ALLOWED_IMPORTS:
                raise SafetyError(f"import from {node.module!r} is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise SafetyError(f"access to dunder attribute {node.attr!r} is not allowed")
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
