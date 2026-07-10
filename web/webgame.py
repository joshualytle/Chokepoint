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

import copy
import json
import traceback

from chokepoint.arsenal import MODULE_LIBRARY, Module, Turret, make_gun
from chokepoint.editor import ArsenalEditor
from chokepoint.gates import DEFAULT_GATE_COST, Gate
from chokepoint.glossary import GLOSSARY, HUD_HELP
from chokepoint.hints import coaching
from chokepoint.lessons import Lessons
from chokepoint.limiter import DEFAULT_LIMITER_COST, Limiter
from chokepoint.maps import MAP_LIST, MAPS
from chokepoint.metrics import summarize_failure
from chokepoint.packets import DIFFICULTY_LIST, KINDS
from chokepoint.parsers import Parser
from chokepoint.safety import SafetyError, safe_exec
from chokepoint.simulation import DWELL_GRACE, MAX_LEAK, QUEUE_CAP, START_HEALTH, World
from chokepoint.tutorial import Step, Tutorial

# the game objects a loadout may use, injected so no imports are even required
_LOADOUT_API = {
    "Turret": Turret, "make_gun": make_gun, "Module": Module,
    "MODULE_LIBRARY": MODULE_LIBRARY, "Parser": Parser, "Gate": Gate, "Limiter": Limiter,
}

_world: World | None = None
_editor: ArsenalEditor | None = None
_selected_module: str | None = None    # module chosen to equip on the next turret tapped


def new_game(map_name: str = "trunk", difficulty: str = "easy") -> str:
    global _world, _editor, _selected_module
    if map_name not in MAPS:
        map_name = MAP_LIST[0]
    _world = World(MAPS[map_name].copy(), difficulty=difficulty)
    _world.paused = True                 # start on the wave preview; UI presses Start
    _editor = ArsenalEditor(_world.unlocked(), bank=_world.bank)
    _selected_module = None
    _undo.clear()
    if difficulty == "ingest":
        _tutorial.signal("ingest")       # the ingest walkthrough waits for this switch
    return json.dumps({"ok": True, "maps": MAP_LIST, "difficulties": DIFFICULTY_LIST})


def _sync() -> None:
    """Push the editor's placements to the world and re-derive gate routing."""
    assert _world is not None and _editor is not None
    _world.set_turrets(_editor.to_turrets())
    _world.set_gates(_editor.to_gates())
    _world.set_limiters(_editor.to_limiters())
    _world.autoroute()


# ---- undo: snapshot the mutable build state before each edit ----
_undo: list[dict] = []
_UNDO_CAP = 60


def _state_snapshot() -> dict:
    # deep copies so undo also reverts in-place edits (e.g. a module attached to a gun)
    assert _world is not None and _editor is not None
    return {"turrets": copy.deepcopy(_editor.turrets), "gates": copy.deepcopy(_editor.gates),
            "limiters": copy.deepcopy(_editor.limiters), "parsers": copy.deepcopy(_world.parsers),
            "map": _world.map.copy(), "balance": _world.bank.balance}


def _record(pre: dict) -> None:
    _undo.append(pre)
    if len(_undo) > _UNDO_CAP:
        del _undo[0]


def _restore(snap: dict) -> None:
    assert _world is not None and _editor is not None
    _editor.turrets = list(snap["turrets"])
    _editor.gates = list(snap["gates"])
    _editor.limiters = list(snap["limiters"])
    _world.map = snap["map"].copy()
    _world.bank.balance = snap["balance"]
    _world.set_parsers(list(snap["parsers"]))
    _rebind_after_topology()


def undo() -> str:
    if not _undo:
        return json.dumps({"ok": False})
    _restore(_undo.pop())
    return json.dumps({"ok": True, "depth": len(_undo)})


