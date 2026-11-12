"""Coaching — turn the live game state into actionable, teachable advice.

Chokepoint is a training app, so it shouldn't just show metrics; it should tell
you *what to fix and why*. ``coaching(world)`` reads the world and returns a
prioritized list of Hints — coverage gaps first (with the exact gun/module that
would fix them), then bottlenecks, latency, routing, and finally an all-clear.

Each Hint explains itself: ``why`` is the cause in plain words (with the
pipeline idea behind it), ``fix`` is the action to take, and — when the fix can
be written in Python — ``code`` is a short snippet to paste inside the loadout.py
function named by ``code_in`` (``build_loadout``, ``build_parsers``, ...).

Pure (no pygame); render shows the top hint live and the full list in the
metrics dashboard.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .arsenal import GUN_LIBRARY, MODULE_LIBRARY, make_gun
from .simulation import QUEUE_CAP, START_HEALTH


@dataclass
class Hint:
    """One piece of coaching. ``text`` is the symptom; ``why``/``fix``/``concept``
    turn it into a lesson — what's happening, why it matters, what to do, and the
    pipeline idea behind it. ``code``/``code_in`` show the fix as Python."""

    text: str
    level: str          # "danger" | "warn" | "tip" | "ok"
    why: str = ""       # the cause, and the pipeline idea behind it
    fix: str = ""       # the concrete action to take
    concept: str = ""   # short concept label, e.g. "consumer coverage"
    # A snippet that applies the fix, and the loadout.py function it goes inside
    # ("build_loadout", "build_parsers", "build_gates" or "build_limiters"). Each
    # snippet appends to a list named after what that function returns (turrets,
    # parsers, gates, limiters). Both are "" when the fix isn't code.
    code: str = ""
    code_in: str = ""


def _gun_accepting(kind: str, unlocked: set[str]) -> str | None:
    """An unlocked gun that accepts ``kind`` (the fix to suggest), or None."""
    for name in GUN_LIBRARY:
        if name in unlocked and kind in make_gun(name).accepts:
            return name
    return None


def _module_accepting(kind: str, unlocked: set[str]) -> str | None:
    for name, mod in MODULE_LIBRARY.items():
        if name in unlocked and kind in mod.add_accepts:
            return name
    return None


def _first_gun(unlocked: set[str]) -> str:
    """Any unlocked gun to bolt a module onto (GUN_LIBRARY order)."""
    return next((name for name in GUN_LIBRARY if name in unlocked), "sieve")


def _node_xy(w: object, nid: str) -> tuple[int, int]:
    """A node's position, rounded so the snippet reads cleanly."""
    node = w.map.nodes[nid]                          # type: ignore[attr-defined]
    return round(node.x), round(node.y)


def _relief(w: object, nid: str, unlocked: set[str]) -> tuple[str, str]:
    """(code, code_in) that adds capacity at a backed-up node.

    Prefer a second consumer for the kind piling up most there (scale out the
    consumers). If no unlocked gun takes it (e.g. undecoded raw alerts), fall
    back to a quelimiter on the node to absorb the burst.
    """
    x, y = _node_xy(w, nid)
    # Counter tallies items; most_common(1) is [(the_top_item, its_count)]
    queued = Counter(p.kind for p in w.queue_at(nid))  # type: ignore[attr-defined]
    if queued:
        kind = queued.most_common(1)[0][0]
        gun = _gun_accepting(kind, unlocked)
        if gun is not None:
            return (f"# a second '{kind}' consumer on node {nid}\n"
                    f'turrets.append(Turret({x}, {y}, gun=make_gun("{gun}")))',
                    "build_loadout")
    return (f"# buffer the burst at node {nid}, release it at a steady rate\n"
            f"limiters.append(Limiter({x}, {y}))", "build_limiters")


