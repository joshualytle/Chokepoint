"""The arsenal — guns, modules, and turrets as drop-in Python objects.

Design goals from the brief:
  * Guns have a STATIC fire rate (a fixed property, never upgraded).
  * You upgrade by attaching MODULES you unlock as you reach later waves.
  * Guns and modules are drop-in: register a new one with a decorator and it
    shows up everywhere (library, tooltips, loadouts).
  * Certain guns PAIR for synergies.
  * A turret carries its own position — placement is just data on the object.

Throughput note: a turret's processing power for an accepted kind is
``fire_rate * effective_damage`` volume/second. Fire rate is fixed; modules
raise damage/range/coverage. If incoming volume for a kind exceeds the combined
throughput of the turrets that accept it, a backlog builds and packets leak —
that is per-type backpressure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
#  Modules — attachable upgrades
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Module:
    """An upgrade you bolt onto a gun. Unlocked by reaching ``unlock_wave``."""

    name: str
    desc: str
    unlock_wave: int = 0
    add_accepts: frozenset[str] = frozenset()
    range_bonus: float = 0.0
    damage_bonus: float = 0.0
    cost: int = 0             # credits to attach this module (see economy.py)


MODULE_LIBRARY: dict[str, Module] = {}


def register_module(mod: Module) -> Module:
    """Drop a module into the global library. Call at import time."""
    MODULE_LIBRARY[mod.name] = mod
    return mod


# Built-in modules. Add your own by calling register_module(Module(...)).
register_module(Module("range+", "Extends processing range by 50.",
                       unlock_wave=1, range_bonus=50, cost=40))
register_module(Module("amp", "Amplifier: +5 processing per shot.",
                       unlock_wave=2, damage_bonus=5, cost=60))
register_module(Module("adapter_dns", "Lets a gun also accept DNS alerts.",
                       unlock_wave=2, add_accepts=frozenset({"dns"}), cost=50))
register_module(Module("dedup", "Deduplicator: collapses repeats, +6 effective processing.",
                       unlock_wave=3, damage_bonus=6, cost=70))
register_module(Module("adapter_endpoint", "Lets a gun also accept endpoint detections.",
                       unlock_wave=4, add_accepts=frozenset({"endpoint"}), cost=80))


# --------------------------------------------------------------------------- #
#  Guns — static fire rate, typed acceptance
# --------------------------------------------------------------------------- #

@dataclass
class Gun:
    """A processing weapon. ``fire_rate`` is static. ``accepts`` is the set of
    packet kinds it can target. Attach modules to raise damage/range/coverage."""

    name: str
    desc: str
    fire_rate: float                       # shots/sec — STATIC, never modified
    damage: float                          # base processing per shot
    base_range: float
    accepts: frozenset[str]
    unlock_wave: int = 0
    cost: int = 0                          # credits to place this gun (see economy.py)
    modules: list[Module] = field(default_factory=list)

    def attach(self, module: Module) -> Gun:
        """Plug in a module. Returns self so you can chain in a loadout."""
        self.modules.append(module)
        return self

    def effective_accepts(self) -> frozenset[str]:
        extra: frozenset[str] = frozenset()
        for m in self.modules:
            extra |= m.add_accepts
        return self.accepts | extra

    def effective_range(self) -> float:
        return self.base_range + sum(m.range_bonus for m in self.modules)

    def effective_damage(self) -> float:
        return self.damage + sum(m.damage_bonus for m in self.modules)

    def dps(self) -> float:
        return self.fire_rate * self.effective_damage()


GUN_LIBRARY: dict[str, Callable[[], Gun]] = {}


def register_gun(name: str) -> Callable[[Callable[[], Gun]], Callable[[], Gun]]:
    """Decorator: register a factory that builds a fresh Gun. Drop-in.

        @register_gun("sieve")
        def sieve() -> Gun:
            return Gun("sieve", "...", fire_rate=3.0, damage=6, base_range=150,
                       accepts=frozenset({"auth", "dns"}))
    """
    def wrap(factory: Callable[[], Gun]) -> Callable[[], Gun]:
        GUN_LIBRARY[name] = factory
        return factory
    return wrap


@register_gun("sieve")
def sieve() -> Gun:
    return Gun("sieve", "Fast filter for auth and DNS noise.",
               fire_rate=3.0, damage=6, base_range=150,
               accepts=frozenset({"auth", "dns"}), unlock_wave=0, cost=90)


@register_gun("scatter")
def scatter() -> Gun:
    return Gun("scatter", "Broad, rapid coverage of IDS and firewall traffic.",
               fire_rate=4.0, damage=4, base_range=140,
               accepts=frozenset({"ids", "firewall"}), unlock_wave=0, cost=110)


@register_gun("auditor")
def auditor() -> Gun:
    return Gun("auditor", "Specialist for cloud audit events.",
               fire_rate=2.0, damage=9, base_range=160,
               accepts=frozenset({"cloudtrail"}), unlock_wave=3, cost=170)


@register_gun("lance")
def lance() -> Gun:
    return Gun("lance", "Heavy single-type processor for endpoint detections.",
               fire_rate=1.5, damage=18, base_range=170,
               accepts=frozenset({"endpoint"}), unlock_wave=4, cost=240)


def make_gun(name: str) -> Gun:
    """Build a fresh gun instance from the library by name."""
    if name not in GUN_LIBRARY:
        raise KeyError(f"unknown gun {name!r}; known: {sorted(GUN_LIBRARY)}")
    return GUN_LIBRARY[name]()


def gun_cost(gun: Gun) -> int:
    """Total credit cost of a gun: its base price plus every attached module."""
    return gun.cost + sum(m.cost for m in gun.modules)


# --------------------------------------------------------------------------- #
#  Turrets — a placed gun (position lives on the object)
# --------------------------------------------------------------------------- #

@dataclass
class Turret:
    """A gun placed on the map. Placement is just ``x``/``y`` on this object."""

    x: float
    y: float
    gun: Gun
    id: str = ""              # assigned by the simulation
    cd: float = 0.0           # fire cooldown
    synergy_mult: float = 1.0  # set each step from active synergies

    def accepts(self) -> frozenset[str]:
        return self.gun.effective_accepts()

    def range(self) -> float:
        return self.gun.effective_range()

    def dps(self) -> float:
        return self.gun.dps() * self.synergy_mult


# --------------------------------------------------------------------------- #
#  Synergies — pair up certain guns for a bonus
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Synergy:
    guns: frozenset[str]
    name: str
    desc: str
    dps_mult: float


SYNERGIES: list[Synergy] = [
    Synergy(frozenset({"sieve", "auditor"}), "Correlation",
            "Auth + cloud audit cross-checks. +25% throughput to both.", 1.25),
    Synergy(frozenset({"scatter", "lance"}), "Layered defense",
            "Broad + heavy coverage. +20% throughput to both.", 1.20),
]


def compute_synergy_mult(turrets: list[Turret]) -> dict[str, float]:
    """Return a per-turret-id throughput multiplier from any active synergies."""
    present = {t.gun.name for t in turrets}
    mult: dict[str, float] = {t.id: 1.0 for t in turrets}
    for syn in SYNERGIES:
        if syn.guns <= present:
            for t in turrets:
                if t.gun.name in syn.guns:
                    mult[t.id] *= syn.dps_mult
    return mult


# --------------------------------------------------------------------------- #
#  Unlocks — what reaching a wave grants you
# --------------------------------------------------------------------------- #

def unlocked_at(wave: int) -> set[str]:
    """Names of guns + modules available once you've reached ``wave``."""
    items = {n for n, f in GUN_LIBRARY.items() if f().unlock_wave <= wave}
    items |= {m.name for m in MODULE_LIBRARY.values() if m.unlock_wave <= wave}
    return items