def load_loadout(src: str) -> str:
    """Exec the player's build_loadout (sandboxed) and deploy what it returns."""
    global _editor
    assert _world is not None
    pre = _state_snapshot()
    try:
        ns = safe_exec(src, _LOADOUT_API)   # sandboxed: no arbitrary imports / escapes
        if "build_loadout" not in ns:
            raise ValueError("define build_loadout(unlocked, slots)")
        turrets = ns["build_loadout"](_world.unlocked(), _world.map.slots)
    except SafetyError as err:
        # a syntax error inside the sandbox check carries the offending line
        line = getattr(err.__cause__, "lineno", None)
        return json.dumps({"ok": False, "error": f"blocked: {err}", "line": line})
    except Exception as err:  # report author errors to the editor, never crash
        line = None
        for fr in traceback.extract_tb(err.__traceback__):
            if fr.filename == "<loadout>":
                line = fr.lineno          # deepest frame in the player's code
        return json.dumps({"ok": False, "error": f"{type(err).__name__}: {err}", "line": line})
    _editor = ArsenalEditor(_world.unlocked(), bank=_world.bank)
    dropped = _editor.seed_purchase(turrets)
    # optional device builders (gates / limiters / parsers), like the desktop loadout
    unlocked, slots = _world.unlocked(), _world.map.slots
    build_gates = ns.get("build_gates")
    if callable(build_gates):
        _editor.seed_purchase_gates(build_gates(unlocked, slots))
    build_limiters = ns.get("build_limiters")
    if callable(build_limiters):
        _editor.seed_purchase_limiters(build_limiters(unlocked, slots))
    parsers = []
    build_parsers = ns.get("build_parsers")
    if callable(build_parsers):
        for ps in build_parsers(unlocked, slots):
            if _world.bank.spend(ps.cost):
                parsers.append(ps)
    _world.set_parsers(parsers)
    _record(pre)
    _sync()
    _tutorial.signal("run")
    return json.dumps({"ok": True, "turrets": len(turrets) - len(dropped),
                       "dropped": len(dropped)})


# ---- interactive placement (reuses the pure ArsenalEditor state machine) ----
def palette_json() -> str:
    assert _world is not None and _editor is not None
    _editor.set_unlocked(_world.unlocked())
    guns = []
    for name in _editor.available_guns():
        g = make_gun(name)
        guns.append({"name": name, "cost": g.cost, "accepts": sorted(g.accepts),
                     "colors": [list(KINDS[k]["color"]) for k in sorted(g.accepts)],
                     "afford": _world.bank.can_afford(g.cost),
                     "selected": name == _editor.selected_gun})
    devices = [
        {"kind": "gate", "cost": DEFAULT_GATE_COST, "desc": "routes kinds at a fork",
         "afford": _world.bank.can_afford(DEFAULT_GATE_COST), "selected": _editor.placing_gate},
        {"kind": "limiter", "cost": DEFAULT_LIMITER_COST, "desc": "buffers + smooths a burst",
         "afford": _world.bank.can_afford(DEFAULT_LIMITER_COST),
         "selected": _editor.placing_limiter},
    ]
    modules = []
    for name in _editor.available_modules():
        mod = MODULE_LIBRARY[name]
        modules.append({"name": name, "cost": mod.cost, "desc": mod.desc,
                        "adds": [list(KINDS[k]["color"]) + [k] for k in sorted(mod.add_accepts)],
                        "afford": _world.bank.can_afford(mod.cost),
                        "selected": name == _selected_module})
    return json.dumps({"guns": guns, "devices": devices, "modules": modules})


def select_gun(name: str) -> str:
    global _selected_module
    assert _editor is not None
    _selected_module = None
    if name == _editor.selected_gun:      # tapping the selected gun again deselects it
        _editor.selected_gun = None
    else:
        _editor.select_gun(name)          # (also clears device-placement modes)
    return json.dumps({"selected": _editor.selected_gun})


def select_device(kind: str) -> str:
    """Choose gate/limiter placement mode (tap again to leave it)."""
    global _selected_module
    assert _editor is not None
    _selected_module = None
    if kind == "gate":
        _editor.placing_gate = not _editor.placing_gate
        _editor.placing_limiter = False
    elif kind == "limiter":
        _editor.placing_limiter = not _editor.placing_limiter
        _editor.placing_gate = False
    if _editor.placing_gate or _editor.placing_limiter:
        _editor.selected_gun = None       # devices and guns are mutually exclusive
    return json.dumps({"gate": _editor.placing_gate, "limiter": _editor.placing_limiter})


