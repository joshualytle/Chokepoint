"""Chokepoint — a programmable, typed-alert tower-defense for learning Python.

Packets are typed alerts that flood the pipeline; turrets are typed consumers
that only process the kinds their gun accepts. Compose guns, modules, and
placements in Python and watch coverage + throughput decide whether you hold.
"""

from .arsenal import GUN_LIBRARY, MODULE_LIBRARY, Gun, Module, Turret, make_gun
from .maps import MAPS, Graph
from .packets import KINDS, Packet
from .simulation import World

__all__ = [
    "World", "Graph", "MAPS", "Packet", "KINDS",
    "Gun", "Module", "Turret", "make_gun", "GUN_LIBRARY", "MODULE_LIBRARY",
]
__version__ = "0.2.0"
