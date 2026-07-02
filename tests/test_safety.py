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


def test_safe_exec_blocks_import_even_if_ast_missed_it():
    # belt-and-suspenders: the guarded __import__ also refuses non-allowlisted modules
    with pytest.raises(SafetyError):
        safe_exec("import os\n")


def test_syntax_error_is_a_safety_error():
    with pytest.raises(SafetyError):
        check_code("def build_loadout(:\n")