def select_module(name: str) -> str:
    """Choose a module to attach to the next turret tapped (tap again to clear)."""
    global _selected_module
    assert _editor is not None
    _selected_module = None if name == _selected_module else name
    if _selected_module is not None:
        _editor.selected_gun = None
        _editor.placing_gate = _editor.placing_limiter = False
    return json.dumps({"selected": _selected_module})


def place_at(x: float, y: float) -> str:
    assert _editor is not None and _world is not None
    bank = _world.bank
    pre = _state_snapshot()
    if _selected_module is not None:      # equip the selected module onto a turret
        ok = _editor.equip_at(x, y, _selected_module)
        if ok:
            _record(pre)
            _tutorial.signal("module")
        _sync()
        why = "" if ok else "tap a turret (can't afford, or it has that module)"
        return json.dumps({"ok": ok, "reason": why})
    if _editor.placing_gate:
        if not _world.map.branching_nodes():
            return json.dumps({"ok": False,
                               "reason": "no fork here — build a branch first (Build mode)"})
        if not bank.can_afford(DEFAULT_GATE_COST):
            return json.dumps({"ok": False, "reason": f"need {DEFAULT_GATE_COST}cr for a gate"})
        g = _editor.place_gate(x, y)
        if g is not None:
            _record(pre)
            _tutorial.signal("gate")
        _sync()
        return json.dumps({"ok": g is not None, "reason": "" if g else "place it near a fork"})
    if _editor.placing_limiter:
        if not bank.can_afford(DEFAULT_LIMITER_COST):
            return json.dumps({"ok": False,
                               "reason": f"need {DEFAULT_LIMITER_COST}cr for a limiter"})
        lm = _editor.place_limiter(x, y)
        if lm is not None:
            _record(pre)
            _tutorial.signal("limiter")
        _sync()
        return json.dumps({"ok": lm is not None, "reason": "" if lm else "click a node"})
    if _editor.selected_gun is None:
        return json.dumps({"ok": False, "reason": "pick a gun or device in the palette first"})
    gun = make_gun(_editor.selected_gun)
    if not bank.can_afford(gun.cost):
        return json.dumps({"ok": False,
                           "reason": f"need {gun.cost}cr for {gun.name} (you have {bank.balance})"})
    turret = _editor.place(x, y)
    if turret is not None:
        turret.x, turret.y = _snap_to_node(x, y)   # sit on its node so it's clearly linked
        _record(pre)
        _tutorial.signal("place")
    _sync()
    return json.dumps({"ok": turret is not None,
                       "reason": "" if turret else "click near the line"})


def _snap_to_node(x: float, y: float) -> tuple[float, float]:
    """Snap a turret to just below its nearest node, so it visibly links to the path."""
    assert _world is not None
    nid = _world.map.nearest_node(x, y)
    nx, ny = _world.map.pos(nid)
    return nx, ny + 24


def move_at(fx: float, fy: float, tx: float, ty: float) -> str:
    """Drag a placed turret / gate / limiter from (fx,fy) to (tx,ty)."""
    assert _editor is not None
    pre = _state_snapshot()
    t = _editor.turret_at(fx, fy)
    if t is not None:
        t.x, t.y = _snap_to_node(tx, ty)
    else:
        g = _editor.gate_at(fx, fy)
        lm = None if g is not None else _editor.limiter_at(fx, fy)
        if g is not None:
            g.x, g.y = tx, ty
        elif lm is not None:
            lm.x, lm.y = tx, ty
        else:
            return json.dumps({"ok": False})
    _record(pre)
    _sync()
    return json.dumps({"ok": True})


def remove_at(x: float, y: float) -> str:
    assert _editor is not None
    pre = _state_snapshot()
    ok = _editor.remove_at(x, y) or _editor.remove_gate_at(x, y) or _editor.remove_limiter_at(x, y)
    if ok:
        _record(pre)
    _sync()
    return json.dumps({"ok": ok})


