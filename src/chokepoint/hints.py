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
    text: str
    level: str  # "danger" | "warn" | "tip" | "ok"


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
            out.append(Hint(f"'{kind}' is leaking — nothing accepts it. Place a {gun} "
                             f"(it accepts {kind}).", "danger"))
        elif mod is not None:
            out.append(Hint(f"'{kind}' is leaking — attach the '{mod}' module to a gun "
                             f"so it accepts {kind}.", "danger"))
        else:
            out.append(Hint(f"'{kind}' is leaking and no tool for it is unlocked yet — "
                             f"clear waves to unlock one.", "warn"))

    # 2. bottleneck — a node backing up (covered, but under-provisioned)
    worst, depth = "", 0
    for nid in w.map.nodes:                          # type: ignore[attr-defined]
        d = len(w.queue_at(nid))                     # type: ignore[attr-defined]
        if d > depth:
            worst, depth = nid, d
    if depth > QUEUE_CAP - 2:
        extra = ("" if w.limiter_at(worst)           # type: ignore[attr-defined]
                 else " — or add a quelimiter (B) upstream to smooth the burst")
        out.append(Hint(f"Node {worst} is backing up ({depth} queued): add throughput "
                        f"(another accepting turret, or an 'amp'/'dedup' module){extra}.", "warn"))

    # 3. latency — health bleeding from aged queues
    if w.health < START_HEALTH * 0.85:               # type: ignore[attr-defined]
        out.append(Hint("Health is dropping: queued alerts are aging out (latency). "
                        "Relieve the busiest node.", "warn"))

    # 4. routing — a fork with no gate wastes the branches
    if w.map.branching_nodes() and not w.gates:      # type: ignore[attr-defined]
        out.append(Hint("This map forks. Place a gate (G) at the fork so each kind flows "
                        "down a lane that can handle it.", "tip"))

    if not out:
        out.append(Hint("Coverage looks solid — hold the line and watch for new kinds.", "ok"))
    return out[:5]
