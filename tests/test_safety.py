"""Tests for the loadout-code sandbox."""

import math
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

from chokepoint import arsenal, gates, loadout, maps
from chokepoint.arsenal import MODULE_LIBRARY, Turret, make_gun, unlocked_at
from chokepoint.editor import ArsenalEditor
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


def _shared_state() -> dict:
    """Copies of every shared registry/constant a loadout could try to change."""
    return {
        "GUN_LIBRARY": dict(arsenal.GUN_LIBRARY),
        "MODULE_LIBRARY": dict(arsenal.MODULE_LIBRARY),
        "SYNERGIES": list(arsenal.SYNERGIES),
        "MAPS": dict(maps.MAPS),
        "MAP_LIST": list(maps.MAP_LIST),
        "DEFAULT_GATE_COST": gates.DEFAULT_GATE_COST,
        "pi": math.pi,
    }


@pytest.fixture
def saved_state():
    """Snapshot the shared state, and put it back afterwards so a failing test
    can't break the rest of the suite (the game holds these exact objects, so
    repair them in place rather than rebinding)."""
    saved = _shared_state()
    yield saved
    for registry, key in ((arsenal.GUN_LIBRARY, "GUN_LIBRARY"),
                          (arsenal.MODULE_LIBRARY, "MODULE_LIBRARY"), (maps.MAPS, "MAPS")):
        registry.clear()
        registry.update(saved[key])
    arsenal.SYNERGIES[:] = saved["SYNERGIES"]
    maps.MAP_LIST[:] = saved["MAP_LIST"]
    gates.DEFAULT_GATE_COST = saved["DEFAULT_GATE_COST"]
    math.pi = saved["pi"]


@pytest.mark.parametrize("bad", [
    # GUN_LIBRARY (dict of gun factories) - both import styles
    "from chokepoint.arsenal import GUN_LIBRARY\nGUN_LIBRARY.clear()\n",
    "from chokepoint.arsenal import GUN_LIBRARY\nGUN_LIBRARY['sieve'] = None\n",
    "import chokepoint.arsenal\nchokepoint.GUN_LIBRARY.pop('sieve')\n",
    # SYNERGIES (a list) - read-only means a tuple: no append/clear/item assignment
    "from chokepoint.arsenal import SYNERGIES\nSYNERGIES.clear()\n",
    "from chokepoint.arsenal import SYNERGIES\nSYNERGIES[0] = None\n",
    "import chokepoint.arsenal\nchokepoint.SYNERGIES.append(None)\n",
    # MAPS (dict of Graphs) and MAP_LIST (list of names)
    "from chokepoint.maps import MAPS\nMAPS.clear()\n",
    "from chokepoint.maps import MAPS\nMAPS['trunk'] = None\n",
    "import chokepoint.maps\nchokepoint.MAPS.pop('trunk')\n",
    "from chokepoint.maps import MAP_LIST\nMAP_LIST.append('nowhere')\n",
    "import chokepoint.maps\nchokepoint.MAP_LIST.clear()\n",
    # registration functions would write straight into the real registries
    "from chokepoint.arsenal import register_gun\nregister_gun('evil')(lambda: None)\n",
    "import chokepoint.arsenal\nchokepoint.register_gun('evil')(lambda: None)\n",
    "from chokepoint.arsenal import Module, register_module\n"
    "register_module(Module('evil', 'x'))\n",
    "import chokepoint.arsenal\n"
    "chokepoint.register_module(chokepoint.Module('evil', 'x'))\n",
])
def test_imported_registries_are_read_only(bad, saved_state):
    with pytest.raises((TypeError, AttributeError, SafetyError)):
        safe_exec(bad)
    assert _shared_state() == saved_state


@pytest.mark.parametrize("rebind", [
    "import chokepoint.maps\nchokepoint.MAPS = {}\n",
    "import chokepoint.arsenal\nchokepoint.GUN_LIBRARY = {}\n",
    "import chokepoint.gates\nchokepoint.DEFAULT_GATE_COST = 0\n",
    "import math\nmath.pi = 3\n",
])
def test_rebinding_a_module_name_does_not_reach_the_real_module(rebind, saved_state):
    # rebinding is allowed (it only changes the loadout's own copy of the module),
    # but the real module the game reads every wave must not change
    safe_exec(rebind)
    assert _shared_state() == saved_state


