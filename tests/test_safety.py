"""Tests for the loadout-code sandbox."""

import pytest

from chokepoint.arsenal import MODULE_LIBRARY, Turret, make_gun
from chokepoint.safety import SafetyError, check_code, safe_exec

_API = {"Turret": Turret, "make_gun": make_gun, "MODULE_LIBRARY": MODULE_LIBRARY}

GOOD = """
def build_loadout(unlocked, slots):
    turrets = [Turret(*slots[0], gun=make_gun("sieve"))]
    if "range+" in unlocked:
        turrets.append(Turret(*slots[1], gun=make_gun("scatter")))
    return turrets
"""


def test_valid_loadout_runs_and_returns_turrets():
    ns = safe_exec(GOOD, _API)
    turrets = ns["build_loadout"](set(), [(0, 0), (1, 1)])
    assert len(turrets) == 1 and turrets[0].gun.name == "sieve"


def test_allows_whitelisted_absolute_import():
    check_code("from chokepoint.arsenal import Turret, make_gun\n")
    check_code("import math\n")


@pytest.mark.parametrize("bad", [
    "import os\n",
    "from os import path\n",
    "from subprocess import run\n",
    "import js\n",                                  # the Pyodide DOM/JS bridge
    "from . import arsenal\n",                      # relative import
    "__import__('os')\n",
    "eval('1+1')\n",
    "exec('x=1')\n",
    "open('/etc/passwd')\n",
    "().__class__.__bases__\n",                     # classic sandbox-escape walk
    "x = (1).__class__\n",
    "y = ''.__class__.__mro__\n",
    "globals()\n",
    "getattr(x, 'y')\n",
    "class Evil: pass\n",
    "while True:\n    pass\n",
])
def test_rejects_dangerous_code(bad):
    with pytest.raises(SafetyError):
        check_code(bad)


@pytest.mark.parametrize("bad", [
    # frame/generator/code/traceback introspection: not dunders, but each one is a
    # step on the walk from your own frame back to the real builtins
    "g.gi_frame\n",
    "c.cr_frame\n",
    "a.ag_frame\n",
    "fr.f_back\n",
    "fr.f_globals\n",
    "fr.f_builtins\n",
    "tb.tb_frame\n",
    "fn.co_consts\n",
    "x._private\n",                                 # any leading underscore
    "'{0.__class__}'.format(1)\n",                  # format strings walk attributes too
    "'{x}'.format_map({})\n",
])
def test_rejects_introspection_attributes(bad):
    with pytest.raises(SafetyError):
        check_code(bad)


def test_generator_frame_walk_escape_is_blocked():
    # a generator's frame links back (f_back) to safe_exec's frame, whose f_builtins
    # are the REAL builtins (open, __import__) - the checker must stop the first step
    escape = (
        "def _g():\n"
        "    yield gen.gi_frame.f_back\n"
        "gen = _g()\n"
        "for fr in gen:\n"
        "    break\n"
        "real = fr.f_back.f_builtins\n"
    )
    with pytest.raises(SafetyError):
        safe_exec(escape, _API)


@pytest.mark.parametrize("bad", [
    # an allowed module, but the NAME imported from it is the module's real builtins
    "from chokepoint.arsenal import __builtins__ as B\n",
    "from math import __loader__\n",
    "from chokepoint.arsenal import _private\n",
    "from math import *\n",                          # star-import hides what it binds
])
def test_rejects_underscore_and_star_imported_names(bad):
    with pytest.raises(SafetyError):
        check_code(bad)


def test_future_import_is_allowed_and_runs():
    # the editor's exporter and the shipped loadout.py both start with this line
    ns = safe_exec("from __future__ import annotations\n" + GOOD, _API)
    assert len(ns["build_loadout"](set(), [(0, 0)])) == 1


@pytest.mark.parametrize("bad", [
    "import __future__\n",                           # only the from-form is a compiler switch
    "from __future__ import *\n",
])
def test_future_module_itself_stays_blocked(bad):
    with pytest.raises(SafetyError):
        check_code(bad)


def test_common_exceptions_can_be_caught_and_raised():
    ns = safe_exec(
        "def first(items):\n"
        "    try:\n"
        "        return items[0]\n"
        "    except IndexError:\n"
        "        return None\n"
        "def check(n):\n"
        "    if n < 0:\n"
        "        raise ValueError('n must be >= 0')\n"
        "    return n\n")
    assert ns["first"]([]) is None and ns["first"]([7]) == 7
    with pytest.raises(ValueError):
        ns["check"](-1)


def test_safe_exec_blocks_import_even_if_ast_missed_it():
    # belt-and-suspenders: the guarded __import__ also refuses non-allowlisted modules
    with pytest.raises(SafetyError):
        safe_exec("import os\n")


def test_syntax_error_is_a_safety_error():
    with pytest.raises(SafetyError):
        check_code("def build_loadout(:\n")