# ---- build mode: edit the topology (add/remove nodes and edges) ----
def _rebind_after_topology() -> None:
    """Drop only packets stranded by a removed node, then re-snap all devices."""
    assert _world is not None
    valid = _world.map.nodes
    _world.packets = [p for p in _world.packets
                      if p.at in valid and (p.moving_to is None or p.moving_to in valid)]
    _sync()


def node_at(x: float, y: float, tol: float = 18.0) -> str:
    assert _world is not None
    m = _world.map
    if not m.nodes:
        return ""
    nid = m.nearest_node(x, y)
    nx, ny = m.pos(nid)
    return nid if (nx - x) ** 2 + (ny - y) ** 2 <= tol * tol else ""


def edge_at(x: float, y: float, tol: float = 9.0) -> str:
    assert _world is not None
    m = _world.map
    best, best_d = "", tol
    for a, b in m.edges():
        ax, ay = m.pos(a)
        bx, by = m.pos(b)
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg))
        d = ((x - (ax + t * dx)) ** 2 + (y - (ay + t * dy)) ** 2) ** 0.5
        if d < best_d:
            best_d, best = d, f"{a},{b}"
    return best


def add_node(x: float, y: float) -> str:
    assert _world is not None
    _record(_state_snapshot())
    _world.map.add_node(x, y)
    _rebind_after_topology()
    _tutorial.signal("node")
    return json.dumps({"ok": True})


def add_edge(a: str, b: str) -> str:
    assert _world is not None
    pre = _state_snapshot()
    ok = _world.map.add_edge(a, b)
    if ok:
        _record(pre)
        _tutorial.signal("edge")
    _rebind_after_topology()
    return json.dumps({"ok": ok})


def remove_node(nid: str) -> str:
    assert _world is not None
    pre = _state_snapshot()
    ok = _world.map.remove_node(nid)
    if ok:
        _record(pre)
    _rebind_after_topology()
    return json.dumps({"ok": ok})


def remove_edge(a: str, b: str) -> str:
    assert _world is not None
    pre = _state_snapshot()
    ok = _world.map.remove_edge(a, b)
    if ok:
        _record(pre)
    _rebind_after_topology()
    return json.dumps({"ok": ok})


def set_paused(flag: bool) -> None:
    if _world is not None:
        _world.paused = bool(flag)


