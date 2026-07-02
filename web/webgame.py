"""Bridge between the Python game core and the web (JS) UI — runs in Pyodide.

The whole simulation stays in Python (this is the "Python front end for training"
part). This module exposes a tiny, JSON-friendly surface so the JavaScript UI can
drive and draw the game without touching the Python object graph:

    new_game(map_name, difficulty)   -> reset
    load_loadout(src)                -> run the player's build_loadout, deploy it
    step(dt)                         -> advance the simulation
    set_paused(flag) / begin()       -> pause control
    snapshot_json()                  -> a JSON string of everything the UI draws

Only pure-Python modules are imported (no pygame), so it loads cleanly under
Pyodide.
"""

from __future__ import annotations

import json

from chokepoint.arsenal import MODULE_LIBRARY, Module, Turret, make_gun
from chokepoint.maps import MAP_LIST, MAPS
from chokepoint.packets import DIFFICULTY_LIST, KINDS
from chokepoint.parsers import Parser
from chokepoint.safety import SafetyError, safe_exec
from chokepoint.simulation import MAX_LEAK, START_HEALTH, World

# the game objects a loadout may use, injected so no imports are even required
_LOADOUT_API = {
    "Turret": Turret, "make_gun": make_gun, "Module": Module,
    "MODULE_LIBRARY": MODULE_LIBRARY, "Parser": Parser,
}

_world: World | None = None


def new_game(map_name: str = "trunk", difficulty: str = "easy") -> str:
    global _world
    if map_name not in MAPS:
        map_name = MAP_LIST[0]
    _world = World(MAPS[map_name].copy(), difficulty=difficulty)
    _world.paused = True                 # start on the wave preview; UI presses Start
    return json.dumps({"ok": True, "maps": MAP_LIST, "difficulties": DIFFICULTY_LIST})


def load_loadout(src: str) -> str:
    """Exec the player's build_loadout and deploy the turrets it returns."""
    assert _world is not None
    try:
        ns = safe_exec(src, _LOADOUT_API)   # sandboxed: no arbitrary imports / escapes
        if "build_loadout" not in ns:
            raise ValueError("define build_loadout(unlocked, slots)")
        turrets = ns["build_loadout"](_world.unlocked(), _world.map.slots)
    except SafetyError as err:
        return json.dumps({"ok": False, "error": f"blocked: {err}"})
    except Exception as err:  # report author errors to the editor, never crash
        return json.dumps({"ok": False, "error": f"{type(err).__name__}: {err}"})
    _world.set_turrets(turrets)
    _world.autoroute()
    return json.dumps({"ok": True, "turrets": len(turrets)})


def set_paused(flag: bool) -> None:
    if _world is not None:
        _world.paused = bool(flag)


def begin() -> None:
    if _world is not None:
        _world.paused = False


def step(dt: float) -> None:
    if _world is not None:
        _world.step(dt)


def _packet_xy(p, m):
    if p.moving_to is None:
        return m.pos(p.at)
    ax, ay = m.pos(p.at)
    bx, by = m.pos(p.moving_to)
    seg = m.edge_len(p.at, p.moving_to) or 1.0
    t = max(0.0, min(1.0, p.seg_pos / seg))
    return ax + (bx - ax) * t, ay + (by - ay) * t


def snapshot() -> dict:
    w = _world
    assert w is not None
    m = w.map
    gaps = sorted(w.coverage_gaps())
    nodes = []
    for nid in m.nodes:
        x, y = m.pos(nid)
        nodes.append({"id": nid, "x": x, "y": y, "queue": len(w.queue_at(nid)),
                      "source": nid == m.source, "sink": nid == m.sink})
    edges = [{"a": a, "b": b, "ax": m.pos(a)[0], "ay": m.pos(a)[1],
              "bx": m.pos(b)[0], "by": m.pos(b)[1]} for a, b in m.edges()]
    packets = []
    for p in w.packets:
        x, y = _packet_xy(p, m)
        packets.append({"x": x, "y": y, "kind": p.kind, "color": list(KINDS[p.kind]["color"])})
    turrets = [{"x": t.x, "y": t.y, "id": t.id, "node": t.node,
                "accepts": sorted(t.accepts()),
                "colors": [list(KINDS[k]["color"]) for k in sorted(t.accepts())]}
               for t in w.turrets]
    stats = {k: {"in": s.spawned, "ok": s.handled, "leak": s.leaked, "now": s.inflight,
                 "color": list(KINDS[k]["color"]), "gap": k in gaps}
             for k, s in w.stats.items() if s.spawned}
    upcoming = [{"kind": k, "n": n, "color": list(KINDS[k]["color"])}
                for k, n in w.upcoming_kinds().items()]
    return {
        "map": m.name, "wave": w.level, "difficulty": w.difficulty,
        "health": round(w.health, 1), "max_health": START_HEALTH,
        "leaks": w.leaks, "max_leaks": MAX_LEAK, "credits": w.bank.balance,
        "coverage_gaps": gaps, "over": w.over, "won": w.won, "paused": w.paused,
        "started": w.started, "upcoming": upcoming,
        "nodes": nodes, "edges": edges, "packets": packets,
        "turrets": turrets, "stats": stats,
    }


def snapshot_json() -> str:
    return json.dumps(snapshot())
