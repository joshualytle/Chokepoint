"""Tests for the loadout-code sandbox."""

import math
from pathlib import Path
from types import MappingProxyType

import pytest

from chokepoint import arsenal, gates, loadout, maps
from chokepoint.arsenal import MODULE_LIBRARY, Turret, make_gun, unlocked_at
from chokepoint.editor import ArsenalEditor
from chokepoint.lessons import LESSONS
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
    assert ns["trunk"] is maps.MAPS["trunk"] and ns["has_trunk"]
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