def begin() -> None:
    if _world is not None:
        _world.paused = False
        _tutorial.signal("start")


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
        q = w.queue_at(nid)
        served: set[str] = set()
        for t in w.turrets:
            if t.node == nid:
                served |= t.accepts()
        lim = w.limiter_at(nid)
        nodes.append({"id": nid, "x": x, "y": y, "queue": len(q),
                      "cap": lim.buffer_cap if lim is not None else QUEUE_CAP,
                      "served": sorted(served),
                      "oldest": round(max((p.wait for p in q), default=0.0), 1),
                      "grace": DWELL_GRACE,
                      "source": nid == m.source, "sink": nid == m.sink})
    edges = [{"a": a, "b": b, "ax": m.pos(a)[0], "ay": m.pos(a)[1],
              "bx": m.pos(b)[0], "by": m.pos(b)[1]} for a, b in m.edges()]
    packets = []
    for p in w.packets:
        x, y = _packet_xy(p, m)
        packets.append({"x": x, "y": y, "kind": p.kind, "color": list(KINDS[p.kind]["color"])})
    turrets = [{"x": t.x, "y": t.y, "id": t.id, "node": t.node,
                "gun": t.gun.name, "desc": t.gun.desc, "dps": round(t.dps(), 1),
                "accepts": sorted(t.accepts()),
                "modules": [m.name for m in t.gun.modules],
                "colors": [list(KINDS[k]["color"]) for k in sorted(t.accepts())]}
               for t in w.turrets]
    gates = [{"id": g.id, "x": m.pos(g.node)[0], "y": m.pos(g.node)[1], "node": g.node,
              "branches": [{"to": b, "kinds": sorted(k for k, i in g.routes.items() if i == bi)}
                           for bi, b in enumerate(m.branches(g.node))]}
             for g in w.gates if g.node in m.nodes]
    limiters = [{"id": lm.id, "x": m.pos(lm.node)[0], "y": m.pos(lm.node)[1], "node": lm.node,
                 "rate": lm.release_rate, "cap": lm.buffer_cap,
                 "buffered": sum(1 for p in w.queue_at(lm.node) if not w.serves(lm.node, p.kind))}
                for lm in w.limiters if lm.node in m.nodes]
    parsers = [{"id": ps.id, "x": m.pos(ps.node)[0], "y": m.pos(ps.node)[1], "node": ps.node,
                "handles": sorted(ps.handles),
                "colors": [list(KINDS[k]["color"]) for k in sorted(ps.handles)]}
               for ps in w.parsers if ps.node in m.nodes]
    debrief = None
    if w.over and not w.won:
        d = summarize_failure(w)
        debrief = {"cause": d.cause, "lines": list(d.lines)}
    stats = {k: {"in": s.spawned, "ok": s.handled, "leak": s.leaked, "now": s.inflight,
                 "color": list(KINDS[k]["color"]), "gap": k in gaps}
             for k, s in w.stats.items() if s.spawned}
    upcoming = [{"kind": k, "n": n, "color": list(KINDS[k]["color"])}
                for k, n in w.upcoming_kinds().items()]
    coach = [{"text": h.text, "level": h.level, "why": h.why, "fix": h.fix,
              "concept": h.concept} for h in coaching(w)[:4]]
    return {
        "map": m.name, "wave": w.level, "difficulty": w.difficulty,
        "health": round(w.health, 1), "max_health": START_HEALTH,
        "leaks": w.leaks, "max_leaks": MAX_LEAK, "credits": w.bank.balance,
        "coverage_gaps": gaps, "over": w.over, "won": w.won, "paused": w.paused,
        "started": w.started, "upcoming": upcoming, "coach": coach, "debrief": debrief,
        "unlocked": sorted(w.unlocked()), "can_undo": len(_undo) > 0,
        "nodes": nodes, "edges": edges, "packets": packets,
        "turrets": turrets, "gates": gates, "limiters": limiters, "parsers": parsers,
        "stats": stats,
    }


def snapshot_json() -> str:
    return json.dumps(snapshot())


# ---- glossary / contextual help (pure data from the core) ----
def help_json() -> str:
    return json.dumps({"glossary": [list(g) for g in GLOSSARY], "hud": HUD_HELP})


# ---- metrics dashboard (the pure Telemetry backend) ----
def metrics_json() -> str:
    assert _world is not None
    tel = _world.telemetry
    kinds = {}
    for k, v in tel.kind_summary().items():
        lat = tel.latency.get(k)
        kinds[k] = {"in": v.spawned, "ok": v.handled, "leak": v.leaked, "peak": v.peak_inflight,
                    "p50": round(lat.percentile(50), 1) if lat else 0.0,
                    "p95": round(lat.percentile(95), 1) if lat else 0.0,
                    "color": list(KINDS[k]["color"])}
    nodes = {n: {"peak": v.peak_queue, "drops": v.overflow_drops, "load": round(v.load_fraction, 2)}
             for n, v in tel.node_summary().items()}
    trend = [{"t": p.t, "health": round(p.health, 1)} for p in tel.trend]
    eff = tel.efficiency(_world)
    return json.dumps({"kinds": kinds, "nodes": nodes, "trend": trend,
                       "cost_per_handled": round(eff["cost_per_handled"], 1),
                       "deployed_cost": eff["deployed_cost"], "handled": eff["handled"],
                       "max_health": START_HEALTH})


