"""The coach explains *why* and shows the fix as Python that really runs.

Every hint kind coaching() produces must carry a why and a fix. When a hint has
a ``code`` snippet, it is pasted into a loadout.py-shaped source and run through
the same paths real loadouts take: the web bridge's sandboxed ``load_loadout``,
and a plain exec + call like the desktop app's ``import loadout``.
"""

import json

import pytest
import webgame as wg

from chokepoint.arsenal import GUN_LIBRARY, MODULE_LIBRARY, Turret, make_gun
from chokepoint.gates import Gate
from chokepoint.hints import Hint, coaching
from chokepoint.limiter import Limiter
from chokepoint.maps import MAPS
from chokepoint.packets import Packet
from chokepoint.parsers import Parser
from chokepoint.simulation import PACKET_SPEED, PACKET_VOLUME, START_HEALTH, World


def _module_only_case() -> tuple[str, set[str]]:
    """A kind + unlock set where only a module (no gun) can cover the kind."""
    for mname, mod in MODULE_LIBRARY.items():
        for kind in sorted(mod.add_accepts):
            guns = [g for g in GUN_LIBRARY if kind not in make_gun(g).accepts]
            if guns:
                return kind, {guns[0], mname}
    pytest.skip("no module adds a kind that some gun lacks")


def _scenarios() -> dict[str, list[Hint]]:
    """One world per hint kind (and per fix branch), keyed by a readable name."""
    out: dict[str, list[Hint]] = {}

    w = World(MAPS["switchback"])
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])
    w.stats["ids"].spawned = 5
    out["coverage-gun"] = coaching(w)

    kind, unlocked = _module_only_case()
    w = World(MAPS["switchback"])
    w.unlocked = lambda: unlocked  # type: ignore[method-assign]
    w.stats[kind].spawned = 5
    out["coverage-module"] = coaching(w)

    w = World(MAPS["switchback"])
    w.unlocked = lambda: set()  # type: ignore[method-assign]
    w.stats["ids"].spawned = 5
    out["coverage-locked"] = coaching(w)

    w = World(MAPS["switchback"])
    w.packets.append(Packet("raw", 12, 12, 60, at="n1", payload="endpoint"))
    out["parse"] = coaching(w)

    w = World(MAPS["switchback"])
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])
    w.packets = [Packet("auth", PACKET_VOLUME, PACKET_VOLUME, PACKET_SPEED, at="n1")
                 for _ in range(12)]
    out["bottleneck"] = coaching(w)

    w = World(MAPS["switchback"])
    w.packets = [Packet("raw", PACKET_VOLUME, PACKET_VOLUME, PACKET_SPEED, at="n1",
                        payload="auth") for _ in range(12)]
    out["bottleneck-raw"] = coaching(w)

    w = World(MAPS["switchback"])
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])
    w.packets = [Packet("auth", PACKET_VOLUME, PACKET_VOLUME, PACKET_SPEED, at="n1")
                 for _ in range(3)]
    w.health = START_HEALTH * 0.5
    out["latency"] = coaching(w)

    w = World(MAPS["delta"])
    w.set_turrets([Turret(340, 180, make_gun("sieve"))])
    out["gate"] = coaching(w)

    w = World(MAPS["switchback"])
    w.set_turrets([Turret(200, 140, make_gun("sieve")),
                   Turret(440, 420, make_gun("scatter"))])
    out["ok"] = coaching(w)
    return out


def _hint(hints: list[Hint], concept: str) -> Hint:
    return next(h for h in hints if h.concept == concept)