def test_imported_registries_can_still_be_read():
    ns = safe_exec(
        "from chokepoint.arsenal import GUN_LIBRARY, SYNERGIES\n"
        "from chokepoint.maps import MAP_LIST, MAPS\n"
        "sieve = GUN_LIBRARY['sieve']()\n"
        "has_sieve = 'sieve' in GUN_LIBRARY\n"
        "gun_names = sorted(GUN_LIBRARY)\n"
        "n_synergies = len(SYNERGIES)\n"
        "synergy_names = [s.name for s in SYNERGIES]\n"
        "trunk = MAPS['trunk']\n"
        "has_trunk = 'trunk' in MAPS\n"
        "map_names = sorted(MAPS)\n"
        "first_map = MAP_LIST[0]\n"
        "n_maps = len(MAP_LIST)\n")
    assert ns["sieve"].name == "sieve" and ns["has_sieve"]
    assert ns["gun_names"] == sorted(arsenal.GUN_LIBRARY)
    assert ns["n_synergies"] == len(arsenal.SYNERGIES)
    assert ns["synergy_names"] == [s.name for s in arsenal.SYNERGIES]
    assert ns["trunk"] == maps.MAPS["trunk"] and ns["has_trunk"]   # a private copy
    assert ns["map_names"] == sorted(maps.MAPS)
    assert ns["first_map"] == maps.MAP_LIST[0] and ns["n_maps"] == len(maps.MAP_LIST)


def test_game_imports_still_see_the_real_registries():
    # only sandboxed imports get stand-ins; the game's own modules are untouched
    safe_exec("from chokepoint.arsenal import GUN_LIBRARY\nfrom chokepoint.maps import MAPS\n")
    assert type(arsenal.GUN_LIBRARY) is dict and type(arsenal.MODULE_LIBRARY) is dict
    assert type(arsenal.SYNERGIES) is list
    assert type(maps.MAPS) is dict and type(maps.MAP_LIST) is list
    assert arsenal.register_gun("sieve") is not None   # the real decorator, not the refuser


def _run_starter(src: str, api: dict | None = None) -> list:
    check_code(src)
    ns = safe_exec(src, api)
    return ns["build_loadout"](unlocked_at(99), [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])


@pytest.mark.parametrize("lesson", [le for le in LESSONS if le.starter is not None],
                         ids=lambda le: le.title)
def test_lesson_starters_run_in_the_sandbox(lesson):
    assert isinstance(_run_starter(lesson.starter), list)


def test_web_default_loadout_runs_in_the_sandbox():
    # the starter text web/app.js puts in the editor (a JS template literal);
    # it relies on the names web/webgame.py injects instead of imports
    app_js = (Path(__file__).parent.parent / "web" / "app.js").read_text(encoding="utf-8")
    src = app_js.split("const DEFAULT_LOADOUT = `", 1)[1].split("`;", 1)[0]
    api = {"Turret": Turret, "make_gun": make_gun,
           "MODULE_LIBRARY": MappingProxyType(MODULE_LIBRARY)}
    assert _run_starter(src, api) == []


def test_editor_export_runs_in_the_sandbox():
    ed = ArsenalEditor(unlocked_at(99))
    ed.select_gun("sieve")
    ed.toggle_module("range+")
    ed.place(100, 120)
    ed.select_gate()
    ed.place_gate(180, 340)
    ed.select_limiter()
    ed.place_limiter(90, 200)
    turrets = _run_starter(ed.to_python(maps.MAPS["trunk"]))
    assert [t.gun.name for t in turrets] == ["sieve"]
    assert [m.name for m in turrets[0].gun.modules] == ["range+"]


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


# ---- huge strings/lists built in one C call (the step budget can't see them) ---- #
# Each of these would try to allocate gigabytes (or hang) without a size cap. They
# must be stopped before the allocation happens, with a clear message.
@pytest.mark.parametrize("bad", [
    "x = 'x' * 10 ** 9\n",
    "x = [0] * 10 ** 9\n",
    "x = 10 ** 9 * (0,)\n",                          # repeat count on the left
    "x = b'x' * 10 ** 9\n",
    "s = 'ab'\nx = s * (10 ** 5) * (10 ** 5)\n",     # a variable, grown in two steps
    "n = 10 ** 9\nx = [None] * n\n",
    "s = 'x'\ns *= 10 ** 9\n",                       # in-place repeat
    "s = 'x'\nfor i in range(40):\n    s += s\n",    # doubling under the step budget
    "s = 'x'\nfor i in range(40):\n    s = s + s\n",
    "l = [0]\nfor i in range(40):\n    l += l\n",
    "d = {'k': [0]}\nfor i in range(40):\n    d['k'] += d['k']\n",
    "l = [0]\nfor i in range(40):\n    l.extend(l)\n",
    "s = 'x' * 1000\nx = s.join([s] * 1000)\n",       # each piece is fine, the join is not
    "s = 'x' * 1000\nx = s.replace('', s)\n",
    "x = 'x'.ljust(10 ** 9)\n",
    "big = [0] * 1000000\nx = sum([big] * 1000, [])\n",
    "import math\nx = math.prod(['x', 10 ** 9])\n",
])
def test_huge_sequences_are_refused(bad):
    with pytest.raises(SafetyError, match="longer than"):
        safe_exec(bad)


def test_huge_sequence_in_a_player_function_is_refused():
    ns = safe_exec("def build_loadout(u, s):\n    return [0] * len(s) ** 9\n")
    with pytest.raises(SafetyError, match="longer than"), step_budget():
        ns["build_loadout"](set(), [(0, 0)] * 10)