# ---- guided tutorial (reuses the pure Tutorial class, web-tailored steps) ----
_WEB_TUTORIAL = [
    Step("Welcome to Chokepoint", [
        "Security alerts flood in from the left and flow to the exit on the right.",
        "Handle each before it exits — or it LEAKS. Too many leaks ends the run."]),
    Step("Alerts have types", [
        "Every alert has a TYPE (its color). Turrets are workers that each handle",
        "certain types. Your job is COVERAGE — a worker for every type that shows up."]),
    Step("Place a worker", [
        "Under the board, click a GUN in the palette, then click a node on the line",
        "to place it. Right-click a turret to remove it."], event="place"),
    Step("Read the dashboard", [
        "The dashboard lists each type:  in / ok / leak / now",
        "(arrived / handled / leaked / in the queue now). A ! marks an uncovered type.",
        "(On a phone the panels are below the board — scroll down.)"]),
    Step("Or build it in code", [
        "Scroll to the code panel (right on desktop, below the board on mobile),",
        "edit build_loadout, and press Run (or Ctrl+Enter). Code and clicks share",
        "one budget — write Python or point-and-click, your choice."], event="run"),
    Step("Send the wave", [
        "Press ▶ Start (top-left). Watch the board; the COACH names what to fix next."],
        event="start"),
    Step("You're ready", [
        "Use 🔧 Build to branch the topology — overload spills to a parallel worker.",
        "Hover any stat for help, or open ❔ Help for the glossary. Good luck!"],
        button="Start"),
]
# ---- walkthrough library: themed, action-gated guides beyond the onboarding ----
_WT_OVERFLOW = [
    Step("Why nodes choke", [
        "A turret drains its queue at a fixed rate. When inflow beats that rate the",
        "queue grows, ages, and bleeds health — that's backpressure."]),
    Step("Add a node off the line", [
        "Press 🔧 Build, then click empty space below the trunk to add a new node."],
        event="node"),
    Step("Branch into it", [
        "Still in Build: click a busy trunk node, then your new node, to draw an edge."],
        event="edge"),
    Step("Rejoin the line", [
        "Now click your new node, then a LATER trunk node, so traffic can flow onward."],
        event="edge"),
    Step("Add a backup worker", [
        "Leave Build mode (🔧 again). Place a turret on the branch node — one that",
        "accepts the same kind as the overloaded worker."], event="place"),
    Step("Spill in action", [
        "When the primary saturates, excess alerts now SPILL down your branch to the",
        "backup automatically — the 'else' path for a full worker. Start a wave and watch."],
        button="Done"),
]
_WT_ROUTING = [
    Step("Forks need routers", [
        "At a fork, traffic takes the default branch unless a GATE routes it. A gate",
        "sends each kind down the branch whose workers can handle it."]),
    Step("Make a fork", [
        "Press 🔧 Build and branch the line: add a node, edge in, edge back out.",
        "(Any new edge completes this step if you already have a fork.)"], event="edge"),
    Step("Place a gate", [
        "Leave Build mode. Under FLOW DEVICES tap gate, then tap near the fork."],
        event="gate"),
    Step("Read the routes", [
        "Hover the gold diamond: each branch lists the kinds routed down it. Routing",
        "is derived from your turrets — it re-derives whenever your build changes."],
        button="Done"),
]
_WT_INGEST = [
    Step("Raw alerts", [
        "Real pipelines receive RAW logs that must be parsed before anything can",
        "consume them. The 'ingest' difficulty simulates exactly that."]),
    Step("Switch to ingest", [
        "Set difficulty to 'ingest' in the top controls (the run resets)."],
        event="ingest"),
    Step("Write a parser", [
        "In the code editor add:",
        "def build_parsers(unlocked, slots):",
        "    return [Parser(*slots[0], handles={'auth', 'ids'})]",
        "then press ▶ Run."], event="run"),
    Step("Watch it decode", [
        "Start the wave. Grey raw alerts hit the parser hexagon and turn into their",
        "real kind, which your turrets can then handle. Payloads no parser handles",
        "stay raw and leak — parse-coverage matters like consumer-coverage."],
        button="Done"),
]
_WT_UPGRADES = [
    Step("Modules upgrade guns", [
        "Fire rate is static — you scale with MODULES: extra damage, or extra kinds",
        "via adapter_* modules. They unlock as waves clear."]),
    Step("Place a turret", ["Place any turret (if your board is empty)."], event="place"),
    Step("Equip a module", [
        "Under MODULES tap one (an adapter changes coverage), then tap your turret.",
        "(Modules appear once unlocked — clear wave 1+, or a lesson's sandbox.)"],
        event="module"),
    Step("Synergies", [
        "Some gun pairs boost each other — hover a turret to see its throughput.",
        "Try sieve + auditor for 'Correlation' (+25% to both)."], button="Done"),
]

