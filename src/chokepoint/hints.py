"""Coaching — turn the live game state into actionable, teachable advice.

Chokepoint is a training app, so it shouldn't just show metrics; it should tell
you *what to fix and why*. ``coaching(world)`` reads the world and returns a
prioritized list of Hints — coverage gaps first (with the exact gun/module that
would fix them), then bottlenecks, latency, routing, and finally an all-clear.

Pure (no pygame); render shows the top hint live and the full list in the
metrics dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass

from .arsenal import GUN_LIBRARY, MODULE_LIBRARY, make_gun
from .simulation import QUEUE_CAP, START_HEALTH


@dataclass
class Hint:
    """One piece of coaching. ``text`` is the symptom; ``why``/``fix``/``concept``
    turn it into a lesson — what's happening, why it matters, what to do, and the
    pipeline idea behind it."""

    text: str
    level: str          # "danger" | "warn" | "tip" | "ok"
    why: str = ""       # the concept / why it matters
    fix: str = ""       # the concrete action to take
    concept: str = ""   # short concept label, e.g. "consumer coverage"


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


def coaching(world: object) -> list[Hint]:
    """Prioritized advice for the current state — the in-game coach."""
    w = world  # typed loosely to avoid importing World (no cycle); read attributes
    out: list[Hint] = []
    unlocked = w.unlocked()                          # type: ignore[attr-defined]

    # 1. coverage gaps — the most common failure, and the most fixable
    for kind in sorted(w.coverage_gaps()):           # type: ignore[attr-defined]
        gun = _gun_accepting(kind, unlocked)
        mod = _module_accepting(kind, unlocked)
        if gun is not None:
            fix = f"Place a {gun} — its gun accepts {kind}."
            level = "danger"
        elif mod is not None:
            fix = f"Attach the '{mod}' module to a gun so it accepts {kind}."
            level = "danger"
        else:
            fix = "Clear waves to unlock a tool that accepts it."
            level = "warn"
        out.append(Hint(
            f"'{kind}' is leaking — no turret accepts it.", level,
            why="Every alert type needs a consumer that accepts it. An uncovered "
                "type flows untouched to the exit and leaks.",
            fix=fix, concept="consumer coverage"))

    # 2. parse gaps — raw alerts with no parser to decode them (ingest difficulty)
    parse_gaps = w.parse_gaps() if hasattr(w, "parse_gaps") else set()
    for payload in sorted(parse_gaps):
        out.append(Hint(
            f"raw '{payload}' alerts can't be decoded — no parser handles them.", "danger",
            why="Raw alerts are unparsed; a turret can't consume one until a parser "
                "decodes it into its real kind.",
            fix=f"Place a parser that handles '{payload}' (build_parsers in loadout.py).",
            concept="parse coverage"))

    # 3. bottleneck — a node backing up (covered, but under-provisioned)
    worst, depth = "", 0
    for nid in w.map.nodes:                          # type: ignore[attr-defined]
        d = len(w.queue_at(nid))                     # type: ignore[attr-defined]
        if d > depth:
            worst, depth = nid, d
    if depth > QUEUE_CAP - 2:
        out.append(Hint(
            f"Node {worst} is backing up ({depth} queued).", "warn",
            why="The consumer here can't keep up with inflow, so the queue grows — "
                "covered, but under-provisioned.",
            fix="Add throughput (another accepting turret or an 'amp' module), a "
                "quelimiter (B) to smooth a burst, or a parallel branch (T) with a "
                "backup turret for overload to spill into.",
            concept="backpressure / scaling consumers"))

    # 4. latency — health bleeding from aged queues
    if w.health < START_HEALTH * 0.85:               # type: ignore[attr-defined]
        out.append(Hint(
            "Health is dropping — queued alerts are aging out.", "warn",
            why="Alerts that dwell past the grace period bleed your latency budget — "
                "the SLA/backpressure failure.",
            fix="Relieve the busiest node: more or faster consumers, a limiter, or a "
                "spill branch.",
            concept="latency / dwell"))

    # 5. routing — a fork with no gate wastes the branches
    if w.map.branching_nodes() and not w.gates:      # type: ignore[attr-defined]
        out.append(Hint(
            "This map forks but has no gate.", "tip",
            why="Without routing, every kind takes the default branch. A gate "
                "pre-filters by type so each consumer only sees relevant traffic.",
            fix="Place a gate (G) at the fork to route each kind down a lane that "
                "handles it.",
            concept="typed routing"))

    if not out:
        out.append(Hint(
            "Coverage looks solid — hold the line and watch for new kinds.", "ok",
            why="No uncovered types, no backed-up nodes, no latency bleed right now.",
            fix="Prep for the next wave (check the preview) and keep credits for gaps.",
            concept="steady state"))
    return out[:5]