def coaching(world: object) -> list[Hint]:
    """Prioritized advice for the current state — the in-game coach."""
    w = world  # typed loosely to avoid importing World (no cycle); read attributes
    out: list[Hint] = []
    unlocked = w.unlocked()                          # type: ignore[attr-defined]

    # 1. coverage gaps — the most common failure, and the most fixable
    for kind in sorted(w.coverage_gaps()):           # type: ignore[attr-defined]
        gun = _gun_accepting(kind, unlocked)
        mod = _module_accepting(kind, unlocked)
        code, code_in = "", ""
        if gun is not None:
            fix = f"Place a {gun} — its gun accepts {kind}."
            level = "danger"
            code = (f"# a consumer for '{kind}' (move x, y onto its lane)\n"
                    f'turrets.append(Turret(*slots[0], gun=make_gun("{gun}")))')
            code_in = "build_loadout"
        elif mod is not None:
            fix = f"Attach the '{mod}' module to a gun so it accepts {kind}."
            level = "danger"
            code = (f"# '{mod}' widens the gun's accepts set to include '{kind}'\n"
                    f'gun = make_gun("{_first_gun(unlocked)}")\n'
                    f'gun.attach(MODULE_LIBRARY["{mod}"])\n'
                    f"turrets.append(Turret(*slots[0], gun=gun))")
            code_in = "build_loadout"
        else:
            fix = "Clear waves to unlock a tool that accepts it."
            level = "warn"
        out.append(Hint(
            f"'{kind}' is leaking — no turret accepts it.", level,
            why=f"Nothing in your build accepts '{kind}', so it's an unhandled event "
                "type — a coverage gap. Those alerts flow untouched to the exit "
                "and count as leaks.",
            fix=fix, concept="consumer coverage", code=code, code_in=code_in))

    # 2. parse gaps — raw alerts with no parser to decode them (ingest difficulty)
    parse_gaps = w.parse_gaps() if hasattr(w, "parse_gaps") else set()
    for payload in sorted(parse_gaps):
        out.append(Hint(
            f"raw '{payload}' alerts can't be decoded — no parser handles them.", "danger",
            why="Raw alerts are unparsed, like log lines before a decoder runs: no "
                "turret accepts 'raw', so one can't be consumed until a parser turns "
                "it into its real kind.",
            fix=f"Place a parser that handles '{payload}' (build_parsers in loadout.py).",
            concept="parse coverage",
            code=(f"# decode raw '{payload}' alerts near the source\n"
                  f'parsers.append(Parser(*slots[0], handles={{"{payload}"}}))'),
            code_in="build_parsers"))

    # 3. bottleneck — a node backing up (covered, but under-provisioned)
    worst, depth = "", 0
    for nid in w.map.nodes:                          # type: ignore[attr-defined]
        d = len(w.queue_at(nid))                     # type: ignore[attr-defined]
        if d > depth:
            worst, depth = nid, d
    if depth > QUEUE_CAP - 2:
        code, code_in = _relief(w, worst, unlocked)
        out.append(Hint(
            f"Node {worst} is backing up ({depth} queued).", "warn",
            why="Alerts arrive here faster than the turrets here can process them, "
                "so the queue grows — per-type backpressure. It's covered, but "
                "under-provisioned, and a full queue overflows.",
            fix="Add throughput (another accepting turret or an 'amp' module), a "
                "quelimiter (B) to smooth a burst, or a parallel branch (T) with a "
                "backup turret for overload to spill into.",
            concept="backpressure / scaling consumers", code=code, code_in=code_in))

    # 4. latency — health bleeding from aged queues
    if w.health < START_HEALTH * 0.85:               # type: ignore[attr-defined]
        code, code_in = _relief(w, worst, unlocked) if depth else ("", "")
        out.append(Hint(
            "Health is dropping — queued alerts are aging out.", "warn",
            why="Every second an alert waits in a queue is dwell time. Past the grace "
                "period it bleeds health — the latency budget (your SLA) — even if "
                "nothing leaks.",
            fix="Relieve the busiest node: more or faster consumers, a limiter, or a "
                "spill branch.",
            concept="latency / dwell", code=code, code_in=code_in))

    # 5. routing — a fork with no gate wastes the branches
    forks = w.map.branching_nodes()                  # type: ignore[attr-defined]
    if forks and not w.gates:                        # type: ignore[attr-defined]
        x, y = _node_xy(w, forks[0])
        out.append(Hint(
            "This map forks but has no gate.", "tip",
            why="Without routing, every kind takes the default branch, so the other "
                "lanes sit idle. A gate is typed routing: it pre-filters by kind so "
                "each consumer only sees traffic it handles.",
            fix="Place a gate (G) at the fork to route each kind down a lane that "
                "handles it.",
            concept="typed routing",
            code=(f"# a gate on fork {forks[0]}; it routes each kind toward a\n"
                  f"# branch whose turrets accept it\n"
                  f"gates.append(Gate({x}, {y}))"),
            code_in="build_gates"))

    if not out:
        out.append(Hint(
            "Coverage looks solid — hold the line and watch for new kinds.", "ok",
            why="Every kind seen so far has a consumer, no node is backing up, and "
                "no alert is dwelling long enough to cost health.",
            fix="Prep for the next wave (check the preview) and keep credits for gaps.",
            concept="steady state"))
    return out[:5]
