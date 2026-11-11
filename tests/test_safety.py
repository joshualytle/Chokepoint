"""Tests for the loadout-code sandbox."""

from pathlib import Path

import pytest

from chokepoint import loadout
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


@pytest.mark.parametrize("bad", [
    "from chokepoint.arsenal import MODULE_LIBRARY\nMODULE_LIBRARY.clear()\n",
    "from chokepoint.arsenal import MODULE_LIBRARY\nMODULE_LIBRARY['amp'] = None\n",
    "import chokepoint.arsenal\nchokepoint.MODULE_LIBRARY.clear()\n",
])
def test_imported_module_library_is_read_only(bad):
    # web/webgame.py injects a read-only MODULE_LIBRARY; importing it must not
    # hand back the live registry dict instead.
    before = dict(MODULE_LIBRARY)
    try:
        with pytest.raises((TypeError, AttributeError)):
            safe_exec(bad)
        assert MODULE_LIBRARY == before
    finally:
        MODULE_LIBRARY.clear()          # repair the shared registry if the test failed
        MODULE_LIBRARY.update(before)


def test_imported_module_library_can_still_be_read():
    ns = safe_exec(
        "from chokepoint.arsenal import MODULE_LIBRARY\n"
        "amp = MODULE_LIBRARY['amp']\n"
        "has_amp = 'amp' in MODULE_LIBRARY\n"
        "names = sorted(MODULE_LIBRARY)\n"
        "maybe = MODULE_LIBRARY.get('nope')\n")
    assert ns["amp"] is MODULE_LIBRARY["amp"] and ns["has_amp"]
    assert ns["names"] == sorted(MODULE_LIBRARY) and ns["maybe"] is None


def test_shipped_loadout_passes_the_sandbox():
    # the example loadout.py is what players paste into the web editor, so it
    # must use the absolute imports the sandbox allows (not `from .arsenal`)
    src = Path(loadout.__file__).read_text(encoding="utf-8")
    check_code(src)
    ns = safe_exec(src)
    slots = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert len(ns["build_loadout"]({"amp"}, slots)) == 2
    assert len(ns["build_parsers"](set(), slots)) == 1


def test_syntax_error_is_a_safety_error():
    with pytest.raises(SafetyError):
        check_code("def build_loadout(:\n")
