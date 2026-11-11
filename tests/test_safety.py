"""Tests for the loadout-code sandbox."""

import sys
from pathlib import Path

import pytest

from chokepoint import loadout
from chokepoint.arsenal import MODULE_LIBRARY, Turret, make_gun
from chokepoint.lessons import LESSONS
from chokepoint.safety import TOO_LONG_MESSAGE, SafetyError, check_code, safe_exec, step_budget

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


# ---- step budget: runaway player code is stopped, not left to freeze the tab ---- #
# Each loop here is small enough to finish quickly WITHOUT a budget, so these tests
# fail fast (rather than hang) on code that has no step budget.

def test_huge_loop_in_module_body_is_cut_off():
    with pytest.raises(SafetyError, match="ran too long"):
        safe_exec("for i in range(10000):\n    pass\n", max_steps=100)


def test_huge_loop_in_a_player_function_is_cut_off():
    ns = safe_exec("def build_loadout(u, s):\n"
                   "    for i in range(10000):\n"
                   "        pass\n"
                   "    return []\n")
    with pytest.raises(SafetyError) as caught, step_budget(100):
        ns["build_loadout"](set(), [])
    assert str(caught.value) == TOO_LONG_MESSAGE
    assert caught.value.__cause__.lineno in (2, 3)   # points into the loop


@pytest.mark.parametrize("body", [
    "x = [i for i in range(10000)]\n",                          # list comprehension
    "x = sum(i for i in range(10000))\n",                       # generator expression
    "x = sum(j for i in range(100) for j in range(100))\n",     # nested generator
    "def g():\n    for i in range(10000):\n        yield i\nx = list(g())\n",
    "x = list(map(lambda i: i, range(10000)))\n",               # called from C
], ids=["listcomp", "genexp", "nested-genexp", "generator", "lambda-via-map"])
def test_comprehensions_and_generators_are_counted(body):
    with pytest.raises(SafetyError, match="ran too long"):
        safe_exec(body, max_steps=500)


def test_player_cannot_catch_the_stop_and_carry_on():
    # the stop is not an Exception, so `except Exception:` must not swallow it
    ns = safe_exec("def build_loadout(u, s):\n"
                   "    try:\n"
                   "        for i in range(10000):\n"
                   "            pass\n"
                   "    except Exception:\n"
                   "        return 'caught'\n"
                   "    return []\n")
    with pytest.raises(SafetyError, match="ran too long"), step_budget(100):
        ns["build_loadout"](set(), [])


@pytest.mark.parametrize("lesson", [le for le in LESSONS if le.starter],
                         ids=lambda le: le.title)
def test_lesson_starters_run_under_the_default_budget(lesson):
    ns = safe_exec(lesson.starter, {"Turret": Turret, "make_gun": make_gun})
    with step_budget():
        ns["build_loadout"](set(), [(float(i), 0.0) for i in range(40)])


def test_normal_code_well_inside_the_budget_is_unaffected():
    ns = safe_exec(GOOD, _API, max_steps=50)
    with step_budget(50):
        assert len(ns["build_loadout"]({"range+"}, [(0, 0), (1, 1)])) == 2


def test_previous_trace_function_is_restored_and_still_works():
    # a debugger or coverage tool may already be tracing: the budget pauses it and
    # must hand it back afterwards - after success AND after a cut-off
    seen: list[str] = []

    def outer_tracer(frame, event, arg):
        seen.append(frame.f_code.co_name)

    def probe():
        return 1

    original = sys.gettrace()
    sys.settrace(outer_tracer)
    try:
        safe_exec("x = 1\n", max_steps=10)
        assert sys.gettrace() is outer_tracer
        with pytest.raises(SafetyError):
            safe_exec("for i in range(1000):\n    pass\n", max_steps=10)
        assert sys.gettrace() is outer_tracer
        probe()                          # the restored tracer still sees new calls
    finally:
        sys.settrace(original)
    assert "probe" in seen


def test_step_budget_leaves_no_tracer_behind():
    original = sys.gettrace()
    with pytest.raises(SafetyError):
        safe_exec("for i in range(1000):\n    pass\n", max_steps=10)
    assert sys.gettrace() is original


# ---- one-line hangs the step budget can't see (the work happens inside C) ---- #
@pytest.mark.parametrize("bad", [
    "x = 10 ** 10 ** 10\n",               # a power of a power
    "x = (10 ** 5) ** 3\n",
    "x = 2 ** 100000\n",                  # a huge constant exponent
    "x = 2 ** -100000\n",
    "x = 2\nx **= 5000\n",
    "try:\n    pass\nexcept:\n    pass\n",          # bare except could swallow the stop
    "try:\n    pass\nfinally:\n    pass\n",          # finally runs after the stop
    "x = Exception.mro()\n",                         # reaches BaseException
])
def test_rejects_code_that_could_dodge_the_step_budget(bad):
    with pytest.raises(SafetyError):
        check_code(bad)


@pytest.mark.parametrize("ok", ["x = 3 ** 2\n", "x = 2.0 ** 0.5\n", "x = 2 ** -3\n",
                                "x = 7\ny = x ** x\n"])
def test_ordinary_powers_are_still_allowed(ok):
    safe_exec(ok)


@pytest.mark.parametrize("bad", ["x = range(10 ** 15)\n", "x = sum(range(10 ** 7))\n",
                                 "x = range(0, 10 ** 30, 2)\n"])
def test_huge_ranges_are_refused(bad):
    with pytest.raises(SafetyError, match="range"):
        safe_exec(bad)


def test_ranges_up_to_the_cap_still_work():
    ns = safe_exec("n = len(range(1000000))\nback = list(range(5, 0, -1))\n")
    assert ns["n"] == 1_000_000 and ns["back"] == [5, 4, 3, 2, 1]