EXPECTED = {  # scenario -> (concept, code_in or "" when the fix isn't code)
    "coverage-gun": ("consumer coverage", "build_loadout"),
    "coverage-module": ("consumer coverage", "build_loadout"),
    "coverage-locked": ("consumer coverage", ""),
    "parse": ("parse coverage", "build_parsers"),
    "bottleneck": ("backpressure / scaling consumers", "build_loadout"),
    "bottleneck-raw": ("backpressure / scaling consumers", "build_limiters"),
    "latency": ("latency / dwell", "build_loadout"),
    "gate": ("typed routing", "build_gates"),
    "ok": ("steady state", ""),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_hint_kind_explains_why_and_fix(name):
    concept, code_in = EXPECTED[name]
    h = _hint(_scenarios()[name], concept)
    assert h.why and h.fix
    assert h.code_in == code_in
    assert bool(h.code) == bool(code_in)


def test_why_names_the_pipeline_idea():
    s = _scenarios()
    assert "coverage gap" in _hint(s["coverage-gun"], "consumer coverage").why
    assert "backpressure" in _hint(s["bottleneck"], "backpressure / scaling consumers").why
    assert "dwell" in _hint(s["latency"], "latency / dwell").why
    assert "typed routing" in _hint(s["gate"], "typed routing").why


def test_snippets_name_the_suggested_tool():
    s = _scenarios()
    assert '"scatter"' in _hint(s["coverage-gun"], "consumer coverage").code
    assert "attach(MODULE_LIBRARY" in _hint(s["coverage-module"], "consumer coverage").code
    assert '"endpoint"' in _hint(s["parse"], "parse coverage").code
    assert "Limiter(" in _hint(s["bottleneck-raw"], "backpressure / scaling consumers").code


# ---- the snippets really run, through the real loadout paths ---- #
_RETURNS = {"build_loadout": "turrets", "build_parsers": "parsers",
            "build_gates": "gates", "build_limiters": "limiters"}
_TYPES = {"build_loadout": Turret, "build_parsers": Parser,
          "build_gates": Gate, "build_limiters": Limiter}


def _loadout_source(code: str, code_in: str) -> str:
    """A loadout.py with ``code`` pasted inside ``code_in`` (others left empty)."""
    lines = ["from chokepoint.arsenal import MODULE_LIBRARY, Turret, make_gun",
             "from chokepoint.gates import Gate",
             "from chokepoint.limiter import Limiter",
             "from chokepoint.parsers import Parser", ""]
    for fn, var in _RETURNS.items():
        lines.append(f"def {fn}(unlocked, slots):")
        lines.append(f"    {var} = []")
        if fn == code_in:
            lines += ["    " + ln for ln in code.splitlines()]
        lines += [f"    return {var}", ""]
    return "\n".join(lines)


def _coded_hints() -> list[tuple[str, Hint]]:
    return [(name, h) for name, hints in sorted(_scenarios().items())
            for h in hints if h.code]


def test_scenarios_cover_every_code_target():
    assert {h.code_in for _, h in _coded_hints()} == set(_RETURNS)


@pytest.mark.parametrize("case", range(len(_coded_hints())))
def test_snippet_runs_in_the_web_sandbox(case):
    name, h = _coded_hints()[case]
    wg.new_game("switchback", "easy")
    wg._world.bank.balance = 100_000          # the snippet, not the budget, is under test
    res = json.loads(wg.load_loadout(_loadout_source(h.code, h.code_in)))
    assert res.get("ok"), f"{name}: {res}"
    assert res["dropped"] == 0
    if h.code_in == "build_loadout":
        assert res["turrets"] == 1


@pytest.mark.parametrize("case", range(len(_coded_hints())))
def test_snippet_runs_as_a_desktop_loadout(case):
    name, h = _coded_hints()[case]
    ns: dict = {}
    exec(compile(_loadout_source(h.code, h.code_in), "<loadout>", "exec"), ns)
    built = ns[h.code_in](set(), MAPS["switchback"].slots)
    assert len(built) == 1 and isinstance(built[0], _TYPES[h.code_in]), name


# ---- the bridge carries why/fix/code to the browser ---- #
def test_bridge_coach_json_carries_why_fix_and_code():
    wg.new_game("trunk", "easy")
    wg._world.stats["ids"].spawned = 5        # an uncovered kind -> coverage hint
    coach = json.loads(wg.snapshot_json())["coach"]
    assert coach
    for h in coach:
        for key in ("text", "level", "why", "fix", "concept", "code", "code_in"):
            assert key in h
    top = coach[0]
    assert top["concept"] == "consumer coverage" and top["why"] and top["fix"]
    assert "turrets.append" in top["code"] and top["code_in"] == "build_loadout"