WALKTHROUGHS: dict[str, dict] = {
    "basics": {"title": "The basics", "steps": _WEB_TUTORIAL,
               "desc": "Alerts, coverage, and your first worker."},
    "overflow": {"title": "Overload & spill", "steps": _WT_OVERFLOW,
                 "desc": "Build a parallel branch so a full worker sheds load."},
    "routing": {"title": "Gates & routing", "steps": _WT_ROUTING,
                "desc": "Split traffic by type at a fork."},
    "ingest": {"title": "Parsers & raw alerts", "steps": _WT_INGEST,
               "desc": "Decode raw logs in code before anything can consume them."},
    "upgrades": {"title": "Modules & synergies", "steps": _WT_UPGRADES,
                 "desc": "Scale a worker's damage or coverage; pair guns for bonuses."},
}

_tutorial = Tutorial(_WEB_TUTORIAL)
_tut_name = "The basics"


def walkthroughs_json() -> str:
    return json.dumps([{"id": wid, "title": w["title"], "desc": w["desc"],
                        "n": len(w["steps"]),
                        "active": _tutorial.active and _tut_name == w["title"]}
                       for wid, w in WALKTHROUGHS.items()])


def start_walkthrough(wid: str) -> str:
    global _tutorial, _tut_name
    w = WALKTHROUGHS.get(wid)
    if w is None:
        return json.dumps({"ok": False})
    _tutorial = Tutorial(list(w["steps"]))
    _tut_name = w["title"]
    return json.dumps({"ok": True})


def _tut_state() -> dict:
    st = _tutorial.step
    if not _tutorial.active or st is None:
        return {"active": False}
    return {"active": True, "i": _tutorial.i, "n": len(_tutorial.script), "name": _tut_name,
            "title": st.title, "body": st.body, "manual": st.is_manual, "button": st.button}


def tutorial_state() -> str:
    return json.dumps(_tut_state())


def tutorial_next() -> str:
    _tutorial.next()
    return json.dumps(_tut_state())


def tutorial_skip() -> str:
    _tutorial.skip()
    return json.dumps({"active": False})


def tutorial_signal(event: str) -> str:
    _tutorial.signal(event)
    return json.dumps(_tut_state())


def tutorial_skip_step() -> str:
    """Force past an action step if the player is stuck (an escape hatch)."""
    _tutorial._advance()
    return json.dumps(_tut_state())


# ---- in-editor Python lessons (reuses the pure Lessons class) ----
_lessons = Lessons()


def _les_state() -> dict:
    le = _lessons.lesson
    if not _lessons.active or le is None:
        return {"active": False}
    if _world is not None:
        _lessons.check(_world, _editor)   # live-update the check against the world
    return {"active": True, "i": _lessons.i, "n": len(_lessons.script),
            "title": le.title, "teach": le.teach, "task": le.task, "concept": le.concept,
            "hands_on": le.starter is not None, "starter": le.starter or "",
            "sandbox": le.sandbox, "passed": _lessons.passed, "can_advance": _lessons.can_advance()}


def lessons_state() -> str:
    return json.dumps(_les_state())


def lessons_next() -> str:
    _lessons.next()
    return json.dumps(_les_state())


def lessons_skip() -> str:
    _lessons.skip()
    return json.dumps({"active": False})


def lessons_start() -> str:
    _lessons.start()
    return json.dumps(_les_state())


def grant_sandbox_credits() -> None:
    """Free credits so a hands-on lesson isn't gated by budget."""
    if _world is not None:
        _world.bank.balance = max(_world.bank.balance, 100000)