def test_sequences_up_to_the_cap_still_work():
    ns = safe_exec(
        "row = [0] * 1000\n"
        "grid = [[0] * 1000 for i in range(10)]\n"
        "line = '-' * 40\n"
        "big = 'x' * 1000000\n"
        "pair = (1, 2) * 3\n"
        "words = ', '.join(['a', 'b'])\n"
        "label = 'gun'.ljust(8) + '|'\n"
        "msg = 'a-b'.replace('-', '+')\n"
        "nums = [1, 2]\nnums += [3]\nnums.extend([4])\nnums *= 2\n"
        "flat = sum([[1], [2]], [])\n"
        "import math\nfactor = math.prod([2, 3, 4])\n"
        "total = 2 * 3 + 4.5 * 2\n")
    assert ns["row"] == [0] * 1000 and len(ns["grid"]) == 10 and len(ns["big"]) == 1_000_000
    assert ns["line"] == "-" * 40 and ns["pair"] == (1, 2, 1, 2, 1, 2)
    assert ns["words"] == "a, b" and ns["label"] == "gun     |" and ns["msg"] == "a+b"
    assert ns["nums"] == [1, 2, 3, 4, 1, 2, 3, 4] and ns["flat"] == [1, 2]
    assert ns["factor"] == 24 and ns["total"] == 15.0


@pytest.mark.parametrize(("src", "err"), [
    ("x = 'a' + 1\n", TypeError),
    ("x = [1] * 'a'\n", TypeError),
    ("x = [].join([])\n", AttributeError),
])
def test_ordinary_mistakes_raise_the_same_errors(src, err):
    # the size guards must not change what an ordinary mistake raises
    with pytest.raises(err):
        safe_exec(src)


# ---- shared classes and maps: reads work, writes can't leak into the game ---- #
def _class_state() -> dict:
    return {"Turret": dict(vars(Turret)), "Gun": dict(vars(arsenal.Gun)),
            "Graph": dict(vars(maps.Graph)),
            "sieve": dict(vars(arsenal.GUN_LIBRARY["sieve"])),
            "make_gun": dict(vars(make_gun))}


@pytest.mark.parametrize("bad", [
    "from chokepoint.arsenal import Turret\nTurret.dps = lambda self: 10 ** 6\n",
    "from chokepoint.arsenal import Gun\nGun.fire_rate = 99\n",
    "from chokepoint.maps import Graph\ndel Graph.copy\n",
    "import chokepoint.maps\nchokepoint.Graph.copy = None\n",
    "from chokepoint.arsenal import Turret\nTurret.cd += 1\n",
    "from chokepoint.arsenal import Turret\nfor Turret.cd in [5]:\n    pass\n",
    "from chokepoint.arsenal import Turret\nTurret.cd, x = 5, 1\n",
    "from chokepoint.arsenal import GUN_LIBRARY\nGUN_LIBRARY['sieve'].tag = 1\n",
    "Turret.cd = 5\n",                                 # a class injected by the UI's api
    "make_gun.tag = 1\n",
])
def test_shared_classes_and_functions_cannot_be_changed(bad):
    before = _class_state()
    with pytest.raises(SafetyError, match="shared"):
        safe_exec(bad, _API)
    assert _class_state() == before


def test_own_objects_and_functions_can_still_be_changed():
    ns = safe_exec(
        "t = Turret(0, 0, gun=make_gun('sieve'))\n"
        "t.x = 5\n"
        "t.gun.damage += 1\n"
        "def helper():\n    return 1\n"
        "helper.note = 'mine'\n"
        "import math\nmath.tau = 6\n", _API)
    assert ns["t"].x == 5 and ns["t"].gun.damage == make_gun("sieve").damage + 1
    assert ns["helper"].note == "mine" and math.tau != 6


def _map_state() -> dict:
    return {name: (g.source, dict(g.nodes), {k: list(v) for k, v in g.adj.items()},
                   list(g.slots))
            for name, g in maps.MAPS.items()}


@pytest.mark.parametrize("bad", [
    "from chokepoint.maps import MAPS\nMAPS['trunk'].slots.clear()\n",
    "from chokepoint.maps import MAPS\nMAPS['trunk'].slots.append((1, 1))\n",
    "from chokepoint.maps import MAPS\nMAPS['trunk'].nodes.clear()\n",
    "from chokepoint.maps import MAPS\nMAPS['trunk'].adj['n0'].clear()\n",
    "from chokepoint.maps import MAPS\nMAPS['trunk'].add_node(1, 1)\n",
    "from chokepoint.maps import MAPS\nMAPS['trunk'].source = 'nowhere'\n",
    "import chokepoint.maps\nchokepoint.MAPS['trunk'].slots[0] = (9, 9)\n",
])
def test_a_maps_own_nodes_and_slots_cannot_be_changed(bad):
    before = _map_state()
    safe_exec(bad)        # allowed: it only changes the loadout's private copy
    assert _map_state() == before
